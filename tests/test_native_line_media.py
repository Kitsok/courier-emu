"""Connected device PCM scripts, without SIP dialogs or modem calls."""
import ctypes as c
import socket

import pytest

from courier_emu.analog_native import NativeLineExchange
from courier_emu.ata import SipLine
from courier_emu.exchange import LineExchange
from courier_emu.media_native import NativeMedia
from courier_emu.sip import PolyphaseResampler
from courier_emu.dsp import load_library


class State(c.Structure):
    _fields_ = [(name, c.c_uint64) for name in
                ('frames', 'underrun_frames', 'underrun_samples', 'pending_peak')]


@pytest.fixture
def models():
    lib = load_library()
    signatures = {
        'create': ([c.c_void_p, c.c_void_p], c.c_void_p),
        'destroy': ([c.c_void_p], None),
        'snapshot': ([c.c_void_p, c.POINTER(State)], None),
        'frames': ([c.c_void_p, c.c_uint64], None),
        'reset': ([c.c_void_p], None),
        'pending': ([c.c_void_p, c.POINTER(c.c_int32), c.c_size_t, c.c_int], c.c_size_t),
        'underruns': ([c.c_void_p, c.POINTER(c.c_uint64), c.c_size_t], c.c_size_t),
    }
    for name, (args, result) in signatures.items():
        fn = getattr(lib, 'courier_line_media_' + name)
        fn.argtypes, fn.restype = args, result
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    media = NativeMedia(sock.fileno())
    media.configure(5, 0, 0, False, 1)
    exchange = NativeLineExchange.adopt(LineExchange())
    exchange.state = 'connected';exchange.off_hook = True
    owner = lib.courier_line_media_create(exchange.native_handle, media.handle)
    assert owner

    class Peer:
        def __init__(self):
            self.tx, self.rx = [], []

        def send_audio(self, samples):
            self.tx.extend(samples)

        def receive_audio(self):
            values, self.rx = self.rx, []
            return values

    reference = SipLine.__new__(SipLine)
    reference.sip = Peer()
    reference._pending = []
    reference._to_network = PolyphaseResampler(8000, 8000)
    reference._from_network = PolyphaseResampler(8000, 8000)
    reference.underrun_frames = reference.underrun_samples = reference.pending_peak = 0
    reference.underrun_log = [];reference.frames = 0
    reference.exchange = LineExchange(peer_audio=reference._peer_samples)
    reference.exchange.state = 'connected';reference.exchange.off_hook = True
    try:
        yield lib, owner, exchange, media, reference
    finally:
        lib.courier_line_media_destroy(owner)
        exchange.close();media.close();sock.close()


def test_direct_media_matches_reference_pcm_and_underruns(models):
    lib, owner, exchange, media, reference = models
    for frame, (count, tx_count, rx_count) in enumerate([
        (800, 800, 500), (800, 600, 1300), (241, 14, 7),
        (80, 0, 0), (900, 1100, 1600), (1, 1, 0),
        (800, 800, 0), (800, 800, 0), (80, 80, 0),
    ], 1):
        reference.frames = frame;lib.courier_line_media_frames(owner, frame)
        tx = [(k*73)%65536-32768 for k in range(tx_count)]
        rx = [(k*91)%65536-32768 for k in range(rx_count)]
        reference.sip.rx.extend(rx);media.queues[1].extend(rx)
        assert exchange.service(True, tx, count) == reference.exchange.service(True, tx, count)
        assert list(media.queues[0]) == reference.sip.tx
        size = lib.courier_line_media_pending(owner, None, 0, 0)
        pending = (c.c_int32 * size)()
        lib.courier_line_media_pending(owner, pending, size, 0)
        assert list(pending) == reference._pending
        state = State();lib.courier_line_media_snapshot(owner, c.byref(state))
        assert (state.underrun_frames, state.underrun_samples, state.pending_peak) == (
            reference.underrun_frames, reference.underrun_samples, reference.pending_peak)
        log = (c.c_uint64 * 128)()
        size = lib.courier_line_media_underruns(owner, log, 64)
        assert list(zip(log[:2*size:2], log[1:2*size:2])) == reference.underrun_log
    lib.courier_line_media_reset(owner)
    assert lib.courier_line_media_pending(owner, None, 0, 0) == 0


def test_owner_rejects_duplicate_attachment_and_non_8khz_loop(models):
    lib, owner, exchange, media, _ = models
    assert not lib.courier_line_media_create(exchange.native_handle, media.handle)
    other = NativeLineExchange.adopt(LineExchange(sample_rate=7200))
    try:
        assert not lib.courier_line_media_create(other.native_handle, media.handle)
    finally:
        other.close()


def test_native_peer_precedes_reference_callback(models):
    lib, owner, exchange, media, _ = models
    calls = []
    exchange.peer_audio = lambda count, tx: calls.append(count) or [17]*count
    assert exchange.service(True, [], 80) == [0]*80
    assert not calls

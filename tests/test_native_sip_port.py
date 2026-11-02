"""Scripted SIP control events, without sockets to a SIP server or modem calls."""
import ctypes as c
import copy
import math
import socket

import pytest

from courier_emu.analog_native import NativeLineExchange, pcm
from courier_emu.ata import SipLine
from courier_emu.dsp import load_library
from courier_emu.media_native import NativeMedia, SIP_STATES


class Control(c.Structure):
    _fields_ = [(name, c.c_int64) for name in ('state', 'inbound', 'last_status', 'signal_fd')]
    _fields_ += [('deadline', c.c_double)]


class State(c.Structure):
    _fields_ = [(name, c.c_uint64) for name in
                ('sip_state', 'incoming_active', 'placed', 'answered', 'frames', 'late_frames')]
    _fields_ += [(name, c.c_double) for name in
                ('next_frame_at', 'frame_duration', 'late_seconds', 'peak_late_seconds')]
    _fields_ += [('clock_started', c.c_uint64)]


class Signalling:
    realtime = False

    def __init__(self):
        self.state = 'idle';self.direction = 'outbound';self.last_status = 0
        self.incoming_from = '123';self.error = '';self.remote_rtp = None
        self.events = [];self.tx = [];self.rx = []

    def poll(self):self.events.append('poll')
    def start_call(self, number):self.events.append(('route', number));self.state = 'inviting'
    def ring_incoming(self):self.events.append('ring');self.state = 'ringing'
    def answer_incoming(self):self.events.append('answer');self.state = 'connected'
    def reject_incoming(self, *args):self.events.append(('reject', args));self.state = 'closed'
    def hangup(self):self.events.append('hangup');self.state = 'closed'
    def send_audio(self, samples):self.tx.extend(samples)
    def receive_audio(self):
        samples, self.rx = self.rx, []
        return samples


@pytest.fixture
def ports(monkeypatch):
    monkeypatch.setenv('COURIER_SIP_TX_BUFFER_MS', '0')
    monkeypatch.delenv('COURIER_SIP_RECORD', raising=False)
    lib = load_library()
    signatures = {
        'create': ([c.c_void_p, c.c_void_p], c.c_void_p),
        'destroy': ([c.c_void_p], None),
        'state': ([c.c_void_p], c.POINTER(State)),
        'control': ([c.c_void_p], c.POINTER(Control)),
        'from': ([c.c_void_p, c.c_char_p], None),
        'begin': ([c.c_void_p, c.c_int, c.POINTER(c.c_int32), c.c_size_t,
                   c.c_int64, c.c_double, c.c_int], c.c_int),
        'resume': ([c.c_void_p], c.c_int),
        'ack': ([c.c_void_p, c.c_int], None),
        'layout': ([c.c_int], c.c_size_t),
    }
    for name, (args, result) in signatures.items():
        fn = getattr(lib, 'courier_sip_port_' + name)
        fn.argtypes, fn.restype = args, result
    assert lib.courier_sip_port_layout(0) == c.sizeof(State)
    assert lib.courier_sip_port_layout(1) == c.sizeof(Control)
    reference = SipLine(Signalling())
    native_sip = Signalling()
    exchange = NativeLineExchange.adopt(copy.deepcopy(reference.exchange))
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    media = NativeMedia(sock.fileno())
    owner = lib.courier_sip_port_create(exchange.native_handle, media.handle)
    assert owner
    state = lib.courier_sip_port_state(owner).contents
    control = lib.courier_sip_port_control(owner).contents

    def sync():
        control.state = SIP_STATES.index(native_sip.state)
        control.inbound = native_sip.direction == 'inbound'
        control.last_status = native_sip.last_status
        media.configure(control.state, 0, 0, False, 1)
        getattr(lib, 'courier_sip_port_from')(owner, native_sip.incoming_from.encode())

    def service(hook, count=800, tx=None, *, now=100, realtime=False):
        tx = tx or []
        reference.sip.realtime = native_sip.realtime = realtime
        reference.cooperative_pacing = True
        monkeypatch.setattr('courier_emu.ata.time.monotonic', lambda: now)
        media.queues[1].extend(native_sip.rx);native_sip.rx = []
        sync()
        expected = reference.service(hook, tx, count)
        assert lib.courier_sip_port_begin(owner, hook, pcm(tx), len(tx), count, now, realtime) == 0
        for _ in range(100):
            event = lib.courier_sip_port_resume(owner)
            if event == 0:break
            assert event > 0
            if event == 1:native_sip.poll()
            elif event == 2:native_sip.reject_incoming(486, 'Busy Here')
            elif event == 3:native_sip.ring_incoming()
            elif event == 4:native_sip.answer_incoming()
            elif event == 5:native_sip.start_call(exchange.dialed)
            elif event == 6:native_sip.reject_incoming()
            elif event == 7:native_sip.hangup()
            sync();lib.courier_sip_port_ack(owner, event == 5)
        else:pytest.fail('subscriber continuation did not finish')
        assert exchange._vector(0) == expected
        assert exchange.status() == reference.exchange.status()
        assert native_sip.events == reference.sip.events
        assert list(media.queues[0]) == reference.sip.tx
        assert (state.sip_state, state.incoming_active, state.placed, state.answered) == (
            SIP_STATES.index(reference._sip_state), reference._incoming_active,
            reference.placed, reference.answered)
        assert (state.frames, state.late_frames, state.late_seconds, state.peak_late_seconds) == (
            reference.frames, reference.late_frames, reference.late_seconds, reference.peak_late_seconds)
        if realtime:
            assert state.next_frame_at == reference._next_frame_at
            assert state.frame_duration == reference._frame_duration

    try:
        yield reference, native_sip, exchange, service, lib, owner, state
    finally:
        lib.courier_sip_port_destroy(owner);exchange.close();media.close();sock.close()


@pytest.mark.parametrize('status', [486, 600, 500])
def test_outgoing_supervision(ports, status):
    reference, sip, exchange, service, *_ = ports
    service(True)
    reference.exchange.dialed = exchange.dialed = '100'
    tone = [round(3000*math.sin(2*math.pi*941*k/8000)
                  +3000*math.sin(2*math.pi*1477*k/8000)) for k in range(800)]
    service(True, tx=tone)
    assert reference.placed == 1
    for state in ('trying', 'ringing', 'failed'):
        reference.sip.state = sip.state = state
        reference.sip.last_status = sip.last_status = status
        service(True)
    service(False, count=11000)


def test_connected_peer_and_remote_release(ports):
    reference, sip, exchange, service, *_ = ports
    service(True)
    reference.exchange.dialed = exchange.dialed = '100'
    tone = [round(3000*math.sin(2*math.pi*941*k/8000)
                  +3000*math.sin(2*math.pi*1477*k/8000)) for k in range(800)]
    service(True, tx=tone)
    assert reference.placed == 1
    reference.sip.state = sip.state = 'connected'
    reference.sip.rx = sip.rx = [900]*160
    service(True, tx=[1200]*800)
    service(True, tx=[1300]*800)
    reference.sip.state = sip.state = 'closed'
    service(True)
    service(False)


def test_incoming_answer_and_local_hangup(ports):
    reference, sip, exchange, service, *_ = ports
    reference.sip.state = sip.state = 'incoming'
    reference.sip.direction = sip.direction = 'inbound'
    service(False)
    service(True)
    service(True, tx=[300]*800)
    service(False)


def test_incoming_busy_and_cancel(ports):
    reference, sip, exchange, service, *_ = ports
    service(True)
    reference.sip.state = sip.state = 'incoming'
    reference.sip.direction = sip.direction = 'inbound'
    service(True)
    service(False, count=11000)
    reference.sip.state = sip.state = 'incoming'
    service(False)
    reference.sip.state = sip.state = 'closed'
    service(False)


def test_empty_hotline_does_not_place_a_request(ports):
    reference, sip, exchange, service, *_ = ports
    reference.exchange.hotline = exchange.hotline = True
    service(True)
    assert reference.placed == 0
    assert reference.exchange.outcome == 'reorder'


def test_cooperative_frame_clock_and_lateness(ports):
    reference, sip, exchange, service, *_ = ports
    for now, count in [(100, 800), (100.09, 80), (100.15, 160), (101, 800), (101.1, 1)]:
        service(False, count=count, now=now, realtime=True)
    assert reference.late_frames == 3

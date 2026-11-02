"""Native port ownership and views; no SIP messages or modem calls."""
import ctypes as c
import gc
import socket
import weakref

import pytest

from courier_emu.analog_native import NativeLineExchange, pcm
from courier_emu.ata import SipLine
from courier_emu.exchange import LineExchange
from courier_emu.media_native import NativeMedia, NativeSipSession
from courier_emu.sip import SipConfig, SipSession
from courier_emu.sip_line_native import NativeSipLine, library


@pytest.fixture
def port(monkeypatch):
    monkeypatch.setenv('COURIER_SIP_TX_BUFFER_MS', '0')
    monkeypatch.delenv('COURIER_SIP_RECORD', raising=False)
    session = NativeSipSession.adopt(SipSession(SipConfig(server='127.0.0.1:9', bind='127.0.0.1')))
    # The native control adapter runs, but signalling is a local script only.
    monkeypatch.setattr(session, 'poll', lambda: None)
    original = SipLine(session)
    original.cooperative_pacing = True
    line = NativeSipLine.adopt(original)
    try:
        yield line, original, session
    finally:
        if not session.closed:
            session.state = 'idle'
        line.close()


def test_adoption_preserves_identity_and_live_status(port, monkeypatch):
    line, original, session = port
    monkeypatch.setattr('courier_emu.sip_line_native.time.monotonic', lambda: 50)
    assert line is original
    assert NativeSipLine.adopt(line) is line
    assert line._next_frame_at is None
    assert line.service(False, [], 80) == [0]*80
    assert line.frames == 1
    assert line._next_frame_at == 50.01
    assert line.pacing_deadline(40) == 50.005
    assert line.status()['frames'] == 1
    assert line._sip_state == 'idle'
    assert session._rtp_clock_thread is None


def test_native_peer_views_and_final_status(port):
    line, _, session = port
    session.state = 'connected'
    line.exchange.state = 'connected';line.exchange.off_hook = True
    session._native_media.queues[1].extend([123]*100)
    assert line.service(True, [800]*80, 80) == [123]*80
    assert line.answered == 1
    assert line.pending_peak == 100
    assert line._pending == [123]*20
    assert list(session._native_media.queues[0]) == [800]*80
    assert line.service(True, [], 80) == [123]*20+[0]*60
    assert line.underrun_samples == 60
    assert line.underrun_log == [(2, 60)]
    line._pending = [7, 8]
    assert line._pending == [7, 8]
    session.state = 'idle'
    line.close()
    assert line.status()['underrun_samples'] == 60
    assert line._pending == [7, 8]
    assert line.underrun_log == [(2, 60)]
    line.close()
    with pytest.raises(RuntimeError, match='closed'):
        line.service(False)


def test_native_owner_pins_devices_after_python_views_close():
    lib = library()
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    media = NativeMedia(sock.fileno())
    exchange = NativeLineExchange.adopt(LineExchange())
    exchange.state = 'connected';exchange.off_hook = True
    owner = lib.courier_sip_port_create(exchange.native_handle, media.handle)
    assert owner
    try:
        lib.courier_sip_port_control(owner).contents.state = 5
        media.close();exchange.close();sock.close()
        assert lib.courier_sip_port_begin(owner, 1, pcm([]), 0, 80, 0, 0) == 0
        assert lib.courier_sip_port_resume(owner) == 1
        lib.courier_sip_port_ack(owner, 0)
        assert lib.courier_sip_port_resume(owner) == 0
        state = lib.courier_sip_port_state(owner).contents
        assert state.answered == 1
    finally:
        lib.courier_sip_port_destroy(owner)
        media.close();exchange.close();sock.close()


def test_port_device_cycles_are_collectible(port):
    # Fixture holds this one; use an independently allocated second port.
    session = NativeSipSession.adopt(SipSession(SipConfig(server='127.0.0.1:9', bind='127.0.0.1')))
    line = NativeSipLine.adopt(SipLine(session))
    refs = [weakref.ref(obj) for obj in (line, line.exchange, session)]
    del line, session
    gc.collect()
    assert all(ref() is None for ref in refs)

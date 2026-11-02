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


def test_native_frames_only_yield_for_ready_signalling_or_timers(port, monkeypatch):
    line, _, session = port
    calls = []

    def poll():
        calls.append('poll')
        try:
            session.socket.recvfrom(256)
        except BlockingIOError:
            pass
        session._register_refresh_at = None

    monkeypatch.setattr(session, 'poll', poll)
    line.service(False, [], 80)
    assert calls == []
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as peer:
        # Readiness marker only; the scripted poll consumes it without parsing.
        peer.sendto(b'ready', session.socket.getsockname())
        line.service(False, [], 80)
    assert calls == ['poll']
    line.service(False, [], 80)
    assert calls == ['poll']
    session._register_refresh_at = 0
    assert line._native_control.deadline == 0
    line.service(False, [], 80)
    assert calls == ['poll', 'poll']
    assert line._native_control.deadline == float('inf')


def test_all_reference_signalling_timer_families_are_published(port):
    line, _, session = port
    assert session.signalling_deadline() == float('inf')
    session._invite_deadline = 80
    session._invite_sent_at = 20
    session._retransmit_after = .5
    session._invite = b'scripted'
    session.state = 'inviting'
    assert line._native_control.deadline == 20.5
    session.state = 'trying'
    assert line._native_control.deadline == 80
    session.state = 'connected'
    session.direction = 'inbound'
    session._incoming_final_at = 90
    session._incoming_next_response_at = 91
    assert line._native_control.deadline == 91
    session._incoming_next_response_at = 130
    assert line._native_control.deadline == 122
    session._incoming_acked = True
    assert line._native_control.deadline == float('inf')
    session._media_update = dict(success=True, acked=False, started=100, next=102)
    assert line._native_control.deadline == 102
    session._media_update = dict(success=True, acked=False, started=100, next=150)
    assert line._native_control.deadline == 132
    session._media_update = None
    session._cancelled_invites = {'retired': (170, b'', ('127.0.0.1', 9))}
    assert line._native_control.deadline == 170
    session._register_refresh_at = 160
    assert line._native_control.deadline == 160
    session.state = 'idle'

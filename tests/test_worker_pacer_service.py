"""Waits finish before the same native service commits its guest clocks."""
import ctypes as c
import socket
import time
import pytest
from courier_emu.analog_native import NativeDaa
from courier_emu.ata import SipLine
from courier_emu.board_media_native import NativeBoardMedia
from courier_emu.daa import CourierDaa
from courier_emu.exchange import LineExchange
from courier_emu.media_native import NativeSipSession
from courier_emu.sip import SipConfig, SipSession
from courier_emu.sip_line_native import NativeSipLine
from courier_emu.worker_poll import WorkerPoll


class Cpu(c.Structure):
    _fields_ = [('regs', c.c_void_p), ('memory', c.c_void_p), ('memory_size', c.c_size_t),
                ('guard', c.c_void_p), ('io_events', c.c_void_p), ('io_count', c.c_uint32),
                ('mmio_events', c.c_void_p), ('mmio_count', c.c_uint32), ('batch_total', c.c_uint64)]


@pytest.fixture
def service():
    session = NativeSipSession.adopt(SipSession(SipConfig(server='127.0.0.1:9', bind='127.0.0.1')))
    line = NativeSipLine.adopt(SipLine(session, exchange=LineExchange()))
    owner = NativeBoardMedia(line, NativeDaa.adopt(CourierDaa()), 4096)
    transport, terminal = socket.socketpair()
    poll = WorkerPoll()
    s = poll.state
    s.armed = 1; s.scheduled = 3; s.native_media = owner.handle
    s.elide_until = 1000000; s.batch = 4096
    s.timer_poll_period = s.timer_poll_owed = 1024
    s.panel_latch = 256; s.line_frame_instructions = 400000
    s.console_fd = transport.fileno(); s.console_present = 1
    s.console_owed = s.console_poll_period = 8192
    s.pacer_period = 1000
    s.pacer_wait.enabled = 1; s.pacer_wait.interval = .002
    line._next_frame_at = time.monotonic()+.1
    cpu = Cpu()
    call = c.CFUNCTYPE(c.c_int, c.c_void_p, c.c_uint64, c.c_uint32, c.c_void_p)(poll.function)
    try:
        yield poll, owner, line, lambda: call(poll.context, 1024, 0, c.byref(cpu))
    finally:
        transport.close(); terminal.close(); owner.close(); line.close()


def test_timeout_commits_exactly_one_service(service):
    poll, owner, _, run = service
    assert run() == 1
    assert poll.state.last_service == owner.state.board_instructions == 1024
    assert poll.state.polls == poll.state.pacer_wait.waits == 1
    assert poll.state.pacer_next == 2024
    assert poll.state.console_owed == 7168


@pytest.mark.parametrize('guard', ['deadline', 'signalling'])
def test_required_python_work_prevents_wait_and_service_commit(service, guard):
    poll, owner, line, run = service
    if guard == 'deadline':poll.state.elide_until = 1024
    else:line._native_control.deadline = 0
    assert run() == 0
    assert poll.state.polls == poll.state.pacer_wait.waits == 0
    assert poll.state.last_service == owner.state.board_instructions == 0

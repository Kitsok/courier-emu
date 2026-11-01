"""Idle waits obey wall deadlines and remain interruptible by terminal input."""
import socket
from types import SimpleNamespace

import pytest

from courier_emu.console import SerialConsole
from courier_emu.pacing import InstructionPacer


class Clock:
    def __init__(self):
        self.now = 10.0
        self.waits = []

    def __call__(self):
        return self.now

    def wait(self, delay):
        self.waits.append(delay)
        self.now += delay
        return False


def service(pacer, clock, instructions, **kwargs):
    return pacer.service(instructions, 1000, idle=True, reset=False,
                         wait=clock.wait, **kwargs)


def test_only_positive_wall_clock_lead_causes_a_wait():
    clock = Clock()
    pacer = InstructionPacer(clock=clock)
    assert not service(pacer, clock, 100)
    assert pacer.next_check == 105
    service(pacer, clock, 105)
    assert clock.waits == pytest.approx([.005])
    clock.now += .020
    service(pacer, clock, 110)
    assert len(clock.waits) == 1
    assert pacer.summary()["waited_seconds"] == pytest.approx(.005)


def test_input_wakes_ahead_wait_without_changing_guest_instructions():
    clock = Clock()
    pacer = InstructionPacer(clock=clock)
    service(pacer, clock, 0)
    before = clock.now
    assert pacer.service(5, 1000, idle=True, reset=False, wait=lambda delay: True)
    assert clock.now == before
    assert pacer.summary() == {"waits": 1, "input_wakeups": 1, "waited_seconds": 0}
    assert pacer.next_check == 10


def test_active_work_never_waits_and_rate_change_reanchors():
    clock = Clock()
    pacer = InstructionPacer(clock=clock)
    service(pacer, clock, 0)
    pacer.service(100, 1000, idle=False, reset=False, wait=clock.wait)
    assert not clock.waits
    pacer.service(200, 2000, idle=True, reset=False, wait=clock.wait)
    assert not clock.waits
    pacer.service(300, 2000, idle=False, reset=True, wait=clock.wait)
    pacer.service(400, 2000, idle=True, reset=False, wait=clock.wait)
    assert not clock.waits


def test_console_wait_does_not_consume_input_and_close_wakes_it():
    peer, worker = socket.socketpair()
    console = SerialConsole(worker.detach())
    try:
        assert not console.wait(0)
        peer.sendall(b"AT\r")
        assert console.wait(.1)
        assert console.poll() == b"AT\r"
        peer.close()
        assert console.wait(.1)
        assert console.poll() == b"" and console.closed
    finally:
        peer.close()
        console.close()


def test_sip_waits_keep_the_media_deadline_and_do_not_sleep_when_late(monkeypatch):
    from courier_emu.ata import SipLine
    clock = Clock()
    polls = []
    monkeypatch.setattr("courier_emu.ata.time.monotonic", clock)
    sip = SimpleNamespace(state="idle", poll=lambda: polls.append(clock.now))
    line = SipLine(sip)
    line.idle_wait = clock.wait
    line._next_frame_at = clock.now + .035
    line._pace(line.line_rate // 10)
    assert clock.waits == pytest.approx([.01, .01, .01, .005])
    assert len(polls) == 4
    assert line._next_frame_at == pytest.approx(10.135)
    assert line.paced_seconds == pytest.approx(.035)
    clock.now += 1
    line._pace(line.line_rate // 10)
    assert len(clock.waits) == 4
    assert line.late_frames == 1

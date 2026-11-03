"""Native pacing leaves input, timers and exceptional FD handling to Python."""
import ctypes as c
import socket
import threading
import time
import pytest
from courier_emu.dsp import load_library
from courier_emu.worker_poll import PacerWaitState


@pytest.fixture
def wait():
    lib = load_library()
    call = lib.courier_worker_pacer_wait
    call.argtypes = [c.c_void_p, c.c_int, c.c_int, c.c_double, c.c_double]
    call.restype = c.c_int
    console, terminal = socket.socketpair()
    signal, peer = socket.socketpair()
    state = PacerWaitState(enabled=1, interval=.002)

    def run(deadline=None, signal_deadline=float('inf'), console_fd=None):
        return call(c.byref(state), console.fileno() if console_fd is None else console_fd,
                    signal.fileno(), time.monotonic()+.1 if deadline is None else deadline,
                    signal_deadline)
    try:
        yield state, run, terminal, peer
    finally:
        for sock in (console, terminal, signal, peer):
            sock.close()


def test_bounded_timeout_changes_only_wait_statistics(wait):
    state, run, _, _ = wait
    assert run() == 1
    assert state.waits == 1 and state.wakeups == 0
    assert state.waited == state.port_waited
    assert 0 < state.waited < .2


@pytest.mark.parametrize('which', ['terminal', 'sip'])
def test_readable_input_is_not_consumed(wait, which):
    state, run, terminal, peer = wait
    (terminal if which == 'terminal' else peer).send(b'x')
    assert run() == -1
    assert state.waits == 0


@pytest.mark.parametrize('which,expected', [('terminal', 2), ('sip', 4)])
def test_input_during_wait_wakes_for_python(wait, which, expected):
    state, run, terminal, peer = wait
    state.interval = .05
    def send():
        time.sleep(.005)
        (terminal if which == 'terminal' else peer).send(b'x')
    thread = threading.Thread(target=send)
    thread.start()
    try:
        assert run() == expected
    finally:
        thread.join()
    assert state.waits == 1
    assert state.wakeups == int(which == 'terminal')
    assert 0 < state.waited < .2


def test_deadline_disabled_and_bad_fd_paths_do_not_wait(wait):
    state, run, _, _ = wait
    assert run(deadline=time.monotonic()-1) == 0
    assert run(signal_deadline=time.monotonic()+.001) == -1
    assert run(console_fd=-1) == -1
    state.enabled = 0
    assert run() == -1
    assert state.waits == 0

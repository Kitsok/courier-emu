"""Yield counters are opt-in and leave service return codes unchanged."""
import ctypes as c
import pytest
from courier_emu.worker_poll import WorkerPoll


@pytest.mark.parametrize('enabled', [False, True])
def test_unarmed_yield_counter_is_optional(monkeypatch, enabled):
    monkeypatch.setenv('COURIER_WORKER_YIELDS', str(int(enabled)))
    poll = WorkerPoll()
    call = c.CFUNCTYPE(c.c_int, c.c_void_p, c.c_uint64, c.c_uint32, c.c_void_p)(poll.function)
    for _ in range(3):
        assert call(poll.context, 1, 0, None) == 0
    assert poll.yield_profile()['native'] == ({'unarmed': 3} if enabled else {})

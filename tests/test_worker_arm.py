"""Rearming must preserve live clocks and detect DSP loader transitions."""
import pytest

from courier_emu.dsp import NativeC5x
from courier_emu.worker_poll import WorkerPoll


@pytest.mark.parametrize('scheduled', [0, 1, 2, 3])
def test_rearm_refreshes_loader_and_batch_state_without_resetting_clocks(scheduled):
    core = NativeC5x.from_program(0, b'\x00\x00')
    try:
        poll = WorkerPoll()
        s = poll.state
        s.core, s.scheduled = core.handle, scheduled
        s.loader_first, s.loader_end = 0x610, 0x653
        s.host_port, s.tick_period = 0x58, 1024
        s.debt, s.x86_ticks, s.ticks, s.polls = 1.5, 123, 45, 67
        for pc, expected in [(0x610, 1), (0x652, 1), (0x653, 0), (0x60f, 0)]:
            core.set_pc(pc)
            s.io_cursor = s.mmio_cursor = s.dirty = 9
            s.line_calls = s.tx_consumed = s.resampled = 8
            s.frame_ok = 1
            poll.arm(poll.context)
            assert s.armed == 1 and s.loader_in_loop == expected
            assert (s.io_cursor, s.mmio_cursor, s.dirty) == (0, 0, 0)
            assert (s.line_calls, s.tx_consumed, s.resampled) == (0, 0, 0)
            assert s.frame_ok == (scheduled == 0)
            assert (s.debt, s.x86_ticks, s.ticks, s.polls) == (1.5, 123, 45, 67)
            assert (s.host_port, s.tick_period) == (0x58, 1024)
    finally:
        core.close()

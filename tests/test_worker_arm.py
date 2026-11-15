"""Rearming must preserve live clocks and detect DSP loader transitions."""
import pytest
from types import SimpleNamespace

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


def test_persistent_configuration_matches_full_snapshots_across_transitions(monkeypatch):
    monkeypatch.setenv('COURIER_WORKER_CONFIG', '1')
    cached, reference = WorkerPoll(), WorkerPoll()
    reference.persistent_configuration = False
    machine = SimpleNamespace(
        _interrupt_stack=[], _last_service=100, frame_instructions=1000,
        _rom_tick=True, console=None, _console_owed=99,
        _last_tick=20, ticks=3, _int0_pending=None, _int1_pending=None,
        hardware_map=SimpleNamespace(tick_vector=15),
        timers=SimpleNamespace(controller=SimpleNamespace(enabled=lambda _: True)))
    bridge = SimpleNamespace(codec=object(), batch=4096, exchange=object(),
                             _exchange_instructions=20, _instructions=100,
                             _codec_instructions=20, _x86_ticks=20)
    for poll in (cached, reference):
        poll.state.service_model = 1

    def seed(mode=3, base=0, active=True, tick=1024):
        for poll in (cached, reference):
            poll.seed_snapshot(123, machine, bridge, base, 100000, mode,
                               active, tick, 1024, 4096)
        assert bytes(cached.state) == bytes(reference.state)

    seed()
    for _ in range(10):
        machine._last_service += 10
        seed()
    assert cached.configuration_refreshes == 1
    for field, value in [('frame_instructions', 2000), ('_rom_tick', False),
                         ('console', object())]:
        setattr(machine, field, value)
        seed()
    for field, value in [('codec', None), ('batch', 2048), ('exchange', None)]:
        setattr(bridge, field, value)
        seed()
    machine.timers.controller.enabled = lambda _: False
    seed(active=False, tick=0)
    seed(base=500)
    before = cached.configuration_refreshes
    seed(mode=1)
    seed()
    assert cached.configuration_refreshes == before + 1

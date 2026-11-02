"""The live timer buffer must implement the existing Python board contract."""
from collections import Counter
from copy import deepcopy
import random

import pytest

from courier_emu.timers import TimerBlock, TIMER_REGISTERS, SOURCE_CONTROL, IMASK
from courier_emu.timers_native import NativeTimerBlock


def assert_same(reference, native):
    assert native == reference
    assert reference == native
    assert native.status() == reference.status()
    assert [t.origin for t in native.timers] == [t.origin for t in reference.timers]
    assert list(native._pending) == reference._pending
    assert native.timebase == reference.timebase


@pytest.mark.parametrize('fast', [False, True])
def test_native_timer_model_matches_random_register_and_clock_scripts(fast):
    rng = random.Random(186)
    reference = TimerBlock(fast=fast)
    native = NativeTimerBlock(reference)
    now = 0
    addresses = tuple(TIMER_REGISTERS) + tuple(SOURCE_CONTROL) + (IMASK, 0xff02, 0xff44)
    for _ in range(2000):
        now += rng.randrange(20000)
        operation = rng.randrange(5)
        address, size, value = rng.choice(addresses), rng.choice((1, 2)), rng.randrange(65536)
        if operation == 0:
            assert native.write(address, size, value, now) == reference.write(address, size, value, now)
        elif operation == 1:
            grant = bool(rng.randrange(2))
            assert native.read(address, size, now, grant=grant) == reference.read(address, size, now, grant=grant)
        elif operation == 2:
            native.tick(now)
            reference.tick(now)
        elif operation == 3:
            assert native.pending_interrupt() == reference.pending_interrupt()
            assert native.take_interrupt() == reference.take_interrupt()
        else:
            native.answers_reads = reference.answers_reads = bool(rng.randrange(2))
        assert_same(reference, native)


def test_native_timer_pending_mask_queue_and_single_shot_semantics():
    reference = TimerBlock(fast=False)
    for timer in reference.timers:
        timer.control, timer.compare_a = 0xa001, 5
    reference.timers[1].control &= ~1
    native = NativeTimerBlock(reference)
    for now in (100, 200):
        reference.tick(now)
        native.tick(now)
        assert_same(reference, native)
    assert list(native._pending) == [8, 18, 19]
    assert native.pending_interrupt() is None
    for block in (reference, native):
        block.controller.masked['timer'] = False
    assert native.pending_interrupt() == 8
    for _ in range(4):
        assert native.take_interrupt() == reference.take_interrupt()
        assert_same(reference, native)


def test_native_timer_deadlines_follow_the_exact_tick_conversion():
    rng = random.Random(403)
    reference = TimerBlock()
    native = NativeTimerBlock(reference)
    for _ in range(500):
        expected = []
        for old, new in zip(reference.timers, native.timers):
            old.control = new.control = rng.choice((0, 0x8001, 0x8003, 0x8004, 0x8008))
            old.compare_a = new.compare_a = rng.randrange(65536)
            old.compare_b = new.compare_b = rng.randrange(65536)
            old.count = new.count = rng.randrange(old.period)
            old.origin = new.origin = rng.randrange(100000)
            remaining = old.ticks_to_max_count()
            if remaining is not None:
                due = old.origin + remaining
                at = max(0, int(due / reference.timebase.ticks_per_instruction))
                while at and reference._tick(at - 1) >= due:
                    at -= 1
                while reference._tick(at) < due:
                    at += 1
                expected.append(at)
        assert native.next_deadline() == (min(expected) if expected else None)


def test_native_timer_views_share_storage_and_deepcopies_are_independent():
    native = NativeTimerBlock(TimerBlock())
    native.timers[1].count = 42
    assert native.native_state.slots[1].count == 42
    native.native_state.slots[1].count = 99
    assert native.timers[1].count == 99
    clone = deepcopy(native)
    assert_same(native.reference(), clone)
    clone.timers[1].count = 123
    clone.controller.masked['timer'] = False
    clone._pending.append(18)
    assert native.timers[1].count == 99
    assert not list(native._pending)
    assert not native.controller.enabled('timer')


def test_native_timer_board_selection_preserves_callback_and_live_ratio():
    reference = TimerBlock()
    native = NativeTimerBlock(reference)
    calls, native_calls = [], []
    reference.on_timebase_change, native.on_timebase_change = calls.append, native_calls.append
    reference.write(0xff32, 2, 32256, 100)
    native.write(0xff32, 2, 32256, 100)
    assert native_calls == calls and len(calls) == 1
    assert native.timebase == reference.timebase
    assert native.native_state.ratio == native.timebase.ticks_per_instruction
    assert native.status() == reference.status()


def test_shared_native_mmio_reads_match_snapshot_reads_and_rollback():
    from courier_emu import x86_interpreter as x86
    from courier_emu.native_timers import NativeTimerReads

    states = []
    for shared in (False, True):
        block = TimerBlock(fast=False)
        block.timers[0].control, block.timers[0].compare_a = 0x8001, 1000
        if shared:
            block = NativeTimerBlock(block)
        counts = Counter()
        cpu = x86.Uc(0, 0, profile='186eb')
        cpu.mem_map(0, len(cpu.memory))
        cpu.native_timer_reads = NativeTimerReads(block, counts)

        def read(cpu, _access, address, size, _value, _user):
            counts[('read', address, size)] += 1
            value = block.read(address, size, cpu.retired)
            cpu.mem_write(address, value.to_bytes(size, 'little'))

        cpu.hook_add(x86.UC_HOOK_MEM_READ, read, None, 0xff30, 0xff47)
        cpu.hook_add(x86.UC_HOOK_MEM_WRITE, lambda *args: None, None, 0x2000, 0x2001)
        cpu.mem_write(0x1000, bytes.fromhex('a1 30 ff a1 32 ff a5'))
        cpu.reg_write(x86.UC_X86_REG_SI, 0xff30)
        cpu.reg_write(x86.UC_X86_REG_DI, 0x2000)
        cpu.emu_start(0x1000, 0, count=3)
        states.append((cpu.memory, cpu.regs, block.reference() if shared else block, counts))
    assert states[0] == states[1]

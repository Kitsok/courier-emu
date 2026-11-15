"""Committed T2 writes must match hooks, including RMW and guarded fallback."""
from collections import Counter
import ctypes

import pytest

from courier_emu import x86_interpreter as x86
from courier_emu.native_timers import NativeTimerReads
from courier_emu.timers import TimerBlock
from courier_emu.timers_native import NativeTimerBlock


@pytest.mark.parametrize('guard_source', [False, True])
@pytest.mark.parametrize('address', [0xff40, 0xff42, 0xff46])
def test_batched_timer_writes_match_synchronous_reference(guard_source, address):
    states, batches = [], []
    for native in (False, True):
        timers = NativeTimerBlock(TimerBlock(fast=False))
        timers.write(0xff42, 2, 10000, 0)
        timers.write(0xff46, 2, 0xc001, 0)
        counts = Counter()
        cpu = x86.Uc(0, 0, profile='186eb')
        cpu.native_enabled = native
        cpu.mem_map(0, len(cpu.memory))

        def read(cpu, _access, address, size, _value, _user):
            counts['reads'] += 1
            cpu.mem_write(address, timers.read(address, size, cpu.retired).to_bytes(size, 'little'))

        def write(cpu, _access, address, size, value, _user):
            counts['writes'] += 1
            timers.write(address, size, value, cpu.retired)

        cpu.hook_add(x86.UC_HOOK_MEM_READ, read, None, address, address + 1)
        cpu.hook_add(x86.UC_HOOK_MEM_WRITE, write, None, address, address + 1)
        if guard_source:
            cpu.hook_add(x86.UC_HOOK_MEM_READ, lambda *args: None, None, 0x2000, 0x2001)
        if native:
            # Preserve normal native timer read diagnostics separately.
            read_counts = Counter()
            cpu.native_timer_reads = NativeTimerReads(timers, read_counts)
            cpu.native_mmio_batch = ((address, address + 1),)

            def replay(events, count):
                for offset in range(0, count * 8, 8):
                    assert events[offset + 7] == 2
                    counts['writes'] += 1

            cpu.native_mmio_callback = replay
        # Word write; byte merge; native read/modify/write; MOVSW with an
        # optional watched source; read immediately after committed writes.
        code = bytes.fromhex('c7 06 40 ff 34 12 c6 06 40 ff 56 ff 06 40 ff a5 a1 40 ff')
        cpu.mem_write(0x1000, code.replace(b'\x40\xff', address.to_bytes(2, 'little')))
        cpu.mem_write(0x2000, b'\x78\x56')
        cpu.reg_write(x86.UC_X86_REG_SI, 0x2000)
        cpu.reg_write(x86.UC_X86_REG_DI, address)
        cpu.emu_start(0x1000, 0, count=5)
        if native:
            counts['reads'] += read_counts[('read', address, 2)]
            batches.append(cpu._native.batches)
        states.append((list(cpu.regs), bytes(cpu.memory), timers.reference(), counts))
    assert states[0] == states[1]
    assert batches[0] == (2 if guard_source else 1) + (address == 0xff46)


def test_worker_eoi_replay_preserves_applied_timer_write_marker():
    from test_worker_deadlines import scheduled
    poll, run = scheduled()
    events = (ctypes.c_uint8 * 16)(
        0x40, 0xff, 0, 0, 0x34, 0x12, 2, 2,
        0x02, 0xff, 0, 0, 0, 0x80, 2, 0)
    poll.cpu.mmio_events = ctypes.addressof(events)
    poll.cpu.mmio_count = 2
    assert run(1024) == 1
    assert (events[7], events[15]) == (2, 1)

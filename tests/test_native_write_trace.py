"""Buffered diagnostic stores retain synchronous hook observations."""
from struct import Struct

from courier_emu import x86_interpreter as x86

RECORD = Struct('=8I')


def cpu_with_trace(code, enabled, first=0x3000, last=0x3001):
    cpu = x86.Uc(0, 0, profile='186eb')
    cpu.mem_map(0, len(cpu.memory))
    cpu.mem_write(0x1000, code)
    cpu.reg_write(x86.UC_X86_REG_SP, 0x4000)
    cpu.mem_write(0x4004, bytes.fromhex('111122223333'))
    events, batches = [], []

    def observe(uc, access, address, size, value, user):
        cs, ss, sp = [uc.reg_read(r) for r in
                      (x86.UC_X86_REG_CS, x86.UC_X86_REG_SS, x86.UC_X86_REG_SP)]
        pc = ((cs << 4) + uc.reg_read(x86.UC_X86_REG_IP)) & 0xfffff
        stack = [int.from_bytes(uc.mem_read(((ss << 4)+sp+offset) & 0xfffff, 2), 'little')
                 for offset in (4, 6, 8)]
        events.append((address, value, pc, size, cs, *stack))

    def replay(data, count):
        batches.append(count)
        events.extend(RECORD.iter_unpack(data[:count*RECORD.size]))

    cpu.hook_add(x86.UC_HOOK_MEM_WRITE, observe, None, first, last)
    if enabled:
        cpu.native_write_trace = ((first, last),)
        cpu.native_write_trace_hook = observe
        cpu.native_write_trace_callback = replay
    return cpu, events, batches


def test_buffered_records_preserve_values_pc_and_changing_stack():
    # Word/byte arithmetic, overflow and stack memory changed between stores.
    code = bytes.fromhex('b8ffff a30030 ff060030 fe060030 '
                         'c7060440efbe ff0e0030 c6060030ff')
    reference, expected, _ = cpu_with_trace(code, False)
    candidate, actual, batches = cpu_with_trace(code, True)
    reference.native_enabled = False
    for cpu in (reference, candidate):
        cpu.emu_start(0x1000, 0, count=7)
    assert actual == expected
    assert len(actual) == 5
    assert actual[0][-3] == 0x1111
    assert actual[-1][-3] == 0xbeef
    assert candidate.regs == reference.regs
    assert candidate.memory == reference.memory
    assert sum(batches) == 5
    assert len(batches) < 5


def test_trace_capacity_flushes_without_losing_or_duplicating_writes():
    code = bytes.fromhex('ff060030 ebfa')
    reference, expected, _ = cpu_with_trace(code, False)
    candidate, actual, batches = cpu_with_trace(code, True)
    for cpu in (reference, candidate):
        cpu.emu_start(0x1000, 0, count=20000)
    assert len(actual) == 10000
    assert actual == expected
    assert candidate.regs == reference.regs
    assert candidate.memory == reference.memory
    # A full buffer can send one store through the synchronous fallback.
    assert 10000-len(batches) <= sum(batches) <= 10000
    assert 1 < len(batches) < 10


def test_partial_instruction_trace_is_discarded_before_watchpoint_fallback():
    # PUSHA stages traced writes before reaching another synchronous hook.
    reference, expected, _ = cpu_with_trace(b'\x60', False, 0x4004, 0x4007)
    candidate, actual, batches = cpu_with_trace(b'\x60', True, 0x4004, 0x4007)
    for cpu in (reference, candidate):
        cpu.reg_write(x86.UC_X86_REG_SP, 0x4008)
        cpu.hook_add(x86.UC_HOOK_MEM_WRITE, lambda *_: None, None, 0x4002, 0x4003)
        cpu.emu_start(0x1000, 0, count=1)
    assert actual == expected
    assert len(actual) == 2
    assert not batches
    assert candidate.regs == reference.regs
    assert candidate.memory == reference.memory


def test_additional_overlapping_hook_keeps_stores_synchronous():
    cpu, events, batches = cpu_with_trace(bytes.fromhex('ff060030 ebfa'), True)
    observed = []
    cpu.hook_add(x86.UC_HOOK_MEM_WRITE, lambda *args: observed.append(args[4]),
                 None, 0x3000, 0x3001)
    cpu.emu_start(0x1000, 0, count=8)
    assert len(events) == len(observed) == 4
    assert observed == [1, 2, 3, 4]
    assert not batches

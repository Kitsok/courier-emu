"""Timer MMIO must preserve values, lazy counts and instruction rollback."""
from collections import Counter
from copy import deepcopy
import random

from courier_emu import x86_interpreter as x86
from courier_emu.native_timers import NativeTimerReads
from courier_emu.timers import TimerBlock, TIMER_REGISTERS


def test_timer_reads_match_python_across_modes_widths_and_expiries():
    rng = random.Random(80186)
    for _ in range(60):
        reference = TimerBlock(fast=False)
        for timer in reference.timers:
            timer.control = rng.choice([0, 0x8000, 0x8001, 0x8003, 0x8004, 0x8008])
            timer.compare_a = rng.randrange(1, 100)
            timer.compare_b = rng.randrange(1, 100)
            timer.count = rng.randrange(timer.period)
        states = []
        for native in (False, True):
            timers = deepcopy(reference)
            counts = Counter()
            cpu = x86.Uc(0, 0, profile="186eb")
            cpu.mem_map(0, len(cpu.memory))
            cpu.native_enabled = native
            if native:
                cpu.native_timer_reads = NativeTimerReads(timers, counts)

            def read(cpu, _access, address, size, _value, _user):
                counts[("read", address, size)] += 1
                value = timers.read(address, size, cpu.retired)
                cpu.mem_write(address, value.to_bytes(size, "little"))

            cpu.hook_add(x86.UC_HOOK_MEM_READ, read, None, 0xff30, 0xff47)
            code = bytearray()
            for address in TIMER_REGISTERS:
                for op in (0xa0, 0xa1):
                    code.extend(bytes([op]) + address.to_bytes(2, "little"))
            cpu.mem_write(0x1000, code)
            cpu.emu_start(0x1000, 0, count=22)
            states.append((cpu.regs, cpu.memory, timers, counts))
        assert states[0] == states[1]


def test_uncommitted_read_does_not_publish_timer_side_effects():
    timers = TimerBlock(fast=False)
    timers.timers[0].control = 0x8001
    timers.timers[0].compare_a = 1000
    cpu = x86.Uc(0, 0, profile="186eb")
    cpu.mem_map(0, len(cpu.memory))
    counts = Counter()
    cpu.native_timer_reads = NativeTimerReads(timers, counts)
    # MOVSW reads a timer then encounters a watched destination. Only the
    # Python fallback's one read may be counted or alter the timer view.
    cpu.reg_write(x86.UC_X86_REG_SI, 0xff30)
    cpu.reg_write(x86.UC_X86_REG_DI, 0x2000)
    cpu.mem_write(0x1000, b"\xa5")

    def read(cpu, _access, address, size, _value, _user):
        counts[("read", address, size)] += 1
        cpu.mem_write(address, timers.read(address, size, cpu.retired).to_bytes(size, "little"))

    cpu.hook_add(x86.UC_HOOK_MEM_READ, read, None, 0xff30, 0xff31)
    cpu.hook_add(x86.UC_HOOK_MEM_WRITE, lambda *args: None, None, 0x2000, 0x2001)
    cpu.emu_start(0x1000, 0, count=1)
    assert counts[("read", 0xff30, 2)] == timers.reads == 1

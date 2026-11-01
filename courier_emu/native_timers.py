"""Batch-local timer read view for the native 80186 engine.

Writes, control reads (which may accelerate a delay), and reads crossing a
max count stay in Python. Ordinary count/compare reads update the same lazy
timer view and diagnostics before any Python handler sees the next access.
"""
import ctypes as c

from .timers import TIMER_REGISTERS


class Slot(c.Structure):
    _fields_ = [(name, c.c_uint64) for name in
                ("origin", "last_tick", "count", "compare_a", "compare_b", "control")]


class ReadState(c.Structure):
    _fields_ = [("instruction_base", c.c_uint64), ("ratio", c.c_double),
                ("slots", Slot * 3), ("reads", (c.c_uint64 * 2) * 11)]


class NativeTimerReads:
    def __init__(self, timers, counts):
        self.timers, self.counts = timers, counts
        self.buffer = bytearray(c.sizeof(ReadState))
        self.state = ReadState.from_buffer(self.buffer)
        self.entries = sorted(TIMER_REGISTERS)

    def prepare(self, base):
        s = self.state
        s.instruction_base = base
        s.ratio = self.timers.timebase.ticks_per_instruction
        for slot, timer in zip(s.slots, self.timers.timers):
            slot.origin = slot.last_tick = timer.origin
            slot.count = timer.count
            slot.compare_a, slot.compare_b = timer.compare_a, timer.compare_b
            slot.control = timer.control
        c.memset(c.addressof(s.reads), 0, c.sizeof(s.reads))

    def finish(self):
        for slot, timer in zip(self.state.slots, self.timers.timers):
            if slot.last_tick != slot.origin:
                timer.advance(max(slot.last_tick, timer.origin))
        for address, sizes in zip(self.entries, self.state.reads):
            for size, count in enumerate(sizes, 1):
                if count:
                    self.counts[("read", address, size)] += count
                    self.timers.reads += count

"""Batch-local timer read view for the native 80186 engine.

Writes, control reads (which may accelerate a delay), and reads crossing a
max count stay in Python. Ordinary count/compare reads update the same lazy
timer view and diagnostics before any Python handler sees the next access.
"""
import ctypes as c
from struct import Struct

from .timers import TIMER_REGISTERS


class Slot(c.Structure):
    _fields_ = [(name, c.c_uint64) for name in
                ("origin", "last_tick", "count", "compare_a", "compare_b", "control")]


class ReadState(c.Structure):
    _fields_ = [("instruction_base", c.c_uint64), ("ratio", c.c_double),
                ("slots", Slot * 3), ("reads", (c.c_uint64 * 2) * 11),
                ("read_mask", c.c_uint64)]


_SLOT_PACK = Struct("=6Q")
assert _SLOT_PACK.size == c.sizeof(Slot)


class NativeTimerReads:
    def __init__(self, timers, counts):
        self.timers, self.counts = timers, counts
        self.buffer = bytearray(c.sizeof(ReadState))
        self.state = ReadState.from_buffer(self.buffer)
        self.entries = sorted(TIMER_REGISTERS)
        self.timer_indexes = tuple(TIMER_REGISTERS[a][0] for a in self.entries)
        self.slot_offsets = tuple(ReadState.slots.offset + i * c.sizeof(Slot)
                                  for i in range(3))
        self.revision = -1

    def prepare(self, base):
        s = self.state
        s.instruction_base = base
        if self.revision != self.timers.revision:
            s.ratio = self.timers.timebase.ticks_per_instruction
            # Write the six native-endian uint64 fields in one call instead
            # of allocating ctypes slot views and assigning each descriptor.
            for offset, timer in zip(self.slot_offsets, self.timers.timers):
                _SLOT_PACK.pack_into(
                    self.buffer, offset, timer.origin, timer.origin,
                    timer.count, timer.compare_a, timer.compare_b, timer.control)
            self.revision = self.timers.revision

    def finish(self):
        s = self.state
        mask = s.read_mask
        if not mask:
            return
        s.read_mask = 0
        touched = 0
        while mask:
            bit = mask & -mask
            mask ^= bit
            index, width = divmod(bit.bit_length() - 1, 2)
            count = s.reads[index][width]
            s.reads[index][width] = 0
            self.counts[("read", self.entries[index], width + 1)] += count
            self.timers.reads += count
            touched |= 1 << self.timer_indexes[index]
        for index in range(3):
            if not touched & (1 << index):
                continue
            slot, timer = s.slots[index], self.timers.timers[index]
            if slot.last_tick != slot.origin:
                timer.advance(max(slot.last_tick, timer.origin))
        self.timers.revision += 1

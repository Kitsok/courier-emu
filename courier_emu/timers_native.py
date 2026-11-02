"""Live Python views of the authoritative native 80186 timer state."""
import ctypes as c
from collections.abc import MutableMapping, MutableSequence
from copy import deepcopy
from dataclasses import fields

from .dsp import load_library
from .timers import Timer, TimerBlock, InterruptController, IMASK_ORDER


class NativeTimer(c.Structure):
    _fields_ = [(name, c.c_int64 if name == 'origin' else c.c_uint64) for name in
                ('index', 'control', 'compare_a', 'compare_b', 'count', 'origin', 'max_counts')]
    enabled = Timer.enabled
    continuous = Timer.continuous
    counts_internally = Timer.counts_internally
    period = Timer.period
    advance = Timer.advance
    ticks_to_max_count = Timer.ticks_to_max_count
    write = Timer.write
    status = Timer.status

    def reference(self):
        return Timer(*(getattr(self, name) for name, _ in self._fields_))

    def __eq__(self, other):
        if isinstance(other, NativeTimer):
            other = other.reference()
        return self.reference() == other


class NativeTimerState(c.Structure):
    _fields_ = [('slots', NativeTimer * 3), ('instruction_base', c.c_uint64),
                ('ratio', c.c_double), ('pending_count', c.c_uint64),
                ('pending', c.c_uint64 * 3)] + [
        (name, c.c_uint64) for name in
        ('controller_mask', 'controller_writes', 'fast', 'answers_reads', 'granted',
         'accelerated', 'reads', 'writes', 'interrupts', 'revision')
    ] + [('read_counts', (c.c_uint64 * 2) * 11), ('read_mask', c.c_uint64),
         ('last_read_tick', c.c_uint64 * 3)]


class MaskView(MutableMapping):
    def __init__(self, state):
        self.state = state

    def __getitem__(self, key):
        if key not in IMASK_ORDER:
            raise KeyError(key)
        return bool(self.state.controller_mask & (1 << IMASK_ORDER.index(key)))

    def __setitem__(self, key, value):
        if key not in IMASK_ORDER:
            raise KeyError(key)
        bit = 1 << IMASK_ORDER.index(key)
        self.state.controller_mask = ((self.state.controller_mask | bit) if value
                                      else (self.state.controller_mask & ~bit))

    def __delitem__(self, key):
        raise TypeError('controller sources cannot be removed')

    def __iter__(self):
        return iter(IMASK_ORDER)

    def __len__(self):
        return len(IMASK_ORDER)


class NativeController(InterruptController):
    def __init__(self, state):
        self._state = state
        self.masked = MaskView(state)

    writes = property(lambda self: self._state.controller_writes,
                      lambda self, value: setattr(self._state, 'controller_writes', value))

    def __eq__(self, other):
        return isinstance(other, InterruptController) and self.status() == other.status()


class PendingView(MutableSequence):
    def __init__(self, state):
        self.state = state

    def __len__(self):
        return self.state.pending_count

    def __getitem__(self, index):
        if isinstance(index, slice):
            return list(self)[index]
        index = index + len(self) if index < 0 else index
        if not 0 <= index < len(self):
            raise IndexError(index)
        return self.state.pending[index]

    def __setitem__(self, index, value):
        index = index + len(self) if index < 0 else index
        if not 0 <= index < len(self):
            raise IndexError(index)
        self.state.pending[index] = value

    def __delitem__(self, index):
        index = index + len(self) if index < 0 else index
        if not 0 <= index < len(self):
            raise IndexError(index)
        for at in range(index + 1, len(self)):
            self.state.pending[at - 1] = self.state.pending[at]
        self.state.pending_count -= 1

    def insert(self, index, value):
        if len(self) == 3:
            raise IndexError('one pending request per timer')
        index = max(0, min(len(self), index + len(self) if index < 0 else index))
        for at in range(len(self), index, -1):
            self.state.pending[at] = self.state.pending[at - 1]
        self.state.pending[index] = value
        self.state.pending_count += 1

    def __eq__(self, other):
        return list(self) == list(other)


def _state_property(name, boolean=False):
    return property(lambda self: bool(getattr(self.native_state, name)) if boolean
                    else getattr(self.native_state, name),
                    lambda self, value: setattr(self.native_state, name, value))


class NativeTimerBlock(TimerBlock):
    """TimerBlock API; fields and native execution share one permanent buffer."""
    def __init__(self, reference):
        if type(reference.controller) is not InterruptController:
            raise ValueError('native timers require the legacy controller map')
        library = load_library()
        layout = (c.c_uint64 * 4)()
        library.courier_timer186_layout(layout)
        expected = (c.sizeof(NativeTimerState), c.sizeof(NativeTimer),
                    NativeTimerState.read_counts.offset, NativeTimerState.revision.offset)
        if tuple(layout) != expected:
            raise RuntimeError(f'native timer layout {tuple(layout)} != {expected}')
        self.buffer = bytearray(c.sizeof(NativeTimerState))
        self.native_state = NativeTimerState.from_buffer(self.buffer)
        self.address = c.addressof(self.native_state)
        # These short state operations need no GIL release/reacquisition.
        self._native_tick = c.PYFUNCTYPE(None, c.c_void_p, c.c_uint64)(
            c.cast(library.courier_timer186_tick, c.c_void_p).value)
        self._native_deadline = c.PYFUNCTYPE(c.c_uint64, c.c_void_p)(
            c.cast(library.courier_timer186_deadline, c.c_void_p).value)
        self.timers = list(self.native_state.slots)
        for dest, source in zip(self.timers, reference.timers):
            for name, _ in NativeTimer._fields_:
                setattr(dest, name, getattr(source, name))
        self.controller = NativeController(self.native_state)
        self.native_state.controller_mask = sum(
            int(reference.controller.masked[name]) << i for i, name in enumerate(IMASK_ORDER))
        self.controller.writes = reference.controller.writes
        self._pending = PendingView(self.native_state)
        self._pending.extend(reference._pending)
        for f in fields(TimerBlock):
            if f.name not in ('timers', 'controller', '_pending'):
                setattr(self, f.name, getattr(reference, f.name))

    timebase = property(lambda self: self._timebase)

    @timebase.setter
    def timebase(self, value):
        self._timebase = value
        self.native_state.ratio = value.ticks_per_instruction

    def tick(self, instructions):
        self._native_tick(self.address, instructions)

    def next_deadline(self):
        value = self._native_deadline(self.address)
        return None if value == (1 << 64) - 1 else value

    def reference(self):
        kwargs = {f.name: getattr(self, f.name) for f in fields(TimerBlock)}
        kwargs.update(timers=[t.reference() for t in self.timers],
                      controller=InterruptController(dict(self.controller.masked), self.controller.writes),
                      _pending=list(self._pending))
        return TimerBlock(**kwargs)

    def __eq__(self, other):
        return self.reference() == (other.reference() if isinstance(other, NativeTimerBlock) else other)

    def __deepcopy__(self, memo):
        clone = NativeTimerBlock(self.reference())
        memo[id(self)] = clone
        clone.on_timebase_change = deepcopy(self.on_timebase_change, memo)
        return clone


for _name in ('fast', 'answers_reads', 'granted', 'accelerated', 'reads', 'writes', 'interrupts', 'revision'):
    setattr(NativeTimerBlock, _name, _state_property(_name, _name in ('fast', 'answers_reads')))

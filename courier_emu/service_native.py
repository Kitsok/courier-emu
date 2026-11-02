"""Shared machine service phases for native and Python execution."""
import ctypes as c
from collections.abc import MutableSequence
from .machine import CourierMachine


class ServiceState(c.Structure):
    _fields_ = [('console_owed', c.c_int64), ('timer_poll_owed', c.c_int64),
                ('last_frame', c.c_int64), ('last_tick', c.c_uint64), ('ticks', c.c_uint64)]
    _fields_ += [(name, c.c_uint64) for name in ('int0_pending', 'int1_pending', 'timer_pending', 'timer_delivered', 'int0_in_service', 'stack_depth')]
    _fields_ += [('stack', c.c_uint8 * 64)]


FIELDS = {'_console_owed': 'console_owed', '_timer_poll_owed': 'timer_poll_owed',
          '_last_frame': 'last_frame', '_last_tick': 'last_tick', 'ticks': 'ticks',
          '_int0_pending': 'int0_pending', '_int1_pending': 'int1_pending',
          '_timer_interrupt_pending': 'timer_pending', 'timer_interrupts': 'timer_delivered',
          '_int0_in_service': 'int0_in_service'}


class ServiceField:
    def __init__(self, field):self.field = field
    def __get__(self, owner, cls=None):
        if owner is None:return self
        value = getattr(owner._native_service_state, self.field)
        if self.field in ('int0_pending', 'int1_pending', 'timer_pending'):return value or None
        return bool(value) if self.field == 'int0_in_service' else value
    def __set__(self, owner, value):setattr(owner._native_service_state, self.field, value or 0)


class NativeServiceMachine(CourierMachine):
    @classmethod
    def adopt(cls, machine):
        if isinstance(machine, cls):return machine
        if type(machine) is not CourierMachine:return machine
        from .dsp import load_library
        lib = load_library()
        lib.courier_service_layout.restype = c.c_size_t
        if lib.courier_service_layout() != c.sizeof(ServiceState):
            raise RuntimeError('native machine service ABI mismatch')
        original = {name: getattr(machine, name) for name in FIELDS}
        stack = list(machine._interrupt_stack)
        machine._native_service_buffer = bytearray(c.sizeof(ServiceState))
        machine._native_service_state = ServiceState.from_buffer(machine._native_service_buffer)
        machine._native_service_address = c.addressof(machine._native_service_state)
        machine.__class__ = cls
        for name, value in original.items():setattr(machine, name, value)
        machine._interrupt_stack = NativeInterruptStack(machine._native_service_state, stack)
        return machine


for _name, _field in FIELDS.items():setattr(NativeServiceMachine, _name, ServiceField(_field))


class NativeInterruptStack(MutableSequence):
    # Python can retain an unusually deep stack. The worker declines native
    # execution above 64 entries, preserving its existing fallback boundary.
    def __init__(self, state, values):
        self.state = state;self.overflow = [];self.replace(values)
    def values(self):return list(self.state.stack[:self.state.stack_depth])+self.overflow
    def replace(self, values):
        self.state.stack_depth = min(64, len(values))
        self.state.stack[:self.state.stack_depth] = values[:64]
        self.overflow = values[64:]
    def __len__(self):return self.state.stack_depth+len(self.overflow)
    def __iter__(self):return iter(self.values())
    def __eq__(self, other):
        return self.values() == (other.values() if isinstance(other, NativeInterruptStack) else other)
    def __repr__(self):return repr(self.values())
    def __getitem__(self, index):return self.values()[index]
    def __setitem__(self, index, value):
        values = self.values();values[index] = value;self.replace(values)
    def __delitem__(self, index):
        values = self.values();del values[index];self.replace(values)
    def insert(self, index, value):
        values = self.values();values.insert(index, value);self.replace(values)


def fold_native_eois(events, count, counts):
    """Fold a batch only when every EOI was already applied by native code."""
    if count <= 0 or len(events) < count*8:return False
    data = bytes(events[:count*8])
    for offset, value in ((0, 2), (1, 255), (2, 0), (3, 0), (7, 1)):
        if data[offset::8].count(value) != count:return False
    widths = data[6::8]
    narrow, wide = widths.count(1), widths.count(2)
    if narrow+wide != count:return False
    if narrow:counts[('write', 0xff02, 1)] += narrow
    if wide:counts[('write', 0xff02, 2)] += wide
    return True

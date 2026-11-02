"""Shared machine service phases for native and Python execution."""
import ctypes as c
from .machine import CourierMachine


class ServiceState(c.Structure):
    _fields_ = [('console_owed', c.c_int64), ('timer_poll_owed', c.c_int64),
                ('last_frame', c.c_int64), ('last_tick', c.c_uint64), ('ticks', c.c_uint64)]


FIELDS = {'_console_owed': 'console_owed', '_timer_poll_owed': 'timer_poll_owed',
          '_last_frame': 'last_frame', '_last_tick': 'last_tick', 'ticks': 'ticks'}


class ServiceField:
    def __init__(self, field):self.field = field
    def __get__(self, owner, cls=None):
        return self if owner is None else getattr(owner._native_service_state, self.field)
    def __set__(self, owner, value):setattr(owner._native_service_state, self.field, value)


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
        machine._native_service_buffer = bytearray(c.sizeof(ServiceState))
        machine._native_service_state = ServiceState.from_buffer(machine._native_service_buffer)
        machine._native_service_address = c.addressof(machine._native_service_state)
        machine.__class__ = cls
        for name, value in original.items():setattr(machine, name, value)
        return machine


for _name, _field in FIELDS.items():setattr(NativeServiceMachine, _name, ServiceField(_field))

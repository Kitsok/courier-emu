"""Live control view of the native ASIC codec initialization master."""
import ctypes as c
import weakref
from collections.abc import MutableSequence

from .analog_native import NativeField
from .codec import CodecBringUp
from .silicon_native import NativeSiliconDaa

NAMES = (None, 'register-reset', 'sample-rate', 'power-up', 'ready', 'gpio', 'levels',
         'line-interface', 'power-up-poll')


class BringUpState(c.Structure):
    _fields_ = [(name, c.c_int64) for name in
                ('rate', 'configuration_1', 'configuration_2', 'level', 'gpio_configuration', 'index', 'polls')]


class NativeSteps(MutableSequence):
    def __init__(self, owner):self.owner = owner
    def values(self):
        owner = self.owner
        fn = owner._native_lib.courier_bringup_steps
        size = fn(owner.native_handle, None, 0, 0)
        data = (c.c_int32 * size)();fn(owner.native_handle, data, size, 0)
        return [NAMES[value] for value in data]
    def replace(self, values):
        data = (c.c_int32 * len(values))(*(NAMES.index(value) for value in values))
        self.owner._native_lib.courier_bringup_steps(self.owner.native_handle, data, len(data), 1)
    def __len__(self):return self.owner._native_lib.courier_bringup_steps(self.owner.native_handle, None, 0, 0)
    def __getitem__(self, index):return self.values()[index]
    def __setitem__(self, index, value):
        values = self.values();values[index] = value;self.replace(values)
    def __delitem__(self, index):
        values = self.values();del values[index];self.replace(values)
    def insert(self, index, value):
        values = self.values();values.insert(index, value);self.replace(values)
    def __iter__(self):return iter(self.values())


class NativeCodecBringUp(CodecBringUp):
    @classmethod
    def adopt(cls, master):
        if isinstance(master, cls):return master
        if type(master) is not CodecBringUp:raise TypeError('custom codec masters retain their implementation')
        part = NativeSiliconDaa.adopt(master.codec)
        lib = part._native_lib
        signatures = {
            'create': ([c.c_void_p], c.c_void_p), 'destroy': ([c.c_void_p], None),
            'layout': ([], c.c_size_t), 'state': ([c.c_void_p], c.POINTER(BringUpState)),
            'step': ([c.c_void_p], c.c_int), 'service': ([c.c_void_p, c.c_int64], None),
            'steps': ([c.c_void_p, c.POINTER(c.c_int32), c.c_size_t, c.c_int], c.c_size_t),
        }
        for name, (args, result) in signatures.items():
            fn = getattr(lib, 'courier_bringup_'+name);fn.argtypes, fn.restype = args, result
        if lib.courier_bringup_layout() != c.sizeof(BringUpState):raise RuntimeError('native codec master ABI mismatch')
        old = dict(vars(master));steps = list(master.steps)
        handle = lib.courier_bringup_create(part.native_address)
        if not handle:raise MemoryError('native codec master allocation failed')
        master._native_lib = lib;master._native_handle = handle
        master._native_state = lib.courier_bringup_state(handle).contents
        master._native_finalizer = weakref.finalize(master, cls._destroy, lib, handle, part._native_buffer)
        master.__class__ = cls
        for name, _ in BringUpState._fields_:setattr(master, name, old[name])
        master.steps = steps
        return master

    @staticmethod
    def _destroy(lib, handle, storage):lib.courier_bringup_destroy(handle)
    @property
    def native_handle(self):return self._native_handle
    @property
    def steps(self):return NativeSteps(self)
    @steps.setter
    def steps(self, values):NativeSteps(self).replace(list(values))
    def step(self):return NAMES[self._native_lib.courier_bringup_step(self.native_handle)]
    def service(self, frames=1):self._native_lib.courier_bringup_service(self.native_handle, frames)


for _name, _ in BringUpState._fields_:
    setattr(NativeCodecBringUp, _name, NativeField(_name))

"""Live control view of the native silicon DAA register device."""
import ctypes as c
from collections.abc import MutableMapping

from .analog_native import NativeField
from .codec import SiliconDaa, RESET_VALUES, CHIP_ID, EXTENDED_ID


class SiliconState(c.Structure):
    _fields_ = [(name, c.c_int64) for name in (
        'line', 'revision', 'off_hook', 'line_connected', 'loop_current_ma',
        'ring_positive', 'ring_negative', 'receive_overload', 'billing_tone',
        'frames', 'resets', 'settling', 'sticky_status')]
    _fields_ += [('registers', c.c_uint16 * 128)]


class NativeRegisters(MutableMapping):
    addresses = tuple(sorted((*RESET_VALUES, CHIP_ID, EXTENDED_ID)))

    def __init__(self, owner):self.owner = owner
    def __iter__(self):return iter(self.addresses)
    def __len__(self):return len(self.addresses)
    def __getitem__(self, address):
        if address not in self.addresses:raise KeyError(address)
        return self.owner._native_state.registers[address]
    def __setitem__(self, address, value):
        if address not in self.addresses:raise KeyError(address)
        self.owner._native_state.registers[address] = value
    def __delitem__(self, address):raise TypeError('native register addresses are fixed')


class NativeSiliconDaa(SiliconDaa):
    @classmethod
    def adopt(cls, device):
        if isinstance(device, cls):return device
        if type(device) is not SiliconDaa:
            raise TypeError('custom silicon DAA models retain their own implementation')
        from .dsp import load_library
        lib = load_library()
        lib.courier_silicon_layout.restype = c.c_size_t
        lib.courier_silicon_action.argtypes = [c.c_void_p, c.c_int, c.c_int64, c.c_int64]
        lib.courier_silicon_action.restype = c.c_int
        if lib.courier_silicon_layout() != c.sizeof(SiliconState):
            raise RuntimeError('native silicon DAA ABI mismatch')
        values = dict(vars(device));registers = dict(device.registers)
        device._native_buffer = bytearray(c.sizeof(SiliconState))
        device._native_state = SiliconState.from_buffer(device._native_buffer)
        device._native_lib = lib
        device.__class__ = cls
        for name, _ in SiliconState._fields_[:-1]:
            setattr(device, '_' + name if name in ('settling', 'sticky_status') else name,
                    values['_' + name if name in ('settling', 'sticky_status') else name])
        for address, value in registers.items():device.registers[address] = value
        return device

    @property
    def native_address(self):return c.addressof(self._native_state)
    @property
    def registers(self):return NativeRegisters(self)

    def _action(self, action, a=0, b=0):
        result = self._native_lib.courier_silicon_action(self.native_address, action, a, b)
        if result < 0:raise ValueError(f'no register at {a:#04x}')
        return result

    def reset(self):self._action(0)
    def elapse(self, frames=1):self._action(1, frames)
    def set_hook(self, off_hook):self._action(2, bool(off_hook))
    def write(self, address, value):self._action(3, address, value & 0xffff)
    def read(self, address):return self._action(4, address)


for _name, _ in SiliconState._fields_[:-1]:
    _python = '_' + _name if _name in ('settling', 'sticky_status') else _name
    setattr(NativeSiliconDaa, _python, NativeField(_name, boolean=_name in (
        'off_hook', 'line_connected', 'ring_positive', 'ring_negative', 'receive_overload', 'billing_tone')))

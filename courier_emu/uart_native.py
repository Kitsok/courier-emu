"""Python inspection and reference API for the authoritative native EB UART."""
import ctypes as c
from dataclasses import fields

from .dsp import load_library
from .uart import EbSerial


class SerialState(c.Structure):
    _fields_ = [(name, c.c_uint64) for name in (
        'control', 'baud_compare', 'baud_count', 'receive_holding',
        'transmitted', 'received', 'holding', 'receive_ready', 'clear_to_send')]
    _fields_ += [('native_reads', c.c_uint64), ('native_writes', c.c_uint64),
                 ('read_counts', (c.c_uint64 * 2) * 5), ('read_mask', c.c_uint64)]


class NativeEbSerial(EbSerial):
    def __init__(self, reference, irq_state):
        library = load_library()
        layout = (c.c_uint64 * 3)()
        library.courier_serial186_layout(layout)
        expected = (c.sizeof(SerialState), SerialState.transmitted.offset,
                    SerialState.clear_to_send.offset)
        if tuple(layout) != expected:
            raise RuntimeError(f'native UART layout {tuple(layout)} != {expected}')
        self.buffer = bytearray(c.sizeof(SerialState))
        self.native_state = SerialState.from_buffer(self.buffer)
        self.address = c.addressof(self.native_state)
        self.irq_state = irq_state
        self.irq_address = c.addressof(irq_state)
        self.pending = reference.pending
        for name, _ in SerialState._fields_[:9]:
            setattr(self, name, getattr(reference, name))
        # Short operations keep the GIL, as does native instruction execution.
        self._read = c.PYFUNCTYPE(c.c_uint32, c.c_void_p, c.c_uint32)(
            c.cast(library.courier_serial186_read, c.c_void_p).value)
        self._write = c.PYFUNCTYPE(c.c_int, c.c_void_p, c.c_void_p,
                                 c.c_uint32, c.c_uint64)(
            c.cast(library.courier_serial186_write, c.c_void_p).value)
        self._deliver = c.PYFUNCTYPE(None, c.c_void_p, c.c_void_p, c.c_uint8)(
            c.cast(library.courier_serial186_deliver, c.c_void_p).value)

    def read(self, address, size):
        value = self._read(self.address, address)
        return None if value == 0xffffffff else value

    def write(self, address, size, value):
        byte = self._write(self.address, self.irq_address, address, value)
        return None if byte < 0 else byte

    def deliver(self, byte):
        self._deliver(self.address, self.irq_address, byte)

    def finish_reads(self, counts):
        state = self.native_state
        mask = state.read_mask
        state.read_mask = 0
        while mask:
            bit = mask & -mask
            mask ^= bit
            index, width = divmod(bit.bit_length() - 1, 2)
            counts[('read', 0xff60 + index * 2, width + 1)] += state.read_counts[index][width]
            state.read_counts[index][width] = 0

    def reference(self):
        from collections import deque
        return EbSerial(**{f.name: deque(self.pending) if f.name == 'pending'
                           else getattr(self, f.name) for f in fields(EbSerial)})


def _field(name):
    boolean = name in ('holding', 'receive_ready', 'clear_to_send')
    return property(lambda self: bool(getattr(self.native_state, name)) if boolean
                    else getattr(self.native_state, name),
                    lambda self, value: setattr(self.native_state, name, value))


for _name, _ctype in SerialState._fields_[:9]:
    setattr(NativeEbSerial, _name, _field(_name))

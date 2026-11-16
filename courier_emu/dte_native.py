"""Live Python view of the native DTE input wire."""
import ctypes as c

from .dsp import load_library
from .uart import DteTransmitLine


class DteWireState(c.Structure):
    _fields_ = [(name, c.c_uint64) for name in
                ('bit_instructions', 'byte', 'started', 'edge')]


class NativeDteTransmitLine(DteTransmitLine):
    def __init__(self, reference):
        library = load_library()
        library.courier_dte186_layout.restype = c.c_size_t
        if library.courier_dte186_layout() != c.sizeof(DteWireState):
            raise RuntimeError('native DTE wire ABI mismatch')
        if reference.bit_instructions <= 0:
            raise ValueError('DTE bit period must be positive')
        self.buffer = bytearray(c.sizeof(DteWireState))
        self.state = DteWireState.from_buffer(self.buffer)
        self.address = c.addressof(self.state)
        self.state.bit_instructions = reference.bit_instructions
        self.byte, self.started, self._edge = reference.byte, reference.started, reference._edge
        self._wire = c.PYFUNCTYPE(c.c_int64, c.c_void_p, c.c_uint, c.c_int64, c.c_uint)(
            c.cast(library.courier_dte186_wire, c.c_void_p).value)

    bit_instructions = property(lambda self: self.state.bit_instructions,
                                lambda self, value: setattr(self.state, 'bit_instructions', value))
    byte = property(lambda self: None if self.state.byte == 256 else self.state.byte,
                    lambda self, value: setattr(self.state, 'byte', 256 if value is None else value))
    started = property(lambda self: self.state.started,
                       lambda self, value: setattr(self.state, 'started', value))
    _edge = property(lambda self: bool(self.state.edge),
                     lambda self, value: setattr(self.state, 'edge', value))

    def begin(self, byte, instructions):
        self._wire(self.address, 0, instructions, byte & 255)

    def take_edge(self):
        return bool(self._wire(self.address, 1, 0, 0))

    def bit_index(self, instructions):
        return self._wire(self.address, 2, instructions, 0)

    def level(self, instructions):
        value = self._wire(self.address, 3, instructions, 0)
        if value < 0:
            raise ValueError('negative shift count')
        return value

    def complete(self, instructions):
        return bool(self._wire(self.address, 4, instructions, 0))

    def idle(self):
        self._wire(self.address, 5, 0, 0)

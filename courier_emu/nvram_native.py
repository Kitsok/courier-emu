"""Existing NVRAM interface with the serial protocol implemented natively."""
import ctypes as c

from .dsp import load_library
from .nvram import CourierNvram


FIELDS = ('reads', 'writes', 'erases', 'write_enabled', '_clock', '_selected',
          '_bits', '_count', '_started', '_opcode', '_address', '_pending',
          '_pending_count', '_shift_out', '_data_out', 'trace_count', 'pio_data_in')


class MicrowireState(c.Structure):
    _fields_ = [('data', c.c_uint8 * 512)] + [
        (name.lstrip('_'), c.c_uint64) for name in FIELDS
    ] + [('traces', (c.c_char * 64) * 256), ('pio_reads', (c.c_uint64 * 2) * 8),
         ('pio_read_mask', c.c_uint64)]


class NativeCourierNvram(CourierNvram):
    @classmethod
    def adopt(cls, device):
        if type(device) is not CourierNvram:
            return device
        library = load_library()
        layout = (c.c_uint64 * 2)()
        library.courier_microwire_layout(layout)
        if tuple(layout) != (c.sizeof(MicrowireState), MicrowireState.traces.offset):
            raise RuntimeError('native Microwire ABI mismatch')
        buffer = bytearray(c.sizeof(MicrowireState))
        state = MicrowireState.from_buffer(buffer)
        state.data[:] = device.data
        for name in FIELDS[:-2]:
            value = getattr(device, name)
            if value is None:
                value = 4 if name == '_opcode' else 65536
            setattr(state, name.lstrip('_'), value)
        for index, entry in enumerate(device.trace[:256]):
            state.traces[index].value = entry.encode('ascii')[:63]
            state.trace_count += 1
        device._native_buffer, device.native_state = buffer, state
        device._native_address = c.addressof(state)
        device._native_write = c.PYFUNCTYPE(None, c.c_void_p, c.c_uint)(
            c.cast(library.courier_microwire_write, c.c_void_p).value)
        device._native_read = c.PYFUNCTYPE(c.c_uint, c.c_void_p)(
            c.cast(library.courier_microwire_read, c.c_void_p).value)
        device.data = memoryview(buffer)[:512]
        device.__class__ = cls
        return device

    @property
    def trace(self):
        state = self.native_state
        return [state.traces[i].value.decode('ascii') for i in range(state.trace_count)]

    def write_latch(self, value):
        self._native_write(self._native_address, value)

    def read_latch(self):
        return self._native_read(self._native_address)

    def finish_reads(self, counts):
        state = self.native_state
        mask = state.pio_read_mask
        state.pio_read_mask = 0
        while mask:
            bit = mask & -mask
            mask ^= bit
            index, width = divmod(bit.bit_length() - 1, 2)
            counts[('read', 0xff50 + index * 2, width + 1)] += state.pio_reads[index][width]
            state.pio_reads[index][width] = 0


def _field(name):
    key = name.lstrip('_')
    boolean = name in ('write_enabled', '_clock', '_selected', '_started', '_data_out')

    def get(self):
        value = getattr(self.native_state, key)
        if name == '_opcode' and value == 4 or name == '_shift_out' and value == 65536:
            return None
        return bool(value) if boolean else value

    def set(self, value):
        if value is None:
            value = 4 if name == '_opcode' else 65536
        setattr(self.native_state, key, value)

    return property(get, set)


for _name in FIELDS:
    setattr(NativeCourierNvram, _name, _field(_name))

"""Native UART-to-terminal output with live machine state."""
import ctypes as c
from .dsp import load_library
from .operational import LOG
from .receive_native import NativeReceiveMachine


class TransmitState(c.Structure):
    _fields_ = [(name, c.c_uint64) for name in ('online', 'truncated', 'size', 'recent_size')]
    _fields_ += [('writes', c.c_uint64 * 2)]
    _fields_ += [(name, c.c_uint64) for name in
                ('error', 'entered', 'left', 'schedule_pending', 'schedule_ready', 'activity')]
    _fields_ += [('serial', c.c_uint8 * 65536), ('recent', c.c_uint8 * 12)]


class NativeTransmitter:
    def __init__(self, machine, uc):
        lib = load_library()
        lib.courier_transmit_layout.restype = c.c_size_t
        if lib.courier_transmit_layout() != c.sizeof(TransmitState):
            raise RuntimeError('native transmit ABI mismatch')
        self.buffer = bytearray(c.sizeof(TransmitState))
        self.state = TransmitState.from_buffer(self.buffer)
        self.state.online = machine.online_mode
        self.state.truncated = machine.serial_truncated
        serial = bytes(machine.serial)
        self.state.size = len(serial)
        self.state.serial[:len(serial)] = serial
        previous = getattr(machine, '_native_transmitter', None)
        recent = (bytes(previous.state.recent[:previous.state.recent_size]) if previous is not None
                  else bytes(v & 127 for v in machine._serial_recent))
        self.state.recent_size = len(recent)
        self.state.recent[:len(recent)] = recent
        self.state.schedule_pending = bool(machine._serial_input_after_connect)
        self.machine, self.console = machine, machine.console
        self._memory = (c.c_uint8 * len(uc.memory)).from_buffer(uc.memory)
        layout = machine._rom_serial
        values = (c.c_uint64 * 4)(layout.callbacks, layout.command_idle,
                                 layout.command_collecting, layout.online_idle)

        def bind(name, result, *args):
            return c.PYFUNCTYPE(result, *args)(
                c.cast(getattr(lib, 'courier_transmit_' + name), c.c_void_p).value)

        create = bind('create', c.c_void_p, c.c_void_p, c.c_void_p, c.c_void_p, c.c_void_p)
        self._destroy = bind('destroy', None, c.c_void_p)
        self.handle = create(c.addressof(self.state), self.console._terminal_handle,
                             c.addressof(self._memory), values)
        if not self.handle:
            raise MemoryError('cannot allocate native transmitter')
        self.write = lambda byte: self._write(self.handle, byte)
        self._write = bind('write', None, c.c_void_p, c.c_uint)
        self._take = bind('take', c.c_size_t, c.c_void_p, c.c_void_p, c.c_size_t)
        self._results = c.create_string_buffer(65536)

    def __del__(self):
        if getattr(self, 'handle', None):
            self._destroy(self.handle)
            self.handle = None

    def finish(self):
        state, machine = self.state, self.machine
        if state.error:
            raise OSError(state.error, 'native terminal output failed')
        if not state.activity:
            return
        state.activity = 0
        for i in range(2):
            if state.writes[i]:
                machine.mmio_counts[('write', 0xff6a, i + 1)] += state.writes[i]
                state.writes[i] = 0
        if state.entered:
            machine.serial_trace.extend(['entered-data-mode'] * state.entered)
            state.entered = 0
        if state.left:
            machine.serial_trace.extend(['left-data-mode'] * state.left)
            state.left = 0
        size = self._take(self.handle, self._results, len(self._results))
        for line in c.string_at(self._results, size).splitlines() if size else ():
            LOG.info('[at] result: %s', line.decode('ascii'))
        if state.schedule_ready:
            machine._schedule_connected_input()
            state.schedule_pending = bool(machine._serial_input_after_connect)
            state.schedule_ready = 0


class NativeTransmitMachine(NativeReceiveMachine):
    online_mode = property(lambda self: bool(self._native_transmitter.state.online),
                           lambda self, value: setattr(self._native_transmitter.state, 'online', value))
    serial_truncated = property(lambda self: bool(self._native_transmitter.state.truncated),
                                lambda self, value: setattr(self._native_transmitter.state, 'truncated', value))
    serial = property(lambda self: bytearray(self._native_transmitter.state.serial[:self._native_transmitter.state.size]))

    @classmethod
    def adopt(cls, machine, uc):
        if type(machine) not in (NativeReceiveMachine, cls):
            return None
        output = NativeTransmitter(machine, uc)
        machine._native_transmitter = output
        machine.__class__ = cls
        return output

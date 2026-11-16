"""Host command notifications from native terminal/receive processing."""
import ctypes as c
import weakref
from .dsp import load_library
from .operational import LOG


class InputState(c.Structure):
    _fields_ = [(name, c.c_uint64) for name in ('events', 'error', 'int1_delivered', 'opened_at')]


class NativeInput:
    def __init__(self, machine, receiver, output):
        lib = load_library()
        lib.courier_input_layout.restype = c.c_size_t
        if lib.courier_input_layout() != c.sizeof(InputState):
            raise RuntimeError('native input service ABI mismatch')
        self.state = InputState()
        self._anchors = (receiver, output, machine.uart, machine.dte_line,
                         machine.timers, machine.dsp_bridge._native_lifecycle)
        parts = (c.c_void_p * 7)(receiver.handle, machine.uart.address,
            machine.dte_line.address, machine._native_service_address,
            machine.timers.address, machine.dsp_bridge._native_lifecycle.handle, output.handle)

        def bind(name, result, *args):
            return c.PYFUNCTYPE(result, *args)(
                c.cast(getattr(lib, 'courier_input_' + name), c.c_void_p).value)

        create = bind('create', c.c_void_p, c.c_void_p, c.c_void_p)
        destroy = bind('destroy', None, c.c_void_p)
        self.handle = create(c.addressof(self.state), parts)
        if not self.handle: raise MemoryError('cannot allocate native input service')
        self._finalizer = weakref.finalize(self, destroy, self.handle)
        self.poll = lambda: self._poll(self.handle)
        self._poll = bind('poll', None, c.c_void_p)
        self._tick = bind('tick', None, c.c_void_p, c.c_void_p, c.c_uint64, c.c_uint32)
        self._text = bind('text', c.c_size_t, c.c_void_p, c.c_uint, c.c_void_p, c.c_size_t)
        self._buffer = c.create_string_buffer(1024)
        self._memory = receiver.memory_address

    def tick(self, now, flags):
        self._tick(self.handle, self._memory, now, flags)

    def finish(self, machine):
        events = self.state.events
        if self.state.int1_delivered:
            machine.int1_delivered = True
        if not events: return
        if events & 8: raise OSError(self.state.error, 'native terminal input failed')
        self.state.events = 0
        if events & 16:
            machine._trace_serial('rom-dte: firmware attention adapter')
            machine._trace_serial(f'rom-dte: receiver ready at {self.state.opened_at}')
        if events & 2:
            size = self._text(self.handle, 1, self._buffer, len(self._buffer))
            LOG.info('[at] command: %r', c.string_at(self._buffer, size).decode('ascii', 'backslashreplace'))
        if events & 1 and machine.dsp_bridge is not None:
            size = self._text(self.handle, 0, self._buffer, len(self._buffer))
            machine.dsp_bridge.note_dte_command(c.string_at(self._buffer, size)[2:])
        if events & 4:
            machine.stop_requested = True

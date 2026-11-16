"""Existing console API backed by native nonblocking terminal I/O."""
import ctypes as c
import math
import os

from .console import SerialConsole
from .dsp import load_library


class TerminalState(c.Structure):
    _fields_ = [('fd', c.c_int64), ('lamps_fd', c.c_int64)] + [
        (name, c.c_uint64) for name in ('received', 'sent', 'dropped', 'closed', 'pending')]


class NativeSerialConsole(SerialConsole):
    @classmethod
    def adopt(cls, console):
        if type(console) is not SerialConsole or console._pending or console._lamps:
            return console
        library = load_library()
        library.courier_terminal_layout.restype = c.c_size_t
        if library.courier_terminal_layout() != c.sizeof(TerminalState):
            raise RuntimeError('native terminal ABI mismatch')
        buffer = bytearray(c.sizeof(TerminalState))
        state = TerminalState.from_buffer(buffer)
        state.fd = console.fd
        state.lamps_fd = -1 if console.lamps_fd is None else console.lamps_fd
        for name in ('received', 'sent', 'dropped', 'closed'):
            setattr(state, name, getattr(console, name))

        def bind(name, result, *args):
            return c.PYFUNCTYPE(result, c.c_void_p, *args)(
                c.cast(getattr(library, 'courier_terminal_' + name), c.c_void_p).value)

        create = bind('create', c.c_void_p)
        handle = create(c.addressof(state))
        if not handle:
            raise MemoryError('cannot allocate native terminal transport')
        console._terminal_buffer, console._terminal_state = buffer, state
        console._terminal_handle = handle
        console._terminal_destroy = bind('destroy', None)
        console._terminal_read = bind('read', c.c_int64, c.c_void_p, c.c_size_t)
        console._terminal_write = bind('write', c.c_int, c.c_uint)
        console._terminal_drain = bind('drain', c.c_int)
        console._terminal_wait = bind('wait', c.c_int, c.c_int)
        console._terminal_lamps = bind('lamps', c.c_int, c.c_char_p, c.c_size_t)
        console._terminal_close = bind('close', None)
        console._input = c.create_string_buffer(4096)
        console._input_size = 4096
        console._input_address = c.addressof(console._input)
        for name in ('fd', 'lamps_fd', 'received', 'sent', 'dropped', 'closed', '_pending', '_lamps'):
            console.__dict__.pop(name, None)
        console.__class__ = cls
        return console

    def __del__(self):
        handle = getattr(self, '_terminal_handle', None)
        if handle:
            self._terminal_destroy(handle)
            self._terminal_handle = None

    @staticmethod
    def _check(error):
        if error:
            raise OSError(error, os.strerror(error))

    def poll(self, limit=4096):
        if limit <= 0:
            self._drain()
            return b''
        if limit > self._input_size:
            self._input = c.create_string_buffer(limit)
            self._input_size = limit
            self._input_address = c.addressof(self._input)
        count = self._terminal_read(self._terminal_handle, self._input_address, limit)
        if count < 0:
            self._check(-count)
        return self._input.raw[:count] if count else b''

    def write(self, value):
        error = self._terminal_write(self._terminal_handle, value & 255)
        if error:
            self._check(error)

    def _drain(self):
        self._check(self._terminal_drain(self._terminal_handle))

    def wait(self, timeout):
        milliseconds = min(2147483647, math.ceil(max(0.0, timeout) * 1000))
        result = self._terminal_wait(self._terminal_handle, milliseconds)
        if result < 0:
            self._check(-result)
        return bool(result)

    def show_lamps(self, line):
        if self._terminal_state.lamps_fd < 0:
            return
        data = line.encode('ascii')
        self._check(self._terminal_lamps(self._terminal_handle, data, len(data)))

    def native_idle_poll_fd(self):
        state = self._terminal_state
        return state.fd if not state.closed and not state.pending and state.lamps_fd < 0 else None

    def close(self):
        self._terminal_close(self._terminal_handle)

    def summary(self):
        state = self._terminal_state
        return dict(received=state.received, sent=state.sent, dropped=state.dropped,
                    pending=state.pending, closed=bool(state.closed))


def _field(name):
    def get(self):
        value = getattr(self._terminal_state, name)
        return bool(value) if name == 'closed' else None if name == 'lamps_fd' and value < 0 else value

    def set(self, value):
        setattr(self._terminal_state, name, -1 if value is None else value)

    return property(get, set)


for _name, _type in TerminalState._fields_[:-1]:
    setattr(NativeSerialConsole, _name, _field(_name))

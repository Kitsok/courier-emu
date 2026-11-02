"""Control and diagnostic views of the persistent native codec/line pipeline."""
import ctypes as c
import math
import sys
import weakref
from collections.abc import MutableSequence

from .analog_native import NativeDaa, pcm
from .resample_native import StreamState
from .line import LINE_FRAME_SAMPLES, LINE_FRAME_INSTRUCTIONS
from .sip_line_native import NativeSipLine


class BoardMediaState(c.Structure):
    _fields_ = [(name, c.c_uint64) for name in
                ('tx_index', 'codec_last', 'idle', 'frames', 'tx_consumed', 'resampled', 'crossing_retune', 'reported_tx_index')]
    _fields_ += [(name, c.c_int64) for name in
                 ('peak_codec', 'peak_line', 'line_rx_peak', 'codec_in_peak', 'handed_peak',
                  'handed_at', 'handed_ever', 'queue_peak')]
    _fields_ += [(name, c.c_uint64) for name in ('queue_input', 'clocked_input', 'replayed')]
    _fields_ += [('cushion_rate', c.c_double)]
    _fields_ += [('codec_instructions', c.c_int64)]


_LIBRARY = None


def library():
    global _LIBRARY
    if _LIBRARY is not None:
        return _LIBRARY
    from .dsp import load_library
    lib = load_library()
    signatures = {
        'create': ([c.c_void_p, c.c_void_p, c.c_size_t, c.c_uint64, c.c_uint64, c.c_int, c.c_int], c.c_void_p),
        'destroy': ([c.c_void_p], None),
        'state': ([c.c_void_p], c.POINTER(BoardMediaState)),
        'layout': ([], c.c_size_t),
        'begin': ([c.c_void_p, c.c_void_p, c.c_int64], c.c_int),
        'resume': ([c.c_void_p, c.c_void_p], c.c_int),
        'reset': ([c.c_void_p, c.c_void_p, c.c_int], c.c_int),
        'values': ([c.c_void_p, c.c_int, c.POINTER(c.c_int16), c.c_size_t, c.c_int], c.c_size_t),
        'collect': ([c.c_void_p, c.c_void_p], c.c_int),
        'queue': ([c.c_void_p, c.c_void_p, c.POINTER(c.c_int32), c.c_size_t, c.c_int64], c.c_int),
        'replace': ([c.c_void_p, c.c_int, c.POINTER(c.c_int16), c.c_size_t], None),
        'stream': ([c.c_void_p, c.c_int], c.POINTER(StreamState)),
        'digits': ([c.c_void_p, c.c_char_p], c.c_char_p),
        'codec': ([c.c_void_p, c.c_void_p], None),
        'service_codec': ([c.c_void_p], None),
    }
    for name, (args, result) in signatures.items():
        fn = getattr(lib, 'courier_board_media_' + name)
        fn.argtypes, fn.restype = args, result
    if lib.courier_board_media_layout() != c.sizeof(BoardMediaState):
        raise RuntimeError('native board media ABI mismatch')
    _LIBRARY = lib
    return lib


class NativeBoardMedia:
    def __init__(self, line, daa, batch):
        if not isinstance(line, NativeSipLine) or not line._native_finalizer.alive:
            raise TypeError('native board media requires a live native subscriber port')
        self.line = line
        self.daa = NativeDaa.adopt(daa) if daa is not None else None
        self._lib = library()
        self._handle = self._lib.courier_board_media_create(
            line._native_port, self.daa.native_address if daa is not None else None,
            LINE_FRAME_SAMPLES, LINE_FRAME_INSTRUCTIONS, batch,
            hasattr(math, 'sumprod'), sys.version_info >= (3, 12))
        if not self._handle:
            raise RuntimeError('native board media allocation failed')
        # Pin only the DAA storage, not the Python device/line graph. Native
        # port references retain the other resources independently.
        self._device_storage = [self.daa._native_buffer if self.daa is not None else None]
        self._finalizer = weakref.finalize(
            self, self._destroy, self._lib, self._handle,
            self._device_storage)
        self.state = self._lib.courier_board_media_state(self._handle).contents

    @staticmethod
    def _destroy(lib, handle, daa_buffer):
        lib.courier_board_media_destroy(handle)

    @property
    def handle(self):
        if not self._finalizer.alive:
            raise RuntimeError('native board media is closed')
        return self._handle

    def service(self, core, instructions):
        if self._lib.courier_board_media_begin(self.handle, core.handle, instructions):
            raise RuntimeError('native codec service could not begin')
        self.resume(core)

    def resume(self, core):
        while True:
            event = self._lib.courier_board_media_resume(self.handle, core.handle)
            if not event:
                return
            if event < 0:
                raise RuntimeError('native codec service failed')
            self.line.control_event(event)

    def reset(self, core, *, rebuild=False):
        if self._lib.courier_board_media_reset(self.handle, core.handle, rebuild):
            raise RuntimeError('native codec reset could not complete')

    def values(self, which, *, consume=False):
        if not self._finalizer.alive:
            if consume:
                raise RuntimeError('native board media is closed')
            return list(self._final_queues[which])
        fn = self._lib.courier_board_media_values
        count = fn(self.handle, which, None, 0, False)
        data = (c.c_int16 * count)()
        fn(self.handle, which, data, count, consume)
        return list(data)

    def replace(self, which, values):
        data = (c.c_int16 * len(values))(*values)
        self._lib.courier_board_media_replace(self.handle, which, data, len(data))

    def collect(self, core):
        if self._lib.courier_board_media_collect(self.handle, core.handle):
            raise RuntimeError('native transmit collection failed')

    def attach_codec(self, master):
        self._device_storage.append(master.codec._native_buffer)
        self._lib.courier_board_media_codec(self.handle, master.native_handle)
        self._native_codec_attached = True

    def service_codec(self):self._lib.courier_board_media_service_codec(self.handle)

    def queue(self, core, samples, instructions):
        data = pcm(samples)
        if self._lib.courier_board_media_queue(self.handle, core.handle, data, len(data), instructions):
            raise RuntimeError('native receive delivery failed')

    def close(self):
        if self._finalizer.alive:
            self._final_queues = tuple(self.values(k) for k in range(3))
            self._final_digits = self._lib.courier_board_media_digits(self.handle, None).decode()
            self._final_streams = tuple(StreamState.from_buffer_copy(
                self._lib.courier_board_media_stream(self.handle, k).contents) for k in range(2))
            self.state = BoardMediaState.from_buffer_copy(self.state)
            self._finalizer()


class NativePcmQueue(MutableSequence):
    """Diagnostic/control operations; the native pipeline accesses its deque directly."""
    def __init__(self, owner, which):
        self.owner, self.which = owner, which

    def __len__(self):
        if not self.owner._finalizer.alive:
            return len(self.owner._final_queues[self.which])
        return self.owner._lib.courier_board_media_values(self.owner.handle, self.which, None, 0, False)

    def __getitem__(self, index):
        return self.owner.values(self.which)[index]

    def __setitem__(self, index, value):
        values = self.owner.values(self.which);values[index] = value
        self.owner.replace(self.which, values)

    def __delitem__(self, index):
        values = self.owner.values(self.which);del values[index]
        self.owner.replace(self.which, values)

    def insert(self, index, value):
        values = self.owner.values(self.which);values.insert(index, value)
        self.owner.replace(self.which, values)

    def __iter__(self):
        return iter(self.owner.values(self.which))

    def extend(self, values):
        self.owner.replace(self.which, self.owner.values(self.which)+list(values))

    def clear(self):
        self.owner.replace(self.which, [])

    def popleft(self):
        if not self:
            raise IndexError('pop from an empty deque')
        data = (c.c_int16 * 1)()
        self.owner._lib.courier_board_media_values(self.owner.handle, self.which, data, 1, True)
        return data[0]


class NativeStreamView:
    _timed = None  # The legacy worker must not borrow/republish native history.

    def __init__(self, owner, receive):
        self.owner, self.receive = owner, receive

    def __getattr__(self, name):
        state = (self.owner._lib.courier_board_media_stream(self.owner.handle, self.receive).contents
                 if self.owner._finalizer.alive else self.owner._final_streams[self.receive])
        if name in ('input_rate', 'output_rate', 'converted'):
            return getattr(state, name)
        raise AttributeError(name)

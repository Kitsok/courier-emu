"""Control and diagnostic views of the persistent native codec/line pipeline."""
import ctypes as c
import math
import sys
import weakref

from .analog_native import NativeDaa
from .line import LINE_FRAME_SAMPLES, LINE_FRAME_INSTRUCTIONS
from .sip_line_native import NativeSipLine


class BoardMediaState(c.Structure):
    _fields_ = [(name, c.c_uint64) for name in
                ('tx_index', 'codec_last', 'idle', 'frames', 'tx_consumed', 'resampled', 'crossing_retune')]
    _fields_ += [(name, c.c_int64) for name in
                 ('peak_codec', 'peak_line', 'line_rx_peak', 'codec_in_peak', 'handed_peak',
                  'handed_at', 'handed_ever', 'queue_peak')]
    _fields_ += [(name, c.c_uint64) for name in ('queue_input', 'clocked_input', 'replayed')]


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
        self._finalizer = weakref.finalize(
            self, self._destroy, self._lib, self._handle,
            self.daa._native_buffer if self.daa is not None else None)
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
        fn = self._lib.courier_board_media_values
        count = fn(self.handle, which, None, 0, False)
        data = (c.c_int16 * count)()
        fn(self.handle, which, data, count, consume)
        return list(data)

    def close(self):
        if self._finalizer.alive:
            self.state = BoardMediaState.from_buffer_copy(self.state)
            self._finalizer()

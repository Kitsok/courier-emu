"""Control-plane view of the native streaming PCM converter.

Native frame owners use Stream directly; this adapter supports diagnostics and
reference comparisons without making Python the owner of FIR history.
"""
import ctypes as c
import math
import sys
import weakref


class StreamState(c.Structure):
    _fields_ = [(name, c.c_double) for name in
                ('input_rate', 'output_rate', 'position', 'input_time', 'next_time')]
    _fields_ += [('converted', c.c_uint64), ('timed', c.c_uint64)]


def library():
    from .dsp import load_library
    lib = load_library()
    signatures = {
        'create': ([c.c_int, c.c_int], c.c_void_p),
        'destroy': ([c.c_void_p], None),
        'convert': ([c.c_void_p, c.POINTER(c.c_int16), c.c_size_t,
                     c.c_double, c.c_double], c.c_int),
        'output': ([c.c_void_p, c.POINTER(c.c_size_t)], c.POINTER(c.c_int16)),
        'snapshot': ([c.c_void_p, c.POINTER(StreamState)], None),
        'layout': ([], c.c_size_t),
        'kernel': ([c.c_double, c.c_int], c.POINTER(c.c_double)),
    }
    for name, (args, result) in signatures.items():
        fn = getattr(lib, 'courier_stream_' + name)
        fn.argtypes, fn.restype = args, result
    if lib.courier_stream_layout() != c.sizeof(StreamState):
        raise RuntimeError('native streaming resampler ABI mismatch')
    return lib


class NativeResampler:
    def __init__(self):
        self._lib = library()
        self._handle = self._lib.courier_stream_create(
            hasattr(math, 'sumprod'), sys.version_info >= (3, 12))
        if not self._handle:
            raise MemoryError('native streaming resampler allocation failed')
        self._finalizer = weakref.finalize(self, self._lib.courier_stream_destroy, self._handle)

    def close(self):
        self._finalizer()

    def snapshot(self):
        if not self._finalizer.alive:
            raise RuntimeError('resampler is closed')
        state = StreamState()
        self._lib.courier_stream_snapshot(self._handle, c.byref(state))
        return state

    def convert(self, samples, input_rate, output_rate):
        if not self._finalizer.alive:
            raise RuntimeError('resampler is closed')
        if not math.isfinite(input_rate) or not math.isfinite(output_rate):
            raise ValueError('sample rates must be finite')
        values = (c.c_int16 * len(samples))(*samples)
        if self._lib.courier_stream_convert(self._handle, values, len(values), input_rate, output_rate):
            raise MemoryError('native streaming conversion failed')
        count = c.c_size_t()
        output = self._lib.courier_stream_output(self._handle, c.byref(count))
        return list(output[:count.value])

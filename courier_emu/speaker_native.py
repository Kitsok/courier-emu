"""Host configuration for native asynchronous speaker playback."""
import ctypes as c
import shutil
import weakref
from .dsp import load_library
from .operational import LOG


class NativeAudioMonitor:
    def __init__(self, volume=.25, *, player=None):
        self.volume = volume
        self.player = player if player is not None else shutil.which('paplay')
        lib = load_library()

        def bind(name, result, *args):
            return c.PYFUNCTYPE(result, *args)(
                c.cast(getattr(lib, 'courier_speaker_' + name), c.c_void_p).value)

        create = bind('create', c.c_void_p, c.c_char_p, c.c_double)
        release = bind('release', None, c.c_void_p)
        self.native_speaker_handle = create(self.player.encode() if self.player else None, volume)
        if not self.native_speaker_handle:
            raise RuntimeError('cannot allocate native speaker playback')
        self._finalizer = weakref.finalize(self, release, self.native_speaker_handle)
        self._enable = bind('enable', None, c.c_void_p, c.c_int)
        self._status = bind('status', c.c_uint, c.c_void_p)
        self._close = bind('close', None, c.c_void_p)
        self._feed = bind('feed', None, c.c_void_p, c.c_void_p, c.c_size_t,
                          c.c_void_p, c.c_size_t)
        self._closed = False
        if not self.player:
            LOG.warning('[speaker] paplay is unavailable; local playback disabled')

    def set_enabled(self, value):
        self._enable(self.native_speaker_handle, value)

    @property
    def enabled(self):
        return bool(self._status(self.native_speaker_handle) & 1)

    @property
    def disabled(self):
        return bool(self._status(self.native_speaker_handle) & 2)

    def feed(self, tx, rx, *, enabled):
        # Compatibility for explicit callers. The native board feeds the
        # speaker directly, without exporting PCM frames into this method.
        self.set_enabled(enabled)
        if not enabled:
            return
        left, right = (c.c_int32 * len(tx))(*tx), (c.c_int32 * len(rx))(*rx)
        self._feed(self.native_speaker_handle, left, len(left), right, len(right))

    def close(self):
        if not self._closed:
            self._close(self.native_speaker_handle)
            self._closed = True
            if self._status(self.native_speaker_handle) & 4:
                LOG.warning('[speaker] playback failed; modem continues')

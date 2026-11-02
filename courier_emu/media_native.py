"""Control-plane interfaces to persistent native RTP media and PCM queues."""
from __future__ import annotations

from collections.abc import MutableSet
from contextlib import contextmanager
import ctypes as c
import math
import time
import weakref

from .analog_native import pcm


class MediaState(c.Structure):
    _fields_ = [(name, c.c_uint64) for name in (
        'sequence', 'timestamp', 'ssrc', 'packets_sent', 'packets_received',
        'octets_sent', 'octets_received', 'preanswer_discarded', 'primed',
        'buffer_samples', 'clocked', 'session_state', 'payload_type', 'law', 'codewords',
        'tx_audio_size', 'rx_audio_size', 'tx_codewords_size', 'rx_codewords_size', 'error')]
    _fields_ += [('next_at', c.c_double), ('gain', c.c_double)]


_LIBRARY = None
I32 = c.POINTER(c.c_int32)


def library():
    global _LIBRARY
    if _LIBRARY is not None:
        return _LIBRARY
    from .dsp import load_library
    lib = load_library()
    signatures = {
        'last_error': ([], c.c_char_p), 'layout': ([], c.c_uint64),
        'create': ([c.c_int], c.c_void_p), 'destroy': ([c.c_void_p], None),
        'stop': ([c.c_void_p], None), 'clock': ([c.c_void_p, c.c_uint64], c.c_int),
        'configure': ([c.c_void_p, c.c_uint64, c.c_uint64, c.c_uint64, c.c_uint64, c.c_double], None),
        'remote': ([c.c_void_p, c.c_char_p, c.c_uint], c.c_int),
        'retire': ([c.c_void_p, c.c_char_p, c.c_uint, c.c_int], c.c_int),
        'lock': ([c.c_void_p], None), 'unlock': ([c.c_void_p], None),
        'snapshot': ([c.c_void_p, c.POINTER(MediaState)], None),
        'set': ([c.c_void_p, c.c_uint, c.c_uint64], None),
        'next': ([c.c_void_p, c.c_double], None),
        'poll': ([c.c_void_p, c.c_double], None),
        'receive': ([c.c_void_p], None),
        'flush': ([c.c_void_p, c.c_double], None),
        'send': ([c.c_void_p, I32, c.c_size_t, c.c_int, c.c_double], None),
        'values': ([c.c_void_p, c.c_int, I32, c.c_size_t, c.c_int], c.c_size_t),
        'clear': ([c.c_void_p, c.c_int], None),
        'append': ([c.c_void_p, c.c_int, I32, c.c_size_t], None),
        'convert': ([c.c_int, c.c_int, I32, I32, c.c_size_t], None),
    }
    for name, (args, result) in signatures.items():
        fn = getattr(lib, 'courier_rtp_' + name)
        fn.argtypes, fn.restype = args, result
    if lib.courier_rtp_layout() != c.sizeof(MediaState):
        raise RuntimeError('native RTP state ABI does not match Python')
    _LIBRARY = lib
    return lib


class NativeMedia:
    def __init__(self, fd, *, sequence=0, timestamp=0, ssrc=0):
        self._lib = library()
        self._handle = self._lib.courier_rtp_create(fd)
        if not self._handle:
            raise RuntimeError(self._lib.courier_rtp_last_error().decode())
        self._finalizer = weakref.finalize(self, self._lib.courier_rtp_destroy, self._handle)
        self._final_state = None
        self.set('sequence', sequence)
        self.set('timestamp', timestamp)
        self.set('ssrc', ssrc)
        self.queues = tuple(NativeQueue(self, k) for k in range(4))

    @property
    def handle(self):
        if self._handle is None:
            raise RuntimeError('native RTP transport is closed')
        return self._handle

    def _check(self, result):
        if result:
            raise ValueError(self._lib.courier_rtp_last_error().decode())

    @contextmanager
    def control(self):
        """Apply SIP control changes atomically with respect to media I/O."""
        self._lib.courier_rtp_lock(self.handle)
        try:
            yield
        finally:
            self._lib.courier_rtp_unlock(self.handle)

    def snapshot(self):
        if self._handle is None:
            return self._final_state
        state = MediaState()
        self._lib.courier_rtp_snapshot(self.handle, c.byref(state))
        return state

    def set(self, name, value):
        if name == 'next_at':
            self._lib.courier_rtp_next(self.handle, value)
            return
        names = [name for name, _ in MediaState._fields_]
        if name not in names[:10] and name != 'error':
            raise ValueError(f'{name} is configured through the media control interface')
        self._lib.courier_rtp_set(self.handle, names.index(name), value)

    def configure(self, state, payload, law, codewords, gain):
        if not math.isfinite(gain):
            raise ValueError('media transmit gain must be finite')
        self._lib.courier_rtp_configure(self.handle, state, payload, law, codewords, gain)

    def remote(self, address):
        self._check(self._lib.courier_rtp_remote(
            self.handle, None if address is None else address[0].encode(),
            0 if address is None else address[1]))

    def retire(self, address, add=True):
        self._check(self._lib.courier_rtp_retire(
            self.handle, None if address is None else address[0].encode(),
            0 if address is None else address[1], add))

    def enable_clock(self, buffer_samples=480):
        self._check(self._lib.courier_rtp_clock(self.handle, buffer_samples))

    def poll(self, now=None):
        self._lib.courier_rtp_poll(self.handle, time.monotonic() if now is None else now)
        self.check_io()

    def check_io(self):
        state = self.snapshot()
        if state.error and not state.clocked:
            raise OSError(state.error, 'native RTP I/O failed')

    def receive(self):
        self._lib.courier_rtp_receive(self.handle)
        self.check_io()

    def flush(self, now):
        self._lib.courier_rtp_flush(self.handle, now)
        self.check_io()

    def send(self, values, *, codewords=False, now=None):
        data = pcm(values)
        self._lib.courier_rtp_send(self.handle, data, len(data), codewords,
                                  time.monotonic() if now is None else now)
        state = self.snapshot()
        if state.error and not state.clocked:
            raise OSError(state.error, 'native RTP I/O failed')

    def values(self, queue, count=None, consume=False):
        fn = self._lib.courier_rtp_values
        if count is None:
            count = fn(self.handle, queue, None, 0, False)
        if count < 0:
            raise ValueError('sample count must not be negative')
        result = (c.c_int32 * count)()
        available = fn(self.handle, queue, result, count, consume)
        return list(result[:min(available, count)])

    def close(self):
        if self._handle is not None:
            self._lib.courier_rtp_stop(self._handle)
            self._final_state = self.snapshot()
            self._finalizer()
            self._handle = None


class NativeQueue:
    """The deque operations used by SIP control, backed by the native queues."""
    def __init__(self, media, which):
        self.media, self.which = media, which

    def __len__(self):
        names = ('tx_audio_size', 'rx_audio_size', 'tx_codewords_size', 'rx_codewords_size')
        return getattr(self.media.snapshot(), names[self.which])

    @property
    def maxlen(self):
        return 16000 if self.which == 0 else None

    def __iter__(self):
        return iter(self.media.values(self.which))

    def clear(self):
        self.media._lib.courier_rtp_clear(self.media.handle, self.which)

    def extend(self, values):
        values = list(values)
        data = pcm(values)
        self.media._lib.courier_rtp_append(self.media.handle, self.which, data, len(data))

    def append(self, value):
        self.extend([value])

    def popleft(self):
        values = self.media.values(self.which, 1, True)
        if not values:
            raise IndexError('pop from an empty deque')
        return values[0]


class NativePeerSet(MutableSet):
    def __init__(self, media, values=()):
        self.media, self.data = media, set()
        media.retire(None)
        for value in values:
            self.add(value)

    def __contains__(self, value):
        return value in self.data

    def __iter__(self):
        return iter(self.data)

    def __len__(self):
        return len(self.data)

    def add(self, value):
        self.media.retire(value, True)
        self.data.add(value)

    def discard(self, value):
        self.media.retire(value, False)
        self.data.discard(value)

    def clear(self):
        self.media.retire(None)
        self.data.clear()


# SIP remains a control-plane implementation. These adapters connect its
# existing dialog state machine to the authoritative native transport.
from .sip import SipSession

SIP_STATES = ('idle', 'inviting', 'trying', 'ringing', 'incoming', 'connected', 'closed', 'failed')


class NativeSipSession(SipSession):
    @classmethod
    def adopt(cls, session):
        if isinstance(session, cls):
            return session
        if type(session) is not SipSession:
            raise TypeError('custom SIP sessions retain their own transport')
        if session._rtp_clock_thread is not None:
            raise RuntimeError('native media must be adopted before starting the Python clock')
        media = NativeMedia(session.rtp_socket.fileno(), sequence=session._rtp_sequence,
                            timestamp=session._rtp_timestamp, ssrc=session._rtp_ssrc)
        queues = (session._tx_audio, session._rx_audio, session._tx_codewords, session._rx_codewords)
        for native, old in zip(media.queues, queues):
            native.extend(old)
        for name, field in MEDIA_FIELDS.items():
            if name not in ('_rtp_sequence', '_rtp_timestamp', '_rtp_ssrc'):
                media.set(field, getattr(session, name))
        peers = NativePeerSet(media, session._retired_rtp_peers)
        session._native_media = media
        session.__class__ = cls
        for name, queue in zip(('_tx_audio', '_rx_audio', '_tx_codewords', '_rx_codewords'), media.queues):
            object.__setattr__(session, name, queue)
        object.__setattr__(session, '_retired_rtp_peers', peers)
        session._sync_native_media()
        media.remote(session.remote_rtp)
        return session

    def _sync_native_media(self):
        self._native_media.configure(SIP_STATES.index(self.state), self.payload_type,
                                     self.config.codec == 'pcma', self.codewords, self.transmit_gain)

    def __setattr__(self, name, value):
        media = self.__dict__.get('_native_media')
        if media is not None and name == '_retired_rtp_peers':
            value = NativePeerSet(media, value)
        object.__setattr__(self, name, value)
        if media is not None:
            if name in ('state', 'payload_type', 'codewords', 'transmit_gain'):
                self._sync_native_media()
            elif name == 'remote_rtp':
                media.remote(value)
            elif name == 'error' and not value:
                media.set('error', 0)

    def enable_media_clock(self, *, buffer_samples=480):
        self._native_media.enable_clock(buffer_samples)

    def _receive_rtp(self):
        self._native_media.receive()
        error = self._native_media.snapshot().error
        if error:
            self.error = str(OSError(error, 'native RTP I/O failed'))

    def _flush_rtp(self, now):
        self._native_media.flush(now)

    def _flush_rtp_locked(self, now):
        self._native_media.flush(now)

    def send_audio(self, samples):
        self._native_media.send(samples)

    def send_pcmu(self, octets):
        self._native_media.send(octets, codewords=True)

    def receive_audio(self):
        return self._native_media.values(1, consume=True)

    def receive_pcmu(self, count=None):
        return bytes(self._native_media.values(3, None if count is None else max(0, count), True))

    def poll(self):
        with self._native_media.control():
            return super().poll()

    def start_call(self, number):
        with self._native_media.control():
            return super().start_call(number)

    def answer_incoming(self):
        with self._native_media.control():
            return super().answer_incoming()

    def hangup(self):
        with self._native_media.control():
            return super().hangup()

    def status(self):
        state = self._native_media.snapshot()
        self._native_status_snapshot = state
        try:
            value = super().status()
        finally:
            del self._native_status_snapshot
        value['rtp_tx_buffer_samples'] = state.buffer_samples if state.clocked else 0
        return value

    def close(self):
        if self.closed:
            return
        media = self._native_media
        try:
            with media.control():
                super().close()
        finally:
            media.close()


MEDIA_FIELDS = {
    '_rtp_sequence': 'sequence', '_rtp_timestamp': 'timestamp', '_rtp_ssrc': 'ssrc',
    '_next_rtp_at': 'next_at', 'rtp_packets_sent': 'packets_sent',
    'rtp_packets_received': 'packets_received', 'rtp_octets_sent': 'octets_sent',
    'rtp_octets_received': 'octets_received',
    'preanswer_samples_discarded': 'preanswer_discarded',
    '_rtp_tx_primed': 'primed', '_rtp_tx_buffer_samples': 'buffer_samples',
}


def media_field(name, field):
    def get(owner):
        media = owner.__dict__.get('_native_media')
        if media is None:
            return owner.__dict__[name]
        state = owner.__dict__.get('_native_status_snapshot')
        return getattr(state if state is not None else media.snapshot(), field)
    def set(owner, value):
        media = owner.__dict__.get('_native_media')
        if media is None:
            owner.__dict__[name] = value
        else:
            media.set(field, value)
    return property(get, set)


for _name, _field in MEDIA_FIELDS.items():
    setattr(NativeSipSession, _name, media_field(_name, _field))

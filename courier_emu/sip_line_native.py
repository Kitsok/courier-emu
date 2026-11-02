"""Control-plane view of the native subscriber-loop port.

The native board calls SipPort directly. This adapter also supports callers
that explicitly service frames from Python, while keeping PCM and device
state in native storage between those frames.
"""
from __future__ import annotations

import ctypes as c
import time
import weakref

from .analog_native import NativeField, NativeLineExchange, pcm
from .ata import SipLine
from .exchange import EXCHANGE_STATES
from .media_native import NativeSipSession, SIP_STATES


class Control(c.Structure):
    _fields_ = [(name, c.c_int64) for name in ('state', 'inbound', 'last_status', 'signal_fd')]
    _fields_ += [('deadline', c.c_double)]


class PortState(c.Structure):
    _fields_ = [(name, c.c_uint64) for name in
                ('sip_state', 'incoming_active', 'placed', 'answered', 'frames', 'late_frames')]
    _fields_ += [(name, c.c_double) for name in
                ('next_frame_at', 'frame_duration', 'late_seconds', 'peak_late_seconds')]
    _fields_ += [('clock_started', c.c_uint64)]


class MediaState(c.Structure):
    _fields_ = [(name, c.c_uint64) for name in
                ('frames', 'underrun_frames', 'underrun_samples', 'pending_peak')]


class Spike(c.Structure):
    _fields_ = [('frame', c.c_uint64), ('milliseconds', c.c_double), ('state', c.c_int64)]


_LIBRARY = None


def library():
    global _LIBRARY
    if _LIBRARY is not None:
        return _LIBRARY
    from .dsp import load_library
    lib = load_library()
    signatures = {
        'create': ([c.c_void_p, c.c_void_p], c.c_void_p),
        'destroy': ([c.c_void_p], None),
        'state': ([c.c_void_p], c.POINTER(PortState)),
        'control': ([c.c_void_p], c.POINTER(Control)),
        'media': ([c.c_void_p], c.c_void_p),
        'from': ([c.c_void_p, c.c_char_p], None),
        'begin': ([c.c_void_p, c.c_int, c.POINTER(c.c_int32), c.c_size_t,
                   c.c_int64, c.c_double, c.c_int], c.c_int),
        'resume': ([c.c_void_p], c.c_int),
        'ack': ([c.c_void_p, c.c_int], None),
        'layout': ([c.c_int], c.c_size_t),
        'spikes': ([c.c_void_p, c.POINTER(Spike), c.c_size_t], c.c_size_t),
    }
    for name, (args, result) in signatures.items():
        fn = getattr(lib, 'courier_sip_port_' + name)
        fn.argtypes, fn.restype = args, result
    for control, layout in ((0, PortState), (1, Control)):
        if lib.courier_sip_port_layout(control) != c.sizeof(layout):
            raise RuntimeError('native subscriber port ABI mismatch')
    signatures = {
        'state': ([c.c_void_p], c.POINTER(MediaState)),
        'pending': ([c.c_void_p, c.POINTER(c.c_int32), c.c_size_t, c.c_int], c.c_size_t),
        'reset': ([c.c_void_p], None),
        'append': ([c.c_void_p, c.POINTER(c.c_int32), c.c_size_t], None),
        'underruns': ([c.c_void_p, c.POINTER(c.c_uint64), c.c_size_t], c.c_size_t),
        'record': ([c.c_void_p, c.c_char_p], c.c_int),
    }
    for name, (args, result) in signatures.items():
        fn = getattr(lib, 'courier_line_media_' + name)
        fn.argtypes, fn.restype = args, result
    _LIBRARY = lib
    return lib


class NativeSipLine(SipLine):
    @classmethod
    def adopt(cls, line):
        if isinstance(line, cls):
            return line
        if type(line) is not SipLine or not isinstance(line.sip, NativeSipSession):
            raise TypeError('native subscriber ports require the standard SIP line and native media')
        if line.line_rate != 8000:
            raise ValueError('native subscriber port requires an 8 kHz loop')
        if line.frames or line._pending:
            raise ValueError('adopt the subscriber port before servicing audio')
        exchange = NativeLineExchange.adopt(line.exchange)
        lib = library()
        handle = lib.courier_sip_port_create(exchange.native_handle, line.sip._native_media.handle)
        if not handle:
            raise RuntimeError('native subscriber port allocation or attachment failed')
        state = lib.courier_sip_port_state(handle).contents
        state.sip_state = SIP_STATES.index(line._sip_state)
        line._native_lib = lib
        line._native_port = handle
        line._native_control = lib.courier_sip_port_control(handle).contents
        line._native_media_handle = lib.courier_sip_port_media(handle)
        line._native_state = state
        line._native_media_state = lib.courier_line_media_state(line._native_media_handle).contents
        line._native_finalizer = weakref.finalize(line, lib.courier_sip_port_destroy, handle)
        if line._recordings is not None:
            for recording in line._recordings:
                recording.close()
            line._recordings = None
            if lib.courier_line_media_record(line._native_media_handle, line._recording_prefix.encode()):
                line._native_finalizer()
                raise OSError('cannot open native subscriber recordings: '+line._recording_prefix)
        line.__class__ = cls
        line.sip._native_port_view = weakref.ref(line)
        line._sync_control()
        return line

    def _sync_control(self):
        if not self._native_finalizer.alive:
            raise RuntimeError('native subscriber port is closed')
        self._native_control.state = SIP_STATES.index(self.sip.state)
        self._native_control.inbound = self.sip.direction == 'inbound'
        self._native_control.last_status = self.sip.last_status
        self._native_control.signal_fd = self.sip.socket.fileno()
        self._native_control.deadline = self.sip.signalling_deadline()
        getattr(self._native_lib, 'courier_sip_port_from')(
            self._native_port, (self.sip.incoming_from or '').encode())

    def control_event(self, event):
        if not self._native_finalizer.alive:
            raise RuntimeError('native subscriber port is closed')
        if event == 1:
            self.sip.poll()
        elif event == 2:
            self.sip.reject_incoming(486, 'Busy Here')
        elif event == 3:
            self.sip.ring_incoming()
        elif event == 4:
            self.sip.answer_incoming()
        elif event == 5:
            self.sip.start_call(self.exchange.dialed)
        elif event == 6:
            self.sip.reject_incoming()
        elif event == 7:
            self.sip.hangup()
        else:
            raise RuntimeError(f'unknown subscriber control event {event}')
        self._sync_control()
        self._native_lib.courier_sip_port_ack(self._native_port, event == 5)

    def service(self, off_hook, transmitted=None, count=None):
        if not self._native_finalizer.alive:
            raise RuntimeError('native subscriber port is closed')
        if count is None:
            count = self.line_rate // 10
        now = time.monotonic()
        if not self.cooperative_pacing and self._next_frame_at is not None:
            while now < self._next_frame_at:
                self.sip.poll()
                before = time.monotonic()
                self.idle_wait(min(.01, self._next_frame_at-now))
                now = time.monotonic()
                self.paced_seconds += max(0, now-before)
        self._sync_control()
        data = pcm(list(transmitted or ()))
        if self._native_lib.courier_sip_port_begin(
                self._native_port, off_hook, data, len(data), count, now, True):
            raise RuntimeError('native subscriber frame could not begin')
        while True:
            event = self._native_lib.courier_sip_port_resume(self._native_port)
            if event == 0:
                return self.exchange._vector(0)
            if event < 0:
                raise RuntimeError('native subscriber frame failed')
            self.control_event(event)

    @property
    def _next_frame_at(self):
        return self._native_state.next_frame_at if self._native_state.clock_started else None

    @property
    def _pending(self):
        if not self._native_finalizer.alive:
            return self._final_pending
        fn = self._native_lib.courier_line_media_pending
        count = fn(self._native_media_handle, None, 0, 0)
        values = (c.c_int32 * count)()
        fn(self._native_media_handle, values, count, 0)
        return list(values)

    @_pending.setter
    def _pending(self, values):
        if not self._native_finalizer.alive:
            raise RuntimeError('native subscriber port is closed')
        self._native_lib.courier_line_media_reset(self._native_media_handle)
        data = pcm(values)
        self._native_lib.courier_line_media_append(self._native_media_handle, data, len(data))

    @property
    def underrun_log(self):
        if not self._native_finalizer.alive:
            return self._final_underruns
        values = (c.c_uint64 * 128)()
        count = self._native_lib.courier_line_media_underruns(self._native_media_handle, values, 64)
        return list(zip(values[:2*count:2], values[1:2*count:2]))

    @property
    def late_spikes(self):
        if not self._native_finalizer.alive:
            return self._final_spikes
        values = (Spike * 64)()
        count = self._native_lib.courier_sip_port_spikes(self._native_port, values, 64)
        return [(item.frame, item.milliseconds, EXCHANGE_STATES[item.state]) for item in values[:count]]

    def close(self):
        if self._native_finalizer.alive:
            self._final_pending = self._pending
            self._final_underruns = self.underrun_log
            self._final_spikes = self.late_spikes
            self._native_state = PortState.from_buffer_copy(self._native_state)
            self._native_media_state = MediaState.from_buffer_copy(self._native_media_state)
            self._native_finalizer()
        super().close()


for _name in ('placed', 'answered', 'frames', 'late_frames', 'late_seconds', 'peak_late_seconds'):
    setattr(NativeSipLine, _name, NativeField(_name))
NativeSipLine._sip_state = NativeField('sip_state', SIP_STATES)
NativeSipLine._incoming_active = NativeField('incoming_active', boolean=True)
NativeSipLine._frame_duration = NativeField('frame_duration')


class MediaField:
    def __init__(self, name):self.name = name
    def __get__(self, owner, cls=None):
        return self if owner is None else getattr(owner._native_media_state, self.name)
    def __set__(self, owner, value):setattr(owner._native_media_state, self.name, value)


for _name in ('underrun_frames', 'underrun_samples', 'pending_peak'):
    setattr(NativeSipLine, _name, MediaField(_name))

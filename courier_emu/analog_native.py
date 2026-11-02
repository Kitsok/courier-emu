"""Live Python interfaces to the native analog line devices.

Device state belongs to C++; Python properties configure or inspect that state.
The same native handles are lent to the integrated board/media worker.
"""
from __future__ import annotations

import ctypes as c
from collections.abc import MutableMapping
from dataclasses import fields
import weakref

from .daa import CourierDaa, DAA_LINE_STATES
from .exchange import LineExchange, DtmfDecoder, EXCHANGE_STATES, EXCHANGE_OUTCOMES, DTMF_KEYS

OPERATIONS = ('idle', 'originate', 'answer', 'dialing', 'trying', 'connected', 'failed', 'ringing')
OUTCOMES = (None, *EXCHANGE_OUTCOMES)


class DaaState(c.Structure):
    _fields_ = [(name, c.c_int64) for name in (
        'line_state', 'sample_rate', 'off_hook', 'operation',
        'generated_samples', 'qualified_samples')]


class ExchangeState(c.Structure):
    _fields_ = [(name, c.c_int64) for name in (
        'sample_rate', 'default_outcome', 'answer_after_rings', 'no_answer_rings',
        'answer_tone_ms', 'interdigit_ms', 'routing_ms', 'first_digit_ms',
        'ring_on_ms', 'ring_off_ms', 'incoming_rings', 'pulse_dialing', 'hotline',
        'state', 'off_hook', 'outcome', 'rings_delivered', 'flashes',
        'elapsed', 'tx_samples', 'rx_samples', 'calls', 'state_at', 'tone_index',
        'hook_at', 'pulses', 'last_digit_at', 'has_router', 'has_peer', 'inbound_present')]


class DecoderState(c.Structure):
    _fields_ = [(name, c.c_int64) for name in (
        'sample_rate', 'block_samples', 'accept_blocks', 'blocks', 'candidate', 'run', 'held')]


class NativeField:
    def __init__(self, name, values=None, boolean=False, offset=0):
        self.name, self.values, self.boolean, self.offset = name, values, boolean, offset

    def __get__(self, owner, cls=None):
        if owner is None:
            return self
        if owner._native_state is None:
            raise RuntimeError('native device is closed')
        value = getattr(owner._native_state, self.name)
        return self.values[value + self.offset] if self.values else bool(value) if self.boolean else value

    def __set__(self, owner, value):
        if owner._native_state is None:
            raise RuntimeError('native device is closed')
        encoded = self.values.index(value) - self.offset if self.values else int(value)
        setattr(owner._native_state, self.name, encoded)


_LIBRARY = None
I32 = c.POINTER(c.c_int32)


def library():
    global _LIBRARY
    if _LIBRARY is not None:
        return _LIBRARY
    from .dsp import load_library
    lib = load_library()
    signatures = {
        'layout': ([c.POINTER(c.c_uint64)], None),
        'daa_action': ([c.c_void_p, c.c_int, c.c_int64], c.c_int),
        'daa_render': ([c.c_void_p, c.c_int64, I32], None),
        'exchange_create': ([], c.c_void_p),
        'exchange_destroy': ([c.c_void_p], None),
        'exchange_state': ([c.c_void_p], c.c_void_p),
        'decoder_state': ([c.c_void_p], c.c_void_p),
        'exchange_string': ([c.c_void_p, c.c_int], c.c_char_p),
        'exchange_set_string': ([c.c_void_p, c.c_int, c.c_char_p], None),
        'exchange_directory': ([c.c_void_p, c.c_char_p, c.c_int64], None),
        'exchange_tone': ([c.c_void_p, I32, c.c_size_t], None),
        'exchange_action': ([c.c_void_p, c.c_int, c.c_int64, c.c_char_p], c.c_int),
        'exchange_begin': ([c.c_void_p, c.c_int, I32, c.c_size_t, c.c_int64], None),
        'exchange_resume': ([c.c_void_p], c.c_int),
        'exchange_route_result': ([c.c_void_p, c.c_int64], None),
        'exchange_peer_result': ([c.c_void_p, I32, c.c_size_t], None),
        'exchange_vector': ([c.c_void_p, c.c_int, I32, c.c_size_t], c.c_size_t),
        'decoder_pending': ([c.c_void_p, I32, c.c_size_t], None),
        'decoder_feed': ([c.c_void_p, I32, c.c_size_t], c.c_char_p),
    }
    for name, (args, result) in signatures.items():
        fn = getattr(lib, 'courier_analog_' + name)
        fn.argtypes, fn.restype = args, result
    sizes = (c.c_uint64 * 3)()
    lib.courier_analog_layout(sizes)
    expected = tuple(map(c.sizeof, (DaaState, ExchangeState, DecoderState)))
    if tuple(sizes) != expected:
        raise RuntimeError(f'analog device ABI {tuple(sizes)} != {expected}')
    _LIBRARY = lib
    return lib


def pcm(values):
    return (c.c_int32 * len(values))(*values)


class NativeDaa(CourierDaa):
    @classmethod
    def adopt(cls, device):
        if isinstance(device, cls):
            return device
        if type(device) is not CourierDaa:
            raise TypeError('custom DAA implementations retain their own device model')
        values = {f.name: getattr(device, f.name) for f in fields(CourierDaa)}
        device._native_buffer = bytearray(c.sizeof(DaaState))
        device._native_state = DaaState.from_buffer(device._native_buffer)
        device._native_lib = library()
        device.__class__ = cls
        for name, value in values.items():
            setattr(device, name, value)
        return device

    @property
    def native_address(self):
        return c.addressof(self._native_state)

    def seize(self, operation='originate'):
        self._native_lib.courier_analog_daa_action(self.native_address, 0, OPERATIONS.index(operation))

    def release(self):
        self._native_lib.courier_analog_daa_action(self.native_address, 1, 0)

    def begin_dialing(self):
        self._native_lib.courier_analog_daa_action(self.native_address, 2, 0)

    def set_call_progress(self, state):
        if state in ('trying', 'ringing', 'connected', 'failed'):
            self._native_lib.courier_analog_daa_action(self.native_address, 3, OPERATIONS.index(state))

    def observe(self, count):
        self._native_lib.courier_analog_daa_action(self.native_address, 4, count)

    def render(self, count):
        if count <= 0:
            return []
        result = (c.c_int32 * count)()
        self._native_lib.courier_analog_daa_render(self.native_address, count, result)
        return list(result)

    def __deepcopy__(self, memo):
        result = self.adopt(CourierDaa(**{f.name: getattr(self, f.name) for f in fields(CourierDaa)}))
        memo[id(self)] = result
        return result


# The reference DAA accepts ringing as a progress state but does not qualify
# its detector in that operation.
for _name, _ in DaaState._fields_:
    setattr(NativeDaa, _name, NativeField(
        _name, DAA_LINE_STATES if _name == 'line_state' else OPERATIONS if _name == 'operation' else None,
        boolean=_name == 'off_hook'))


class NativeDirectory(MutableMapping):
    def __init__(self, owner, original):
        self.owner, self.data = owner, {}
        for key, value in original.items():
            self[key] = value

    def __getitem__(self, key):
        return self.data[key]

    def __setitem__(self, key, value):
        code = OUTCOMES.index(value)
        self.owner._native_lib.courier_analog_exchange_directory(self.owner.native_handle, key.encode(), code)
        self.data[key] = value

    def __delitem__(self, key):
        if key not in self.data:
            raise KeyError(key)
        self.owner._native_lib.courier_analog_exchange_directory(self.owner.native_handle, key.encode(), -1)
        del self.data[key]

    def __iter__(self):
        return iter(self.data)

    def __len__(self):
        return len(self.data)


class NativeDecoder(DtmfDecoder):
    @property
    def digits(self):
        return self._owner._get_string(2)

    @digits.setter
    def digits(self, value):
        self._owner._set_string(2, value)

    @property
    def _pending(self):
        return self._owner._vector(2)

    @_pending.setter
    def _pending(self, value):
        data = pcm(value)
        self._owner._native_lib.courier_analog_decoder_pending(self._owner.native_handle, data, len(data))

    def feed(self, samples):
        data = pcm(samples)
        return self._owner._native_lib.courier_analog_decoder_feed(
            self._owner.native_handle, data, len(data)).decode()


for _name, _ in DecoderState._fields_:
    _python_name = '_' + _name if _name in ('candidate', 'run', 'held') else _name
    setattr(NativeDecoder, _python_name, NativeField(
        _name, (None, *DTMF_KEYS) if _name in ('candidate', 'held') else None,
        offset=1 if _name in ('candidate', 'held') else 0))


class NativeLineExchange(LineExchange):
    @classmethod
    def adopt(cls, device):
        if isinstance(device, cls):
            return device
        if type(device) is not LineExchange:
            raise TypeError('custom exchanges retain their own device model')
        values = {f.name: getattr(device, f.name) for f in fields(LineExchange)}
        decoder = values.pop('decoder')
        if type(decoder) not in (DtmfDecoder, NativeDecoder):
            raise TypeError('custom digit receivers retain their own device model')
        lib = library()
        handle = lib.courier_analog_exchange_create()
        device._native_lib, device._native_handle = lib, handle
        device._native_state = ExchangeState.from_address(lib.courier_analog_exchange_state(handle))
        device._native_finalizer = weakref.finalize(device, lib.courier_analog_exchange_destroy, handle)
        device.__class__ = cls
        device._bind_decoder(decoder)
        for name, value in values.items():
            setattr(device, name, value)
        return device

    def _bind_decoder(self, decoder):
        if type(decoder) not in (DtmfDecoder, NativeDecoder):
            raise TypeError('custom digit receivers retain their own device model')
        values = {f.name: getattr(decoder, f.name) for f in fields(DtmfDecoder)}
        decoder._owner = self
        decoder._native_state = DecoderState.from_address(
            self._native_lib.courier_analog_decoder_state(self.native_handle))
        decoder.__class__ = NativeDecoder
        object.__setattr__(self, 'decoder', decoder)
        for name, value in values.items():
            setattr(decoder, name, value)

    @property
    def native_handle(self):
        if self._native_state is None:
            raise RuntimeError('native exchange is closed')
        return self._native_handle

    def _get_string(self, field):
        return self._native_lib.courier_analog_exchange_string(self.native_handle, field).decode()

    def _set_string(self, field, value):
        self._native_lib.courier_analog_exchange_set_string(self.native_handle, field, value.encode())

    @property
    def dialed(self):
        return self._get_string(0)

    @dialed.setter
    def dialed(self, value):
        self._set_string(0, value)

    @property
    def inbound_number(self):
        return self._get_string(1) if self._native_state.inbound_present else None

    @inbound_number.setter
    def inbound_number(self, value):
        self._native_state.inbound_present = value is not None
        self._set_string(1, value or '')

    def __setattr__(self, name, value):
        if name == 'decoder' and '_native_state' in self.__dict__:
            self._bind_decoder(value)
            return
        if name in ('router', 'peer_audio') and '_native_state' in self.__dict__:
            setattr(self._native_state, 'has_router' if name == 'router' else 'has_peer', value is not None)
        if name == 'directory' and '_native_state' in self.__dict__:
            self._native_lib.courier_analog_exchange_directory(self.native_handle, None, -1)
            value = NativeDirectory(self, dict(value))
        if name == 'dial_tone' and '_native_state' in self.__dict__:
            value = tuple(value)
            data = pcm(value)
            self._native_lib.courier_analog_exchange_tone(self.native_handle, data, len(data))
        object.__setattr__(self, name, value)

    def _vector(self, field):
        fn = self._native_lib.courier_analog_exchange_vector
        count = fn(self.native_handle, field, None, 0)
        result = (c.c_int32 * count)()
        fn(self.native_handle, field, result, count)
        return list(result)

    def _route_result(self):
        result = self.router(self.dialed)
        self._native_lib.courier_analog_exchange_route_result(self.native_handle, OUTCOMES.index(result))

    def _action(self, code, value=0, text=None):
        event = self._native_lib.courier_analog_exchange_action(self.native_handle, code, value, text)
        if event == 1:
            self._route_result()

    def ring(self, number=None):
        self._action(0, text=None if number is None else number.encode())

    def release(self):
        self._action(1)

    def answer(self):
        self._action(2)

    def set_outcome(self, outcome):
        if outcome not in EXCHANGE_OUTCOMES:
            raise ValueError(f'invalid exchange outcome {outcome!r}')
        self._action(3, OUTCOMES.index(outcome))

    def _enter(self, state):
        self._action(4, EXCHANGE_STATES.index(state))

    def _observe_hook(self, off_hook):
        self._action(5, bool(off_hook))

    def _accept_digit(self, digit):
        self._action(6, ord(digit))

    def _route(self):
        self._action(7)

    def _advance(self):
        self._action(8)

    def service(self, off_hook, transmitted=None, count=None):
        transmitted = list(transmitted or [])
        if count is None:
            count = len(transmitted)
        if count <= 0:
            return []
        data = pcm(transmitted)
        self._native_lib.courier_analog_exchange_begin(self.native_handle, off_hook, data, len(data), count)
        while True:
            event = self._native_lib.courier_analog_exchange_resume(self.native_handle)
            if event == 0:
                return self._vector(0)
            if event == 1:
                self._route_result()
            elif event == 2:
                # Peer callbacks are only the reference/control-plane adapter.
                # The integrated native media provider bypasses this bridge.
                chunk = self._vector(1)
                step = min(80, count - (len(self._vector(0))))
                received = list(self.peer_audio(step, chunk))[:step]
                samples = pcm(received)
                self._native_lib.courier_analog_exchange_peer_result(self.native_handle, samples, len(samples))
            else:
                raise RuntimeError(f'unknown native exchange event {event}')

    def close(self):
        if self._native_state is not None:
            self.decoder._native_state = None
            self._native_state = None
            self._native_finalizer()

    def __deepcopy__(self, memo):
        import copy
        result = LineExchange()
        memo[id(self)] = result
        for field in fields(LineExchange):
            if field.name == 'decoder':
                value = DtmfDecoder(**{
                    f.name: copy.deepcopy(getattr(self.decoder, f.name), memo)
                    for f in fields(DtmfDecoder)})
            elif field.name == 'directory':
                value = copy.deepcopy(dict(self.directory), memo)
            else:
                value = copy.deepcopy(getattr(self, field.name), memo)
            setattr(result, field.name, value)
        return self.adopt(result)


for _name, _ in ExchangeState._fields_:
    if _name in ('has_router', 'has_peer', 'inbound_present'):
        continue
    _python_name = '_' + _name if _name in ('state_at', 'tone_index', 'hook_at', 'pulses', 'last_digit_at') else _name
    _values = EXCHANGE_STATES if _name == 'state' else OUTCOMES if _name in ('outcome', 'default_outcome') else None
    setattr(NativeLineExchange, _python_name, NativeField(
        _name, _values, boolean=_name in ('off_hook', 'pulse_dialing', 'hotline')))

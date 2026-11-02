"""Authoritative native media views on the standalone Courier bridge."""
from collections.abc import MutableMapping

from .board_media_native import NativeBoardMedia, NativePcmQueue, NativeStreamView
from .bridge import CourierDspBridge
from .sip_line_native import NativeSipLine


class NativeServiceStats(MutableMapping):
    fields = dict(tx_index='reported_tx_index', tx_consumed='tx_consumed',
                  tx_peak_codec='peak_codec', tx_peak_line='peak_line',
                  tx_batches_crossing_retune='crossing_retune')

    def __init__(self, owner, original):
        self.owner, self.other = owner, dict(original)

    def __getitem__(self, key):
        if key in self.fields:
            value = getattr(self.owner.state, self.fields[key])
            if key not in self.other and not value:
                raise KeyError(key)
            return value
        return self.other[key]

    def __setitem__(self, key, value):
        if key in self.fields:
            setattr(self.owner.state, self.fields[key], value)
        self.other[key] = value

    def __delitem__(self, key):
        if key in self.fields:
            raise TypeError('native service counters cannot be deleted')
        del self.other[key]

    def __iter__(self):
        keys = dict.fromkeys(self.other)
        keys.update((key, None) for key, field in self.fields.items()
                    if getattr(self.owner.state, field))
        return iter(keys)

    def __len__(self):
        return sum(1 for _ in self)


class BoardField:
    def __init__(self, name):self.name = name
    def __get__(self, owner, cls=None):
        return self if owner is None else getattr(owner._native_media_owner.state, self.name)
    def __set__(self, owner, value):setattr(owner._native_media_owner.state, self.name, value)


class NativeCourierDspBridge(CourierDspBridge):
    @classmethod
    def adopt(cls, bridge):
        if isinstance(bridge, cls):
            return bridge
        if type(bridge) is not CourierDspBridge:
            raise TypeError('custom bridges retain their own device implementation')
        if (bridge.line is not None or bridge.legacy_carrier_fallback or bridge.rx_acquisition_assist
                or bridge.audio_monitor is not None or bridge.rx_samples or bridge.asic_transparent):
            raise ValueError('native bridge requires the standard standalone media path')
        if bridge._exchange_tx_index or bridge._exchange_line_buffer or bridge._codec_in_flight:
            raise ValueError('adopt native media before servicing codec audio')
        line = NativeSipLine.adopt(bridge._sip_line)
        if bridge.codec is not None:
            from .codec import SiliconDaa
            from .silicon_native import NativeSiliconDaa
            if type(bridge.codec.codec) is SiliconDaa:
                NativeSiliconDaa.adopt(bridge.codec.codec)
        owner = NativeBoardMedia(line, bridge.daa, bridge.batch)
        if bridge.codec is not None:
            from .codec import CodecBringUp
            from .codec_native import NativeCodecBringUp
            if type(bridge.codec) is CodecBringUp:
                NativeCodecBringUp.adopt(bridge.codec)
                owner.attach_codec(bridge.codec)
        digits = bridge.dial_digits
        stats = bridge._line_service
        # Install the shared state before switching class, so descriptors can
        # never observe a partially adopted bridge.
        bridge._native_media_owner = owner
        bridge._sip_line = line
        bridge._line_service = NativeServiceStats(owner, stats)
        bridge._exchange_line_buffer = NativePcmQueue(owner, 0)
        bridge._codec_in_flight = NativePcmQueue(owner, 1)
        bridge._exchange_rx_samples = NativePcmQueue(owner, 2)
        bridge._codec_to_line = NativeStreamView(owner, 0)
        bridge._line_to_codec = NativeStreamView(owner, 1)
        bridge.__class__ = cls
        bridge.dial_digits = digits
        bridge._sync_media_flags()
        return bridge

    def _sync_media_flags(self):
        state = self._native_media_owner.state
        state.queue_input = bool(self._call_overlay_active or self._call_resume_pending or self.boot_rom_enabled)
        state.clocked_input = bool(self.boot_rom_enabled and self.line is not None)

    def __setattr__(self, name, value):
        owner = self.__dict__.get('_native_media_owner')
        old_core = self.__dict__.get('core') if name == 'core' else None
        super().__setattr__(name, value)
        if owner is not None:
            if name in ('_call_overlay_active', '_call_resume_pending', 'boot_rom_enabled', 'line'):
                self._sync_media_flags()
            elif name == 'core' and old_core is not None and old_core is not value:
                owner.reset(value, rebuild=True)

    def _service_exchange(self):
        if self.audio_monitor is not None:
            raise RuntimeError('native media monitor integration is not enabled')
        self._native_media_owner.service(self.core, self._instructions)

    def _take_line_audio(self):
        self._native_media_owner.collect(self.core)

    def _service_codec(self):
        from .codec_native import NativeCodecBringUp
        if isinstance(self.codec, NativeCodecBringUp):self._native_media_owner.service_codec()
        else:super()._service_codec()

    def _queue_line_audio(self, samples):
        self._native_media_owner.queue(self.core, samples, self._instructions)

    def set_reset(self, asserted):
        edge = bool(asserted) and not self._reset_asserted
        super().set_reset(asserted)
        if edge:
            self._native_media_owner.reset(self.core)

    @property
    def _rx_cushion_rate(self):
        return self._native_media_owner.state.cushion_rate or None

    @_rx_cushion_rate.setter
    def _rx_cushion_rate(self, value):
        self._native_media_owner.state.cushion_rate = value or 0

    @property
    def dial_digits(self):
        owner = self._native_media_owner
        if not owner._finalizer.alive:
            return owner._final_digits
        return owner._lib.courier_board_media_digits(owner.handle, None).decode()

    @dial_digits.setter
    def dial_digits(self, value):
        owner = self._native_media_owner
        owner._lib.courier_board_media_digits(owner.handle, value.encode())

    def close(self):
        self._native_media_owner.close()
        super().close()


for _python, _native in {
    '_exchange_tx_index': 'tx_index', '_exchange_codec_last': 'codec_last', '_exchange_idle': 'idle',
    '_line_rx_peak': 'line_rx_peak', '_codec_in_peak': 'codec_in_peak',
    '_codec_handed_peak': 'handed_peak', '_codec_handed_at': 'handed_at',
    '_codec_handed_ever': 'handed_ever', '_codec_queue_peak': 'queue_peak', '_codec_replayed': 'replayed',
    '_codec_instructions': 'codec_instructions',
}.items():
    setattr(NativeCourierDspBridge, _python, BoardField(_native))

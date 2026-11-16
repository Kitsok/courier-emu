"""Live views of the native analog DSP loader and lifecycle owner."""
import ctypes as c
import weakref
from collections.abc import MutableMapping
from .dsp import load_library
from .bridge_native import NativeCourierDspBridge


FIELDS = {
    '_reset_asserted': 'reset_asserted', '_cpu_int1_asserted': 'cpu_int1',
    '_dsp_restarted': 'restarted', '_loader_started': 'loader_started',
    '_loader_nmi_seen': 'nmi_seen', '_download_destination': 'destination',
    'active': 'active', 'launched': 'launched', '_runtime_mode': 'runtime_mode',
    '_runtime_ready': 'runtime_ready', '_runtime_ready_delay': 'runtime_delay',
    '_line_tx_index': 'line_tx_index', '_sip_tx_index': 'sip_tx_index',
    '_audio_codec_frames': 'audio_frames', '_audio_line_samples_due': 'audio_samples_due',
    'bootstrap_match': 'match', '_last_bootstrap_bytes': 'last_bytes',
    '_last_bootstrap_match': 'last_match', 'bootstraps': 'bootstraps',
    'transfer_commands': 'transfers', 'checksum_submits': 'checksums',
    'boot_strobes_native': 'boot_strobes_native',
    '_runtime_header': 'runtime_header', '_runtime_data': 'runtime_data',
    '_runtime_inbound_seen': 'inbound_seen', 'host_messages_delivered': 'host_delivered',
    'dsp_messages_taken': 'messages_taken', 'dsp_stream_acks': 'stream_acks',
    '_overlay_status': 'overlay_status', '_overlay_destination_pending': 'overlay_pending',
    '_overlay_destination_mark': 'overlay_mark',
    '_overlay_destination_write_mark': 'overlay_write_mark',
    '_overlay_halves_since_start': 'overlay_halves', 'overlay_strobes_native': 'overlay_strobes',
    'overlay_words_verified': 'overlay_verified', 'overlay_words_unreadable': 'overlay_unreadable',
    'overlay_downloads': 'overlay_downloads', 'overlay_id': 'overlay_id',
    'overlay_match': 'overlay_match', 'overlay_destination_waits': 'overlay_waits',
}
BOOLEAN = {'reset_asserted', 'cpu_int1', 'restarted', 'loader_started', 'nmi_seen',
           'active', 'launched', 'runtime_mode', 'runtime_ready', 'inbound_seen', 'overlay_pending'}


class LifecycleState(c.Structure):
    _fields_ = [(name, c.c_int64 if name == 'runtime_delay' else
                 c.c_double if name == 'audio_samples_due' else c.c_uint64)
                for name in ('reset_asserted', 'cpu_int1', 'nmi_low', 'restarted',
                    'loader_started', 'nmi_seen', 'destination', 'active', 'launched',
                    'runtime_mode', 'runtime_ready', 'runtime_delay', 'line_tx_index',
                    'sip_tx_index', 'audio_frames', 'audio_samples_due', 'match', 'last_bytes',
                    'last_match', 'bootstraps', 'transfers', 'checksums', 'bootstrap_size',
                    'boot_strobes_native', 'pins_seen', 'pin_sync')]
    _fields_ += [(name, c.c_uint64) for name in ('runtime_header', 'runtime_data',
        'pending_header', 'pending_data', 'pending_valid', 'inbound_seen', 'inbound_count',
        'host_delivered', 'messages_taken', 'stream_acks', 'host_event', 'event_header',
        'event_data', 'event_ack')]
    _fields_ += [(name, c.c_uint64) for name in ('overlay_status', 'overlay_pending',
        'overlay_mark', 'overlay_write_mark', 'overlay_halves', 'overlay_strobes',
        'overlay_verified', 'overlay_unreadable', 'overlay_downloads', 'overlay_id',
        'overlay_match', 'overlay_waits')]
    _fields_ += [('error', c.c_char * 512)]


class NativeBootstrap:
    def __init__(self, owner): self.owner = owner
    def __len__(self): return self.owner.state.bootstrap_size
    def __bytes__(self): return self.owner.bytes()
    def __getitem__(self, key): return bytes(self)[key]
    def __eq__(self, other): return bytes(self) == other
    def extend(self, values): self.owner.write_bytes(values, 1)
    def clear(self): self.owner.write_bytes(b'', 0)


class NativeLifecycle:
    def __init__(self, bridge):
        from .bridge import (C51_NMI_DISPATCH_CELL, C51_ROM_NMI_ENTRY, C50_ROM_FRAME_IRQ,
                             HOST_TAG_CELL, HOST_WORD_CELL, HOST_STATUS_CELL, DSP_STREAM_PORT)
        lib = load_library()
        lib.courier_lifecycle_layout.restype = c.c_size_t
        if lib.courier_lifecycle_layout() != c.sizeof(LifecycleState):
            raise RuntimeError('native DSP lifecycle ABI mismatch')
        self.state = LifecycleState()
        self.media, self.core = bridge._native_media_owner, bridge.core
        self._past_resets = list(bridge._reset_log)
        self._final_resets = []

        def bind(name, result, *args):
            return c.PYFUNCTYPE(result, *args)(
                c.cast(getattr(lib, 'courier_lifecycle_' + name), c.c_void_p).value)

        create = bind('create', c.c_void_p, c.c_void_p, c.c_void_p, c.c_void_p)
        destroy = bind('destroy', None, c.c_void_p)
        self.handle = create(c.addressof(self.state), self.media.handle, self.core.handle)
        if not self.handle: raise MemoryError('cannot allocate DSP lifecycle owner')
        self._anchors = []
        self._finalizer = weakref.finalize(self, destroy, self.handle)
        self._configure = bind('configure', None, c.c_void_p, c.c_void_p, c.c_void_p)
        self._config = (c.c_uint64 * 9)(bridge.transfer.first_strobe, bridge.bootstrap_target_size,
            C51_NMI_DISPATCH_CELL, C51_ROM_NMI_ENTRY, C50_ROM_FRAME_IRQ,
            HOST_TAG_CELL, HOST_WORD_CELL, HOST_STATUS_CELL, DSP_STREAM_PORT)
        self._configure(self.handle, self.core.handle, self._config)
        window = bind('window', None, c.c_void_p, c.c_uint, c.c_void_p)
        for strobe, data in bridge._windows.items():
            anchor = (c.c_uint8 * len(data)).from_buffer(data)
            self._anchors.append(anchor)
            window(self.handle, strobe, c.addressof(anchor))
        self._bytes = bind('bytes', c.c_int, c.c_void_p, c.c_char_p, c.c_size_t, c.c_uint)
        self._read = bind('read', c.c_size_t, c.c_void_p, c.c_void_p, c.c_size_t)
        self._apply = bind('apply', c.c_int, c.c_void_p, c.c_uint, c.c_uint)
        self._accept = bind('accept', c.c_int, c.c_void_p, c.c_char_p, c.c_uint)
        self._resets = bind('resets', c.c_size_t, c.c_void_p, c.c_void_p, c.c_size_t)
        self._message = bind('message', c.c_uint64, c.c_void_p, c.c_uint, c.c_uint64, c.c_uint64)
        self._message_keys = bind('message_keys', c.c_size_t, c.c_void_p, c.c_void_p, c.c_size_t)
        self._overlay = bind('overlay', None, c.c_void_p, c.c_uint, c.c_char_p, c.c_size_t, c.c_uint)
        self._overlay_log = bind('overlay_log', c.c_size_t, c.c_void_p, c.c_uint, c.c_void_p, c.c_size_t)
        add_overlay = bind('overlay_add', None, c.c_void_p, c.c_uint, c.c_uint, c.c_char_p, c.c_size_t)
        for row in bridge._overlay_rows():
            data = bridge._overlay_payload(row)
            add_overlay(self.handle, row.index, bool(row.entry_word), data, len(data))
        self.heads, self.destinations = NativeOverlayLog(self, 0), NativeOverlayLog(self, 1)
        self._final_overlay_logs = ([], [])
        for value in bridge.overlay_heads: self.heads.append(value)
        for value in bridge.overlay_destinations: self.destinations.append(value)
        self.inbound = NativeMessages(self)
        self.delivered = NativeDeliveries(self)
        for pair in bridge._runtime_inbound: self.inbound.append(pair)
        for key, count in bridge._runtime_inbound_delivered.items(): self.delivered[key] = count
        pending = bridge._runtime_pending
        if pending is not None:
            self.state.pending_header, self.state.pending_data = pending
            self.state.pending_valid = 1
        self._final_inbound, self._final_delivered = (), {}
        self.bootstrap = NativeBootstrap(self)
        self.write_bytes(bridge.bootstrap, 0)
        self.write_bytes(bridge.expected_bootstrap, 2)
        self._final_bootstrap = b''

    def write_bytes(self, values, operation):
        data = bytes(values)
        if self._bytes(self.handle, data, len(data), operation):
            raise MemoryError('cannot update native bootstrap')

    def bytes(self):
        if not self._finalizer.alive: return self._final_bootstrap
        data = c.create_string_buffer(self.state.bootstrap_size)
        size = self._read(self.handle, data, len(data))
        return c.string_at(data, size)

    def apply(self, operation, value=0):
        result = self._apply(self.handle, operation, value)
        if result < 0: raise RuntimeError(self.state.error.decode('utf-8', 'replace'))
        return result

    def accept(self, window, codec):
        result = self._accept(self.handle, bytes(window), codec)
        if result < 0: raise RuntimeError(self.state.error.decode('utf-8', 'replace'))
        return bool(result)

    def bind_core(self, core):
        self.core = core
        self._configure(self.handle, core.handle, self._config)

    def resets(self):
        if not self._finalizer.alive:
            return self._final_resets
        count = self._resets(self.handle, None, 0)
        rows = (c.c_int64 * (3 * count))()
        self._resets(self.handle, rows, count)
        return self._past_resets + [dict(frame=rows[3*i], instructions=rows[3*i+1],
                                        tx_written=rows[3*i+2]) for i in range(count)]

    def finish(self, machine):
        if self.state.error:
            raise RuntimeError(self.state.error.decode('utf-8', 'replace'))
        if not self.state.pin_sync and not self.state.host_event:
            return False
        self.state.pin_sync = 0
        if self.state.host_event:
            from .x86_interpreter import UC_X86_REG_CS, UC_X86_REG_IP
            self.state.host_event = 0
            words = self.state.event_header, self.state.event_data
            cpu = machine.uc
            pc = ((cpu.reg_read(UC_X86_REG_CS) << 4) + cpu.reg_read(UC_X86_REG_IP)) & 0xfffff
            bridge = machine.dsp_bridge
            bridge._record_runtime_message(words, pc)
            bridge._deliver_host_message(*words)
            bridge._answer_runtime_request(*words)
            self.message(6)
        machine._dsp_in_reset = bool(self.state.reset_asserted)
        machine._dsp_nmi_low = bool(self.state.nmi_low)
        if machine.uc.native_after_io is not None:
            machine.uc.native_after_io()
        return True

    def message(self, operation, value=0, argument=0):
        return self._message(self.handle, operation, value, argument)

    def overlay(self, operation, data=b'', value=0):
        self._overlay(self.handle, operation, data, len(data), value)

    def close(self):
        if self._finalizer.alive:
            self._final_bootstrap = self.bytes()
            self._final_resets = self.resets()
            self._final_inbound = tuple(self.inbound)
            self._final_delivered = dict(self.delivered)
            self._final_overlay_logs = (list(self.heads), list(self.destinations))
            self._finalizer()


class LifecycleField:
    def __init__(self, field): self.field = field
    def __get__(self, owner, cls=None):
        if owner is None: return self
        value = getattr(owner._native_lifecycle.state, self.field)
        if self.field in ('match', 'last_match', 'overlay_match'): return None if value == 2 else bool(value)
        if self.field == 'overlay_id': return None if value == (1 << 64) - 1 else value
        return bool(value) if self.field in BOOLEAN else value
    def __set__(self, owner, value):
        if self.field in ('match', 'last_match', 'overlay_match') and value is None: value = 2
        if self.field == 'overlay_id' and value is None: value = (1 << 64) - 1
        setattr(owner._native_lifecycle.state, self.field, value)


class NativeLifecycleBridge(NativeCourierDspBridge):
    @classmethod
    def adopt(cls, bridge):
        if isinstance(bridge, cls): return bridge
        if type(bridge) is not NativeCourierDspBridge: return bridge
        original = {name: getattr(bridge, name, False) for name in FIELDS}
        owner = NativeLifecycle(bridge)
        bridge._native_lifecycle = owner
        bridge.__class__ = cls
        for name, value in original.items(): setattr(bridge, name, value)
        return bridge

    bootstrap = property(lambda self: self._native_lifecycle.bootstrap,
                         lambda self, values: self._native_lifecycle.write_bytes(values, 0))
    _runtime_inbound = property(lambda self: self._native_lifecycle.inbound)
    _runtime_inbound_delivered = property(lambda self: self._native_lifecycle.delivered)
    overlay_heads = property(lambda self: self._native_lifecycle.heads)
    overlay_destinations = property(lambda self: self._native_lifecycle.destinations)

    def _reset_overlay_transfer(self):
        self._native_lifecycle.overlay(0)
        super()._reset_overlay_transfer()

    def _accumulate_overlay(self, half, *, group_committed):
        owner = self._native_lifecycle
        for base, block in self._overlay_groups:
            owner.overlay(1, bytes(block), base)
        self._overlay_groups.clear()
        owner.overlay(2, bytes(half), group_committed)

    @property
    def _runtime_pending(self):
        s = self._native_lifecycle.state
        return (s.pending_header, s.pending_data) if s.pending_valid else None

    @_runtime_pending.setter
    def _runtime_pending(self, value):
        s = self._native_lifecycle.state
        s.pending_valid = value is not None
        if value is not None: s.pending_header, s.pending_data = value

    def _deliver_host_message(self, header, data):
        return bool(self._native_lifecycle.message(3, ((header & 65535) << 16) | (data & 65535)))

    def __setattr__(self, name, value):
        super().__setattr__(name, value)
        if name == 'core' and '_native_lifecycle' in self.__dict__:
            self._native_lifecycle.bind_core(value)

    def _settle_nmi_dispatch(self): self._native_lifecycle.apply(0)
    def _start_rom_loader(self): self._native_lifecycle.apply(1)
    def _commit_rom_group(self, strobe): self._native_lifecycle.apply(2, strobe)
    def _rom_loader_armed(self): return bool(self._native_lifecycle.apply(3))
    def _accept_bootstrap_window(self, window):
        return self._native_lifecycle.accept(window, self.codec is not None)

    _reset_log = property(lambda self: self._native_lifecycle.resets())

    def set_reset(self, asserted): self._native_lifecycle.apply(5, bool(asserted))
    def set_cpu_int1(self, asserted): self._native_lifecycle.apply(6, bool(asserted))
    def pulse_nmi(self): self._native_lifecycle.apply(7)
    def _configure_frame_interrupt(self): self._native_lifecycle.apply(8)
    def float_runtime_bus(self): self._native_lifecycle.apply(9)

    def close(self):
        self._native_lifecycle.close()
        super().close()


for _name, _field in FIELDS.items():
    setattr(NativeLifecycleBridge, _name, LifecycleField(_field))


class NativeMessages:
    def __init__(self, owner): self.owner = owner
    def __len__(self): return self.owner.state.inbound_count
    def __iter__(self): return (self[i] for i in range(len(self)))
    def __getitem__(self, index):
        if not self.owner._finalizer.alive: return self.owner._final_inbound[index]
        if index < 0: index += len(self)
        if not 0 <= index < len(self): raise IndexError('mailbox index out of range')
        value = self.owner.message(2, index)
        return value >> 16, value & 65535
    def append(self, pair):
        self.owner.message(0, ((pair[0] & 65535) << 16) | (pair[1] & 65535))
    def popleft(self):
        value = self.owner.message(1)
        if value == 1 << 32: raise IndexError('pop from empty mailbox')
        return value >> 16, value & 65535


class NativeOverlayLog:
    def __init__(self, owner, kind): self.owner, self.kind = owner, kind
    def values(self):
        if not self.owner._finalizer.alive: return self.owner._final_overlay_logs[self.kind]
        count = self.owner._overlay_log(self.owner.handle, self.kind, None, 0)
        width = 2 if self.kind else 8
        data = c.create_string_buffer(width * count)
        self.owner._overlay_log(self.owner.handle, self.kind, data, count)
        return [f'{int.from_bytes(data.raw[i:i+width], "little"):04x}' if self.kind
                else data.raw[i:i+width].hex() for i in range(0, len(data), width)]
    def __iter__(self): return iter(self.values())
    def __len__(self): return len(self.values())
    def __getitem__(self, index): return self.values()[index]
    def append(self, value):
        data = int(value, 16).to_bytes(2, 'little') if self.kind else bytes.fromhex(value)
        self.owner.overlay(4 if self.kind else 3, data)


class NativeDeliveries(MutableMapping):
    def __init__(self, owner): self.owner = owner
    @staticmethod
    def key(value):
        header, data = value.split(':')
        return (int(header, 16) << 16) | int(data, 16)
    def __getitem__(self, key):
        if not self.owner._finalizer.alive: return self.owner._final_delivered.get(key, 0)
        return self.owner.message(4, self.key(key))
    def __setitem__(self, key, value): self.owner.message(5, self.key(key), value)
    def __delitem__(self, key): raise TypeError('mailbox totals cannot be deleted')
    def __iter__(self):
        if not self.owner._finalizer.alive: return iter(self.owner._final_delivered)
        count = self.owner._message_keys(self.owner.handle, None, 0)
        values = (c.c_uint32 * count)()
        self.owner._message_keys(self.owner.handle, values, count)
        return iter(f'{v >> 16:04x}:{v & 65535:04x}' for v in values)
    def __len__(self):
        if not self.owner._finalizer.alive: return len(self.owner._final_delivered)
        return self.owner._message_keys(self.owner.handle, None, 0)

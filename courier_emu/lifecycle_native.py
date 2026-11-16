"""Live views of the native analog DSP loader and lifecycle owner."""
import ctypes as c
import weakref
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
}
BOOLEAN = {'reset_asserted', 'cpu_int1', 'restarted', 'loader_started', 'nmi_seen',
           'active', 'launched', 'runtime_mode', 'runtime_ready'}


class LifecycleState(c.Structure):
    _fields_ = [(name, c.c_int64 if name == 'runtime_delay' else
                 c.c_double if name == 'audio_samples_due' else c.c_uint64)
                for name in ('reset_asserted', 'cpu_int1', 'nmi_low', 'restarted',
                    'loader_started', 'nmi_seen', 'destination', 'active', 'launched',
                    'runtime_mode', 'runtime_ready', 'runtime_delay', 'line_tx_index',
                    'sip_tx_index', 'audio_frames', 'audio_samples_due', 'match', 'last_bytes',
                    'last_match', 'bootstraps', 'transfers', 'checksums', 'bootstrap_size',
                    'boot_strobes_native')]
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
        from .bridge import C51_NMI_DISPATCH_CELL, C51_ROM_NMI_ENTRY, C50_ROM_FRAME_IRQ
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
        self._config = (c.c_uint64 * 5)(bridge.transfer.first_strobe, bridge.bootstrap_target_size,
            C51_NMI_DISPATCH_CELL, C51_ROM_NMI_ENTRY, C50_ROM_FRAME_IRQ)
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

    def close(self):
        if self._finalizer.alive:
            self._final_bootstrap = self.bytes()
            self._final_resets = self.resets()
            self._finalizer()


class LifecycleField:
    def __init__(self, field): self.field = field
    def __get__(self, owner, cls=None):
        if owner is None: return self
        value = getattr(owner._native_lifecycle.state, self.field)
        if self.field in ('match', 'last_match'): return None if value == 2 else bool(value)
        return bool(value) if self.field in BOOLEAN else value
    def __set__(self, owner, value):
        if self.field in ('match', 'last_match') and value is None: value = 2
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

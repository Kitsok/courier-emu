"""Live machine fields and queue backed by the native analog DTE receiver."""
import ctypes as c
from .dsp import load_library
from .service_native import NativeServiceMachine


class ReceiveState(c.Structure):
    _fields_ = [(name, c.c_uint64) for name in
                ('opened', 'attention_armed', 'started', 'edge_at', 'bit', 'count')]


class NativeReceiver:
    def __init__(self, machine, uc):
        lib = load_library()
        lib.courier_receive_layout.restype = c.c_size_t
        if lib.courier_receive_layout() != c.sizeof(ReceiveState):
            raise RuntimeError('native receive ABI mismatch')
        self.state = ReceiveState()
        self._memory = (c.c_uint8 * len(uc.memory)).from_buffer(uc.memory)
        self.memory_address = c.addressof(self._memory)
        layout = machine._rom_serial
        values = (c.c_uint64 * 10)(*(getattr(layout, name) for name in
            ('callbacks', 'receive_isr', 'attention', 'command_idle', 'command_collecting',
             'mode', 'output_flags', 'online_idle', 'echo_setting')), 0)

        def bind(name, result, *args):
            return c.PYFUNCTYPE(result, *args)(
                c.cast(getattr(lib, 'courier_receive_' + name), c.c_void_p).value)

        create = bind('create', c.c_void_p, c.c_void_p, c.c_void_p)
        self.handle = create(c.addressof(self.state), values)
        if not self.handle:
            raise MemoryError('cannot allocate native receive queue')
        self._destroy = bind('destroy', None, c.c_void_p)
        self._push = bind('push', c.c_int, c.c_void_p, c.c_char_p, c.c_size_t)
        self._pop = bind('pop', c.c_int, c.c_void_p)
        self._peek = bind('peek', c.c_int, c.c_void_p, c.c_size_t)
        self._advance = bind('advance', c.c_uint, c.c_void_p, c.c_void_p,
                             c.c_void_p, c.c_void_p, c.c_void_p, c.c_uint64, c.c_uint)
        self.uart_address = machine.uart.address
        self.irq_address = machine._native_service_address
        self.wire_address = machine.dte_line.address
        self.extend(machine.serial_rx)

    def __del__(self):
        if getattr(self, 'handle', None):
            self._destroy(self.handle)
            self.handle = None

    def __len__(self):
        return self.state.count

    def __getitem__(self, index):
        if index < 0:
            index += len(self)
        value = -1 if index < 0 else self._peek(self.handle, index)
        if value < 0:
            raise IndexError('receive queue index out of range')
        return value

    def extend(self, values):
        data = bytes(values)
        if data and self._push(self.handle, data, len(data)):
            raise MemoryError('cannot extend native receive queue')

    def popleft(self):
        value = self._pop(self.handle)
        if value < 0:
            raise IndexError('pop from an empty receive queue')
        return value

    def advance(self, now, flags):
        return self._advance(self.handle, self.memory_address, self.uart_address,
                             self.irq_address, self.wire_address, now, flags)


FIELDS = {'_rom_dte_opened': 'opened', '_online_attention_armed': 'attention_armed',
          '_rx_started_at': 'started', '_rx_edge_at': 'edge_at', '_rom_rx_bit': 'bit'}


class NativeReceiveMachine(NativeServiceMachine):
    @classmethod
    def adopt(cls, machine, uc):
        if type(machine) is not NativeServiceMachine and not isinstance(machine, cls):
            return None
        original = {name: getattr(machine, name) for name in FIELDS}
        receiver = NativeReceiver(machine, uc)
        machine._native_receiver = receiver
        if type(machine) is NativeServiceMachine:
            machine.__class__ = cls
        machine.serial_rx = receiver
        for name, value in original.items():
            setattr(machine, name, value)
        return receiver


def _field(field):
    return property(lambda self: getattr(self._native_receiver.state, field),
                    lambda self, value: setattr(self._native_receiver.state, field, value))


for _name, _native in FIELDS.items():
    setattr(NativeReceiveMachine, _name, _field(_native))

"""Verify the experimental MAME-to-Courier bus adapter, not the MAME ISA."""
import pytest

from courier_emu import x86_interpreter as x
from courier_emu.x86_mame import LIBRARY, MameUc


pytestmark = pytest.mark.skipif(
    not LIBRARY.exists(),
    reason='build the optional backend with COURIER_X86_BACKEND=mame ./build.sh',
)


def cpu():
    result = MameUc(0, 0)
    result.mem_map(0, 0x100000)
    result.reg_write(x.UC_X86_REG_SP, 0x8000)
    return result


def test_mame_word_device_accesses_and_port_callbacks_keep_width_and_time():
    machine = cpu()
    events = []

    def read(owner, _access, address, size, _value, _user):
        events.append(('read', address, size, owner.retired))
        owner.mem_write(address, (0xabcd).to_bytes(size, 'little'))

    def write(owner, _access, address, size, value, _user):
        events.append(('write', address, size, value, owner.retired))

    machine.hook_add(x.UC_HOOK_MEM_READ, read, None, 0xff66, 0xff67)
    machine.hook_add(x.UC_HOOK_MEM_WRITE, write, None, 0xff6a, 0xff6b)
    machine.hook_add(x.UC_HOOK_INSN, lambda *_: 0x42, None, 1, 0, x.UC_X86_INS_IN)
    machine.hook_add(x.UC_HOOK_INSN, lambda owner, p, n, v, _: events.append(
        ('out', p, n, v, owner.retired)), None, 1, 0, x.UC_X86_INS_OUT)
    machine.mem_write(0x1000, bytes.fromhex('a1 66 ff a3 6a ff ba 34 12 ec ee 90'))
    machine.emu_start(0x1000, 0, count=6)
    assert events == [('read', 0xff66, 2, 0), ('write', 0xff6a, 2, 0xabcd, 1),
                      ('out', 0x1234, 1, 0x42, 5)]
    assert machine.regs[x.UC_X86_REG_AX] == 0xab42
    assert machine.retired == machine.mame_retired == 6
    assert machine._native is None


def test_mame_clock_stop_resume_and_callback_register_updates(monkeypatch):
    machine = cpu()
    monkeypatch.setattr(x.Uc, 'emu_start', lambda *_a, **_kw: pytest.fail('Python CPU fallback'))
    machine.mem_write(0x1000, b'\x40' * 20)  # INC AX
    clocks = []

    def service(owner, now, _):
        clocks.append(now)
        owner.reg_write(x.UC_X86_REG_AX, 100)
        owner.emu_stop()

    machine.instruction_clock_add(4, service)
    machine.emu_start(0x1000, 0, count=10)
    assert clocks == [4]
    assert machine.retired == 3 and machine.regs[x.UC_X86_REG_AX] == 100
    machine._clock_callback = None
    machine.emu_start(0x1003, 0, count=2)
    assert machine.retired == 5 and machine.regs[x.UC_X86_REG_AX] == 102


def test_mame_stops_after_inflight_write_and_before_watched_instruction():
    machine = cpu()
    machine.mem_write(0x1000, bytes.fromhex('a3 6a ff 40'))
    machine.reg_write(x.UC_X86_REG_AX, 0x1234)
    machine.hook_add(x.UC_HOOK_MEM_WRITE, lambda owner, *_: owner.emu_stop(),
                     None, 0xff6a, 0xff6b)
    machine.emu_start(0x1000, 0, count=2)
    assert machine.retired == 1 and machine.mem_read(0xff6a, 2) == b'\x34\x12'
    assert machine.regs[x.UC_X86_REG_AX] == 0x1234
    machine.hook_add(x.UC_HOOK_CODE, lambda owner, *_: owner.emu_stop(), None, 0x1003, 0x1003)
    machine.emu_start(0x1003, 0, count=1)
    assert machine.retired == 1 and machine.regs[x.UC_X86_REG_IP] == 0x1003
    with pytest.raises(BufferError):
        machine.memory.append(0)  # persistent native pointers must stay valid


@pytest.mark.parametrize('code,vector,fault', [(b'\xcd\x31', 0x31, None), (b'\x0f', 6, 6)])
def test_mame_interrupt_notifications_preserve_board_dispatch(code, vector, fault):
    machine = cpu()
    observed = []

    def interrupt(owner, number, _):
        observed.append((number, owner.fault))
        owner.emu_stop()

    machine.hook_add(x.UC_HOOK_INTR, interrupt)
    machine.mem_write(0x1000, code)
    machine.emu_start(0x1000, 0, count=1)
    assert observed == [(vector, fault)]
    assert machine.retired == 1


def test_mame_native_uart_and_irq_delivery_avoid_device_callbacks():
    import ctypes
    from collections import Counter
    from courier_emu.service_native import ServiceState, NativeSerialPending
    from courier_emu.uart import EbSerial
    from courier_emu.uart_native import NativeEbSerial

    machine = cpu()
    buffer = bytearray(ctypes.sizeof(ServiceState))
    state = ServiceState.from_buffer(buffer)
    state.irq_enabled = 1
    reference = EbSerial()
    reference.pending = NativeSerialPending(state, [])
    uart = NativeEbSerial(reference, state)
    machine.native_irq_state, machine.native_irq_model = buffer, state
    machine.native_uart, machine.native_uart_counts = uart, Counter()

    def unexpected(*_):
        pytest.fail('native UART/EOI access crossed into Python')

    machine.hook_add(x.UC_HOOK_MEM_READ, unexpected, None, 0xff60, 0xff6b)
    machine.hook_add(x.UC_HOOK_MEM_WRITE, unexpected, None, 0xff00, 0xff6b)
    machine.native_uart_hooks = (unexpected, unexpected)
    machine.native_mmio_batch = ((0xff02, 0xff03),)
    output = []

    def replay(events, count):
        for offset in range(0, count * 8, 8):
            if events[offset + 7] == 4 and events[offset] == 0x6a:
                output.append(events[offset + 4])

    machine.native_mmio_callback = replay
    # RX ISR echoes the byte through native UART and EOIs once, then IRETs.
    machine.mem_write(0x50, b'\x00\x20\x00\x00')
    machine.mem_write(0x2000, bytes.fromhex('a0 68 ff a2 6a ff c7 06 02 ff 00 80 cf'))
    machine.mem_write(0x1000, bytes.fromhex('fb 40 90 90 90'))
    uart.deliver(0x55)
    machine.emu_start(0x1000, 0, count=2)
    assert state.irq_entries[2] == 0  # STI's following instruction is protected
    machine.emu_start(0x1002, 0, count=4)
    assert output == [0x55] and state.irq_entries[2] == 1
    assert state.stack_depth == 0 and list(uart.pending) == [0x15]
    assert uart.native_state.native_reads == uart.native_state.native_writes == 1

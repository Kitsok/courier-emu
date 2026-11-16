"""Native analog IRQ delivery must survive masked windows and preserve guards."""
import ctypes

import pytest

from courier_emu import x86_interpreter as x86
from courier_emu.service_native import ServiceState


def machine():
    cpu = x86.Uc(0, 0)
    cpu.mem_map(0, 0x10000)
    cpu.reg_write(x86.UC_X86_REG_SP, 0x8000)
    cpu.reg_write(x86.UC_X86_REG_SI, 0x400)
    cpu.reg_write(x86.UC_X86_REG_FLAGS, 0x202)
    cpu.mem_write(0x1000, b'\x90' * 200)
    buffer = bytearray(ctypes.sizeof(ServiceState))
    state = ServiceState.from_buffer(buffer)
    state.irq_enabled = 1
    cpu.native_irq_state = buffer
    cpu.native_irq_model = state
    for vector in (8, 12, 13, 15, 20, 21):
        address = 0x2000 + vector*32
        cpu.mem_write(vector*4, address.to_bytes(2, 'little') + b'\0\0')
        # Record delivery order, EOI, then return through the guest stack.
        cpu.mem_write(address, bytes((0xc6, 4, vector, 0x46))
                      + bytes.fromhex('c7 06 02 ff 00 80 cf'))
    return cpu, state


def test_native_irq_priority_uart_fifo_and_eoi_without_python_dispatch():
    cpu, state = machine()
    state.external_pending, state.int0_pending = 15, 12
    state.serial_pending[:], state.serial_count = (21, 20), 2
    state.int1_pending, state.timer_pending = 13, 8
    state.refresh_pending()
    cpu.emu_start(0x1000, 0, count=100)
    assert bytes(cpu.mem_read(0x400, 6)) == bytes((15, 12, 21, 20, 13, 8))
    assert list(state.irq_entries) == [1, 1, 2, 1, 1]
    assert state.pending_mask == state.stack_depth == state.int0_in_service == 0
    assert state.timer_delivered == 1
    assert cpu.retired == cpu._native.retired == 100
    assert cpu._native_irq_guard_fallbacks == 0


def test_native_irq_enters_immediately_after_popf_restores_if():
    cpu, state = machine()
    cpu.reg_write(x86.UC_X86_REG_FLAGS, 2)
    cpu.mem_write(0x8000, b'\x02\x02')
    cpu.mem_write(0x1010, b'\x9d')
    state.int0_pending = 12
    state.refresh_pending()
    cpu.emu_start(0x1000, 0, count=17)
    assert cpu.reg_read(x86.UC_X86_REG_FLAGS) & x86.IF
    assert list(state.irq_entries) == [0]*5
    cpu.emu_start(0x1011, 0, count=8)
    assert cpu.mem_read(0x400, 1) == b'\x0c'
    assert state.irq_entries[1] == 1 and state.pending_mask == 0
    assert cpu._clock_callback is None  # no Python clock/IRQ callback required


@pytest.mark.parametrize('guarded', ('vector', 'stack'))
def test_native_irq_guarded_entry_leaves_request_cpu_and_memory_intact(guarded):
    cpu, state = machine()
    state.int0_pending = 12
    state.refresh_pending()
    kind, address = ((x86.UC_HOOK_MEM_READ, 48) if guarded == 'vector'
                     else (x86.UC_HOOK_MEM_WRITE, 0x7ffa))
    cpu.hook_add(kind, lambda *_: None, None, address, address+1)
    before = list(cpu.regs), bytes(cpu.memory), bytes(cpu.native_irq_state)
    cpu.reg_write(x86.UC_X86_REG_IP, 0x1000)
    before[0][x86.UC_X86_REG_IP] = 0x1000
    cpu.emu_start(0x1000, 0, count=8)
    assert (cpu.regs, bytes(cpu.memory), bytes(cpu.native_irq_state)) == before
    assert cpu._native_irq_fallback and cpu._native_irq_guard_fallbacks == 1
    assert cpu.retired == 0


@pytest.mark.parametrize('watched', [False, True])
@pytest.mark.parametrize('opcode,flags', [(b'\xfb', 2), (b'\x8e\xd0', 0x202),
                                         (b'\x17', 0x202)])
def test_native_irq_preserves_one_instruction_shadow_across_batches(opcode, flags, watched):
    cpu, state = machine()
    cpu.reg_write(x86.UC_X86_REG_FLAGS, flags)
    cpu.mem_write(0x8000, b'\0\0')
    cpu.mem_write(0x1000, opcode + bytes.fromhex('be 00 05') + b'\x90'*50)
    if watched:
        cpu.hook_add(x86.UC_HOOK_CODE, lambda *_: None, None, 0x1000, 0x1000)
    cpu.emu_start(0x1000, 0, count=1)
    assert state.interrupt_shadow == 1
    state.int0_pending = 12
    state.refresh_pending()
    cpu.emu_start(0x1000+len(opcode), 0, count=20)
    assert cpu.mem_read(0x500, 1) == b'\x0c'
    assert cpu.mem_read(0x400, 1) == b'\0'
    assert state.irq_entries[1] == 1


def test_sti_with_if_already_set_does_not_extend_interrupt_shadow():
    cpu, state = machine()
    cpu.mem_write(0x1000, bytes.fromhex('fb be 00 05') + b'\x90'*50)
    cpu.emu_start(0x1000, 0, count=1)
    assert state.interrupt_shadow == 0
    state.int0_pending = 12
    state.refresh_pending()
    cpu.emu_start(0x1001, 0, count=20)
    assert cpu.mem_read(0x400, 1) == b'\x0c'


@pytest.mark.parametrize('guarded', ('code', 'write'))
def test_native_irq_publishes_entry_when_first_handler_instruction_yields(guarded):
    cpu, state = machine()
    kind, address = ((x86.UC_HOOK_CODE, 0x2000+12*32) if guarded == 'code'
                     else (x86.UC_HOOK_MEM_WRITE, 0x400))
    cpu.hook_add(kind, lambda *_: None, None, address, address)
    state.int0_pending = 12
    state.refresh_pending()
    cpu.emu_start(0x1000, 0, count=20)
    assert cpu.mem_read(0x400, 1) == b'\x0c'
    assert state.irq_entries[1] == 1
    assert state.stack_depth == state.int0_in_service == state.pending_mask == 0
    assert cpu.reg_read(x86.UC_X86_REG_SP) == 0x8000


def test_native_irq_survives_device_poll_aliasing_a_cli_popf_loop():
    cpu, state = machine()
    cpu.mem_write(0x1000, b'\x90'*4 + bytes.fromhex('9c fa 90 90 90 90 9d eb f7'))
    produced = []

    def poll(cpu, total, _user):
        if not produced:
            assert not cpu.reg_read(x86.UC_X86_REG_FLAGS) & x86.IF
            state.int0_pending = 12
            state.refresh_pending()
            produced.append(total)

    cpu.instruction_clock_add(8, poll)
    cpu.emu_start(0x1000, 0, count=100)
    assert produced == [8]
    assert cpu.mem_read(0x400, 1) == b'\x0c'
    assert state.irq_entries[1] == 1 and state.pending_mask == 0
    assert cpu._clock_interrupt_retries == 0


def test_native_specific_eoi_removes_matching_in_service_vector():
    cpu, state = machine()
    state.stack_depth, state.int0_in_service = 2, 1
    state.stack[:2] = (12, 15)
    cpu.mem_write(0x1000, bytes.fromhex('c7 06 02 ff 0c 00'))
    cpu.emu_start(0x1000, 0, count=1)
    assert state.stack_depth == 1 and state.stack[0] == 15
    assert state.int0_in_service == 0


def test_python_device_event_enters_irq_before_boundary_instruction():
    cpu, state = machine()
    cpu.mem_write(0x1000, b'\x90'*7 + bytes.fromhex('be 00 05') + b'\x90'*50)
    produced = []

    def poll(cpu, total, _user):
        if not produced:
            state.int0_pending = 12
            state.refresh_pending()
            produced.append(total)

    cpu.instruction_clock_add(8, poll)
    cpu.emu_start(0x1000, 0, count=30)
    assert produced == [8]
    assert cpu.mem_read(0x400, 1) == b'\x0c'
    assert cpu.mem_read(0x500, 1) == b'\0'
    assert state.irq_entries[1] == 1

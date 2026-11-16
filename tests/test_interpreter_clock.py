import pytest

from courier_emu import x86_interpreter as x86


def _cpu(code: bytes):
    cpu = x86.Uc(0, 0, profile="186eb")
    cpu.mem_map(0, 0x1000)
    cpu.mem_write(0, code)
    return cpu


def test_instruction_clock_calls_at_bounded_intervals():
    cpu = _cpu(b"\x90" * 12)
    calls = []
    cpu.instruction_clock_add(4, lambda _cpu, total, _user: calls.append(total))

    cpu.emu_start(0, 0, count=10)

    assert calls == [4, 8]
    assert cpu.retired == 10


def test_instruction_clock_can_stop_before_boundary_instruction():
    cpu = _cpu(b"\x90" * 12)

    def stop(cpu, _total, _user):
        cpu.emu_stop()

    cpu.instruction_clock_add(4, stop)
    cpu.emu_start(0, 0, count=10)

    assert cpu.retired == 3
    assert cpu.reg_read(x86.UC_X86_REG_IP) == 3


@pytest.mark.parametrize('native', [False, True])
def test_masked_poll_retries_when_critical_section_restores_interrupts(native):
    # Four setup instructions align every eight-instruction poll with CLI.
    # The loop does enable interrupts, but a periodic sampler never sees it.
    code = b'\x90'*4 + bytes.fromhex('9c fa 90 90 90 90 9d eb f7')
    states = []
    for retry in (False, True):
        cpu = _cpu(code)
        cpu.native_enabled = native
        cpu.reg_write(x86.UC_X86_REG_SP, 0x800)
        cpu.reg_write(x86.UC_X86_REG_FLAGS, 0x202)
        calls = []

        def poll(cpu, total, _user):
            enabled = bool(cpu.reg_read(x86.UC_X86_REG_FLAGS) & x86.IF)
            calls.append((total, enabled))
            if retry and not enabled:
                cpu._clock_interrupt_retry = True

        cpu.instruction_clock_add(8, poll)
        cpu.emu_start(0, 0, count=100)
        assert cpu.retired == 100
        states.append(calls)
        if retry:
            assert cpu._clock_interrupt_retries > 0
    assert states[0] and not any(enabled for _, enabled in states[0])
    assert any(enabled for _, enabled in states[1])

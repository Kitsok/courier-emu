"""Rollback must retain progress made by preceding register-only instructions."""
import pytest
from courier_emu import x86_interpreter as x86


@pytest.mark.parametrize('profile', ['186eb', '386ex'])
@pytest.mark.parametrize('tail', [bytes.fromhex('a10030'), bytes.fromhex('a30030'), b'\x60'])
def test_watchpoint_after_register_only_progress_matches_reference(profile, tail):
    cpus, observations = [], []
    # MOV/INC/XCHG/STC followed by a guarded read, store or multi-store PUSHA.
    code = bytes.fromhex('b83412 40 bb7856 93 f9') + tail
    for native in (False, True):
        cpu = x86.Uc(0, 0, profile=profile)
        cpu.native_enabled = native
        cpu.mem_map(0, len(cpu.memory))
        cpu.mem_write(0x1000, code)
        cpu.reg_write(x86.UC_X86_REG_SP, 0x3008)
        seen = []
        def observe(uc, access, address, size, value, user):
            seen.append((access, address, size, value, tuple(uc.regs)))
        cpu.hook_add(x86.UC_HOOK_MEM_READ | x86.UC_HOOK_MEM_WRITE, observe, None, 0x3000, 0x300f)
        cpu.emu_start(0x1000, 0, count=6)
        cpus.append(cpu); observations.append(seen)
    assert observations[0] == observations[1]
    assert cpus[0].regs == cpus[1].regs
    assert cpus[0].memory == cpus[1].memory


def test_prefix_and_extended_register_fallback_keeps_current_ip():
    cpus = []
    code = bytes.fromhex('b83412 40 66b878563412 40')
    for native in (False, True):
        cpu = x86.Uc(0, 0, profile='386ex')
        cpu.native_enabled = native
        cpu.mem_map(0, len(cpu.memory))
        cpu.mem_write(0x1000, code)
        cpu.emu_start(0x1000, 0, count=4)
        cpus.append(cpu)
    assert cpus[0].regs == cpus[1].regs
    assert cpus[0].memory == cpus[1].memory

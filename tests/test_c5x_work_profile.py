"""Diagnostic work counts distinguish execution, native blocks and idle clocks."""
import struct
import pytest
from courier_emu.dsp import NativeC5x


def words(values):
    return struct.pack('<%dH'%len(values),*values)


def profiled_core(code, origin=0x6000):
    core=NativeC5x.from_program(origin,words(code))
    if not core.clear_work_profile():
        core.close()
        pytest.skip('requires a C5X_PROFILE_WORK diagnostic library')
    core.host_write(0x26,0x10)
    core.set_pc(origin)
    return core


def test_idle_fast_forward_does_not_count_executed_opcodes():
    with profiled_core([0xbe22]) as core:
        core.step_cycles(100000)
        assert core.state()['instructions']>=100000
        assert core.work_profile()==[[0x6000,1,0,0xbe22,0]]


def test_delay_slots_count_as_executed_bodies():
    with profiled_core([0x7d80,0x6004,0x7800,0x7800,0x8b00]) as core:
        core.step(1)
        assert core.state()['instructions']==1
        assert core.work_profile()==[[0x6000,1,0,0x7d80,0],
                                     [0x6002,1,0,0x7800,0],
                                     [0x6003,1,0,0x7800,0]]


def test_hardware_repeat_counts_one_opcode_body():
    with profiled_core([0xbb07,0xa290,0x7000]) as core:
        core.host_write(0x10,0x310)
        core.load_program(words(range(1,9)),0x7000)
        core.step(2)
        assert core.work_profile()==[[0x6000,1,0,0xbb07,0],[0x6001,1,0,0xa290,0]]


def test_reset_retains_diagnostic_work_and_detects_opcode_changes():
    with profiled_core([0x8b00]) as core:
        core.step(1)
        core.reset()
        core.load_program(words([0x7801]),0x6000)
        core.set_pc(0x6000);core.step(1)
        assert core.work_profile()==[[0x6000,2,0,0x7801,1]]
        assert core.clear_work_profile()
        assert core.work_profile()==[]


@pytest.mark.parametrize('enabled',[False,True])
def test_native_arithmetic_work_is_not_counted_twice(monkeypatch,enabled):
    monkeypatch.setenv('COURIER_C5X_TRAINING_BLOCK','1' if enabled else '0')
    block=[0x528a,0x8d7d,0x8c7e,0x7304,0x557e,0x8d7e,
           0x547d,0xbe03,0x627e,0x61a0,0x6290]
    with profiled_core([0x8b00,*block],0x879c) as core:
        core.host_write(7,0x30)
        core.host_write(0x10,0x320);core.host_write(0x12,0x330)
        core.load_program(words([0xbc06]),0x6000)
        core.set_pc(0x6000);core.step(1);core.clear_work_profile()
        core.set_pc(0x879c);core.step_cycles(12)
        rows=core.work_profile()
        assert rows[0]==[0x879c,1,0,0x8b00,0]
        assert rows[1:]==[[0x879d+i,1,int(enabled),op,0] for i,op in enumerate(block)]


@pytest.mark.parametrize('enabled',[False,True])
def test_native_repeat_counts_each_represented_opcode_once(monkeypatch,enabled):
    monkeypatch.setenv('COURIER_C5X_TRAINING_BLOCK','1' if enabled else '0')
    block=[0x6a8a,0x628e,0x747e,0x548d,0x5199,0x98aa,0x90ab,
           0x6a8c,0x628e,0x747d,0x549d,0x508b,0x98ac,0x90a9]
    with profiled_core([0x8b00,0xbec6,0xb95d,*block],0xb94d) as core:
        core.host_write(7,0x30);core.host_write(9,2)
        for ar in range(8):core.host_write(0x10+ar,0x340+ar*16)
        core.load_program(words([0xbc06]),0x6000)
        core.set_pc(0x6000);core.step(1);core.clear_work_profile()
        core.set_pc(0xb94d);core.step_cycles(45)
        assert core.work_profile()==[[0xb94d,1,0,0x8b00,0],[0xb94e,1,0,0xbec6,0],
            *[[0xb950+i,3,3*int(enabled),op,0] for i,op in enumerate(block)]]

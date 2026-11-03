"""Guarded observed arithmetic block agrees with instruction execution."""
import ctypes
import struct
import pytest
from courier_emu.dsp import NativeC5x

BLOCK = [0x528a,0x8d7d,0x8c7e,0x7304,0x557e,0x8d7e,
         0x547d,0xbe03,0x627e,0x61a0,0x6290]


def words(values):
    return struct.pack('<%dH' % len(values), *values)


def run(monkeypatch, enabled, budget, pm, ovm, changed=False, trace=False, near_event=False, alias=False):
    monkeypatch.setenv('COURIER_C5X_TRAINING_BLOCK', str(enabled))
    setup = [0xbf08,0x320,0xbf0a,0x37d if alias else 0x330,0xbc06,0xbf00|pm,
             0xbe43 if ovm else 0xbe42,0xbf8f,0x7fff]
    with NativeC5x.from_program(0x6000, words(setup)) as core:
        core.host_write(7,0x30)
        if not near_event:core.host_write(0x26,0x10) # Admit an event-free window.
        for a in range(0x300,0x380):core.set_data(a,(a*137)^0xaaaa)
        core.set_pc(0x6000);core.step(6)
        code = list(BLOCK)
        if changed:code[8] = 0x7800
        core.load_program(words([0x8b00,*code,*([0x7800]*16)]),0x879c)
        core.trace_data_writes(trace);core.set_pc(0x879c)
        core.step_cycles(budget)
        query=core.library.courier_c5x_training_block_hits
        query.argtypes=[ctypes.c_void_p];query.restype=ctypes.c_uint64
        hits=query(core.handle)
        snapshot=(core.state(),core.serial_state(),core.memory_map(),
                  [core.data(a) for a in range(0x300,0x380)],
                  [core.data_write_count(a) for a in range(0x300,0x380)])
        return snapshot,hits


@pytest.mark.parametrize('budget',[1,5,11,12,13])
@pytest.mark.parametrize('pm',range(4))
@pytest.mark.parametrize('ovm',[False,True])
def test_block_matches_reference(monkeypatch,budget,pm,ovm):
    expected,_=run(monkeypatch,0,budget,pm,ovm)
    actual,hits=run(monkeypatch,1,budget,pm,ovm)
    assert actual==expected
    assert hits==int(budget>=12)


@pytest.mark.parametrize('changed,trace',[(True,False),(False,True)])
def test_block_rejects_changed_code_or_tracing(monkeypatch,changed,trace):
    expected,_=run(monkeypatch,0,12,0,False,changed,trace)
    actual,hits=run(monkeypatch,1,12,0,False,changed,trace)
    assert actual==expected
    assert hits==0


def test_block_falls_back_at_timer_boundary(monkeypatch):
    expected,_=run(monkeypatch,0,12,0,False,near_event=True)
    actual,hits=run(monkeypatch,1,12,0,False,near_event=True)
    assert actual==expected
    assert hits==0


def test_block_preserves_live_operand_aliases(monkeypatch):
    expected,_=run(monkeypatch,0,12,0,True,alias=True)
    actual,hits=run(monkeypatch,1,12,0,True,alias=True)
    assert actual==expected
    assert hits==1

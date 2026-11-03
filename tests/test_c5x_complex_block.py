"""Observed V.32 arithmetic loop retains interpreter state and boundaries."""
import ctypes
import struct
import pytest
from courier_emu.dsp import NativeC5x

BLOCK = [0x6a8a,0x628e,0x747e,0x548d,0x5199,0x98aa,0x90ab,
         0x6a8c,0x628e,0x747d,0x549d,0x508b,0x98ac,0x90a9]

def words(values):
    return struct.pack('<%dH'%len(values), *values)


def run(monkeypatch, enabled, budget, pm=0, ovm=False, trm=False,
        repeat=True, alias=False, cbcr=0, trace=False, changed=False,
        near_event=False, short_repeat=False, arp=0):
    monkeypatch.setenv('COURIER_C5X_TRAINING_BLOCK', str(enabled))
    setup=[0xbf00|pm,0xbe43 if ovm else 0xbe42,0xbc06,0x7360,0x5461,0x8b88|arp]
    with NativeC5x.from_program(0x6000, words(setup)) as core:
        core.host_write(7,0x30 | (2 if trm else 0))
        if not near_event: core.host_write(0x26,0x10)
        for a in range(0x300,0x500): core.set_data(a,((a*137)^0xaaaa)&65535)
        for ar in range(8): core.host_write(0x10+ar,0x37d if alias else 0x340+ar*0x10)
        core.host_write(0x1a,0x3e0); core.host_write(0x1b,core.register(0x10+(cbcr&7)))
        core.host_write(0x1c,0x3f0); core.host_write(0x1d,core.register(0x10+((cbcr>>4)&7)))
        core.host_write(0x1e,cbcr)
        core.set_pc(0x6000); core.step(6)
        code=list(BLOCK)
        if changed: code[13]=0x90a8
        if repeat:
            image=[0x8b00,0xbec6,0xb959 if short_repeat else 0xb95d,*code]
            origin=0xb94d
            core.host_write(9,2)  # Three body executions.
        else:
            image=[0x8b00,*code]; origin=0xb94f
        core.load_program(words(image+[0x8b00]*64),origin)
        core.trace_data_writes(trace); core.set_pc(origin); core.step_cycles(budget)
        query=core.library.courier_c5x_complex_block_hits
        query.argtypes=[ctypes.c_void_p];query.restype=ctypes.c_uint64
        hits=query(core.handle)
        result=(core.state(),core.serial_state(),core.memory_map(),
                [core.register(a) for a in [4,6,7,*range(9,0x20)]],
                [core.data(a) for a in range(0x300,0x500)],
                [core.data_write_count(a) for a in range(0x300,0x500)])
        return result,hits


@pytest.mark.parametrize('budget',[3,16,17,18,31,45,46])
@pytest.mark.parametrize('pm',range(4))
@pytest.mark.parametrize('ovm,trm',[(False,False),(True,True)])
def test_repeat_block_matches_reference(monkeypatch,budget,pm,ovm,trm):
    expected,_=run(monkeypatch,0,budget,pm,ovm,trm)
    actual,hits=run(monkeypatch,1,budget,pm,ovm,trm)
    assert actual==expected
    assert (hits>0)==(budget>=17)


@pytest.mark.parametrize('cbcr',[0,0xef,0x0d,0xe0,0xdd,0x09,0xa0])
@pytest.mark.parametrize('arp',[0,1,5,7])
def test_live_aliases_and_circular_updates(monkeypatch,cbcr,arp):
    expected,_=run(monkeypatch,0,45,pm=2,ovm=True,alias=True,cbcr=cbcr,arp=arp)
    actual,hits=run(monkeypatch,1,45,pm=2,ovm=True,alias=True,cbcr=cbcr,arp=arp)
    assert actual==expected
    assert hits>0


@pytest.mark.parametrize('option',['trace','changed','near_event','short_repeat'])
def test_unsupported_windows_retain_interpreter(monkeypatch,option):
    expected,_=run(monkeypatch,0,17,**{option:True})
    actual,hits=run(monkeypatch,1,17,**{option:True})
    assert actual==expected
    assert hits==0


def test_straight_line_block_without_repeat(monkeypatch):
    expected,_=run(monkeypatch,0,15,repeat=False)
    actual,hits=run(monkeypatch,1,15,repeat=False)
    assert actual==expected
    assert hits==1

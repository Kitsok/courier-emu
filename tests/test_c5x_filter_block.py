"""The observed five-tap filter helper matches instruction-level execution."""
import ctypes
import struct
import pytest
from courier_emu.dsp import NativeC5x

BLOCK=[0x081f,0xb805,0x881f,0x7804,0xbe59,0xbb04,0xaa90,
       0xbe04,0x7805,0x7790,0x7780,0xa080,0x2f7b,0x9880,0xef00]

def words(values):return struct.pack('<%dH'%len(values),*values)


def run(monkeypatch,enabled,budget,pm=0,ovm=False,sxm=True,trm=False,
        arp=1,base=0x310,cbcr=0,saram=False,alias=False,changed=False,
        near_event=False,trace=False,watch=False,codec=False,braf=False,repeats=None):
    monkeypatch.setenv('COURIER_C5X_TRAINING_BLOCK',str(enabled))
    setup=[0xbc06,0xbf00|pm,0xbe43 if ovm else 0xbe42,
           0xbe47 if sxm else 0xbe46,0x8b88|arp]
    with NativeC5x.from_program(0x6000,words(setup)) as core:
        core.host_write(7,0x30 | (2 if trm else 0))
        if not near_event:core.host_write(0x26,0x10)
        if saram:base=0x810
        pma=0x2010 if alias else 0x2200 if saram else 0x7000
        addresses=sorted(set(range(0x300,0x380))|set(range(max(0x60,base-8),base+24)))
        for a in addresses:core.set_data(a,((a*137)^0xaaaa)&65535)
        core.load_program(words([30000,0xb9b0,0x7fff,0x8000,73]*4),pma)
        core.host_write(0x10+arp,base)
        core.host_write(0x1f,(pma-5)&65535)
        core.host_write(0xd,0x1b);core.host_write(0xe,0xd)
        core.host_write(0x1a,base+9);core.host_write(0x1b,base)
        core.host_write(0x1c,base+5);core.host_write(0x1d,base+4)
        core.host_write(0x1e,cbcr)
        core.set_pc(0x6000);core.step(5)
        if braf:core.host_write(7,0x31 | (2 if trm else 0))
        core.load_program(words([0x7a80,0x8aae if repeats is None else 0x8aac]+[0x8b00]*64),0x6000)
        code=list(BLOCK)
        if changed:code[11]=0xa081
        core.load_program(words(code),0x8aae)
        if repeats is not None:
            core.host_write(9,repeats)
            core.load_program(words([0xbec6,0x8abb]),0x8aac)
        core.trace_data_writes(trace)
        if watch:core.trace_register(0x1f,16)
        if codec:core.set_call_tdm_active(True);core.set_line_dac_slot(base+3)
        core.set_pc(0x6000);core.step_cycles(budget)
        query=core.library.courier_c5x_filter_block_hits
        query.argtypes=[ctypes.c_void_p];query.restype=ctypes.c_uint64
        hits=query(core.handle)
        snapshot=(core.state(),core.serial_state(),core.memory_map(),core.stack(),
            [core.register(a) for a in [4,6,7,*range(9,0x20)]],
            [(core.data(a),core.data_write_count(a)) for a in [0x1f,*addresses]],
            [core.program(pma+i) for i in range(5)],core.io_events(),core.register_trace())
        return snapshot,hits


@pytest.mark.parametrize('budget',[4,5,22,26,27,28])
@pytest.mark.parametrize('pm',range(4))
@pytest.mark.parametrize('ovm,sxm,trm',[(False,True,False),(True,False,True)])
def test_filter_preserves_flags_memory_and_budget(monkeypatch,budget,pm,ovm,sxm,trm):
    expected,_=run(monkeypatch,0,budget,pm,ovm,sxm,trm)
    actual,hits=run(monkeypatch,1,budget,pm,ovm,sxm,trm)
    assert actual==expected
    assert hits==int(budget>=23)


@pytest.mark.parametrize('arp,cbcr',[(0,0),(1,9),(1,0x90),(1,0x99),(6,0xef),(7,0xef)])
@pytest.mark.parametrize('base',[0x310,0x378])
def test_circular_updates_and_live_operands(monkeypatch,arp,cbcr,base):
    expected,_=run(monkeypatch,0,40,pm=2,arp=arp,cbcr=cbcr,base=base)
    actual,hits=run(monkeypatch,1,40,pm=2,arp=arp,cbcr=cbcr,base=base)
    assert actual==expected
    assert hits==1


@pytest.mark.parametrize('pm',range(4))
@pytest.mark.parametrize('alias',[False,True])
def test_saram_timing_and_coefficient_aliases(monkeypatch,pm,alias):
    expected,_=run(monkeypatch,0,32,pm=pm,saram=True,alias=alias)
    actual,hits=run(monkeypatch,1,32,pm=pm,saram=True,alias=alias)
    assert actual==expected
    assert hits==1


@pytest.mark.parametrize('option',['changed','near_event','trace','watch','codec','braf'])
def test_unsupported_cases_retain_instruction_execution(monkeypatch,option):
    expected,_=run(monkeypatch,0,27,**{option:True})
    actual,hits=run(monkeypatch,1,27,**{option:True})
    assert actual==expected
    assert hits==0


def test_external_delay_moves_retain_ignored_move_diagnostics(monkeypatch):
    expected,_=run(monkeypatch,0,40,base=0x8100)
    actual,hits=run(monkeypatch,1,40,base=0x8100)
    assert actual==expected
    assert hits==0


@pytest.mark.parametrize('repeats',[0,1,3])
@pytest.mark.parametrize('budget',[6,24,25,26,29,48,86])
def test_filter_body_preserves_block_repeat_edges(monkeypatch,repeats,budget):
    expected,_=run(monkeypatch,0,budget,repeats=repeats)
    actual,hits=run(monkeypatch,1,budget,repeats=repeats)
    assert actual==expected
    assert (hits>0)==(budget>=25)

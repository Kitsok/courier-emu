"""Native MADD helpers preserve delay slots, register writes and live aliases."""
import ctypes
import struct
import pytest
from courier_emu.dsp import NativeC5x

RETURNING=[0x881f,0x7804,0xbe59,0xbb04,0xab90,0xbe04,0x7804,0xa080,0xff00,0x2f7b,0x9880]
PREPARING=[0x8809,0x7804,0xbe59,0xbb04,0xab90,0xbe04,0x7804,0xa080,0x2f7b,0x9880]
def words(values):return struct.pack('<%dH'%len(values),*values)


def run(monkeypatch,enabled,budget,returns=True,pm=0,ovm=False,sxm=True,trm=False,
        arp=1,base=0x310,cbcr=0,saram=False,alias=False,changed=False,
        near_event=False,trace=False,watch=False,codec=False,braf=False):
    monkeypatch.setenv('COURIER_C5X_TRAINING_BLOCK',str(enabled))
    if saram:base=0x810
    pma=0x2010 if alias else 0x2200 if saram else 0x7000
    incoming=pma if returns else 3
    setup=[0xbc06,0xbf00|pm,0xbe43 if ovm else 0xbe42,
           0xbe47 if sxm else 0xbe46,0x8b88|arp,0xbf80,incoming]
    with NativeC5x.from_program(0x6000,words(setup)) as core:
        core.host_write(7,0x30 | (2 if trm else 0))
        if not near_event:core.host_write(0x26,0x10)
        addresses=sorted(set(range(0x300,0x380))|set(range(max(0x60,base-8),base+24)))
        for a in addresses:core.set_data(a,((a*137)^0xaaaa)&65535)
        core.load_program(words([30000,0xb9b0,0x7fff,0x8000,73]),pma)
        core.host_write(0x10+arp,base);core.host_write(0x1f,pma)
        core.host_write(0xd,0x1b);core.host_write(0xe,0xd)
        core.host_write(0x1a,base+9);core.host_write(0x1b,base)
        core.host_write(0x1c,base+5);core.host_write(0x1d,base+4)
        core.host_write(0x1e,cbcr)
        core.set_pc(0x6000);core.step(6)
        if braf:core.host_write(7,0x31 | (2 if trm else 0))
        first=0x8a7d if returns else 0x8aa2
        core.load_program(words([0x7a80,first]+[0x8b00]*64),0x6000)
        code=list(RETURNING if returns else PREPARING)
        if changed:code[7]=0xa081
        core.load_program(words(code+([] if returns else [0xef00])),first)
        core.trace_data_writes(trace)
        if watch:core.trace_register(0x1f if returns else 9,16)
        if codec:core.set_call_tdm_active(True);core.set_line_dac_slot(base+5)
        core.set_pc(0x6000);core.step_cycles(budget)
        query=core.library.courier_c5x_madd_block_hits
        query.argtypes=[ctypes.c_void_p];query.restype=ctypes.c_uint64
        snapshot=(core.state(),core.serial_state(),core.memory_map(),core.stack(),
            [core.register(a) for a in [4,6,7,*range(9,0x20)]],
            [(core.data(a),core.data_write_count(a)) for a in [9,0x1f,*addresses]],
            [core.program(pma+i) for i in range(5)],core.io_events(),core.register_trace())
        return snapshot,query(core.handle)


@pytest.mark.parametrize('returns',[False,True])
@pytest.mark.parametrize('budget',[4,5,18,19,20,21,23,30])
@pytest.mark.parametrize('pm',range(4))
@pytest.mark.parametrize('ovm,sxm,trm',[(False,True,False),(True,False,True)])
def test_madd_helpers_match_reference(monkeypatch,returns,budget,pm,ovm,sxm,trm):
    expected,_=run(monkeypatch,0,budget,returns,pm,ovm,sxm,trm)
    actual,hits=run(monkeypatch,1,budget,returns,pm,ovm,sxm,trm)
    assert actual==expected
    assert hits==int(budget>=(21 if returns else 19))


@pytest.mark.parametrize('returns',[False,True])
@pytest.mark.parametrize('arp,cbcr',[(0,0),(1,9),(1,0x90),(1,0x99),(6,0xef),(7,0xef)])
def test_madd_circular_updates_and_ar0_mirrors(monkeypatch,returns,arp,cbcr):
    expected,_=run(monkeypatch,0,40,returns,pm=2,arp=arp,cbcr=cbcr,base=0x378)
    actual,hits=run(monkeypatch,1,40,returns,pm=2,arp=arp,cbcr=cbcr,base=0x378)
    assert actual==expected
    assert hits==1


@pytest.mark.parametrize('returns',[False,True])
@pytest.mark.parametrize('pm',range(4))
@pytest.mark.parametrize('alias',[False,True])
def test_madd_saram_aliases_and_timing(monkeypatch,returns,pm,alias):
    expected,_=run(monkeypatch,0,40,returns,pm=pm,saram=True,alias=alias)
    actual,hits=run(monkeypatch,1,40,returns,pm=pm,saram=True,alias=alias)
    assert actual==expected
    assert hits==1


@pytest.mark.parametrize('returns',[False,True])
@pytest.mark.parametrize('option',['changed','near_event','trace','watch','codec','braf'])
def test_madd_unsupported_windows_fall_back(monkeypatch,returns,option):
    expected,_=run(monkeypatch,0,30,returns,**{option:True})
    actual,hits=run(monkeypatch,1,30,returns,**{option:True})
    assert actual==expected
    assert hits==0

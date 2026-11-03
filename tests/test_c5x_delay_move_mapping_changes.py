"""Delay-line copies follow remaps, including cached modes and write tracing."""
import struct
import pytest
from courier_emu.dsp import NativeC5x


def words(*values):
    return struct.pack('<%dH' % len(values), *values)


@pytest.mark.parametrize('model', ['c51', 'c52', 'c53'])
@pytest.mark.parametrize('opcode', [0x7790, 0x7290, 0xab90, 0xa390])
@pytest.mark.parametrize('trace', [False, True])
def test_delay_line_copy_tracks_cnf_ovly_and_cached_maps(model, opcode, trace):
    with NativeC5x.from_program(0x6000, b'', model=model) as core:
        core.host_write(0x1f, 0x7000)
        core.load_program(words(3), 0x7000)
        for pmst, cnf in ((0x30, 0), (0x30, 1), (0x10, 1), (0, 0), (0x30, 0)):
            core.host_write(7, pmst)
            core.load_program(words(0xbe45 if cnf else 0xbe44), 0x6100)
            core.set_pc(0x6100)
            core.step(1)
            for address in (0x100, 0x300, 0x800, 0xcfff):
                core.trace_data_writes(False)
                core.set_data(address, 7)
                core.set_data(address+1, 0x1234)
                code = [0xbf09, address, 0x8b89, opcode]
                if opcode == 0xa390:code.append(0x7000)
                core.load_program(words(*code), 0x6000)
                before = core.data_write_count(address+1)
                core.trace_data_writes(trace)
                core.set_pc(0x6000)
                core.step(3)
                internal = ((address == 0x100 and not cnf) or address == 0x300
                            or (address == 0x800 and model != 'c52' and bool(pmst & 0x20)))
                assert core.data(address+1) == (7 if internal else 0x1234)
                assert core.data_write_count(address+1)-before == int(internal)
                if trace:
                    events = core.data_events()
                    assert len(events) == int(internal)

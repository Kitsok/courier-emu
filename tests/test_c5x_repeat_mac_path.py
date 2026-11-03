"""Small repeated filters match the general path retained for write tracing."""
import struct
import pytest
from courier_emu.dsp import NativeC5x


def words(values):
    return struct.pack('<%dH' % len(values), *values)


@pytest.mark.parametrize('opcode', [0xa290, 0xa3a0, 0xab90, 0xaa80])
@pytest.mark.parametrize('pm', range(4))
def test_repeated_mac_matches_general_path(opcode, pm):
    snapshots = []
    for trace in (False, True):
        dma, pma = 0x310, 0x7000
        code = [0xbf09, dma, 0x8b89, 0xbf00 | pm, 0xbe43,
                0xbf8f, 0x7fff, 0xbe09, 0xbb07, opcode]
        if opcode >> 8 in (0xa2, 0xa3):code.append(pma)
        with NativeC5x.from_program(0x6000, words(code)) as core:
            core.host_write(7, 0x30 | (2 if pm & 1 else 0))
            core.host_write(0x1f, pma)
            core.load_program(words([30000, -18000 & 65535]*4), pma)
            for offset in range(-8, 10):
                core.set_data(dma+offset, (30000 if offset & 1 else -29000) & 65535)
            core.trace_data_writes(trace)
            core.set_pc(0x6000)
            core.step(8)
            snapshots.append(dict(state=core.state(), serial=core.serial_state(),
                mapping=core.memory_map(), temps=[core.register(r) for r in (0xc, 0xd, 0xe)],
                data=[core.data(dma+i) for i in range(-8, 10)],
                writes=[core.data_write_count(dma+i) for i in range(-8, 10)]))
    assert snapshots[0] == snapshots[1]

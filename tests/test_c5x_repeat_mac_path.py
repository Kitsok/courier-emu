"""Small repeated filters match the general path retained for write tracing."""
import struct
import pytest
from courier_emu.dsp import NativeC5x


def words(values):
    return struct.pack('<%dH' % len(values), *values)


@pytest.mark.parametrize('opcode,arp', [(0xa290, 1), (0xa3a0, 1), (0xab90, 1), (0xaa80, 1), (0xaa90, 0)])
@pytest.mark.parametrize('pm', range(4))
def test_repeated_mac_matches_general_path(opcode, arp, pm):
    snapshots = []
    for trace in (False, True):
        dma, pma = 0x310, 0x7000
        code = [0xbf08 | arp, dma, 0x8b88 | arp, 0xbf00 | pm, 0xbe43,
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


@pytest.mark.parametrize('model,pfirst,dma', [('c51', 0x2000, 0x808), ('c53', 0x4000, 0x808), ('c53', 0x4000, 0x13e8)])
def test_saram_repeat_preserves_live_coefficient_aliases(model, pfirst, dma):
    snapshots = []
    for trace in (False, True):
        # Coefficients alias the delay-line destinations in physical SARAM.
        pma, base = pfirst+dma-0x800, dma-8
        code = [0xbf09, dma, 0x8b89, 0xbb07, 0xaba0]
        with NativeC5x.from_program(0x6000, words(code), model=model) as core:
            core.host_write(7, 0x30)
            core.host_write(0x1f, pma)
            for i in range(24):core.set_data(base+i, i*13+1)
            core.trace_data_writes(trace)
            core.set_pc(0x6000)
            core.step(4)
            snapshots.append(dict(state=core.state(), mapping=core.memory_map(),
                data=[core.data(base+i) for i in range(24)],
                writes=[core.data_write_count(base+i) for i in range(24)]))
    assert snapshots[0] == snapshots[1]


@pytest.mark.parametrize('opcode', [0xa290, 0xa3a0, 0xab90, 0xaa80])
@pytest.mark.parametrize('buffer', [1, 2, 3])
@pytest.mark.parametrize('end', [0x300, 0x310, 0x309, 0x317, 0x320])
def test_circular_repeat_matches_general_path(opcode, buffer, end):
    snapshots = []
    for trace in (False, True):
        code = [0xbf08, 0x310, 0x8b88, 0xbb07, opcode]
        if opcode >> 8 in (0xa2, 0xa3):
            code.append(0x7000)
        with NativeC5x.from_program(0x6000, words(code)) as core:
            core.host_write(7, 0x30)
            core.host_write(0x1f, 0x7000)
            # Both selectors can name AR0. Buffer 1 wins when both enable.
            core.host_write(0x1a, 0x318)
            core.host_write(0x1b, end)
            core.host_write(0x1c, 0x308)
            core.host_write(0x1d, end)
            core.host_write(0x1e, (8 if buffer & 1 else 0) |
                            (0x80 if buffer & 2 else 0))
            core.load_program(words(range(1, 9)), 0x7000)
            for a in range(0x2f0, 0x330):
                core.set_data(a, (a*137)^0xaaaa)
            core.trace_data_writes(trace)
            core.set_pc(0x6000)
            core.step(4)
            snapshots.append(dict(state=core.state(), mapping=core.memory_map(),
                regs=[core.register(r) for r in range(0xc, 0x20)],
                data=[core.data(a) for a in range(0x2f0, 0x330)],
                writes=[core.data_write_count(a) for a in range(0x2f0, 0x330)]))
    assert snapshots[0] == snapshots[1]

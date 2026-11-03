"""Experimental dispatch pairing retains instruction boundaries and live code."""
import struct
import pytest
from courier_emu.dsp import NativeC5x


def snapshot(core):
    return (core.state(), core.serial_state(), core.memory_map(),
            [core.data(a) for a in range(0x2f0, 0x310)],
            [core.data_write_count(a) for a in range(0x2f0, 0x310)])


@pytest.mark.parametrize('budget', [1, 2, 3, 6, 12])
@pytest.mark.parametrize('rewrite', [False, True])
def test_pair_matches_reference_at_run_boundaries(monkeypatch, budget, rewrite):
    results = []
    for enabled in ('0', '1'):
        monkeypatch.setenv('COURIER_C5X_DMOV_PAIR', enabled)
        code = [0xbf09, 0x301, 0x8b89, 0x7790, 0x7780, 0x7980, 0x6003]
        with NativeC5x.from_program(0x6000, struct.pack('<7H', *code)) as core:
            for address in range(0x2f0, 0x310):
                core.set_data(address, address ^ 0x55aa)
            core.set_pc(0x6000)
            core.step(2)
            if rewrite:
                core.step_cycles(1)
                # Replace the second instruction after the first has retired.
                core.load_program(struct.pack('<H', 0x7800), 0x6004)
            core.step_cycles(budget)
            results.append(snapshot(core))
    assert results[0] == results[1]

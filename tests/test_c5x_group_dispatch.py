"""Grouped threaded dispatch must match instruction-stepped boundaries."""
import struct
import pytest
from courier_emu.dsp import NativeC5x


@pytest.mark.parametrize('pattern', [
    [0xbe00,0xbe01,0xbe02,0xbe03,0xbe04,0xbe05],
    [0xbf08,0x300,0xbf09,0x380,0xbf80,123,0xbe01,0xbe00],
    [0xbec4,3,0xbe00,0xbf80,77,0xbe01],
])
def test_grouped_cycle_runs_match_plain_instruction_steps(pattern):
    code=(pattern*256)
    program=struct.pack('<%dH'%len(code),*code)
    with NativeC5x.from_program(0x6000,program) as threaded, NativeC5x.from_program(0x6000,program) as plain:
        threaded.set_pc(0x6000);plain.set_pc(0x6000)
        for budget in (1, 2, 3, 7, 31, 97, 101):
            before=threaded.state()['instructions']
            threaded.step_cycles(budget)
            retired=threaded.state()['instructions']-before
            plain.step(retired)
            assert threaded.state()==plain.state()
            assert threaded.serial_state()==plain.serial_state()
            assert threaded.codec_state()==plain.codec_state()


def test_grouped_idle_and_interrupt_edges_match_plain_steps():
    program=struct.pack('<4H',0xbe40,0xbe22,0x8b00,0x8b00)
    with NativeC5x.from_program(0x6000,program) as threaded, NativeC5x.from_program(0x6000,program) as plain:
        for core in (threaded,plain):
            core.set_pc(0x6000);core.host_write(0x04,1<<5)
        for interrupt in (False,True):
            if interrupt:
                threaded.interrupt(5);plain.interrupt(5)
            before=threaded.state()['instructions']
            threaded.step_cycles(32)
            plain.step(threaded.state()['instructions']-before)
            assert threaded.state()==plain.state()

"""A false XC that skips the last word of an RPTB body must not end the block loop."""
import struct

from courier_emu.dsp import NativeC5x

LDP0, LACL2, SAMM_BRCR, CLRC_C, LACL0 = 0xBC00, 0xB902, 0x8809, 0xBE4E, 0xB900
RPTB, END, ADD1, XC1_C, ADD16, NOP = 0xBEC6, 0x0009, 0xB801, 0xE711, 0xB810, 0x8B00


def run(words, steps):
    with NativeC5x.from_program(0, struct.pack(f"<{len(words)}H", *words), rebuild=True) as core:
        core.step(steps)
        return core.state()


def test_false_xc_over_the_block_end_still_loops():
    # BRCR = 2 gives three passes. C is clear, so XC 1,C skips ADD #16, the
    # last word of the body. SPRU056D: the skipped word is a NOP, and its fetch
    # still triggers the block repeat. The core used to advance the PC past it
    # and leave after one pass (ACC = 1).
    prog = [LDP0, LACL2, SAMM_BRCR, CLRC_C, LACL0, RPTB, END, ADD1, XC1_C, ADD16, NOP, NOP, NOP, NOP]
    assert run(prog, 40)["acc"] & 0xFFFFFFFF == 3

# Reuse conditions within uninterrupted threaded execution

Each instruction's consume_cycles computes the current architectural
condition snapshot, stores it as the next start sample, and separately
retains XC's pipeline sample. Threaded continuation previously rebuilt
that same start sample again in step_begin. Skip only this duplicate
assignment during uninterrupted threaded continuation. Initial run entry,
individual/general steps and delay-slot execution still sample afresh.

Two handlers, taken BCND and CC, clear OV after charging their cycles.
Refresh their next-start sample after that clear while preserving the
existing XC pipeline sample. Delayed branches clear overflow before their
slots; the final slot already produces the next-start sample. Event
servicing changes interrupt/codec state, not ACC, OV, C or TC. Repeats
change addresses and PC, leaving the carried condition snapshot valid.

This changes neither guest arithmetic nor cycle counts. Seven new short
comparisons exercise threaded XC samples against individual steps,
including the two post-cycle overflow clears and final delay slots.
The notebook build and 162 focused checks pass. A broader interrupt-file
check has five IFR assertions failing with extra timer bit 8; the same
five failures reproduce with the preserved pre-arithmetic-inline library.
These are pre-existing failures, not passing coverage for this change.

A53 counters and actual training validation remain outstanding. This is
a distinct candidate from the previously rejected address-only cycle
specialization: consume_cycles and its condition calculation are intact;
only the redundant next-instruction assignment is removed. No physical
call was made for this stage.

The combined circular-span and snapshot-reuse notebook build also
completes one bounded loopback at 9600/ARQ/V34/LAPM/V42BIS on both
endpoints and exchanges exact marker data in both directions. The
arithmetic-block opt-in is enabled. Total setup/training/data time is
36.26 seconds; this is a functional check, not a controlled throughput
comparison. No cProfile or extra trace hook was enabled. See
`dsp-optimization-batch-local-9600.json`.

## A53 validation and mixed control result

GCC 12 builds the combined candidate successfully. Seven standalone
threaded/individual condition comparisons pass on A53 without adding
pytest to the target. Three alternating pairs per case compare against
the preceding circular-span library on CPU 3. State digests match for
all cases; counters cover the measured phase without multiplexing.

Median host-cycle reductions are 15.79% MADD, 4.87% MADS, 6.79% arithmetic
training and 3.95% address work. DMOV regresses by 6.18%, consistently in
all three pairs, while its retired host instructions decrease by 5.43%.
All five workloads retire fewer host instructions (5.43–9.59%). Thus
instruction reduction alone does not establish a universal speedup.

ARM symbol inspection shows the same 1068-byte separate DMOV opcode
body in both variants, while its threaded wrapper shrinks from 744 to
684 bytes. There is no accidental DMOV-body inlining or wrapper growth.
This does not identify the cause of the cycle regression; code placement
and instruction delivery remain possible explanations, not measurements.
Avoid speculative alignment flags without a representative reason.

Retain this candidate for the combined physical-training evaluation,
with the DMOV regression explicitly recorded. Four narrow improvements
do not yet establish an overall training gain. Raw runs, manifest and
library identity are in `dsp-threaded-condition-arm.json`. The normal
runtime library remains unchanged, and the physical attempt will select
the isolated combined library explicitly.

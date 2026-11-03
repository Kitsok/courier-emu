# A53 training-only CPU attribution

The existing 2026-11-03 physical-call capture can be analyzed without
placing another call. The mgetty failure journal provides both realtime
1793694453.527752 and monotonic 4310.459459 seconds. This clock anchor maps
the physical log's ATA at 09:26:31 to monotonic 4247.932–4248.932. The
selected interval 4255–4305 is safely after answer and before NO CARRIER;
boot, dialing and hangup are excluded. A current clock-offset check agreed
with the recorded journal anchor within 20 microseconds.

The retained perf event is `cycles:u` with no lost samples. Percentages
weight sample periods. They describe host CPU attribution, not exact
instruction frequencies or before/after speedup.

| Code | Whole attempt | Interior training window |
| --- | ---: | ---: |
| Native C5x/devices | 46.48% | 66.83% |
| Native x86 | 18.70% | 22.84% |
| Python | 31.25% | 8.52% |

Two additional training windows support that conclusion: 4250–4310 gives
66.35% C5x/devices, 23.10% x86 and 8.77% Python; 4270–4300 gives 66.74%,
22.26% and 9.36%, respectively. These are overlapping controls on the same
attempt, not independent performance trials.

The main window samples x86 `run_batch<true>` at 18.69%, Python evaluation
at 3.69%, C5x BE dispatch at 3.29%, MADD at 3.11%, ADRK dispatch at 2.34%,
and delay-slot execution at 1.96%. MADS, memory loads/stores and other
threaded DSP handlers also contribute. Resampling accounts for 1.49%.
No one sampled DSP instruction explains the entire native share.

This changes the next optimization priority: actual DSP execution is the
largest training cost, followed by native x86. Whole-attempt Python and
yield counts overstate their relative importance during training. Removing
Python alone could not close the measured real-time deficit. The previous
generic BE/BF dispatch candidate remains rejected; its isolated timings
do not justify adopting it because a dispatch symbol is sampled here.

The first narrow DSP candidate is eliminating repeated memory-region
classification in delay-line/MAC operations by using the existing validated
address-map cache, while retaining the slow path when mappings are dirty.
Arithmetic, memory side effects, diagnostics and guest cycle accounting
must remain exact. Adopt only after differential checks and fixed-work
notebook/A53 measurements. No new call, physical setting change or
temperature sampling occurred during this analysis.

Full weighted symbol rows, interval controls and clock anchor are retained
in `docs/a53-training-hotspots.json`.

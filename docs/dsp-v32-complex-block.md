# Native execution of the observed V.32 arithmetic loop

Exact-profile notebook windows at 2, 6 and 10 seconds after SIP answer
identify the fourteen single-cycle instructions b950–b95d inside a
42-iteration RPTB loop. The caller executes each site 126 times in the
bounded trace windows. Both endpoints negotiate 9600/ARQ/V32/LAPM/V42BIS
and exchange exact marker data. These traces select a code candidate;
they do not measure full-training frequencies or CPU shares. Raw windows
include nearby live program words, final state and AR/circular registers.
See `dsp-v32-training-sequences.json.gz` and its summary JSON.

The existing COURIER_C5X_TRAINING_BLOCK=1 opt-in now also admits this exact
live code in external program storage. The new path directly executes
the original arithmetic and ordered DARAM reads/writes in C++. It reuses
the existing ADD, SUB and product-scaling semantics, preserving sticky
OV, saturation, carry and temporary-register loads. Intermediate memory
aliases remain live, rather than preloading all operands before stores.

Admission requires valid maps, DARAM for every source/destination, no
codec sink destination, no tracing/rare state, no instruction repeat or
delay-slot state, and room for all fourteen modeled cycles before the
next event/run boundary. Circular updates retain buffer-1 precedence.
Only AR5 is reread after its decrement inside the body; its wrapped next
address is preflighted too. Other AR updates and final ARP/ARB are
committed exactly. Access/write/fetch counters and final PC/opcode,
previous PC, cycles and instruction retirement match ordinary execution.
The final two stores do not change conditions, so XC's final sample and
the next instruction's start sample equal the final arithmetic state.

Block repeats are admitted only if no repeat edge falls inside this
body. Consecutive complete bodies may share native execution when PASR
and PAER match the observed body. Apply a repeat edge only when another
full body can execute; leave partial-budget/event cases to ordinary
stepping. Preserve the final iteration that runs after BRAF clears.
A separate complex_block_hits query proves actual entry and resets with
the core. Other code and unsupported mappings keep the interpreter.

The notebook native build succeeds and 162 focused complex-loop, XC and
existing arithmetic-block checks pass in 1.12 seconds. Coverage includes
partial/full budgets, saturation/product modes, TRM, multiple aliases,
circular wraps and precedence, changed code, tracing, timer fallback,
repeat edges and ordinary straight-line use. The counter tool includes
a 42-body complex workload with architectural repeat-register hashing.
A53 cost and real-training hit coverage remain unmeasured at this stage.
No new physical call was made for this change.

## Admit the observed mixed-memory layout

The first hit-sampled exact-profile check ends with NO CARRIER and zero
complex-block hits. Existing arithmetic hits occur, but the complex
DARAM-only guard never admits the real workload. A subsequent bounded
operand capture at b950 records AR1=09f8, AR2=db6c, AR3=0a22, AR4=db96,
AR5=02bf and AR6=02e9, with DP=7 and CBCR=ef. This combines SARAM,
shared external storage and DARAM. These are entry snapshots, unlike the
unrelated final-state registers at the end of a batch. Raw captures are
in `dsp-v32-loop-operands.json.gz`. The diagnostic run also fails carrier;
it is not a clean speed or reliability comparison.

Extend preflight to ordinary non-register mapped cells. Resolve each
cell's backing storage and read-counter class once per body, retaining
live values across the ordered reads/writes. Register/IO/timer cells still
reject the path. Shared-RAM destinations overlapping b950–b95d reject
before any mutation, since they would change instructions still being
executed or used by later iterations. The same numeric address in a
separate global bank is safe and remains admitted. Recheck every body's
addresses so advancing pointers cannot cross into unsafe destinations.

A small counter-workload smoke check uses local FIFO acknowledgements
without perf hardware events. Enabled/disabled state digests match for
DARAM, observed mixed memory and the original arithmetic block. The two
complex kernels record 68601 admitted bodies per million modeled cycles;
the original arithmetic kernel records 62500. This checks reproducibility
and entry, not target speed. Raw smoke results are retained in
`dsp-native-block-counter-smoke.json`. The tool now supplies both complex
layouts and hashes their touched storage and repeat registers.

The rebuilt mapped-cell source passes 204 focused complex-loop, arithmetic
block and XC checks in 1.45 seconds. New cases compare mixed storage,
separate global memory and code-alias rejection against ordinary stepping,
including matching memory/fetch counters. Full initial failure and hit
samples are in `dsp-v32-loop-guard-evidence.json`. Real-workload admission
and A53 performance of the refined path remain outstanding.

## Actual training admission after refinement

The exact-profile notebook run at be07260 negotiates
9600/ARQ/V32/LAPM/V42BIS on both endpoints and exchanges both exact data
markers. A once-per-second hit sampler records 237621 caller and 237339
answerer complex bodies by the final connected sample, with no observed
complex-counter reset in either endpoint's samples. Both counters begin
at zero in this connected interval. Existing arithmetic blocks also run.
Total setup/training/data time is 29.73 seconds, but this is not a
controlled whole-training comparison and includes the hit sampler.
Raw outcome and samples are in `dsp-v32-mapped-local.json`. This verifies
real V.32 use of the refined path; A53 performance remains outstanding.

Two additional focused checks verify that an IO-mapped coefficient source
and a codec-sink destination retain instruction stepping and zero native
hits. IO event contents, PCs and instruction timestamps match the
reference. All 101 complex-loop checks pass in 0.94 seconds. These extend
boundary coverage without changing runtime code or the target build.

## First combined A53 counters

The isolated GCC build compares against the preceding condition-reuse
library, whose existing arithmetic-block opt-in is enabled. Three
alternating reference/new-disabled/new-enabled orders per case run on
CPU 3 with acknowledged user-cycle/instruction counter control. All
architectural digests match and counters run without multiplexing.

The complex DARAM kernel drops from 152699056 to 40929720 median host
cycles (73.20%); the observed mixed layout drops from 158520080 to
39976173 (74.78%). Host instructions fall by 69.85% and 71.42%.
The original arithmetic kernel drops from its already-fast 69088152 to
28468585 cycles (58.79%), with 59.17% fewer host instructions.

DMOV cycles improve 5.92%, despite 1.15% more host instructions. The
address control regresses 4.67%, with 1.37% more host instructions, in
both disabled and enabled new variants. The common threaded wrapper
currently checks both native entry PCs after every instruction. Move
these checks into the matching first-opcode wrappers before retaining
this common-path cost. This follow-up remains unmeasured; do not claim
the kernel gains as an application speedup or physical connection.
Raw runs and build manifest are in `dsp-v32-native-arm.json`.

## Restrict native admission checks to matching opcode wrappers

Move each entry check into the threaded wrapper of its first opcode:
SQRA for 879d, LACC16 for b950. Other opcode wrappers no longer inspect
native block entry PCs or flags. These checks occur after the ordinary
first-opcode fetch and before its execution. A rejected block continues
with that already-fetched opcode normally. An admitted block counts only
the remaining ten or thirteen program fetches in its first body and
commits all of its own retirement; the wrapper must not retire it again.
Subsequent native repeat bodies still account for all fourteen fetches.

This also permits admission after an ordinary block-repeat edge and at
run entry, where the prior global checks missed the first instruction.
The normal target/event/PCM/rare checks still run after a translated body
before another ordinary fetch. Unsupported operands/budgets preserve
the already-fetched opcode and instruction-level execution exactly.

The notebook build and focused differential checks pass. Counter-tool
smoke comparisons retain the same architectural digests for both complex
layouts and the original arithmetic block. Complex hits rise slightly
from 68601 to 68627 per million modeled cycles because more repeat/run
entries can be admitted. These are eligibility checks without hardware
perf events; target cost remains outstanding for this follow-up.
Raw smoke results are in `dsp-native-entry-counter-smoke.json`.

## Corrected-entry A53 and notebook validation

The corrected entry wrappers rebuild successfully in a separate A53
library. Three alternating reference/disabled/enabled orders per case
again retain matching architectural digests and positive native hits.
Against the preceding condition-reuse library, median enabled cycles
fall by 72.94% in DARAM complex work, 74.44% in observed mixed memory
and 52.50% in the original arithmetic kernel. Host instructions fall by
69.46%, 71.04% and 52.99%, respectively.

The unrelated address control is now 0.33% lower in cycles, with 0.91%
fewer instructions: the prior 4.67% regression is absent in this short
comparison. DMOV cycles are 9.26% lower, with 0.76% fewer instructions.
Do not interpret the near-zero address timing as a precise gain or
attribute all layout-sensitive cycle changes to instruction counts.
Raw runs and manifest are in `dsp-v32-entry-arm.json`.

The final notebook build's hit-instrumented run returns NO CARRIER,
whereas a subsequent run without that extra Python hook establishes
9600/ARQ/V32/LAPM/V42BIS on both ends and exchanges exact data in 32.81
seconds including setup. Keep both outcomes in `dsp-v32-entry-local.json`.
This does not prove that instrumentation alone caused the failure; the
known timing sensitivity and few runs preclude a reliability estimate.
The final physical attempt will omit that extra Python hook while still
recording media, packets and low-frequency perf samples. These narrow
kernel results do not establish a physical connection or real-time
whole-training throughput. No physical call has run for this batch yet.

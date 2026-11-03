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

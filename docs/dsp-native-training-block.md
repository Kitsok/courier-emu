# Guarded observed arithmetic block prototype

COURIER_C5X_TRAINING_BLOCK=1 enables a per-core experiment for the eleven
observed one-word instructions at 879d–87a7. It remains off by default.
The original arithmetic handlers execute in their original order, with
live operand reads and writes. This stage amortizes repeated fetch/dispatch
and front/retirement setup; it is not a general translator or a claim of
algebraic equivalence to a replacement modem algorithm.

Admission checks require the exact eleven current code words in external
program storage, valid maps, DARAM operands/destinations, no circular
configuration, no codec sink destination, no tracing/diagnostic front flags,
no active hardware repeat/block repeat or delayed-condition state, and a
run budget and event deadline extending past the block. Unusual cases
retain the interpreter. DARAM writes cannot alias this external code span;
there is no stale decoded cache. Program fetch counters account for all
eleven instructions only after admission succeeds.

All handlers charge one cycle and update the condition snapshot at their
end. With no intervening architectural observer/event admitted, repeating
step_begin's same snapshot assignment is redundant. Final PC/opcode,
previous PC, instruction count and timer tail are committed as instruction
execution would leave them. Events that fall inside or at the end of the
window reject the block instead of being delayed. Original memory helpers
retain access/write counters and live alias ordering.

A diagnostic native hit query proves tests enter the block rather than
silently falling back. Reset clears hits while retaining the opt-in core
configuration. The notebook library builds. Sixty-seven focused block,
XC and cycle checks pass in 0.40 seconds. Coverage includes product scaling,
saturation, cycle budgets across the window, actual hits, live operand
aliases, changed code, write tracing and timer-boundary fallback. This does
not establish complete interrupt coverage or target performance.

Next validate on A53 against enabled, disabled and pre-prototype libraries,
including controls for the new eligibility branch and a training trace
eligibility sample. Reject if this does not reduce useful execution work.
No new physical call or settings change was made for the prototype. The
broader executor and physical ARQ connection remain unfinished.

## Counter workload preparation

The phase-controlled counter tool now offers --case training. It sets up
the observed code and DARAM operands, stops the synthetic timer to admit
an event-free window, and loops through the exact block and an ordinary
branch. It records block hits separately from the architectural digest,
plus the measurement-source hash. The DMOV/address controls retain their
previous setup (the DMOV case name is dmov).

A notebook workload smoke check used a local acknowledgement responder,
not perf counters: disabled and enabled runs both execute one million
modeled cycles and produce digest
`e5741405abc660a90432ca16818415c4a0fd21a9276f97ca6c9da3d3d33306b4`.
Hits are zero versus 62500, proving admission throughout this synthetic
window. No hardware count or target gain is inferred from that smoke test.
A53 reference/disabled/enabled counter comparisons are queued after the
isolated target build, with state and positive-hit assertions.

## First A53 and actual-training results

The isolated GCC build completed. Three alternating orders of preserved
reference, disabled and enabled variants ran on CPU 3 with acknowledged
user-cycle/instruction counters. All final-state digests match per case.
The enabled synthetic training loop executes 62500 native blocks in one
million modeled cycles. Median host cycles fall from 116854315 to
69269557 (40.72% reduction), and instructions from 125293087 to 79653978
(36.43%). Versus the new disabled binary, enabled cycles fall by 36.98%.
These are block-kernel results, not whole-training savings.

Unrelated DMOV cycles are about 2.3% lower than preserved reference, while
address-update cycles are about 0.6% higher. Their instruction counts rise
by less than 1%. The eligibility branch therefore still has control cost;
these observations do not establish zero default overhead.

One notebook loopback run with the prototype enabled completes at both
ends with CONNECT 31200/ARQ/V34/LAPM/V42BIS and exact bidirectional markers
in 32.08 seconds including setup. A separate once-per-second sampler
records 21 connected samples per endpoint, all with zero block hits and
CBCR=239 (ef). This is functional validation through fallback, not proof
that training used the native block or got faster. The profiling tool's
instrumented=false refers only to cProfile; the hit sampler was active.

CBCR ef enables circular buffers on AR7 and AR6, not AR2, which is the
only auxiliary register incremented/decremented by this observed block.
The current guard rejects every nonzero CBCR, so it unnecessarily excludes
this observed configuration. The next stage must narrow that guard while
continuing to reject circular updates affecting AR2 and checking every
actual memory access. Other eligibility conditions may still exclude
training; positive real-work hits must be measured before adoption.

Raw target counters, build manifest and local hit samples are retained in
`dsp-native-block-first-results.json`. The deployed nanovax library remains
the original reference. No physical call or modem-setting change was made.

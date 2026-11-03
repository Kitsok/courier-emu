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

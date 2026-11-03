# Reuse conditions in address-only instructions

ADRK, SBRK and MAR only change auxiliary address state. Their handlers
call UPDATE_AR or GET_ADDRESS/UPDATE_ARP, which may change AR, ARP, ARB,
ARCR and INDX, including circular/bit-reversed updates. They do not access
guest memory/devices or change ACC, OV, C or TC. Their current condition
state therefore equals the snapshot captured before opcode dispatch.

Use a dedicated one-cycle accounting helper for these three instructions.
When no delayed-condition sample is pending, copy the existing start
snapshot to the XC sample without recomputing condition_state or storing
the same start value again. Preserve the pending-delay rule and increment
the cycle count once. Leave generic cycle accounting, retirement, timer
and interrupt/event processing unchanged. The earlier generic-retirement
review remains applicable: this is a specialization with a narrow proof,
not removal of architectural boundaries.

The notebook native build passes. Thirty focused XC, repeat-block,
instruction-audit and MAC-cycle checks pass in 0.20 seconds. Six additional
pipeline cases cover these address instructions before XC and in the last
delayed-branch slot. This establishes focused correctness, not a target
speedup or complete interrupt coverage. ARM comparison against a preserved
reference, including arithmetic and memory controls, is still required.
No new physical call or settings change was made for this stage.

## Reject after A53 control regressions

The isolated normal-GCC build completed. Twelve direct XC cases match
the preserved reference on A53 (plain/threaded, immediate predecessor/
last delay slot), with digest
`b526f837a04b60b2e0f4df8da781250e531d1f8e05df7aa4a644dc7b0952e73f`.
All timed kernel state/counter digests match too. Three alternating pairs
on CPU 3 used one million modeled cycles per case. The address-update
control improves by 3.06%, but MACD-DARAM regresses by 8.04% and MADS by
16.13%. Other kernels are mixed, including SARAM MADD improving by 7.76%.
Short controls limit precise attribution; the broad negative tradeoff
does not justify keeping this candidate on the isolated control gain.

Restore generic cycle accounting for all three opcodes and remove the
special helper. Retain the six architectural XC tests, which also pass
the reference and do not depend on the removed optimization. The variant
was never deployed; the active runtime remains unchanged. Raw manifest,
XC comparisons and timings are in `dsp-address-cycle-arm-results.json`.
No new physical call or modem-setting change was made.

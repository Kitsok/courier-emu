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

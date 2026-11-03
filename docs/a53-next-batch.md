# DSP, x86 and Python overhead batch

## Delayed arithmetic return

Extend the opt-in arithmetic block at DSP 879d through the observed
RETCD at 87a8 and its SACH *+ / SACL *-,AR1 delay slots. Admit the
extension only when all 15 cycles fit before both the run limit and next
event, the exact tail words match and neither destination is a codec
sink. Existing DARAM and AR2 circular guards cover both result stores.
A rejected extension still uses the 11-cycle arithmetic prefix.

The extension preserves ordered stores, AR2, ARP/ARB, stack popping,
condition samples, opcode fetch counts and delayed-slot retirement
accounting. It records all three added bodies in diagnostic work counts;
only RETCD adds a retired outer instruction. No extra per-core storage
or normal-interpreter entry checks are introduced.

417 focused arithmetic, XC, MADD and filter checks pass in 2.44 seconds.
New differential cases cover budgets around the return, all PM modes and
operand aliases, including hardware stack comparison. An initial test
invocation began before the isolated library was published and failed to
load it; the completed-library runs pass. A53 performance and final call
validation remain pending until the batch is finished.

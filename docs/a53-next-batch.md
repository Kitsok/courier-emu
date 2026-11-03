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

## Consecutive x86 immediate fetches

The native x86 fetch helper advances IP once for consecutive two- and
four-byte immediates, rather than redoing segment/address arithmetic and
IP updates for each byte. Segment-offset and physical-address wrap retain
the existing bytewise path; single-byte fetches remain direct. This does
not remove memory guards, rollback checkpoints or instruction boundaries.

40 focused native x86 checks pass in 2.16 seconds, including new immediate
cases at segment and bus wrap boundaries, both CPU profiles, watched
stores, I/O callbacks and interrupt edges. At IP fffe the Python inline
16-bit MOV reads its second immediate byte linearly; the old and new
native helpers instead preserve architectural IP wrap. That case checks
explicit expected register values rather than adopting the reference bug.

A short notebook counter smoke run matches all seven final state hashes.
Timing varies in both directions and is not evidence of an A53 gain. This
candidate requires the final target comparison before retention; raw
notebook smoke results are in `x86-fetch-notebook-smoke.json`.

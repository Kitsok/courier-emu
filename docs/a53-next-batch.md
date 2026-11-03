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

## Python native-batch argument assembly

Pass the fixed native x86 argument layout directly instead of repeatedly
concatenating, padding and expanding optional argument tuples. Native host
I/O, polling, buffered MMIO, legacy/live timer buffers and write traces
retain their existing positions. Keep callback and timer preparation /
completion order unchanged, including publishing state before observers.
The change removes Python allocations at each batch boundary without
increasing instruction budgets or postponing device callbacks.

The combined wrapper/native path passes 40 focused x86 checks and 52
focused timer, write-trace, worker-deadline and pacer checks (1.82 seconds
for the latter). The first wider invocation included firmware-scale cases
and hit restricted socket fixtures: 52 passed, two failed and three errored
at socket creation. The focused rerun permits local socket fixtures and
excludes the five firmware-scale cases. No physical call was made for an
individual stage. Target measurements and the final batch call follow.


### Reject the fetch candidate after A53 comparison

Three alternating CPU-3 repetitions of one million instructions per
workload show no useful target gain. The candidate costs 2.36% more CPU
in mixed memory, 4.17% more in traced memory and 3.37% more in the memory
control; register and 386 controls are essentially unchanged. All state
hashes match. Restore the preceding native implementation and retain the
wrap checks. Raw results are in `x86-fetch-arm-rejected.json`. Do not
attribute any later call behavior to this rejected candidate.

### Narrow RAM-read experiment

A second isolated candidate placed timer-window checks before the timer
model loads and kept the complex timer reader out of line. It passes 47
focused x86/timer/trace checks. Target controls again do not support
retention: mixed memory improves 3.61%, traced memory 0.73%, but register
and 386 controls regress substantially. Revert the experiment before the
final call. `x86-ram-arm-rejected.json` retains its small counter run.
Neither attempted native x86 change is a retained performance gain.

### Correct the return workload before judging its timing

The first return workload leaves ARP=1 on return, then executes MAR in
direct mode (a NOP). It subsequently reads a register operand and bypasses
the native block: both variants have zero measured native hits. Replace
that header with MAR *,AR0 and require positive measured hits. Keep the
invalid run in `dsp-return-fixture-invalid.json`; its return timings are
not evidence of native-return performance. Its non-return control also
shows unnecessary tail-guard overhead. Test the tail opcode first so the
usual non-return case avoids budget/deadline checks for that extension.

# Observed DMOV successor dispatch experiment

The loopback training windows contain the pair 7790,7780 at PC 8ab7,
190 times across both endpoints. COURIER_C5X_DMOV_PAIR=1 selects an
experimental successor shortcut once per core; it is disabled by default.
After executing 7790 through the ordinary DMOV handler, the threaded
wrapper still performs repeat-edge handling, retirement, event servicing,
run-budget checks, PCM-yield checks and rare-state checks. It then begins
the next instruction normally, fetching its live opcode and sampling
conditions. Only if that opcode is 7780 does it enter the known DMOV
wrapper directly instead of using the generic dispatch table.

This is a direct successor-dispatch prototype, not a native-code
translator or a multi-instruction atomic operation. No memory access,
architectural event boundary, access counter or code-identity check is
removed. There is no decoded-code cache to invalidate. Unsupported
successors retain generic dispatch. Reset retains the per-core experimental
configuration, independently of architectural state.

The notebook build succeeds and 41 focused checks pass in 0.24 seconds.
Ten enabled/disabled comparisons cover cycle budgets 1, 2, 3, 6 and 12,
including replacement of the second opcode between execution slices.
Snapshots include CPU/serial state, map counters, data and write counts.
Existing delay-line, MAC-cycle and condition-sampling checks also pass.
These checks do not establish target speed or complete interrupt coverage.

Next compare enabled, disabled and pre-prototype libraries on A53. The
additional per-DMOV eligibility work can cost time even while disabled;
include unrelated instruction and single-DMOV controls. Inspect target
code generation to verify the direct successor path is distinct. Reject
or revise the prototype if it offers no useful tradeoff. No physical call
or whole-training gain is claimed from this stage. The larger execution
backend and physical ARQ connection remain unfinished.

## Reject after A53 comparison

Nanovax rebuilt the prototype and compared three alternating orders of
reference, disabled and enabled libraries, on CPU 3. Each case used
500000 modeled cycles after 100000 warmup cycles. All CPU/serial/map/data/
write-count digests match. Median CPU seconds:

| Kernel | Reference | Disabled | Enabled |
| --- | ---: | ---: | ---: |
| Observed pair | 0.066002 | 0.070953 | 0.067953 |
| Single DMOV control | 0.062123 | 0.068567 | 0.063315 |
| Register control | 0.090231 | 0.101879 | 0.089977 |

The enabled pair is about 2.96% slower than reference; disabled is about
7.50% slower. Controls also vary substantially, including the unrelated
register case, so these short timings do not precisely isolate causes.
They establish no useful target improvement and do not justify keeping
extra dispatch eligibility work. Remove the runtime prototype, environment
flag and tests specific to the removed path. Preserve the recorded training
sequences and target results for future executor work.

ARM code generation produces a 204-instruction DMOV wrapper with a
separate call to the opcode body and a generic indirect dispatch tail.
The experiment did not integrate instruction bodies or amortize their
architectural setup. Merely selecting a known successor is insufficient
evidence for a faster block executor. Raw disassembly remains on nanovax
at `/tmp/courier-dmov-pair-disassembly.txt`; raw measurements are in
`dsp-dmov-pair-arm-results.json`. No physical call was made.

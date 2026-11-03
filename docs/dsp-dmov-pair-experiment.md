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

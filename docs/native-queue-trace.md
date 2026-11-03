# Buffer diagnostic RAM writes inside native x86 execution

Training-only exit counters identified a useful boundary after the Python
function profile: watched writes accounted for 39.3% of caller and 47.0% of
answerer native batch exits. These counts exclude boot. The hottest sites
include `incw 0x02ea`, `decw 0x02ec` and `movb 0x08,0x02ca`, inside the broad
DSP diagnostic watch range. These are diagnostic observations of ordinary
RAM stores; the hook changes no device state. Initial exit evidence is in
`docs/local-training-exits.json`.

## Implementation and boundaries

The standard native worker now opts this hook into a native record buffer.
The CPU still executes and commits each guest store in order. Capturing a
diagnostic record no longer ends the native batch. Python folds the records
when the batch returns, before executing the next Python boundary action.

Each 32-byte record retains address, value, callback-time PC, width, CS and
stack words at SP+4/+6/+8. Capturing stack data before the store preserves
the existing caller/producer attribution even if later instructions change
the stack. Earlier staged stores in the same instruction are visible to
the stack capture. A guard failure discards that instruction's records
before the synchronous fallback executes it. A full 128 KiB buffer also
returns control safely. Additional overlapping observers keep the original
synchronous hook behavior. Device-changing and arbitrary memory watches
remain synchronous.

`COURIER_NATIVE_QUEUE_TRACE=0` selects the reference hook. The x86 native
extension must be rebuilt when deploying this change. Separate compiler
specializations keep trace work out of ordinary execution; record capture
is reached only through the existing watched-write branch. No per-
instruction trace-capacity check is needed.

An initial implementation added about 12.6% CPU time to an ordinary tight
x86 loop. It was revised before acceptance. The final comparison against
the original library matches registers and memory and shows no slowdown
in that notebook loop (0.08835 s original, 0.08679 s candidate medians).
These small differences are not a general interpreter speedup claim.

## Fixed-work measurements, 2026-11-03

`tools/benchmark_write_trace.py` executes word increments/decrements in the
diagnostic range, folding the same counters and retaining the same bounded
history. Four pairs reverse synchronous/buffered order on alternate pairs.
The build, initial guard construction and final state hashing are outside
the timed window. Times are process CPU medians. The A53 run is pinned to
CPU 3 and uses an isolated package under `/tmp`; the working checkout on
nanovax is unchanged.

| Host | Guest instructions | Synchronous | Buffered | CPU reduction |
| --- | ---: | ---: | ---: | ---: |
| Notebook | 300,000 | 2.6999 s | 0.4439 s | 83.6% |
| A53 | 150,000 | 10.7372 s | 2.2214 s | 79.3% |

Every repetition matches final memory, registers, diagnostic counters and
retained history. This measures the diagnostic-write path, not the entire
emulator. The `--unwatched` control writes outside the diagnostic range:
with buffering enabled it differs by +1.9% CPU on the notebook and +0.13%
on A53 over six pairs of 20 million guest instructions. The A53 difference
is smaller than the observed repetition spread.

## Correctness and local training

The final focused CPU/worker suite passes 38 tests. It covers changing
stack contents, callback PCs and values, overflow, partial-instruction
rollback, overlapping hooks, randomized instruction equivalence,
interrupt behavior and real firmware boot with speaker monitoring on/off.
The boot comparisons also require exact diagnostic counters and retained
records. An earlier broader regression run passed 78 tests with two
optional-image skips; the final focused run follows the compiler changes.

After implementation, the same local training driver ran the reference
and candidate sequentially without concurrent regression work. All four
endpoints reported `CONNECT 31200/ARQ/V34/LAPM/V42BIS` and transferred exact
bidirectional data.

| Training observation | Caller reference / candidate | Answerer reference / candidate |
| --- | ---: | ---: |
| Native batch exits for watched writes | 8,134 / 1,078 | 10,288 / 1,210 |
| Native batches | 20,530 / 13,820 | 21,851 / 12,928 |
| Process CPU | 15.958 / 15.245 s | 15.193 / 14.465 s |
| Guest x86 instructions | 68.479 / 67.292 million | 68.625 / 67.611 million |

Combined training CPU falls by about 4.6% in this pair. The guest work
differs, and training depends on both peers and wall-clock RTP, so this
single pair does not establish a fixed-work whole-call speedup. An earlier
candidate capture overlapped regression work and retired much more guest
work; it is excluded from the timing comparison. The physical connection
goal on A53 remains unverified. No physical modem settings were changed,
no physical call was placed and no temperatures were sampled.

Raw repetitions, ordinary-execution controls, source hashes and final
training windows are retained in `docs/native-queue-trace-results.json`.
The next measured targets remain native service yields/rearming and the
DSP instruction workload; this change removes most diagnostic write exits
but does not resolve the A53 real-time deficit by itself.

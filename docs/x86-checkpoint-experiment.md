# Rejected x86 checkpoint-elision experiment

Training-only perf attributes 22.84% of user cycles to native x86, including
18.69% in `run_batch<true>`. An ARM annotation of the whole captured attempt
shows sampled loads/stores for the interpreter's register rollback copy.
This suggested checking whether known non-faulting instructions could omit
that copy.

The candidate skipped checkpoints only for a whitelist of unprefixed 80186
register operations, immediate register moves and simple branches/flag
operations that cannot yield. Every potentially faulting/prefixed operation
and all 386 execution retained full checkpoints. The runtime candidate is
removed; only the measurements, candidate patch and regression checks are
retained.

`tools/benchmark_x86_checkpoints.py` loads both prebuilt libraries and runs
five million guest instructions after 10000 warmup. Six paired repetitions
reverse order on alternate pairs. Final registers and complete memory must
match, as must buffered write traces where enabled. Build/setup and final
state hashing are outside the timer; trace hashing is identical timed
work in both backends. The A53 run uses CPU 3 and an isolated directory
`/tmp/courier-x86-checkpoints-a53`.

| Workload | Notebook CPU reduction | A53 CPU reduction |
| --- | ---: | ---: |
| Register/branch loop | 9.5% | 1.4% |
| Counter loop | 10.7% | 0.6% |
| Mixed memory | 0.7% | -8.4% |
| Buffered diagnostic stores | -0.6% | -6.6% |
| Memory control | -6.2% | -6.8% |
| Prefixed control | 5.5% | 0.9% |
| 386 control | -2.8% | -6.2% |

Correctness passes 36 existing native differential/trace cases and seven
new rollback checks. The new checks guard progress made before a watched
read/store/PUSHA, plus prefixed and extended-register fallback. All measured
memory/register/trace hashes match. Correctness does not justify adopting
a candidate with these A53 regressions. Register-only notebook gains are
not representative of its target-host tradeoff.

The production x86 implementation is restored. The independently validated
DSP cached-region improvement remains. No new physical call was made and
no physical settings or temperatures were touched. Exact repetitions and
the rejected source diff are in `docs/x86-checkpoint-experiment.json`.
Further x86 work needs representative training opcode/access attribution
or a design that improves the memory-heavy path as well; this experiment
is not a basis for claiming an overall training improvement.

# Performance comparison

Baseline: ../baseline-20261115/. All-five medians are compared here; cold first and later sample statistics are separately preserved in comparison.json. Each workload uses 30M instructions; steady excludes a 30M warm-up and measures 29,990,912 instructions. These are observed differences across different times on the same host, not controlled causal speedup estimates.

| Workload | Baseline CPU s | Candidate CPU s | Difference | Baseline wall s | Candidate wall s |
| --- | ---: | ---: | ---: | ---: | ---: |
| idle | 4.168 | 3.907 | -6.3% | 4.174 | 3.900 |
| dial | 5.934 | 5.379 | -9.4% | 5.928 | 5.377 |
| steady | 5.781 | 5.579 | -3.5% | 8.821 | 8.822 |

All repeated candidate memory hashes, CPU registers, DSP state, DSP serial state, terminal output, timers and interrupt states match the original baseline for the corresponding workload. All runs reached instruction-limit. Native batching counters may change.

Compilation and construction are outside timed execution. Tests and benchmarks ran without overlapping each other. No host configuration was changed. Results apply to local idle/dialing/loopback-SIP workloads, not connected modem throughput or A53 performance. Thermal/load drift and the broad original baseline spread prevent claims about small speed changes. Hardware perf counters remain unavailable.

## Change and validation

Eligible Timer 2 count writes at 0xff40 now update the shared native timer model only after the entire x86 instruction passes its guards. The native worker preserves the timer-applied marker when processing EOI records, and Python replays diagnostics without writing again. The path requires the standard native board, captured diagnostics already full, no memory watch and a shared timer model. COURIER_NATIVE_TIMER_WRITES=0 retains the previous boundary for comparison. Other MMIO and board timebase callbacks retain their existing handling.

Build: PYTHON=.venv/bin/python ./build.sh — passed (build.txt).
Tests: .venv/bin/python -m pytest -q tests/test_native_timer_writes.py tests/test_native_timer_model.py tests/test_native_timer_reads.py tests/test_native_interpreter.py tests/test_interpreter_clock.py tests/test_native_machine.py tests/test_native_worker_media_boot.py tests/test_worker_arm.py tests/test_worker_deadlines.py — 106 passed, 2 skipped (tests.txt). Optional Ie030002.nac and main211.xmf firmware tests were skipped.

New regressions cover byte merging, read/modify/write, reads immediately following writes, guarded MOVSW fallback and mixed EOI/timer replay markers. The final 22 accepted benchmark runs (15 timing, 1 profile, 6 alternating controls) match every recorded original guest-state field, including timer diagnostics. Exact commands and flags are in commands.json. The rejected diagnostic candidate and failing-before-fix regression are retained under diagnostic-duplicate-replay/; none of those timings enter this comparison.

## Native boundary counts

- idle: 89,361 → 82,277 batches (-7.9%), 7,084 native timer writes.
- dial: 97,888 → 90,034 batches (-8.0%), 7,505 native timer writes.

## Alternating comparison of step 4 alone

Six fresh-process dialing runs alternate disabled/enabled in the order 0,1,1,0,0,1. They use the same built binary, 30M guest instructions and cold process caches. All guest state matches the original.

- Disabled: median CPU 5.723s; wall 5.719s; batches [97888, 97888, 97888].
- Enabled: median CPU 5.607s; wall 5.603s; batches [90034, 90034, 90034].

Observed step-4-only CPU difference: -2.0%. Three samples per variant and host drift limit precision; this is not evidence for connected modem throughput.

## Sequential results against the original baseline

All rows compare five-run CPU medians with the original baseline. They are observations made at different times, not independent causal effects. See each step directory for raw samples, cold/warm separation, incremental differences and test/build logs.

| Step / commit | Idle | Dial | Paced idle | Tests |
| --- | ---: | ---: | ---: | --- |
| 1: snapshot arming / c8f170d | -1.3% | -5.8% | -1.3% | 55 passed |
| 2: DSP clock / 0496458 | -4.0% | -6.2% | -0.6% | 20 passed |
| 3: timer programming / bbd6c17 | -3.8% | +2.3% | +2.3% | 52 passed |
| 4: native timer writes / this commit | -6.3% | -9.4% | -3.5% | 106 passed, 2 skipped |

## Incremental comparison with step 3

- idle: 4.010 → 3.907 CPU seconds (-2.6%).
- dial: 6.072 → 5.379 CPU seconds (-11.4%).
- steady: 5.911 → 5.579 CPU seconds (-5.6%).

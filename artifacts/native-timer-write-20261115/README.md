# Performance comparison

Baseline: ../baseline-20261115/. All-five medians are compared here; cold first and later sample statistics are separately preserved in comparison.json. Each workload uses 30M instructions; steady excludes a 30M warm-up and measures 29,990,912 instructions. These are observed differences across different times on the same host, not controlled causal speedup estimates.

| Workload | Baseline CPU s | Candidate CPU s | Difference | Baseline wall s | Candidate wall s |
| --- | ---: | ---: | ---: | ---: | ---: |
| idle | 4.168 | 4.010 | -3.8% | 4.174 | 4.006 |
| dial | 5.934 | 6.072 | +2.3% | 5.928 | 6.109 |
| steady | 5.781 | 5.911 | +2.3% | 8.821 | 8.822 |

All repeated candidate memory hashes, CPU registers, DSP state, DSP serial state, terminal output, timers and interrupt states match the original baseline for the corresponding workload. All runs reached instruction-limit. Native batching counters may change.

Compilation and construction are outside timed execution. Tests and benchmarks ran without overlapping each other. No host configuration was changed. Results apply to local idle/dialing/loopback-SIP workloads, not connected modem throughput or A53 performance. Thermal/load drift and the broad original baseline spread prevent claims about small speed changes. Hardware perf counters remain unavailable.

## Change and checks

Timer register and legacy interrupt-controller writes now operate on the shared C++ Timers186 buffer. Native logic preserves low-byte merging, ENABLE/INHIBIT gating, MAX COUNT behavior, controller masks, register-access clock advancement and diagnostics. Python retains the T0 compare-A board-selection callback before publishing its final origin. This step preserves the existing Python MMIO boundary.

Build: PYTHON=.venv/bin/python ./build.sh — passed (build.txt).
Tests: .venv/bin/python -m pytest -q tests/test_native_timer_model.py tests/test_native_timer_reads.py tests/test_worker_deadlines.py tests/test_native_worker_media_boot.py — 52 passed (tests.txt), including randomized timer/controller scripts, read rollback, board selection and full boot comparisons.

Commands: .venv/bin/python tools/benchmark_standalone.py --repeat 5; then --dial --repeat 5; then --warmup-instructions 30000000 --repeat 5.

## Incremental comparison with step 2

- idle: 4.002 → 4.010 CPU seconds (+0.2%).
- dial: 5.564 → 6.072 CPU seconds (+9.1%).
- steady: 5.746 → 5.911 CPU seconds (+2.9%).

## Isolated write cost

Six alternating pairs in one process compare TimerBlock.write(native_block, 0xff40, 2, value, instructions) with native_block.write on fresh NativeTimerBlock instances. Each sample performs 50,000 writes, with value=i&65535 and instructions=i. Median process CPU time: Python 0.103802s; native 0.075356s (27.4% less). Raw samples are in write-microbenchmark.json. This measures only the write primitive and does not establish an end-to-end speedup.

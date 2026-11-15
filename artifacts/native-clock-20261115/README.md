# Performance comparison

Baseline: ../baseline-20261115/. All-five medians are compared here; cold first and later sample statistics are separately preserved in comparison.json. Each workload uses 30M instructions; steady excludes a 30M warm-up and measures 29,990,912 instructions. These are observed differences across different times on the same host, not controlled causal speedup estimates.

| Workload | Baseline CPU s | Candidate CPU s | Difference | Baseline wall s | Candidate wall s |
| --- | ---: | ---: | ---: | ---: | ---: |
| idle | 4.168 | 4.002 | -4.0% | 4.174 | 4.000 |
| dial | 5.934 | 5.564 | -6.2% | 5.928 | 5.558 |
| steady | 5.781 | 5.746 | -0.6% | 8.821 | 8.822 |

All repeated candidate memory hashes, CPU registers, DSP state, DSP serial state, terminal output, timers and interrupt states match the original baseline for the corresponding workload. All runs reached instruction-limit. Native batching counters may change.

Compilation and construction are outside timed execution. Tests and benchmarks ran without overlapping each other. No host configuration was changed. Results apply to local idle/dialing/loopback-SIP workloads, not connected modem throughput or A53 performance. Thermal/load drift and the broad original baseline spread prevent claims about small speed changes. Hardware perf counters remain unavailable.

## Change and checks

DSP instruction accumulation, batch threshold and cycle-debt earning now operate directly on the persistent C++ board state. Python retains a reference helper. Multiplication is rounded before addition to preserve Python arithmetic on targets with fused operations. Exchange, codec, call-control and DSP service ordering is unchanged.

Build: PYTHON=.venv/bin/python ./build.sh — passed (build.txt).
Tests: .venv/bin/python -m pytest -q tests/test_native_board_media.py tests/test_native_worker_media.py tests/test_native_worker_media_boot.py tests/test_worker_arm.py — 20 passed (tests.txt), including 2,005 randomized/boundary DSP clock steps with exact fractional debt comparisons.

Commands: tools/benchmark_standalone.py --repeat 5, then --dial --repeat 5, then --warmup-instructions 30000000 --repeat 5, all with .venv/bin/python.

## Incremental comparison with step 1

- idle: 4.112 → 4.002 CPU seconds (-2.7%).
- dial: 5.588 → 5.564 CPU seconds (-0.4%).
- steady: 5.705 → 5.746 CPU seconds (+0.7%).

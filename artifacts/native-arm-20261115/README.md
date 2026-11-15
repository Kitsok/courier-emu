# Performance comparison

Baseline: ../baseline-20261115/. All-five medians are compared here; cold first and later sample statistics are separately preserved in comparison.json. Each workload uses 30M instructions; steady excludes a 30M warm-up and measures 29,990,912 instructions. These are observed differences across different times on the same host, not controlled causal speedup estimates.

| Workload | Baseline CPU s | Candidate CPU s | Difference | Baseline wall s | Candidate wall s |
| --- | ---: | ---: | ---: | ---: | ---: |
| idle | 4.168 | 4.112 | -1.3% | 4.174 | 4.107 |
| dial | 5.934 | 5.588 | -5.8% | 5.928 | 5.583 |
| steady | 5.781 | 5.705 | -1.3% | 8.821 | 8.822 |

All repeated candidate memory hashes, CPU registers, DSP state, DSP serial state, terminal output, timers and interrupt states match the original baseline for the corresponding workload. All runs reached instruction-limit. Native batching counters may change.

Compilation and construction are outside timed execution. Tests and benchmarks ran without overlapping each other. No host configuration was changed. Results apply to local idle/dialing/loopback-SIP workloads, not connected modem throughput or A53 performance. Thermal/load drift and the broad original baseline spread prevent claims about small speed changes. Hardware perf counters remain unavailable.

## Change and checks

Move per-batch snapshot publication to courier_worker_arm: reset batch counters and sample the DSP program counter in C++; initialize fixed worker configuration only once. Preserve the paired frame snapshot and live clocks. Dynamic eligibility and deadline checks remain unchanged.

Build: PYTHON=.venv/bin/python ./build.sh (passed; build.txt).
Tests: .venv/bin/python -m pytest -q tests/test_worker_arm.py tests/test_worker_deadlines.py tests/test_native_worker_media.py tests/test_native_worker_media_boot.py tests/test_worker_pacer_service.py tests/test_worker_yield_profile.py — 55 passed (tests.txt).

Benchmark commands:

```sh
.venv/bin/python tools/benchmark_standalone.py --dial --repeat 5
.venv/bin/python tools/benchmark_standalone.py --repeat 5
.venv/bin/python tools/benchmark_standalone.py --warmup-instructions 30000000 --repeat 5
COURIER_X86_PROFILE=1 .venv/bin/python tools/benchmark_standalone.py --warmup-instructions 30000000 --repeat 1 --profile-out artifacts/native-arm-20261115/courier.prof
```

Observed CPU median differences: idle -1.3%, dialing -5.8%, paced window -1.3%. The paced wall median is unchanged. Timing variation prevents attributing these changes entirely to this implementation.

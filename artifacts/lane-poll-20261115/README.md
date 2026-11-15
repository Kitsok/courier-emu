# Courier performance comparison

22 accepted benchmark runs match all recorded original guest-state fields. Five repetitions each idle/dial/paced; one separate profile; six fresh-process alternating controls. Native compilation and construction are excluded. Steady timings use the window after 30M warm-up instructions. First/cold and later samples remain in raw JSON.

| Workload | Original CPU | Previous-round CPU | Previous-step CPU | Candidate CPU | Vs original | Vs previous step |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| idle | 4.168 | 3.907 | 3.915 | 3.852 | -7.6% | -1.6% |
| dial | 5.934 | 5.379 | 5.348 | 5.206 | -12.3% | -2.7% |
| steady | 5.781 | 5.579 | 5.578 | 5.567 | -3.7% | -0.2% |

Alternating COURIER_NATIVE_LANE_PENDING: disabled median 5.598s; enabled 5.494s (-1.9%). Order 0,1,1,0,0,1, same binary and fresh processes.

Timings are observations on this host, with thermal/load drift and limited samples. Small differences do not establish causal improvements. These are loopback idle/dial workloads, not connected modem data or A53 measurements. Profiles include overlapping native work and pacing waits. Exact commands/flags and raw measurements are retained.

## Implementation and checks

A single native query reports boot and overlay events/errors. Refreshing skips empty Python drain callbacks and retains boot-before-overlay replay order. Pending loader errors are included even without additional work. COURIER_NATIVE_LANE_PENDING=0 retains separate polling. Lane eligibility checks and panel/DTR invalidation remain live.

Build: PYTHON=.venv/bin/python ./build.sh — passed (build.txt).
Tests: .venv/bin/python -m pytest -q tests/test_native_port_models.py tests/test_native_worker_media_boot.py tests/test_serialsim_panel_cache.py tests/test_native_board_media.py tests/test_worker_arm.py tests/test_native_timer_writes.py — 34 passed (tests.txt). New coverage exercises simultaneous boot/overlay work, missing-ACK errors and clearing each pending channel.

All 22 accepted benchmark runs match original baseline state. Alternating paced controls show an observed -1.9% CPU difference; this small difference remains subject to host variation. No connected-call performance is inferred from these idle/dial measurements.

## Round commits

- 117f04b: persistent worker configuration (52 tests).
- 53ca883: native Timer 2 compare/control programming (64 tests).
- 0fcc638: native exchange/codec clocks (21 tests).
- This commit: combined native lane pending queries (34 tests).

All four changes passed native build checks and repeated baseline state comparisons. Adjacent directories preserve per-step timing differences and alternating controls, including noisy or slower samples.

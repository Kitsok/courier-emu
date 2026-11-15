# Courier performance comparison

22 accepted benchmark runs match all recorded original guest-state fields. Five repetitions each idle/dial/paced; one separate profile; six fresh-process alternating dialing controls. Native compilation and construction are excluded. Steady timings use the window after 30M warm-up instructions. First/cold and later samples remain in raw JSON.

| Workload | Original CPU | Previous-round CPU | Previous-step CPU | Candidate CPU | Vs original | Vs previous step |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| idle | 4.168 | 3.907 | 3.748 | 4.638 | +11.3% | +23.8% |
| dial | 5.934 | 5.379 | 5.368 | 5.481 | -7.6% | +2.1% |
| steady | 5.781 | 5.579 | 5.505 | 5.659 | -2.1% | +2.8% |

Alternating COURIER_NATIVE_TIMER2_PROGRAMMING: disabled median 5.400s; enabled 5.334s (-1.2%). Order 0,1,1,0,0,1, same binary and fresh processes.

Timings are observations on this host, with thermal/load drift and limited samples. Small differences do not establish causal improvements. These are loopback idle/dial workloads, not connected modem data or A53 measurements. Profiles include overlapping native work and pacing waits. Exact commands/flags and raw measurements are retained.

## Implementation and checks

Native Timer 2 programming now covers count, compare A and control writes. Writes commit only after instruction guards succeed, and diagnostics decode the actual register address. Control reads and calibrated-delay grants remain in Python. COURIER_NATIVE_TIMER2_PROGRAMMING=0 retains count-only batching for an isolated comparison.

Build: PYTHON=.venv/bin/python ./build.sh — passed (build.txt).
Tests: .venv/bin/python -m pytest -q tests/test_native_timer_writes.py tests/test_native_timer_model.py tests/test_native_timer_reads.py tests/test_native_interpreter.py tests/test_native_worker_media_boot.py — 64 passed (tests.txt). Added count/compare/control byte/RMW/fallback coverage.

## Additional paced-window controls

Because the newly migrated registers are frequent after startup, six additional fresh-process alternating controls measure the post-warm-up window. All six match every recorded baseline state field. Raw samples and commands are in window-controls.json and window-control-*.json. There are 28 accepted firmware runs in total.

Disabled CPU median 5.541s; enabled 5.482s (-1.1%). Median native batches 14142 → 12544 (-11.3%). Window wall time remains paced at approximately 8.82s.

The earlier boot-heavy idle timing is slower than both saved baselines and has broad spread; it is retained without attributing the difference to this small register migration. Alternating window controls establish fewer Python/native boundaries, with only a small observed CPU difference.

# Courier performance comparison

22 accepted benchmark runs match all recorded original guest-state fields. Five repetitions each idle/dial/paced; one separate profile; six fresh-process alternating dialing controls. Native compilation and construction are excluded. Steady timings use the window after 30M warm-up instructions. First/cold and later samples remain in raw JSON.

| Workload | Original CPU | Previous-round CPU | Previous-step CPU | Candidate CPU | Vs original | Vs previous step |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| idle | 4.168 | 3.907 | 3.907 | 3.748 | -10.1% | -4.1% |
| dial | 5.934 | 5.379 | 5.379 | 5.368 | -9.5% | -0.2% |
| steady | 5.781 | 5.579 | 5.579 | 5.505 | -4.8% | -1.3% |

Alternating COURIER_WORKER_CONFIG: disabled median 5.293s; enabled 5.458s (+3.1%). Order 0,1,1,0,0,1, same binary and fresh processes.

Timings are observations on this host, with thermal/load drift and limited samples. Small differences do not establish causal improvements. These are loopback idle/dial workloads, not connected modem data or A53 measurements. Profiles include overlapping native work and pacing waits. Exact commands/flags and raw measurements are retained.

## Implementation and checks

The shared native media worker retains configuration between batches, comparing all relevant inputs before reuse. Deadline and last-service fields still update per batch. Changing modes or taking the legacy snapshot path invalidates the cache. Dynamic eligibility checks remain unchanged. COURIER_WORKER_CONFIG=0 selects full publication for comparison. The first idle run publishes persistent configuration six times over 82,277 native batches.

Build: PYTHON=.venv/bin/python ./build.sh — passed (build.txt).
Tests: .venv/bin/python -m pytest -q tests/test_worker_arm.py tests/test_worker_deadlines.py tests/test_native_worker_media_boot.py tests/test_native_timer_writes.py tests/test_worker_pacer_service.py — 52 passed (tests.txt). The added transition test compares the full snapshot bytes while cadence, masks, device presence and scheduling modes change.

CPU changes versus the previous round are -4.1% idle, -0.2% dialing and -1.3% paced idle. Alternating controls measured +3.1% CPU time with caching enabled, with substantial sample variation; no end-to-end speedup is established. The structural result is fewer configuration publications while preserving guest state and batching.

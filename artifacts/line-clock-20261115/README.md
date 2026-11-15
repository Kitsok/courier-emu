# Courier performance comparison

22 accepted benchmark runs match all recorded original guest-state fields. Five repetitions each idle/dial/paced; one separate profile; six fresh-process alternating controls. Native compilation and construction are excluded. Steady timings use the window after 30M warm-up instructions. First/cold and later samples remain in raw JSON.

| Workload | Original CPU | Previous-round CPU | Previous-step CPU | Candidate CPU | Vs original | Vs previous step |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| idle | 4.168 | 3.907 | 4.638 | 3.915 | -6.1% | -15.6% |
| dial | 5.934 | 5.379 | 5.481 | 5.348 | -9.9% | -2.4% |
| steady | 5.781 | 5.579 | 5.659 | 5.578 | -3.5% | -1.4% |

Alternating COURIER_NATIVE_LINE_CLOCK: disabled median 6.286s; enabled 6.041s (-3.9%). Order 0,1,1,0,0,1, same binary and fresh processes.

Timings are observations on this host, with thermal/load drift and limited samples. Small differences do not establish causal improvements. These are loopback idle/dial workloads, not connected modem data or A53 measurements. Profiles include overlapping native work and pacing waits. Exact commands/flags and raw measurements are retained.

## Implementation and checks

The persistent C++ board owner advances exchange and codec clock phases and services due work in exchange-before-codec order. Signalling and monitor events return to Python, then resume the same clock operation without earning time twice. Custom codec masters and COURIER_NATIVE_LINE_CLOCK=0 retain Python scheduling.

Build: PYTHON=.venv/bin/python ./build.sh — passed (build.txt).
Tests: .venv/bin/python -m pytest -q tests/test_native_board_media.py tests/test_native_codec_bringup.py tests/test_native_worker_media.py tests/test_native_worker_media_boot.py — 21 passed (tests.txt). New tests cover multiple service boundaries, exact codec/device/phase comparisons and a live UDP event before codec clock advancement.

Alternating controls use the post-startup window, not boot-inclusive CPU totals. Their observed CPU median difference is -3.9%, but sample spread is large; this does not establish a stable causal speedup. All 22 accepted runs match recorded baseline state.

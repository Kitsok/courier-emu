# Native service yield attribution

The updated diagnostic-buffering runtime was profiled during local loopback
Courier training on 2026-11-03. Both peers established
`CONNECT 31200/ARQ/V34/LAPM/V42BIS` and transferred exact data. Native yield
counters are opt-in through `COURIER_WORKER_YIELDS=1`; Python rearm counts
are also collected only when enabled. The training driver retains counter
snapshots at SIP answer and after both firmware CONNECT results, excluding
boot. Source and Python mirror changes require rebuilding the DSP library.

| Yield / rearm | Caller | Answerer |
| --- | ---: | ---: |
| Media-clock pacing wait | 6,335 | 5,724 |
| Unarmed snapshot | 1,648 | 1,717 |
| Snapshot deadline | 412 | 411 |
| DSP transition | 341 | 237 |
| Media edge | 0 | 1 |
| Rearm attempts | 8,777 | 8,137 |
| Rearm declined | 10 | 17 |

Pacing accounts for approximately 71–73% of these yields. Python rearming
costs 1.353/1.222 seconds cumulatively in the instrumented windows. cProfile
uses elapsed time: select waits and native execution must not be treated as
Python CPU shares. The retained attribution is
`docs/service-yields-baseline.json`; full captures are under
`/tmp/courier-service-yields-baseline`.

The next implementation target is the short, bounded media-clock wait.
The reference first polls SIP signalling, waits for terminal input for up
to the 2 ms pacer interval, updates wait/pacing statistics and then runs the
same service. A native equivalent must preserve signalling deadlines,
terminal/error readiness, stop responsiveness, pacing statistics, and all
pre-DSP service/interrupt ordering. Required work or unexpected FD states
must still yield to Python. Waiting itself is not CPU pressure; the target
is repeated Python service and snapshot reconstruction around each wait.
No physical call or physical settings change was made.

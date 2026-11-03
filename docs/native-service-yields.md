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

## Bounded native wait implementation

The persistent native worker can now finish the short media-clock wait
without returning to Python. It performs all guest-state preflights first,
pumps the existing native RTP transport, and waits for at most the configured
pacer interval (2 ms in standard operation). Terminal and SIP readiness,
expired signalling deadlines, invalid descriptors, interruption and errors
still return control to Python. Readiness is never consumed in C++.

Completed wait statistics are folded back into DeadlinePacer and the line's
paced-seconds counter. A readiness continuation advances the pacing deadline
once and delivers the pending console/signalling action in the Python
service, avoiding a second wait. Custom consoles and a full input FIFO keep
the reference path. `COURIER_NATIVE_PACER_WAIT=0` selects the reference.
Rebuild the DSP library when deploying the changed shared-state layout.

Component and worker checks pass 52 cases: timeout bounds, input arriving
before/during a wait, signalling deadlines, disabled/invalid-FD paths,
service-clock commits and original scheduler/interrupt/media regressions.
Local modem/data and performance validation follow as a separate milestone.
The previous saturated A53 call did not pace: this optimization benefits
positive media-clock lead and is not a solution to its catch-up deficit.

## Final measurements and adoption decision

`tools/benchmark_service_pacing.py` compares a fixed number of stable
native services. The reference yields for Python SIP polling and
DeadlinePacer waiting, then resumes the same service. The candidate
completes its wait inside the native worker. This excludes full Python
snapshot reconstruction and all modem/DSP firmware work. Four paired
repetitions reverse order on alternate pairs. The A53 package is isolated
under `/tmp/courier-service-pacing-a53`, pinned to CPU 3; the normal checkout
is unchanged. Setup/build is excluded, and final service state must match.

| Fixed-service workload | Reference CPU | Native CPU | CPU reduction |
| --- | ---: | ---: | ---: |
| Notebook: 200 services, 1 ms positive lead | 0.06382 s | 0.02074 s | 67.5% |
| A53: 200 services, 1 ms positive lead | 0.13567 s | 0.02145 s | 84.2% |
| Notebook: 20,000 services, past deadline | 0.04076 s | 0.03872 s | small/noisy |
| A53: 20,000 services, past deadline | 0.29854 s | 0.30032 s | -0.6% |

The catch-up control performs no waits and shows no material change in
this isolated workload. It does not establish full-emulator throughput.
The old saturated A53 physical call had no pacing sleeps, so the positive-
lead gains must not be presented as a solution to its real-time shortfall.

A deterministic positive-lead firmware comparison additionally matches
memory, registers, DSP/serial state, timers, service phases, I/O counts and
queue diagnostics for eight million guest instructions. The native side
must actually perform waits. This brings the selected checks to 53.

The instrumented local candidate pair established
`CONNECT 31200/ARQ/V34/LAPM/V42BIS` at both ends and transferred exact data.
Caller/answerer rearm attempts fell from 8777/8137 in the initial reference
profile to 2928/2937. Native pacing-wait yields fell to zero while 6854/6541
waits stayed native. These differing training runs locate work; they are
not a fixed-work CPU improvement measurement.

Final uninstrumented validation had mixed results. The reference pair
connected and transferred exact data, but the candidate pair returned
`NO CARRIER` at both ends and transferred no markers. The failed capture
is retained alongside the successful captures. Fixed-work state equality
and component tests do not explain or outweigh this failed training gate;
timing-sensitive modem/audio behavior remains unresolved. No whole-call
speedup is claimed, and there was no additional physical call.

**The reference wait remains the normal default.** The candidate requires
explicit `COURIER_NATIVE_PACER_WAIT=1`. Its code and measurements are kept
for investigation, but it is not an accepted normal-operation enhancement.
The earlier implementation milestone supplied the candidate; final
validation is what determined this conservative default. No deployment or
physical modem settings change was made, and no temperatures were sampled.
Raw benchmark repetitions and successful/failed call summaries are retained
in `docs/native-service-pacing-results.json`.

The next useful investigation is the remaining unarmed-snapshot yields
and their invalidating port/memory callbacks. Unlike pacing waits, that
handoff work can matter while A53 is behind real time. Establishing safe
reuse across those boundaries still requires measured attribution and
state-equivalence checks.

## Actual rebuilt A53 call

The subsequent rebuilt physical call confirms that this host does not
currently benefit from pacing waits: zero waits were recorded while CPU
remained saturated and media lag reached approximately 80 seconds. The
physical modem answered but did not connect. Unarmed snapshots and DSP
transitions dominate observed native yield reasons in that attempt.
See `docs/physical-call-rebuilt-20261103.json` and the dated section in
`docs/physical-call-a53.md`. No experimental-wait call was placed.

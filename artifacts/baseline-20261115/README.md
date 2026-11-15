# Courier emulator baseline — 2026-11-15

Revision: `e94926db2bb3f4d40dc92a958ab532e0ab3ff725`. Host: absurd, Intel Core i5-5257U, Python 3.14.4, GCC 15.2.0. Source tree was clean before measurement. Backlog: kostik/projects, task #49 (Courier emulator).

## Timings

Five runs per workload, executed sequentially without overlapping benchmarks. All figures are seconds. First repetitions are kept separate because subsequent repetitions reuse process filter caches.

| Workload | First CPU / wall | Remaining four CPU median (range) | Remaining four wall median (range) |
| --- | ---: | ---: | ---: |
| Boot + idle, 30M instructions | 3.966 / 3.966 | 4.215 (3.906–5.255) | 4.218 (3.900–5.687) |
| Boot + dial, 30M instructions | 6.275 / 6.386 | 5.867 (5.650–5.969) | 5.861 (5.644–5.963) |
| Post-startup idle, ~30M instructions | 4.888 / 6.828 | 5.850 (5.275–9.836) | 8.849 (7.020–11.698) |

Post-startup runs exclude a 30M-instruction warm-up using console callbacks; the actual measured window is 29,990,912 instructions starting at 30,007,296. Top-level steady.json timings include warm-up; the table uses window timings. This path includes console polling and SIP pacing, so it is a separate workload from the no-console boot runs. Native compilation and machine construction are excluded. First-use filter work remains included in boot timings. Exact commands are preserved in *.command.json.

## Verification

All 16 benchmark runs completed with instruction-limit status. Within each of the three repeated workloads, all five final memory hashes, CPU registers, DSP state, DSP serial state, terminal output, timer state and interrupt state matched. Native batching/service counters vary in the paced window; they are retained as observations, not exact invariants. summary.json contains the comparison counts and all timing samples.

## Profile findings

The separate post-startup idle profile records 3.50M Python calls. Cumulative timings overlap and include native calls and waiting; they must not be added or treated as unprofiled CPU shares.

- 17,394 native batches, averaging approximately 1,724 native instructions each; 1,548 batches execute zero instructions. Native execution covers about 99.97% of the measured guest instructions.
- 9,659 board-service calls. Native snapshot arming totals 1.024 profiled seconds; bridge clock handling totals 0.833 seconds. These are useful candidates for reducing Python/native coordination.
- MMIO replay totals 0.340 seconds and MMIO writes 0.300 seconds. Leading watched exits occur at guest PCs 0x82ba1 and 0x9ec30; identify their device side effects before changing guards.
- SIP pacing includes 2.038 seconds in time.sleep. Waiting is not removable CPU work.
- The native run call totals 1.343 seconds, including native CPU/DSP/device work that cProfile cannot separate.

profile.txt contains cumulative and internal-time tables; courier.prof is the original profile. profile.json retains exit counters and measured-window MMIO counts. These results favor investigating service arming and device transitions before extending CPU opcode coverage; they do not establish the gain from any proposed migration.

## Limits

This is a local x86 notebook baseline, not an A53 measurement or a connected modem/data-throughput test. The SIP peer is a loopback UDP sink. Thermal sensors reached 88 °C near the end; samples show substantial timing variation, especially in the paced window. Background processes, thermal readings and load are recorded in environment.json and environment-end.json. No host tuning or service changes were made. Small performance changes require alternating baseline/candidate measurements under more stable conditions.

Hardware perf counters were unavailable: perf stat -e cycles,instructions true failed with perf_event_paranoid=4. No native CPU/DSP time attribution is claimed. Detailed worker-yield instrumentation was enabled for the profile, but this benchmark does not serialize its separate yield report; the saved native exit counters are the available boundary evidence.

No emulator source was changed. Raw results, commands, environment, profile and this report remain in this directory; no commit was created.

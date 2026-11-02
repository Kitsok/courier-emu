# Local standalone training attribution

`tools/profile_local_training.py` runs two analog403 Courier instances over
loopback SIP/RTP. Each endpoint uses a new temporary ARQ-only EEPROM,
transmit gain 0.25, no synthetic echo and no speaker monitor. It uses the
normal serial-console launcher and native worker integration. It neither
registers with the configured PBX nor accesses the physical modem.

Run with the same Python environment used for the emulator:

```sh
python tools/profile_local_training.py --output /tmp/training-profile --profile
python tools/profile_local_training.py --output /tmp/training-exits --batch-exits
```

The output directory must not exist. Each role retains its configuration,
terminal, diagnostic report and measurement boundaries. With `--profile`,
`training.prof` contains cProfile data. With `--batch-exits`, boundary
snapshots include native exit counters so boot can be subtracted. Without
`--profile`, the same driver provides a reference with cProfile disabled.

## Notebook capture, 2026-11-03

Both instrumented endpoints negotiated
`CONNECT 31200/ARQ/V34/LAPM/V42BIS` and received the opposite endpoint's exact
data marker. The profiling windows begin when SIP becomes connected and end
after the driver observes firmware CONNECT at both endpoints. They include
modem training and any interval until the second endpoint connects. Boot
and dialing are excluded. The raw capture is
`/tmp/courier-training-profile-2`; retained function attribution is in
`docs/local-training-profile.json`.

| Window | Caller | Answerer |
| --- | ---: | ---: |
| Elapsed time | 27.89 s | 27.90 s |
| Process CPU time | 23.22 s | 22.21 s |
| Guest x86 instructions | 94,106,370 | 93,891,583 |
| Native x86 batches in profile | 26,755 | 29,275 |
| Native rearming calls | 9,604 | 8,857 |
| DSP queue diagnostic callbacks | 10,570 | 13,904 |

The largest Python self-time entries are native-batch handling
(`NativeInterpreter.execute`, 0.565/0.576 s), rearming (`arm`,
0.443/0.428 s), and the interpreter's outer execution loop
(`emu_start`, 0.331/0.346 s). Supporting work includes attribute/native
state views, diagnostic queue writes, queue lengths, EOI folding, lane
refresh and SIP control synchronization. Rearming costs 1.505/1.351 s
cumulatively, including its eligibility and state checks.

cProfile uses elapsed time here: native `run` includes both x86 execution
and DSP work inside native polls, and `select` includes pacing waits.
Neither those entries nor the Python self times are unprofiled CPU shares.
The instrumented pair takes 44.91 s including boot and transfer. A separate
reference with cProfile disabled also connects and transfers exact data,
taking 32.29 s. The training paths retire different guest instruction
counts, so those durations cannot be used as a fixed-work speedup ratio.

The evidence points to reducing native/Python handoffs, rather than one
dominant remaining device function. Training-only native batch exit counts
are the next gate: whole-process counts are dominated by boot-time hardware
discovery and must not be used to choose a training optimization. In
particular, diagnostic queue hooks are frequent, but buffering them must
preserve the guest PC, stack-derived caller, store ordering and counts.
No implementation change is justified merely by callback count.

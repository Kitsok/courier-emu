# Standalone Courier DSP/SIP optimization

Target: Cortex-A53 aarch64 SBC. Primary workload: standalone analog403 with
the DSP and SIP, as selected by the user. Notebook measurements guide changes;
they do not establish A53 throughput. Existing paired-call figures in
`paired-emulation-performance.md` describe a different workload.

## Measurement setup (2026-11-01)

Notebook: Intel Core i5-5257U, two cores/four threads, Python 3.14.4,
GCC 15.2.0. Native libraries use the repository's normal `-O3` build.
`perf stat -e cycles,instructions true` fails with `perf_event_paranoid=4`.
Use cProfile to locate Python overhead, then unprofiled process CPU time to
measure changes. cProfile cannot separate DSP work inside native x86 polls.

`tools/benchmark_standalone.py` constructs the captured 403 board with its
EEPROM fixture, DSP, codec, exchange and real SIP session bound to loopback.
It reserves a local UDP sink; no configured PBX or external subscriber is
contacted. Each repetition boots a new machine. Compilation and construction
are outside the timed interval; lazy filter generation remains inside it.

```sh
python3 tools/benchmark_standalone.py --repeat 3
python3 tools/benchmark_standalone.py --dial --repeat 3
python3 -m cProfile -o /tmp/courier-sip.prof tools/benchmark_standalone.py --dial --repeat 1
COURIER_X86_PROFILE=1 python3 tools/benchmark_standalone.py --dial --repeat 1
```

These are boot-plus-idle/dialing workloads, not negotiated data throughput.
Thirty million instructions represent about 8.8 seconds of board time.
Wall time includes SIP pacing; CPU time measures work, including any helper
threads. Report both. Fresh processes include cold filter generation, while
later repetitions reuse process filter caches. Do not mix those samples.
Check final guest memory hashes and registers as well as performance.

## Initial findings

An exploratory older 302 ROM run without SIP completes 10M instructions in
2.63 s (3.80M/s, 1.12 times modeled instruction rate); this is not the 403
baseline. The standalone 403 idle run takes 5.81-6.19 CPU seconds for 30M
instructions and about 8.3 wall seconds. Those exploratory samples overlapped
profiling and are unsuitable for small A/B improvements.

The dialing cProfile run makes 8.35M Python calls. Native execution takes
1.97 s, Python native-batch dispatch 1.00 s, MMIO write/read handlers
0.40/0.36 s, and timer snapshot preparation 0.28 s across 104,892 calls.
First-use Kaiser window construction takes another 0.37 s. These are
instrumented costs, not percentages of an unprofiled run.

Native exit counters show 105,294 batches, including 23,781 zero-length
batches, and only 284 native instructions per batch despite 99.7% native
instruction coverage. Watched reads/writes around 0x814xx dominate boot;
these include device side effects and cannot simply be ignored. High native
coverage alone therefore does not mean low Python overhead.

Next: measure snapshot packing as a bounded optimization of the frequent
Python/native boundary, compare exact timer behavior and firmware state,
then measure longer steady operation and active SIP media before selecting
larger structural changes. Follow-up A53 results appear below.

## Nanovax inventory and live CPU sample

Read-only inspection through `ssh nanovax` found a FriendlyElec NanoPi R2S,
four Cortex-A53 r0p4 cores, little-endian aarch64, 408-1296 MHz with the
`ondemand` governor. Python is 3.11.2 and GCC is 12.2.0 on Debian, Linux
6.1.63. The clean checkout was at 25c2aa9. Python's FIR accumulation differs
from notebook Python 3.14, so compare each implementation against its local
baseline, not against cross-version guest hashes.

The machine already ran a Courier serialsim/SIP worker from a separate
`/dev/shm` deployment, plus a DECserver emulator taking another core and a
VAX process. Temperature was 83.8 C; thermal trip points are 70/85/95 C.
Sampled frequency varied between 600 and 1008 MHz during inspection. No
services, governor settings or deployment files were changed.

Unlike the notebook, nanovax permits user hardware counters. A 10-second,
99-Hz `perf record -g -p 5375 -- sleep 10` sample collected 1015 samples
without losses. Flat DSO shares of user cycles:

| Component | Share |
| --- | ---: |
| CPython 3.11 | 67.44% |
| Native x86 engine | 17.24% |
| DSP library (including resampler and native polls) | 10.38% |
| ctypes | 2.84% |
| libc / libffi | 2.10% |

`_PyEval_EvalFrameDefault` alone is 28.38%, `run_batch` is 13.88%, and
`resample::Timed::run` is 2.41%. This samples the existing worker's current
state, not a controlled connected modem data call. It supports investigating
Python/native boundaries first; it does not establish data-call capacity.
Raw data remains at `/tmp/courier-opt-live.data` on nanovax. Thermal/load
conditions prevent treating a single remote wall-time sample as a stable
maximum-throughput result.

## Timer snapshot packing

Replace six ctypes field assignments per timer with one native-endian
`Struct('=6Q').pack_into` call. Derive offsets from the ctypes layout and
check the slot size; preserve invalidation and read publication behavior.
No native ABI or guest timing changes.

Forced-refresh microbenchmarks on the notebook take about 0.32 s per 100k
refreshes with ctypes versus 0.13-0.16 s with packing. On nanovax, alternating
30k-refresh runs take 1.16/1.57 s with ctypes and 0.64/0.80 s with packing.
The operation itself is roughly twice as fast on the target.

Full-workload notebook measurements initially suggested a gain, but a
reverse run and alternating fresh-process runs did not reproduce it.
Alternating cold dialing medians: original 8.264 CPU seconds, packed 8.336
CPU seconds (0.9% slower, too small to establish a regression here). Do not
claim a notebook end-to-end speedup from this change.

Nanovax's first original/packed runs take 96.35/91.66 CPU seconds and
96.95/92.51 wall seconds for 30M instructions. The observed CPU reduction
is 4.9%, but thermal/load drift means one pair cannot attribute all of it
to packing. This remains far below real time (0.092/0.096 times modeled
instruction rate) for boot/dialing under the sampled conditions.

All final memory hashes, registers, native batch and scheduler counts match
between implementations on each host. The firmware hash also happens to
match across hosts for this workload, but that is not assumed generally.
Notebook regression: 14 tests passed in `test_native_timer_reads.py` and
`test_worker_deadlines.py`, including random timer modes, rollback, register
programming, idle, commands and dialing versus Python services.

Retain this as a bounded reduction in target snapshot overhead, without
claiming that it solves the larger Python scheduling bottleneck. Remote
candidate modules and benchmarks live only in `/tmp`; the deployed modem
and remote checkout remain unchanged.

## Symmetric Kaiser window initialization

The phase table has mirrored pairs: phase `PHASES-p` has the negated tap
offsets of phase `p` in reverse order. The Kaiser window is even. With the
current power-of-two phase count, both offsets are represented exactly,
so reusing reversed rows preserves every floating-point entry.

Compute phases 0 through 512 and fill their partners by reversal. This
reduces Bessel evaluations from 131072 to 65664 without changing the sinc
kernel or FIR accumulation. The cache still serves later kernels normally.
Exhaustive comparison with the old implementation matches all 131072
entries on both x86_64/Python 3.14 and aarch64/Python 3.11.

Window generation CPU time: notebook 0.433 -> 0.210 s; nanovax
3.751 -> 1.944 s. These are isolated first-use costs, not steady audio
throughput gains. Full notebook cold-dialing alternating pairs are noisy:
optimized/original 9.122/8.969 s, then 8.152/8.410 s. All guest state and
scheduler counters match; no reliable full-workload percentage is claimed.
All 20 resampler rate-change, waveform and Python/native comparison tests
pass. This optimization saves startup work only.

## Parallel services and thermal interference

At the user's request, stopped both user test services on nanovax:
`courier-serialsim-test.service` and `decserver90tl-test.service`. Both
report MainPID=0 and have no running worker processes; their final systemd
state is failed/exit-code after shutdown. They were not restarted. The VAX
and PBX services continue running. Previous loaded-host timings above are
retained as observations, not clean capacity measurements.

Before stopping those services, counters on the live Courier worker measured
0.991 CPUs used, an effective 0.681 GHz, 0.47 host instructions per cycle,
17.3% branch misses and 2.83% cache misses. Events were multiplexed at about
83%; these are broad indicators. Thermal/frequency behavior and Python's
dispatch-heavy work both matter on this in-order CPU. A local microbenchmark
or a fast notebook result cannot establish that a live SBC call is viable.

After stopping the two test services, repeated original/combined-optimized
30M-instruction runs take 55.958/55.828 CPU seconds and 55.193/55.077 wall
seconds. Memory, registers, native batch and scheduler counts remain exact.
The 0.23% difference is within noise: **no end-to-end speedup is established**.
The board still measured 84.2 C after testing, with 1.2 GHz observed during
the run, so even these results do not establish cool-board capacity.
Stopping the competing services improved the original baseline from about
96 to 56 CPU seconds; that environmental effect must not be attributed to
the code changes. Modeled instruction throughput is about 0.158 times real
time in this boot/dialing test. Neither change establishes real-time calls.

[Raw benchmark records](standalone-performance-results.json) preserve the
clean ARM pair and the alternating notebook runs, including final guest
hashes/registers. The benchmark exits unsuccessfully if a run stops before
the requested instruction limit.

Next structural investigation: profile separate post-boot idle, dialing,
training and connected-media windows, with temperature/frequency recorded.
The many short native batches and the live Python share justify investigating
device-access batching and worker snapshot/arming boundaries. Preserve the
existing device side effects and guest timing; optimizing the DSP alone
cannot remove the Python share measured in this running state.

## Post-boot measurement windows (2026-11-02)

The benchmark now accepts `--warmup-instructions 30000000` and measures the
following `--instructions` window through a console with the runtime's 8192
instruction polling period and cooperative SIP pacing. This is a separate
workload from the earlier console-free boot measurements. With `--dial`, the
AT command is scheduled at the warmup boundary. The local SIP sink does not
answer, so this measures idle or dialing, not modem training/connected data.

`--profile-out PATH --repeat 1` enables cProfile only during that window.
Both timing and profiling stop at a console poll before the instruction
limit, excluding final diagnostic-report construction. Start/end boundaries
are quantized by polling; actual measured instruction counts are reported.
Counter deltas capture the selected window rather than the full boot.

```sh
COURIER_X86_PROFILE=1 python3 tools/benchmark_standalone.py \
  --warmup-instructions 30000000 --instructions 10000000 --repeat 1 \
  --profile-out /tmp/courier-idle-steady.prof
```

The corrected idle profile measures 9,986,048 instructions, 9,624 native
batches, 3,310 native polls, and 6,442 Python service/arming calls. Arming
costs 0.344 s cumulatively, MMIO replay 0.125 s and interrupt dispatch
0.152 s, in a 2.713 s instrumented window. Of the window's MMIO traffic,
8,416 writes are end-of-interrupt at 0xff02; 1,917 other writes and 861 reads
remain. The expensive boot EEPROM register traffic is absent. UART status
reads alone (587) would not explain most steady overhead.

An initial profiling attempt included final report building, which lazily
drains native I/O logs. That falsely put boot I/O counts in the selected
window and attributed about 0.07 s to DSP diagnostic extraction. The corrected
console endpoint excludes that work. This is why instruction-window counters
must be captured before `run()` constructs its final report.

Next measured change: avoid replaying the full generic MMIO/device handler
for end-of-interrupt writes whose only remaining effects are the interrupt
stack and access tallies. Native polling already applies some stack effects
and marks the corresponding log records; replay must honor those marks.

### End-of-interrupt replay experiment

Tried a specialized replay of 0xff02 writes that retains width-specific
counters and the interrupt stack while bypassing irrelevant timer, UART,
EEPROM and trace checks. All final memory, register, scheduler and window
counter comparisons match, and all 14 worker/timer regressions pass.

Alternating off/on/on/off notebook runs give mean window CPU times of
2.112/2.120 s for idle and 2.266/2.223 s for dialing. Idle did not improve;
the small dialing difference is insufficient to establish a robust benefit.
The candidate is dropped. Generic MMIO replay remains unchanged. The next
step is native interrupt entry, which removes register/memory API calls
from each dispatched interrupt rather than trimming device-handler checks.

### Guarded interrupt entry in C++

Courier's interrupt dispatcher now offers ordinary real-mode entry to the
native x86 extension. One call validates the vector read and all three stack
writes, pushes the frame, reads the vector and publishes the four changed
registers. Watchpoints, unmapped memory, a physical boundary crossing or a
stale mapping guard decline before changing anything and retain the Python
dispatcher. Python still owns pending requests and the controller stack;
this moves entry mechanics, not the complete interrupt controller.

The Courier reference differs from the existing I-modem helper: it reads the
vector after writing the frame, permits zero vectors, preserves TF and adds
two to software-interrupt return IP. The new helper preserves that behavior,
including frames overlapping the vector table and SP wrapping through zero.
`COURIER_NATIVE_INTERRUPTS=0` retains Python entry for comparison.

Notebook validation: 43 interpreter, worker and timer tests pass, followed
by seven focused entry tests after adding explicit stack-wrap and physical
boundary cases. The focused tests include 200 randomized hardware/software
frames, zero vectors, watched final pushes, unmapped memory and stale guards.
Full firmware tests compare native entry plus native scheduling against the
Python entry/service paths for idle, AT/ATI7 and dialing.

Alternating off/on/on/off runs measure the following post-boot window CPU
times (means of two fresh-process samples per mode):

| Notebook window | Python entry | Native entry | CPU reduction |
| --- | ---: | ---: | ---: |
| Idle | 2.118 s | 2.094 s | 1.1% |
| Dialing | 2.239 s | 2.112 s | 5.7% |

Every final guest hash/register set and scheduler/native/window counter
matches within its workload. The idle profile confirms 5,942 native entries;
dispatcher cumulative time drops from 0.152 to 0.043 s, and total profile
calls fall from 1.543M to 1.442M. Profile timings are diagnostic, not the
unprofiled speed measurements above. The idle gain is small relative to
notebook variation; dialing provides the stronger local signal.

Nanovax built the new extension with GCC 12.2 in `/tmp/courier-irq`, using
the original checkout and DSP library for both modes. Its two parallel test
services remain inactive, MainPID=0. One off/on pair per workload gives:

| A53 window | Python entry | Native entry | CPU reduction |
| --- | ---: | ---: | ---: |
| Idle | 11.389 s | 10.614 s | 6.8% |
| Dialing | 13.699 s | 13.681 s | 0.1% (within noise) |

All guest memory/register and scheduler/native/window counter comparisons
match on ARM too. Temperature ranged from 79.6 to 85.8 C at run boundaries;
the result is workload-dependent and the 6.8% observation is not a guaranteed
gain under controlled clocks. No connected-data capacity claim is made.
The deployed runtime and remote checkout were not changed.

Retain the guarded entry optimization: it removes repeated Python APIs and
preserves the reference semantics, with measurable entry-cost and selected
workload benefits. [Raw interrupt benchmark records](standalone-interrupt-results.json)
include both notebook and ARM measurements, actual window sizes and guest
state. The remaining Python service arming, timer/controller scheduling and
pending-request dispatch are separate migration targets; this change does
not put the whole CPU/device interaction loop in C++.

## Native board-tick scheduling

The standalone scheduled worker now owns the recurring ROM board tick in
shared native state: its period, phase, count, vector, INT1 mask and pending
INT0/INT1 requests. Ordinary tick entry remains inside the x86 batch. A tick
coincident with a frame edge enters the board vector first and retains INT0;
an enabled INT1 is also retained for later delivery. Pending requests initially
yield the next service to Python. Guarded vectors/stacks and timer-counter
expiries retain the Python service. `COURIER_NATIVE_WORKER_TICK=0` restores
the old board-tick deadline. Paired workers retain their original path.

Full idle, AT/ATI7 and dialing comparisons against Python services pass.
Seven focused cases cover tick/frame/INT1 priority, flags, deferred requests,
watched stacks/vectors, future origins and delayed IF. Notebook alternating
off/on/on/off post-boot window means:

| Window | Python ticks | Native ticks | Native ticks per window |
| --- | ---: | ---: | ---: |
| Idle | 2.106 s | 2.091 s | 215 |
| Dialing | 2.187 s | 2.179 s | 352 |

Those sub-1% differences are noise, not an established speedup. Native polls
increase 3310 -> 3525 for idle and 4277 -> 4631 for dialing, replacing the
corresponding Python tick services. Final memory, registers, all reported
timer state and pending/in-service interrupt state match. The benchmark now
records those peripheral comparisons and native tick counts explicitly.
The next step removes the remaining Python service for deferred INT0/INT1.

### Deferred interrupts and snapshot ownership

The scheduled worker now delivers deferred INT0/INT1 requests in C++ at the
same timer-poll boundary and IF condition as Python. A new frame edge still
precedes deferred INT1, and the board tick precedes both. Requests remain
latched while IF is clear. Vector/stack guards precede all service changes;
timer-counter expiries, UART work and other device transitions still yield.
`COURIER_NATIVE_WORKER_IRQS=0` keeps the first-step deferred Python path.

The tick ISR also writes a watched diagnostic counter in the DSP-queue
address range. That write ended its native batch even though the hook only
records a trace. For this precise write-watch exit the worker can reuse its
native snapshot after the instruction commits, refreshing EOI stack and
panel state replayed from the batch. I/O exits, code hooks and full Python
services cannot take this shortcut. The exit reason is published before
return bookkeeping so the reuse decision cannot mistake an I/O handler for
a diagnostic write.

An initial attempt rebuilt a complete snapshot after each diagnostic write.
It increased native services but saved no CPU. Snapshot reuse reduced that
cost, and four layout-checked native-endian packed writes now replace the
common ctypes clock-field assignments. The reference path retains ordinary
assignments. This is still a snapshot boundary, not permanent native
ownership of every device field.

All 58 worker, timer and interpreter tests pass, including reset commands,
deferred priority, IF holdoff, polling boundaries, entry guards and exact
firmware/device-state comparisons against Python. Alternating longer
notebook windows (30M measured instructions after 30M warmup) give:

| Window | Python scheduling | Native scheduling | CPU reduction |
| --- | ---: | ---: | ---: |
| Idle | 6.250 s | 6.181 s | 1.1% |
| Dialing | 6.584 s | 6.515 s | 1.0% |

The reduction is small. In the shorter window, native services increase
3310 -> 5271 for idle and 4277 -> 6103 for dialing, while batch returns fall
9624 -> 7663 and 8105 -> 6288. Those structural changes do not imply the
same percentage CPU reduction. Earlier un-packed ARM pairs regressed while
observed frequency fell from 1296/1200 to 1008/816 MHz; they are retained as
negative observations, not hidden or attributed solely to the code.

The benchmark supports `--perf-control FIFO` with `perf stat -D -1
--control=fifo:FIFO` to count only the selected post-boot window. A local
ARM smoke test verifies enable/disable and counter output. This lets the
next ARM comparison report host instructions and cycles alongside CPU time,
without changing the governor or confusing warmup with steady work.

### ARM window counters and final validation

After packing, nanovax ran idle off/on/on/off and dialing off/on, counting
only each measured 9,986,048-instruction window. Two PMU events fit without
multiplexing (100% running time). The FIFO enable/disable commands exclude
boot and final reports; their processing is asynchronous, so boundary
precision is bounded by perf's command handling rather than a guest opcode.

| A53 window | Python scheduling | Native scheduling | Reduction |
| --- | ---: | ---: | ---: |
| Idle host instructions (mean) | 5.290 billion | 5.158 billion | 2.48% |
| Dialing host instructions | 7.600 billion | 7.405 billion | 2.57% |
| Idle CPU seconds (mean) | 10.918 | 10.641 | 2.5%, frequency-sensitive |
| Dialing CPU seconds | 14.340 | 14.378 | No gain |

The two idle reference instruction counts differ by only 0.01%; the two
native counts differ by about 0.1%. Thus the instruction-work reduction is
more convincing than the CPU-time reduction. The idle reference CPU times
range from 9.84 to 11.99 s as frequency changes. Temperatures at run
boundaries range from 76.9 to 85.4 C. Cycle counts also fall, but external
memory stalls consume different numbers of cycles at different frequencies;
do not attribute their full reduction to code or promise a fixed-clock gain.

All ARM guest memory/register, timer and interrupt-state comparisons match.
The remote checkout is clean, both parallel test services remain inactive,
and candidate code/libraries reside only in `/tmp/courier-worker`. Governor
settings and other services were not changed. The notebook suite passes 58
tests, plus two focused checks that the native exit reason is visible before
return callbacks (a safety condition for diagnostic snapshot reuse).

[Measurement records](standalone-worker-scheduler-results.json) retain all
stages, including the initial regressions, raw PMU counter output and
deduplicated guest/peripheral states. The final result is a small notebook
CPU reduction and about 2.5% less host instruction work on A53, rather than
a large or consistently observed ARM throughput gain.

Remaining ownership boundaries: timer-counter max-count expiry and its
requests, UART work, complete media frames and device transitions still
return to Python. The timer deadline scan and snapshot publication also
remain; removing those copies needs persistent native timer/device state,
not merely additional native callbacks. Connected training/data capacity
has not been established by these idle/dialing measurements.

## Authoritative timer/controller state

The analog ROM worker can now use a permanent native-layout timer buffer
(`native/timers186.hpp`, mirrored by `timers_native.py`). The three counters,
origins, compare/control registers, mask bits, pending queue and diagnostic
counts have one authoritative representation. Python fields are live views
of that buffer; native timer reads update the same counters on instruction
commit. Ordinary reads no longer copy or reconstruct timer snapshots.

Native clock advancement and deadline calculation preserve the Python
model's single-shot, alternating, external/prescaled, zero-compare, mask and
pending-request rules. Register programming and calibrated-delay grants
retain the reference Python logic on live fields. Unsupported board mask
maps keep their existing model. `COURIER_NATIVE_TIMER_MODEL=0` selects the
original TimerBlock and its snapshot read view.

This first step retains the timer-expiry boundary in worker scheduling.
It establishes storage ownership before native expiry/delivery is enabled.
Randomized register/clock scripts, mask/queue cases, exact deadline tests,
independent deep copies and transactional MMIO read rollback match the
reference. The initial timer/worker/interpreter run passes 66 tests,
including idle, identification, dialing and reset firmware comparisons.
The shared header is a dependency of both native builds, and layout checks
guard the Python/C++ ABI. Performance is assessed after moving the expiry
boundary, rather than claiming a gain from the storage change alone.

### Native counter expiry and timer request delivery

The scheduled worker now advances the shared counters at the reference
timer-poll boundary, latches requests while masked or with IF clear, and
delivers timer interrupts through the native interrupt path. It no longer
scans timer deadlines in Python or returns solely for a counter expiry.
After-run bookkeeping does not tick or copy the authoritative counters.
`COURIER_NATIVE_TIMER_POLL=0` retains the expiry boundary with shared state;
`COURIER_NATIVE_TIMER_MODEL=0` restores the original model and read snapshots.
Normal paired workers and alternate controller maps keep their existing path.

Expiry is preflighted before committing the service. A guarded vector or
stack therefore leaves counters and requests unchanged, so Python can run
the service once. DSP reply/loader/error yields also leave timer completion
to the existing Python continuation. Timer requests collected by a service
remain pending behind frame/INT1 delivery when required.

The first implementation diverged in full firmware despite passing isolated
expiry tests. The reference suppresses *generation* of the board tick while
a timer request is latched, including a request collected in that service.
Treating that as ordinary delivery priority shifts the firmware's calibration
and scheduling. The corrected implementation and a dedicated priority test
preserve this distinction. The 10M and 30M idle checkpoints then match
exactly, and all four firmware comparison cases pass with explicit assertions
that native timer polling and delivery execute.

The combined timer/worker/interpreter/build suite passes 76 tests; additional
checks cover native delivery use and unmodelled-read fallback. A separately
compiled pre-change source tree at `ed89410` is the performance reference,
so the comparison includes the full model and compiler-layout change.
Alternating before/after/after/before notebook runs use 30M measured
instructions after 30M warmup:

| Window | Before | After | Mean CPU reduction |
| --- | ---: | ---: | ---: |
| Idle | 5.929 s | 5.680 s | 4.2% |
| Dialing | 6.455 s | 6.306 s | 2.3% |

The dialing samples vary more than idle; retain that uncertainty. Final
guest memory, registers, all reported timer state and pending/in-service
interrupt state match in every sample. ARM results are collected with
isolated before/after source builds and windowed hardware counters.

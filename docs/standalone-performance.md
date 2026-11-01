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

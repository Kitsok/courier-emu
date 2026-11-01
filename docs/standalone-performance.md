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
larger structural changes. A53 results remain unmeasured.

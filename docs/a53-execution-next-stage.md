# Next execution-stage requirements after training timing analysis

Current read-only nanovax inspection at `a1e1a69` confirms four online
Cortex-A53 cores, affinity 0–3, ondemand policy, and a permitted maximum
of 1296 MHz. The sampled current frequency is 1296 MHz. No competing
Courier worker/build/call is present. This is not a frequency trace during
training and does not establish a sustained clock. No governor or host
settings were changed and no temperatures were read.

The retained diagnostic call delivered 4.0 seconds of outbound RTP over
10.02 seconds of wall time. It needs roughly 2.5 times that delivery rate
merely to reach real time in this attempt. Earlier interior attribution
places 59.37% of CPU in C5x/devices, 29.87% in native x86 and 8.84% in
Python. These are different intervals, so the following is a planning
bound rather than a predicted speedup: halving all C5x/device cost would
give only 1/(1-0.5937/2), about 1.42 times overall throughput. Even making
Python free gives only about 1.10 times. Narrow handler inlining cannot
close this gap by itself. Both native execution engines remain relevant.

A larger DSP executor must reduce repeated instruction dispatch/setup
while retaining the current interpreter as its correctness reference.
A cached handler pointer alone still performs an indirect call per
instruction and is not equivalent to native block translation. No large
speedup should be assumed from merely adding a decoded cache.

Code inspection identifies these mandatory boundaries for a prototype:

- Preserve per-instruction condition sampling, cycle count, timer/event
  deadlines, interrupt eligibility and PCM-frame yield boundaries.
- End optimized execution at unsupported control transfers, delay slots,
  hardware repeats, mapped-register or port effects until those are
  explicitly supported; resume the existing interpreter at the same PC.
- Include downloaded external code in the design: a ROM-only accelerator
  would not cover the full training workload.
- Validate code identity across PM_WRITE16, host load_program, shared data
  writes, SARAM aliases and B0 program/data remapping. Direct MAC span
  writes also alias program storage and cannot bypass this requirement.
- Preserve tracing and access counters, and use targeted comparison of
  state and code modifications before whole-call validation.

The current source has no comprehensive code-generation epoch shared by
all these write paths. A translation cache therefore requires explicit
identity guards or complete invalidation coverage before adoption. This
is a larger implementation stage; another unchecked inlining or dispatch
cache claim would not address the measured deficit. The physical ARQ
connection remains unestablished.

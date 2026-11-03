# SBC feasibility review after the DSP/Python batch

## Assessment

Reliable real-time Courier/SIP operation is not demonstrated on the
current Cortex-A53 target. A literal Cortex-A35 target remains a research
possibility, not a supported performance expectation. Small local changes
alone no longer have evidence sufficient to justify predicting success.
The next viable approach needs a measured whole-workload improvement,
likely involving broader native execution in both emulated processors.

Nanovax is a NanoPi R2S with four Cortex-A53 cores and a permitted maximum
of 1296 MHz, not a Cortex-A35 host. No A35 benchmark exists in these
findings. A board's sustained frequency, cache implementation and memory
system matter; an A35 prediction cannot be derived from its name alone.
Arm describes A35 as an eight-stage in-order ARMv8-A design emphasizing
small area and low power, and compares its efficiency with A53:
https://developer.arm.com/community/arm-community-blogs/b/architectures-and-processors-blog/posts/introducing-cortex-a35-arm-s-most-efficient-application-processor
This supplies architectural context, not courier-emu throughput evidence.

## What the repository establishes

- Latest physical validation has no modem CONNECT: physical NO CARRIER
  and emulator BUSY. Notebook exact-profile ARQ/data success validates a
  functional path but does not establish SBC capacity or interoperability.
- The latest worker consumes 101.67% CPU across the sampled probe, with
  zero pacing waits. This is saturation of approximately one core, not a
  measured 1.67% real-time shortfall. Required CPU work may exceed capacity
  substantially while utilization remains pinned near 100%.
- Latest outgoing RTP contains 3.80 seconds of audio over an 8.91-second
  packet span; incoming media spans 9.14 seconds with regular packet
  arrival. Outgoing activity is delayed and gaps reach 441 ms. These are
  failed-call observations, not an exact fixed-audio processing benchmark.
- Earlier analysis in a53-execution-next-stage.md estimated roughly 2.5x
  delivery throughput was needed in that attempt. It is a historical
  planning indicator, not a current measured speedup requirement.
- The latest return kernel saves 42.26% of its own host cycles, and the
  configured Python binding microbenchmark saves 23.64%. Neither result
  has established an improvement in physical-call response. Both attempted
  x86 changes were rejected after target regressions.

## Remaining opportunity and its limits

The current default executes x86 and DSP firmware synchronously on one
emulation thread, largely through native C++ interpreters. Moving more
surrounding Python code to C++ cannot remove their instruction-dispatch,
addressing, flag, repeat and event costs automatically.

Latest short training attribution is 45.44% DSP/devices, 34.01% x86 and
16.84% Python. As an illustrative Amdahl bound, removing all that Python
cost gives only about 1.20x throughput. Halving both native shares gives
about 1.66x overall; reducing both to one third gives about 2.13x. This
arithmetic assumes fixed representative shares and unchanged work. It is
not a forecast, and five-second samples from failed calls cannot establish
a sustained-call budget. It shows why either Python-only optimization or
one narrow DSP kernel is unlikely to settle feasibility.

Broader guarded native blocks or dynamic translation remain plausible
ways to reduce both execution engines' costs. Their benefit is unproven;
code modification/alias invalidation, exact condition/repeat behavior,
interrupts and device deadlines remain correctness requirements. Separate
x86/DSP threads could use another core but introduce scheduling and
synchronization costs and do not by themselves prove adequate throughput.
The architecture supports neither automatic four-core scaling nor a
simple multiplication of current throughput by the core count.

## Decision gate

Measure process CPU time per fixed amount of processed audio on the
actual physical-training path, and establish whether backlog grows over
that interval. A useful engineering target is at most 16 ms of work per
20 ms of audio (about 20% single-core capacity reserve), with bounded
media gaps. The exact scheduler service granularity need not be 20 ms.
Then evaluate a broader executor prototype by that whole-workload metric.
A successful mandatory-ARQ connection to physical modem 100 remains the
acceptance criterion, followed by sustained data/media validation.

If that prototype cannot close the measured deficit, retaining an A35/A53
requirement requires another architectural change; a faster SBC is the
practical alternative. Current evidence supports neither declaring the
hardware fundamentally incapable nor promising that another small batch
will make it reliable. No call, build, hardware query or setting change
was performed for this review.

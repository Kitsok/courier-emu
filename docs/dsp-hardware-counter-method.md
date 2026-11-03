# Phase-controlled DSP hardware counters

Use tools/measure_dsp_counters.py with a prebuilt library on Linux/A53.
Run under taskset for a consistent CPU. perf starts with events disabled;
worker setup and 100000 warmup DSP cycles finish before an acknowledged
enable command. Disable and acknowledge counters after the native kernel,
before reading final state. Counts include a small amount of Python and
FIFO acknowledgement work around the call, not process/library startup
or core setup. The state digest checks CPU/serial/map/data/write counts.

The tool reads cycles:u and instructions:u, retains raw CSV and rejects
unsupported events or less than 99% counter running time. It records actual
retired instructions and executed modeled cycles, CPU time and library
hash. Control acknowledgements from the installed perf include a NUL;
handle that framing without mistaking it for a missing response. A first
probe exposed this framing issue and failed before producing valid data;
the corrected probe and final tool both completed successfully.

Two reference runs of the paired-DMOV loop produced matching state hashes.
The final run retires 555556 guest instructions over exactly one million
DSP cycles, using 147578860 host user cycles and 151818082 host user
instructions in 0.114395 CPU seconds. Both counters report 100% running.
This is approximately 148 host cycles per modeled DSP cycle for this
specific loop, not an estimate for every training instruction. The prior
probe gave 148169323 host cycles and 151850571 host instructions.

The active reference library remains unchanged. No governor, temperature
or modem-setting queries/changes and no physical call were involved.
Use counter counts alongside alternating timing controls in future
comparisons; do not retroactively declare earlier candidate rejections
incorrect from these two reference observations. Raw successful probes
are in dsp-hardware-counter-validation.json. This improves measurement
quality and does not itself accelerate or establish a physical call.

## Compiler comparison with controlled phases

Three alternating GCC/Clang 16 pairs per kernel confirm matching state
while measuring only acknowledged execution phases. Median paired-DMOV
host cycles are 147814759 versus 166771541 (12.82% more with Clang); host
instructions are 151803733 versus 165140342 (8.79% more). Address-update
cycles are 193194868 versus 215161780 (11.37% more), and instructions
230702488 versus 248327878 (7.64% more). Raw counters all report 100%
running. These two kernels support the Clang rejection independently of
CPU-time variation; they do not validate every earlier microbenchmark or
quantify whole-training performance. Raw runs and medians are retained in
`dsp-compiler-phase-counters.json`. No new call or host-policy change was
needed.

The training trace prose previously swapped caller and answerer labels.
The authoritative raw windows and structured summary were correctly
labeled; prose is corrected to caller 12288 entries, answerer 6566.
The observed DMOV pair counts are caller 148 and answerer 42. This changes
no aggregate counts or physical-connection conclusions.

# Native execution of the initial-handshake five-tap filter

Executed-work profiles put the MADS body at 8aae–8abb at about 17% of
caller opcode bodies in each of the first three modeled seconds after
SIP answer. It runs inside the RPTB whose opcode/immediate are bec6,8abb
at 8aac. Its return at 8abc is outside that repeat body. This is a more
relevant initial-response candidate than the later complex loop.

The existing COURIER_C5X_TRAINING_BLOCK=1 opt-in now admits the exact
fourteen live code words. The C++ path preserves explicit BMAR read,
ADD and write semantics; five MAC taps with ordered coefficient/data
reads; product scaling, saturation and sticky flags; circular AR updates;
two ordered DMOV copies; normalization and the final direct operand and
store. It retains register/data/program access counts, write counts,
temporary registers and repeat state. MADS intentionally leaves TREG1/2
unchanged. AR0's mirror updates are preserved when NDX is clear.

Admission rejects mapped operand registers, traced BMAR writes, codec
sinks, unsupported DMOV sources, changed code and diagnostic/delay or
instruction-repeat state. Coefficients require a valid mapped program
span. Preflight determines modeled MAC bus costs and requires the whole
body to fit before the next event/run boundary. Block repeats may cover
the body but cannot have an edge inside it. Leave the repeat edge to
ordinary stepping. When no block repeat is active, a matching RETC may
also execute natively if its four cycles fit. Stack pop, final PC/opcode,
condition samples and retirement are committed accordingly.

An initial draft fused the complete helper including RETC but rejected
BRAF. It connected with exact ARQ data under the diagnostic build, yet
admitted only roughly 27% of caller bodies and none of the early answerer
bodies. The source/profile evidence exposed the RPTB boundary. Refine
admission around the body instead of optimizing only the final iteration.
Both diagnostic outcomes and their actual frame intervals are retained
in `dsp-filter-work-coverage.json` and compressed work profiles.

The refined version passes 302 focused filter, arithmetic, complex and
XC checks in 1.99 seconds. Cases cover partial budgets, PM/OVM/SXM/TRM,
AR0 mirrors, circular wraps/precedence, SARAM timing and coefficient
aliases, register observers, codec writes, timer boundaries, changed
code and repeat edges with zero, one or three additional repetitions.
Small FIFO-acknowledged counter smoke checks retain matching state for
DARAM and SARAM; native hits prove admission. These are not hardware
perf measurements. Raw smoke data is in `dsp-filter-counter-smoke.json`.

The refined exact-profile notebook run establishes
9600/ARQ/V32/LAPM/V42BIS on both endpoints and exchanges exact data.
More than 99.8% of the early caller's filter bodies are admitted. Total
native opcode-body coverage rises from about 13% to about 29.5%; early
answerer coverage rises as well. Frequencies are not CPU shares and
instrumented run durations are not controlled speed comparisons.
A53 performance and physical initial-response improvement remain
unmeasured. No physical call was made for this milestone.

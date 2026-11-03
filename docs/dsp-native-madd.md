# Native execution of the neighboring initial-handshake MADD helpers

The executed-work profile identifies the helper at 8a7d–8a87 and the
preparation helper at 8aa2–8aab as roughly another 21% of caller opcode
bodies in each of the first three modeled seconds. Both run five MADD
taps with delay-line copies, then normalize and store a result.

The native opt-in now recognizes their exact live code in external
program storage. One helper writes BMAR and returns through RETCD with
two delay-slot instructions. The other writes BRCR and stops before the
following RPTB. Preserve those distinct register writes, stack behavior,
PC/opcode context and retirement: delay-slot bodies do not retire as
separate outer instructions in the existing accounting model.

Preflight resolves five internal data sources, five ordered copy
destinations, the final store and direct addend. Coefficients remain live
across the copies, because SARAM aliases can change later coefficients.
Existing product scaling, ADD flags, saturation, normalization and TRM
behavior are retained; MADD does not load TREG1/2. Circular updates and
AR0 mirrors are committed exactly. Preserve repeat state and bus timing,
including SARAM contention, and require the complete body before the
next event/run boundary. Unsupported mappings, observers, codec writes,
changed code, unsafe repeats and delayed/instruction-repeat state retain
the interpreter. Entry checks affect only the SAMM opcode wrapper.

The notebook native build passes 369 focused MADD/filter/arithmetic/XC
checks in 2.13 seconds. Tests cover partial budgets, both helpers, all PM
modes, saturation/SXM/TRM, AR0 mirrors, circular wraps and precedence,
SARAM coefficient aliases, register observers, codec writes, timers and
changed code. Small FIFO-acknowledged counter smoke checks match state
and record positive native hits for both helpers and SARAM data with
external coefficients. These do not measure A53 performance. Raw smoke
data is in `dsp-madd-counter-smoke.json`.

Actual-training coverage and A53 gains remain outstanding at this stage.
The previous MADS physical attempt and its observed response improvement
are independent evidence; no additional physical call was made for this
implementation milestone. Keep error correction mandatory and physical
modem settings untouched.

## Measured initial-training coverage

The diagnostic notebook run at 144a466 establishes
9600/ARQ/V32/LAPM/V42BIS on both ends and exchanges exact marker data.
The new helpers admit more than 99.8% of their early caller opcode
bodies. Total native-body coverage in each of the first three modeled
caller seconds reaches about 49.85%, versus about 29.5% with only the
MADS addition and about 13% before both filter families. Early answerer
coverage also rises. The third answerer interval is waiting work with
none of these native bodies, rather than proof of missing admission.

Keep these frequencies separate from CPU shares and unprofiled speed.
The collection includes the C5X_PROFILE_WORK diagnostic build, so its
36.38-second total run duration is not a controlled timing result.
Raw work rows and outcomes are in `dsp-madd-work-profile.json.gz` and
`dsp-madd-work-coverage.json`. A53 validation remains pending; no new
physical call has run for this MADD batch.

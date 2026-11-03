# Isolated DSP compiler comparison

The threaded executor requests Clang statement-level always_inline and
musttail behavior. Actual GCC 12 ARM code still calls separate opcode
bodies. Targeted inlining helped one load/store kernel, but subsequent
arithmetic and successor experiments did not provide useful target gains.
A Clang build of the same source is a distinct code-generation experiment,
not evidence of a speedup until measured.

Read-only nanovax inspection finds LLVM 13 libraries but no Clang executable.
APT offers Clang 14 and 16. A simulated no-recommends Clang 14 installation
would add nine packages and upgrade/remove none: clang-14,
libclang-common-14-dev, libclang-cpp14, libclang1-14, libgc1, libllvm14,
libobjc-12-dev, libobjc4 and llvm-14-linker-tools. No package was installed.
The user has been asked whether to add build tools to this shared host;
that preference is pending. The active GCC runtime remains unchanged.

`tools/build_dsp_variant.py --compiler /usr/bin/clang++-14 --output /tmp/libcourier-c5x-clang14.so`
uses the same optimization/link flags and translation units as the normal
DSP builder. It refuses the active runtime path or existing output, builds
through a temporary file, and records compiler version, source hashes,
command and resulting library hash. Existing prebuilt-library overrides
allow comparisons without replacing the deployed library. CLI help and
Python syntax checks pass; a Clang compilation is pending availability.

After building, first inspect the emitted hot wrappers and compare state,
counters and alias behavior with the GCC reference. Measure relevant DSP
kernels with unaffected controls before a bounded full-training check.
Do not infer an A53 connection from a compiler or kernel result. No new
physical call, physical setting change, governor change or temperature
query was performed in this preparation stage.

## Separate GCC code-generation diagnostic

While package installation remains pending, the isolated builder also
accepts repeated --extra-flag arguments and records them in the command
manifest. This permits a current-source GCC integration diagnostic without
changing host packages or the active library. CLI and syntax checks pass.

Earlier paired-performance notes mention unsuccessful inline-limit tuning;
therefore no gain is presumed from revisiting flags. The narrower question
is whether current GCC 12 integrates the actual sampled opcode bodies with
larger automatic-inlining and unit-growth limits. Inspect generated hot
wrappers before deciding whether further timing is justified. Stop if
integration does not occur; broader code growth can regress instruction
cache behavior even if calls disappear. This remains an isolated experiment.

## Current-source GCC diagnostic built

The separate build with max-inline-insns-auto=1000 and inline-unit-growth=100
completed. It is 889608 bytes versus the deployed 826400 bytes, about 7.65%
larger. Actual ADD-memory integration occurs, while MADD and DMOV still
call separate bodies. Wrapper instruction counts alone are not execution
costs and do not establish a throughput gain. An ambiguous LT/LTS prefix
match in the inspection helper was excluded from retained results.

More inlining emitted low-address LAMM/SAMM/LMMR SARAM-bound warnings.
Those opcodes mask operands below 0080; valid maps classify that range as
registers or low DARAM. Thirty-six short cases covering GREG and DARAM
0060/007f across C51/C52/C53, tracing enabled/disabled, and plain/threaded
execution match the deployed reference, including expected results and
state/access/write counters. Digest:
`dae44553bdbad6ebe96492509c631a93859b4278a095e6c6e57a89f2c7e001f7`.
This checks the warning paths but does not establish complete correctness
or prove every compiler warning benign. No benchmark or physical call
was made with the variant yet. The active runtime remains unchanged.

The build manifest, source/library hashes, selected generated-handler
calls and matching checks are in `dsp-gcc-inline-diagnostic.json`. This
partial code integration justifies a bounded kernel comparison, with
unaffected controls, before deciding whether any larger validation is
worthwhile. Clang installation remains pending the user's preference.

## Reject the GCC flag variant on kernel controls

Three alternating reference/candidate pairs, pinned to CPU 3, used
500000 modeled cycles per case with matching final architecture, serial
state, access counters, data and write counts. SARAM MADD improves by
8.28%, but MACD-DARAM regresses by 4.88%, DMOV-DARAM by 5.35%, LTD-SARAM
by 5.07%, and the primary-instruction control by 11.83%. Other cases vary
from a 2.44% improvement to a 1.83% regression. Short MAC timings have
limited precision; these are kernel observations, not full-training
performance estimates.

This mixed result and the control regressions do not justify replacing
the active library or making another physical call. Reject this flag
combination for adoption. The separate artifact remains under /tmp for
inspection; no runtime rollback is needed because it was never deployed.
Raw results are in `dsp-gcc-inline-kernels.json`. The normal source and
compiler flags are unchanged.

Clang is still absent and the installation preference remains unanswered.
It would exercise the statement-level forced integration intended by the
existing executor, rather than this GCC heuristic change. No installation
or physical-modem setting change is authorized by elapsed waiting time.

## Clang installation authorized and completed

After the user's go-ahead, nanovax installed clang-14 1:14.0.6-12 with
no recommends. APT added the nine previously listed packages, upgraded
none and removed none. It downloaded 37.2 MB and reported 213 MB of
additional installed space. Installation completed successfully.

An isolated Clang DSP build has been started through the recorded-variant
builder at `/tmp/libcourier-c5x-clang14.so`. This is not a runtime switch
or validation result. The deployed GCC DSP library still has SHA-256
`1b215212c54722fedb41a75a690be51788f75e50bc1a0ae35f4d79bdfc1f3c56`.
No physical modem setting was altered and no test call was made during
installation. Earlier pending-installation notes describe historical
state; authorization is now resolved.

## Clang 14 compatibility result

The isolated Clang 14.0.6 build completed, at 774152 bytes. It warns that
the statement-level clang::always_inline attribute is unknown and ignored.
Actual ARM wrappers still call separate MADD, DMOV and ADD-memory bodies.
It therefore does not fully exercise the intended forced-integration path.
The artifact remains separate at `/tmp/libcourier-c5x-clang14.so`, with
the builder's source/compiler/library manifest alongside it.

All 36 focused low-address cases match the deployed GCC reference and
the recorded digest. No benchmark under package-installation load was
attempted; performance and wider correctness remain unproven.

The authorized compiler comparison is proceeding to Clang 16. The reviewed
APT plan adds six packages, upgrades/removes none, downloads 38.8 MB and
reports 227 MB additional installed space. Its installation is in progress.
A tiny source probe will require both statement always_inline and musttail
with unknown/ignored attributes treated as errors before another full DSP
build is started. The active GCC runtime remains untouched.

## Compatible Clang 16 probe passed

The authorized toolchain comparison installed Clang 16.0.6
(1:16.0.6-15~deb12u1) and the six reviewed packages successfully. There
were no upgrades or removals. Clang 14 remains available as a distinct
compiler baseline; neither compiler changes the deployed runtime.

Before another full build, Clang 16 compiled a tiny syntax probe containing
both statement-level always_inline and musttail with
-Werror=unknown-attributes and -Werror=ignored-attributes. It passed.
The isolated full DSP build is now running at
`/tmp/libcourier-c5x-clang16.so`, with unknown attributes treated as errors
so the earlier compatibility problem cannot be silently accepted.

The probe verifies annotation acceptance, not actual opcode integration,
correctness or speed. Those remain separate emitted-code and runtime
checks. The deployed library hash is still the recorded GCC reference.
No physical call or modem-setting change was made during this stage.

## Clang 16 integration validated, performance rejected

The isolated Clang 16 build completed with unknown attributes treated as
errors. Exact-symbol inspection confirms no separate opcode-body calls
inside the inspected MADD, DMOV, LT, LACC-memory, ADD-memory and SACH
wrappers. The artifact is 838688 bytes versus the active GCC 826400 bytes
(about 1.49% larger). This achieves the requested code integration.

All 60 focused cases match reference architecture and counter digests:
36 register/DARAM cases plus twelve load/store and twelve arithmetic
threaded cases. Eight additional kernel families match state, serial,
map counters, data and write counts in every timed repetition.

Three alternating pairs on CPU 3, 500000 modeled cycles per case, find
no useful timing gain. Clang DMOV-DARAM is 15.30% slower, LTD-SARAM 9.85%
slower and the primary control 14.26% slower. Repeated MAC cases regress
by roughly 49–78%, with external MADD 6.64% slower. Short MAC timings
have limited precision, but the consistent regressions do not support
deployment or another physical call.

Reject this unmodified Clang 16 build for runtime adoption. The normal
GCC artifact and build flags remain active; no rollback is needed because
all compiler variants stayed under /tmp. Installed toolchains remain
available for future work. Generated integration alone is not a speedup
and does not resolve the physical connection deficit. Manifest, exact
handler calls, matching checks and all raw timings are retained in
`dsp-clang16-comparison.json`. No physical modem settings were changed.

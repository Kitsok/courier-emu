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

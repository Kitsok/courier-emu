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

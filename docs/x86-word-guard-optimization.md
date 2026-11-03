# Packed word guards in the native x86 interpreter

Training attribution places roughly 29% of sampled CPU in native x86.
The traced specialization is required for complete diagnostic write records;
its stack snapshots and replay contract are preserved. Removing tracing
without preserving those semantics was not selected.

For an ordinary two-byte memory access, read both guard bytes with memcpy
and check replicated permission/watch masks together. Return directly only
when both bytes permit the operation and neither is watched. The original
byte loop handles traced writes, watched bytes, denied permissions and
unusual sizes. Bounds checking remains before the packed read. Replicated
byte masks make the result independent of host endianness, and memcpy
avoids unaligned-load undefined behavior. No guest memory read or write
is reordered past a failed guard.

The notebook extension builds successfully. Forty-three native interpreter,
write-trace and checkpoint checks pass in 16.22 seconds, including randomized
instruction equivalence, changing trace stacks, partial-instruction
fallback and interrupt behavior. No new heavy test workload or physical
call was introduced.

This is a performance candidate, not a measured speedup. It adds a size
branch to other access sizes and may alter code layout. Compare ordinary
word memory, traced memory and byte/register controls on A53 before
claiming a benefit; reject it if target controls regress. The earlier
checkpoint-elision experiment remains rejected.

## Reject after A53 comparison

Nanovax rebuilt the candidate and ran three alternating pairs of one
million instructions per case, after 100000 warmup instructions, pinned
to CPU 3. All architectural/trace digests match. Ordinary word-memory
control improves by 9.43%, but traced memory regresses by 7.67%, byte
memory by 4.61%, and the 386 register control by 2.40%. Other register
controls vary by roughly 4–5%, limiting precise attribution.

The actual training interpreter uses traced execution. The observed
traced and byte regressions outweigh the isolated word result; remove
the packed check rather than retain it on the strength of one kernel.
Raw measurements are in `x86-word-guard-arm-results.json`. No physical
call, physical settings change or temperature sampling was performed.
Restore the pre-candidate interpreter library after checking that native
sources match its revision. This candidate establishes no training gain.

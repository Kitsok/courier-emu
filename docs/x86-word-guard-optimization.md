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

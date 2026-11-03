# DSP code-inspection optimization passes

Requested scope: implement suitable candidates from code inspection, commit
at each stage, then reread the changed code and perform a second pass.
Validation is limited to native compilation and short focused correctness
checks. No performance benchmark campaign, heavy integration workload,
modem call, nanovax deployment or temperature sampling is part of this work.
No speedup is claimed without subsequent measurement.

## First pass — repeated operand decoding

Seventeen hardware-repeated MAC, block-transfer and port-I/O handlers now
decode their opcode addressing fields once per instruction rather than once
per tap/word. Dynamic DP, ARP and auxiliary-register contents remain live.
Circular, indexed and bit-reversed addressing retain the existing update
logic. This also preserves repeated register transfers that change address
state while executing; only immutable opcode fields are hoisted.

Validation: native build and 15 focused MAC/instruction checks pass, including
an OUT repeat whose first iteration changes ARP. No timing measurement or
call was performed.

## First pass — direct-span repeated MACs

Repeated MAC/MACD/MADD/MADS can use validated DARAM and coefficient spans
instead of rerouting every memory access through the general map helpers.
Only simple indirect addressing is eligible. Guards reject dirty maps,
write tracing, active circular addressing, wraparound, mapped-register data,
codec-write slots and coefficient spans crossing an on-chip window. ROM
holes and all unusual cases retain the general implementation. Live pointer
loads preserve coefficient/data aliasing; guest arithmetic and cycle
formulas remain unchanged. Access and write counters remain accounted for.

Validation: native build and 25 focused checks pass. Sixteen small filters
compare direct and tracing-forced general paths across all product-scaling
modes, saturation, MAC variants and auxiliary-register updates. No timing
measurement or call was performed.

## First pass — hoist invariant MAC work

The eligible direct-span kernel now selects product scaling and data-move
behavior once. Accumulator/product intermediates stay local; temporary
registers, auxiliary-register position and access counters are committed
once at the end. Per-address write counts and live coefficient/data loads
remain ordered in the loop. These hoists are restricted to the side-effect-
free span guards introduced in the preceding stage; the general path still
performs each dynamic action normally. AR0's NDX-clear mirrors are retained.

Validation: native build and 29 focused checks pass, including AR0 mirror
updates, all product modes, saturation and tracing-forced fallback. No
measurement or call was performed. The first implementation pass is now
complete; the next stage rereads the changed code before making additional
optimizations.

## Second pass — SARAM spans and alias-safe bounds

Rereading the completed first pass showed that the same guarded kernel can
also cover contiguous SARAM operands. The second pass adds that mapping
with its own read counter and model-specific bounds. Coefficients remain
live when they overlap future delay-line destinations. The reread also
corrected pointer-offset expressions to compute bounded integer offsets
before pointer addition, including high SARAM and B0-program addresses.

Validation: native build and short SARAM checks pass, including overlapping
coefficient/data storage on C51 and C53 and the upper C53 SARAM window.
No benchmark or call was run.

## Second pass — MAC setup and timing classification

General MAC fallbacks now decode operands only after the direct path is
rejected and capture the initial effective address before entering the
loop. This removes a first-tap test from every iteration without changing
dynamic address updates. Cycle accounting reuses valid cached memory-map
entries; dirty mappings retain the original region classifiers. Guest
cycle formulas and missing-ROM timing remain unchanged. Product scaling
uses unsigned shifts for defined 32-bit wrapping, including negative
products.

Validation: native build and 38 focused MAC checks pass. No benchmark or
call was run.

## Final reread and completion

Both inspection passes are complete for this batch. The final reread
checked the complete change against the original address helpers, memory
classifiers, access counters, repeated-instruction retirement and event
handling. Span bounds keep direct accesses inside one backing allocation;
coefficient loads remain live across overlapping delay-line writes. General
register, circular, indexed and bit-reversed cases retain dynamic handling.

No further inspection-only change was selected. In particular:

- Event, interrupt, delayed-condition and repeat-edge bookkeeping still
  carries architectural state and cannot simply be removed or postponed.
- Extending direct spans to general block transfers would need additional
  treatment of overlapping storage, mapped registers and per-word effects.
- A full decoded-instruction cache would need invalidation for downloaded
  code, overlays and aliased program/data writes. The implemented operand
  predecode is local to one executing instruction and needs no such cache.
- Caching reversed INDX values would add a comparison, branch and cache
  state to rare addressing. Its target benefit is uncertain; it was not
  added on the assumption that a cache is inherently faster.

These remain possible future investigations, rather than unvalidated
changes in this batch. Runtime commits, in implementation order:

| Pass | Commit | Change |
| --- | --- | --- |
| First | `4c8a698` | Decode repeat operands once |
| First | `483a86d` | Guarded direct-span MAC execution |
| First | `b3e9741` | Hoist invariant MAC work |
| Second | `e7c8192` | Extend spans to SARAM and review alias bounds |
| Second | `4586a54` | Reuse initial operand and cached timing state |

Each runtime stage was built and received short focused checks. The last
runtime stage passed 38 checks in 0.24 seconds with the already-built native
library. No additional test campaign was introduced for this final review.
There is no measured speedup or new physical-modem connection result from
this batch; ARM build, normal-workload performance and end-to-end call
validation remain outstanding.

## Follow-up from the rebuilt physical attempt

The completed batch was rebuilt on nanovax and called physical modem 100;
see `physical-call-inspection-20261103.json` and `physical-call-a53.md`.
Neither end connected. An interior training profile attributes 2.15% to
`try_repeat_mac`, including eligibility and eligible kernel execution.
The four MAC callers now test RPTC before calling that out-of-line helper,
so unrepeated instructions go directly to their existing general path.
The helper retains its defensive check. This changes no guest state,
repeat count, arithmetic, map handling or cycle accounting.

Validation: native notebook build and 38 short focused MAC checks pass.
This follow-up has not been rebuilt on ARM or measured and no additional
call was made. It cannot save the entire helper share: repeated eligible
work still runs there.

Inspection of the actual GCC 12 ARM binary also found that threaded
wrappers for MADD, LACC-memory and SACH call separate opcode bodies.
The source's Clang statement-level always-inline annotation does not force
GCC to integrate these bodies. This provides a concrete compiler/codegen
candidate for a later batch: selectively integrate small hot handlers,
checking code size and target cost before broader adoption. The sampled
wrapper cost includes architectural retirement and next-opcode setup;
it is not all removable function-call overhead. The previously rejected
BE/BF table-dispatch experiment remains rejected.

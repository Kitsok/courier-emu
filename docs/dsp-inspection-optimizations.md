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

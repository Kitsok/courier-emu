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

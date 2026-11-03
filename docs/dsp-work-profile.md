# Count real DSP opcode work before selecting more native blocks

The historical instruction total includes idle fast-forward clocks and
does not count each delay-slot instruction separately. It cannot measure
what fraction of interpreter work a native block removes. An optional
C5X_PROFILE_WORK build now records each executed opcode body at its PC,
including delay slots, and marks bodies replaced by native blocks.
Hardware repeated micro-operations are still one dispatched opcode.
Idle waiting and skipped clocks do not enter these counts. The counters
are work frequencies, not CPU-time shares; expensive repeated opcodes
and device/event processing still need separate interpretation.

The diagnostic table records executed/native counts, last opcode and
opcode-change count per PC. Counts survive architectural reset until
explicitly cleared. A sparse bulk API avoids a Python callback per DSP
instruction. All storage and call sites are compile-time guarded. A
normal notebook rebuild has identical .text bytes to the preceding normal
library (SHA-256 9483e61b…). No production code-cost change is inferred
for other compiler configurations solely from that notebook comparison.

Build separately with tools/build_dsp_variant.py --extra-flag=-DC5X_PROFILE_WORK.
Use tools/profile_local_training.py --dsp-work --nvram
artifacts/courier-emu-v32.nvram with that isolated library. The tool clears
counts at SIP answer, collects intervals ending at ten, twenty and thirty
additional modeled line frames, then the remaining training interval.
Actual first/end frame counts are retained; frames are 100 ms here.
Collection occurs at signaling polls and can perturb timing. A replaced
or closed core marks the result incomplete. The final sample is taken
before bridge destruction. The initial attempted run used a wrong SIP
session frame accessor; it failed as a diagnostic-tool error. The fixed
accessor uses the line adapter, and the subsequent collection completes.

The diagnostic build passes 214 focused checks in 1.52 seconds. Dedicated
checks cover idle skips, delay slots, hardware repeats, opcode changes,
reset retention and no duplicate counting of native bodies. The notebook
collection establishes 9600/ARQ/V32/LAPM/V42BIS on both ends with exact
bidirectional data. This is functional validation under instrumentation,
not a speed or reliability benchmark. Raw profiles and outcome are in
`dsp-v32-work-profile.json.gz` and `dsp-v32-work-summary.json`.

Caller windows contain about 6.75 million executed opcode bodies per
modeled second in the first three seconds after SIP answer. Roughly 13%
are already native. The five-tap helpers at 8aae and 8a7d account for a
large part of the remaining execution, while the later b950 complex loop
is not a significant native contributor yet. Prior short trace windows
therefore did not establish whole-training or initial-response weight.
The next candidate is the complete 8aae MADS helper, with its explicit
BMAR access, repeat operation, delay-line moves and return. Preserve
register/device boundaries and live memory aliases rather than replacing
firmware-level protocol decisions. No new physical call was made for
this diagnostic milestone.

# Reuse conditions within uninterrupted threaded execution

Each instruction's consume_cycles computes the current architectural
condition snapshot, stores it as the next start sample, and separately
retains XC's pipeline sample. Threaded continuation previously rebuilt
that same start sample again in step_begin. Skip only this duplicate
assignment during uninterrupted threaded continuation. Initial run entry,
individual/general steps and delay-slot execution still sample afresh.

Two handlers, taken BCND and CC, clear OV after charging their cycles.
Refresh their next-start sample after that clear while preserving the
existing XC pipeline sample. Delayed branches clear overflow before their
slots; the final slot already produces the next-start sample. Event
servicing changes interrupt/codec state, not ACC, OV, C or TC. Repeats
change addresses and PC, leaving the carried condition snapshot valid.

This changes neither guest arithmetic nor cycle counts. Seven new short
comparisons exercise threaded XC samples against individual steps,
including the two post-cycle overflow clears and final delay slots.
The notebook build and 162 focused checks pass. A broader interrupt-file
check has five IFR assertions failing with extra timer bit 8; the same
five failures reproduce with the preserved pre-arithmetic-inline library.
These are pre-existing failures, not passing coverage for this change.

A53 counters and actual training validation remain outstanding. This is
a distinct candidate from the previously rejected address-only cycle
specialization: consume_cycles and its condition calculation are intact;
only the redundant next-instruction assignment is removed. No physical
call was made for this stage.

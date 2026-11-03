# Linear spans inside enabled circular buffers

Inspection of the 9600-bps loopback trace identifies repeated MADD and
MADS sequences at 8a81 and 8ab4, alongside the existing 879d arithmetic
block. Raw bounded traces and candidate counts are retained in
`dsp-training-9600-sequences.json.gz` and its summary JSON. Both endpoints
connect at 9600/ARQ/V34/LAPM/V42BIS and exchange exact marker data.
The trace is diagnostic and covers three short windows per endpoint;
counts do not establish full-call frequencies or CPU shares.

The repeated MAC span guard previously rejected every circular buffer
selecting the active AR. UPDATE_AR only wraps when the old AR equals
its configured end. Admit the existing linear kernel when that endpoint
is outside the complete visited address interval. Include the final
tap in this check because it also updates AR. The * mode never updates
AR and needs no circular rejection. Preserve buffer-1 precedence when
both selectors name the same AR. Crossing a wrap, map boundary, register,
codec sink or tracing condition retains the general path.

The arithmetic kernel is unchanged. Live coefficient aliases, memory
counters, write counts, flags and AR0 mirrors retain existing behavior.
The notebook build and 147 focused MAC, cycle and block checks pass in
0.72 seconds. New comparisons cover both circular buffers and their
precedence, each MAC family, both directions, no update, final-tap wraps
and interior wraps, using the tracing path as the reference.

The hardware-counter tool adds five-tap MADD/MADS workloads with AR7
and CBCR ef, with the circular endpoint outside the tap span. These
isolate eligibility savings, not full training improvement. Target
counter validation remains outstanding. No new physical call was made.

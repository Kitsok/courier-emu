# Local connected-call baseline — in progress

User-selected workload: two local SIP Courier emulator instances and a 60-second bidirectional transfer. No physical modem, PBX, existing PTY, or existing NVRAM is used. The native analog403 profile establishes carrier without forcing CONNECT or acquisition assistance. All network endpoints are loopback.

## Validation

- Native build passed (build.txt).
- Three binary-socket benchmark tests passed: exact bidirectional stream verification, corruption rejection, and empty-window rejection (tests.txt). These tests do not establish modem interoperability.
- The unchanged native SIP data regression passed in 33.71 seconds (existing-regression.txt), including V.34/LAPM carrier and exact marker exchange.

## Trials

- run-01: initial harness startup; SIP/RTP connected but modem carrier failed. The 60-second data window never began.
- run-02-reference: same initial startup with all four new optimizations disabled; carrier also failed. This comparison does not isolate the failure's cause.
- run-03: startup aligned with the existing regression. Both endpoints reported CONNECT 31200/ARQ/V34/LAPM/V42BIS and exchanged markers. At an offered 2,340 bytes/s per direction, binary data verified initially (caller received 1,989 bytes, answerer 817), then stalled. Caller emitted NO CARRIER after roughly 40 seconds of the attempted transfer, which the verifier correctly rejected as unexpected payload. Peak media lateness was 14,246.1 ms caller / 8,267.6 ms answerer.

No trial completed the requested 60-second verified transfer. No connected throughput or CPU baseline is claimed, and no percentage comparison with the distinct idle/dial workloads is valid. trial-summary.json and per-trial reports preserve failures rather than omitting them.

The harness offers deterministic pseudorandom binary data, checks every received byte, accounts for worker process-tree CPU time and drains accepted data after the measurement window. Default offered load is 75% of negotiated baud divided by ten, explicitly below nominal serial bit rate; this does not model RTS/CTS flow control or prove maximum throughput. An explicit --bytes-per-second option is prepared for a user-selected lighter workload.

Pending user choice: retry at 100 bytes/s each way, or investigate the sustained-data/media-timing failure first. The connected benchmark and evidence remain uncommitted until this step is resolved. The four preceding code enhancements are already committed separately (117f04b, 53ca883, 0fcc638, d004ee2).

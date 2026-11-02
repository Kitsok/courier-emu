# Native standalone board and media migration

The target is standalone analog403 Courier with DSP and SIP on nanovax,
calling the physical modem at 100 with negotiated error correction. Physical
modem settings must remain untouched. Do not collect temperatures. Complete
the native migration before physical test calls or performance measurements;
use local model and correctness checks during implementation. Commit each
validated implementation milestone.

## Persistent line devices

`native/analog_devices.hpp` owns the DAA, exchange and DTMF receiver state and
executes their logic. `courier_emu/analog_native.py` provides live Python
interfaces for configuration and diagnostics. Adoption preserves the original
Python object's identity, so existing board/control-plane references observe
the native state. The ABI checks all three POD layouts. Exchange strings,
directory, decoder buffers and frame continuations live in the native object;
DAA storage uses a permanent buffer shared with the native implementation.
The header is tracked by the native build dependency list.

The native exchange covers every reference exchange state, hook transitions,
pulse classification, DTMF debounce and held-key behavior, routing timers,
ring cadence, outcomes and tone generation. A frame continuation preserves
the exact 80-sample subframe and callback order when control-plane routing or
a reference peer provider needs Python. The integrated native media provider
will use this continuation directly, without per-subframe PCM callbacks.
Floating-point contraction is disabled in the device implementation to retain
the reference waveform and Goertzel operation order.

Nineteen device-only comparisons pass: all DTMF keys with fragmented input,
all call outcomes with multiple dial-tone plans, incoming ring/release,
pulse scripts, randomized hook/outcome and DAA scripts, routing/peer callback
order, live state, receiver replacement, directory mutations and independent copies. These tests
make no calls and measure no throughput. The runtime is not yet switched to
these models: activation belongs with the integrated board/frame owner.

## Remaining implementation

RTP, subscriber supervision and the codec/frame pipeline are implemented as
persistent native components below. Runtime construction still needs to
adopt them before any Python media thread starts. Connect the authoritative
media fields and reset/rebuild edges to the bridge, then attach the pipeline
to the native worker with exact signalling continuations. Move remaining
eligible board/device I/O and clock state into the native board context so
the normal worker no longer republishes those devices at batch boundaries.
Keep Python SIP signalling, configuration, diagnostics and explicit reference
models. Preserve optional recording/monitor behavior when choosing runtime
eligibility or adding native sinks.

After the full path is implemented, validate native/reference behavior and
error-corrected data behavior locally, then build on A53 and perform the
physical call and performance measurements. The physical success criterion
requires both modems to establish error correction; local carrier detection
or SIP answer alone is insufficient.

## Persistent native RTP transport

`native/rtp_media.hpp` owns a duplicate of the RTP socket, packet state,
retired peers, PCM/codeword queues, G.711 conversion and the media-clock
thread. Its queues are shared directly with the forthcoming native frame
owner. It preserves transmit reserve/repriming, sequence and timestamp wrap,
preanswer discard and the reference transport's receive filtering. No silent
samples are invented to mask a stalled producer.

`courier_emu/media_native.py` supplies control-plane interfaces and a SIP
adapter that preserves the existing session's identity and signalling state
machine. RTP counters and queue views read authoritative native state. SIP
control updates can hold a native recursive lock so address retirement and
other dialog changes are atomic relative to media I/O. The native clock is
joined before its socket/object is destroyed. Python media threads are not
used by this transport.

Thirteen local transport checks pass, including all 65536 signed PCM input
values for both encoders, all 256 codewords for both decoders, headers/gain,
clock wrap, retired peers/payload filters, raw codewords, preanswer discard,
queue limits, clock reserve/underflow and final counters. Adoption and the
SIP receive adapter are checked without creating a SIP dialog or modem call.
Together with the device/build checks, 37 checks pass. The native build now
tracks the transport header and links its worker-thread dependency explicitly.
Runtime activation and the complete native frame pipeline remain pending;
no physical calls or performance measurements were made for this stage.

## Native streaming rate adaptation

`native/stream_resample.hpp` now owns kernel generation and caching, FIR
history, residual position, clock-edge history and conversion output. It
reuses the established native FIR arithmetic, including timed conversion
across codec clock changes. Kernel rounding and accumulation follow the
Python version's reference behavior. Initial equal-rate and unprogrammed
pass-through retain the reference's counter and clock-state semantics.

`courier_emu/resample_native.py` provides an explicit control-plane adapter;
frame owners can call the C++ object directly without constructing Python
kernel tables or sample lists. Nine local checks compare every coefficient
of four complete kernel tables and exact PCM/state across fragmented fixed
rates, output retunes, input-clock changes and unprogrammed pass-through.
All pass. Runtime integration remains pending; no modem calls or performance
measurements were performed for this milestone.

## Direct native exchange-to-RTP PCM

`native/line_media.hpp` attaches a persistent native PCM provider to the
exchange. Connected 80-sample subframes send directly to the native RTP
queue and consume its receive queue. Pending receive audio, underrun
counters and the bounded underrun log stay in C++. The provider preserves
short transmit blocks, partial receive blocks, pending audio across frames
and per-subframe silence padding. Routing still yields explicitly to SIP
signalling. The initial provider requires the standalone 8 kHz loop; other
loop rates are rejected rather than incorrectly relabelled.

Three device-only checks cover exact reference output, transmit queues,
pending input, underrun statistics and logs across varied block sizes,
duplicate/rate validation, and bypass of Python peer callbacks. Combined
with RTP, analog and streaming-converter checks, 44 checks pass. SIP dialog
supervision, board/codec integration and runtime activation remain pending.
No SIP dialogs, modem calls or performance measurements were performed.

## Native subscriber-loop supervision

`native/sip_port.hpp` owns the subscriber port's SIP-to-loop and loop-to-SIP
state transitions, incoming-call flag, placed/answered counts and cooperative
frame clock/lateness accounting. Its frame continuation yields explicit
control events for SIP polling, routing, ringing, answering, rejection and
hangup. After each event the same frame/subframe resumes without replaying
PCM. Signalling parsers and transactions remain on the Python control plane.
The native exchange/transport provider supplies connected audio throughout.

Eight scripted checks cover decoded-digit routing, busy and failed outcomes,
connected audio, remote release, incoming answer/local hangup, busy rejection,
cancellation, empty-number routing and cooperative clock/lateness behavior.
Reference event order, waveforms, transmit queues, exchange status and port
counters match exactly. The empty hotline retains the reference behavior:
reorder locally without creating a SIP request or incrementing placed calls.
Combined with native media/device/resampler checks, 52 checks pass.

These scripts use fake signalling objects and local UDP sockets only. There
were no SIP dialogs, firmware modem calls, physical calls or performance
measurements. Runtime adapters, codec/board integration and replacing the
remaining per-batch worker snapshots remain outstanding before final call
and measurement validation.

## Live subscriber-port interfaces and native lifetimes

`courier_emu/sip_line_native.py` adapts the standard SIP line in place before
its first frame. Port state, frame deadlines, counters, receive backlog,
underrun history and lateness history are live native views. Signalling
control events invoke the existing SIP session methods and resume the native
continuation. Explicit Python frame callers remain supported while the
forthcoming native board will invoke the same port directly. The adapter
currently accepts the normal unrecorded 8 kHz loop with native SIP media;
recorded/custom lines retain their reference implementation.

Native frame owners retain exchange and media objects independently of
Python views. Destroying a view cannot leave a port with dangling device
references, and cyclic Python line/session references remain collectible.
Final diagnostic values survive explicit close. Four additional local checks
validate identity and live status, native PCM/backlog views and final status,
continued native operation after both Python device views close, and cycle
collection. All 56 combined local checks pass. No SIP messages, modem calls
or performance measurements were performed. Runtime activation and codec /
authoritative board-worker integration are still outstanding.

## Native signalling readiness and timer checks

The native port now checks the SIP socket with a non-consuming readiness
poll and compares the next signalling deadline before yielding to Python.
When neither requires attention it services native RTP and continues the
same frame entirely in C++. The control-plane SIP session publishes state
and its earliest timer after relevant updates and after polling; this covers
INVITE retransmission/setup, inbound-answer and media-update acknowledgement,
registration refresh and cancelled-INVITE expiry. Readiness errors and media
I/O errors still hand control back for the existing signalling/error path.

Two additional checks verify an idle frame makes no Python poll, socket
readiness and expired timers yield once, and each reference timer family
publishes its correct minimum deadline. All 58 combined local checks pass.
The readiness marker is consumed by a fake signalling handler: no SIP dialog,
firmware/physical modem call or performance measurement was made. Runtime
activation and direct codec/authoritative worker integration remain pending.

## Direct native DSP codec and subscriber-frame pipeline

`native/board_media.hpp` now reads the C5x transmit array directly, converts
at the exact clock events that generated each segment, assembles complete
line frames and resumes the native subscriber port. Receive PCM is converted
and queued directly to the C5x FIFO. Line buffering, conversion history,
peaks, the receive-start cushion, in-flight receive copies, deferred input
and DAA observation stay native. Both the standalone preconverted receive
path and clocked raw-line input preserve their reference behavior.

Explicit reset and rebuild hooks reset output cursors, discard reset-era
transmit buffering where required and replay in-flight receive words to a
replacement DSP. The pipeline lends the current C5x for each service rather
than retaining a core pointer that could become stale. It retains the native
subscriber port independently of Python views. Signalling yields retain the
current frame and reject an intervening reset; resumption does not replay
codec audio. `courier_emu/board_media_native.py` supplies control/diagnostic
interfaces, pins DAA storage and preserves final scalar diagnostics on close.

Eight device-script checks compare native and Python paths using real C5x
cores running a tiny controlled program, without modem firmware. They cover
clock changes, a mixed-rate undrained batch, fallback cadence, clocked ADC,
deferred input, reset, rebuild/replay and a signalling yield midway through
a frame. PCM buffers, FIFO statistics, sample peaks, DAA status and delivered
ADC registers match. Together with native components and existing codec/rate
regressions, 77 checks pass. No SIP dialogs, modem calls or performance
measurements were made. Runtime activation, bridge views and authoritative
worker/board I/O integration remain outstanding before final validation.

## Bridge integration and reset ownership

`courier_emu/bridge_native.py` now adapts the standard standalone bridge in
place. Its scalar counters and transmit-service statistics read native board
state; PCM queue and resampler views expose native storage for diagnostics
and explicit control operations. Complete frame service and explicit
transmit/receive operations use the native pipeline. Dialed digits and DAA
state are updated by frame completion inside C++.

The bridge constructor has a staging opt-in, `COURIER_NATIVE_BOARD=1`, for the
standard standalone ROM/SIP/exchange path without recording, legacy carrier
fallback, acquisition assistance or transparent ASIC experiments. It adopts
SIP before `SipLine` starts the media clock. The default remains the reference
bridge until worker integration is complete. The staging native bridge does
not yet support a subsequently attached Python audio monitor.

Actual shared-reset edges clear native output cursors and buffered output;
core replacement replays in-flight ADC words once. The reference replay block
is bypassed when the native owner handles it. Reset keeps the last reported
transmit index separate from the current output cursor, matching reference
diagnostics. The worker cannot borrow/republish native resampler history
through its old timed-converter interface.

Six additional local checks cover real bridge construction with the analog403
image (without executing modem commands), identity and native media-clock
ownership, authoritative views, queue/final diagnostics, core replacement,
explicit codec delivery, frame-owned digits/DAA updates and the shared reset
edge. Together with native/codec regressions, 83 checks pass. No SIP dialogs,
modem calls or performance measurements were performed. Native worker service
and authoritative remaining board/device I/O integration are still pending;
the active goal is not yet achieved.

## Native worker frame integration

Scheduled mode 3 invokes the persistent native media owner directly, including
complete frames and mixed-rate transmit batches. Its pacing check reads the
live native frame clock and buffer. No PCM buffers, resampler history or media
counters are copied through the legacy worker snapshot. Worker clocks and
remaining board/device service still require further migration.

SIP events and DAA predicate changes yield before the DSP/interrupt tail.
Python completes the pending frame, advances the remaining bridge work with
zero additional clock time, then finishes the existing interrupt tail. Media
uses return codes 6/7: code 4 is reserved by the x86 engine for an interrupt
taken inside its poll. Reusing 4 originally allowed guest execution to continue
past an incomplete media service; the boot regression exposed the resulting
timer divergence. Separate codes restore exact resumption.

Five controlled worker scripts validate complete native frames, mixed-rate
batches, SIP readiness handoff, DAA qualification edges and live pacing. A
boot-only regression compares Python/native workers for 8 million guest
instructions with an injected DAA state and exchange phase change, reaching
the actual resumption path. CPU registers/memory, I/O counts, timer results,
DSP state, media state, DAA/exchange state and PCM queues match exactly.
No AT commands, SIP dialogs or modem calls are used. Runtime stays opt-in
pending the remaining board/device state and service migration.

The combined native component, worker, boot and codec checks pass: 120 passed,
with five legacy firmware workloads explicitly deselected to defer dial/call
validation until the migration is complete. No performance measurements or
physical calls were made for this milestone.

## Native silicon DAA register device

`native/silicon_daa.hpp` implements the Si3021/Si3014 register model: reset
values for both lines, PLL rate selection, power settling and readiness,
isolation-barrier access errors, sticky status clearing, hook/current and
ring/status inputs. `courier_emu/silicon_native.py` adopts the standard device
in place with permanent shared storage and live register/configuration views.
The opt-in native bridge now adopts its standard silicon device as well.
Custom device implementations keep their existing model.

Four checks compare two 2000-operation randomized register/line scripts and
both ASIC bring-up variants against the reference. Combined with the native
worker device checks and boot comparison, ten checks pass. A further boot
comparison with native bridge adoption enabled also passes. No AT commands,
SIP dialogs, modem calls or performance measurements were made. The ASIC
bring-up scheduler and its worker clock remain to be moved into C++.

## Native ASIC codec initialization and service clock

`native/codec_bringup.hpp` implements the seven-step initialization master,
including repeated readiness polling and the bounded service loop. The live
Python adapter preserves master/device identity, configuration, index, poll
count and the initialization trace. Standard native bridges now adopt the
master and retain its silicon device storage for native service lifetime.

The persistent native board owns the codec instruction clock. Scheduled
worker mode 3 advances and consumes that clock directly, after exchange work
and before the DSP step. Codec deadlines no longer force Python handoff for
this path. A media yield leaves the shared clock intact so Python can finish
any due codec service while resuming the same boundary. Reference/custom
codec paths retain their existing service boundary.

Three new master checks compare both line variants, step order, readiness
polling, nondefault configuration, repeated initialization and adoption after
partial progress. The boot regression compares complete codec status and
asserts native codec services are exercised, in addition to CPU, timer,
media and DSP equivalence through the injected DAA transition. Calls and
performance measurements remain deferred until the migration is finalized.

Validation: 58 master/device/worker/bridge checks pass; five legacy firmware
call workloads are explicitly deselected. No modem calls or performance
measurements were performed for this milestone.

## Shared native DSP scheduling context

The persistent native board now owns the bridge instruction count, exchange
service remainder, accumulated DSP ticks, probe-clock marker, DSP cycle debt,
cycle estimate and CPU-to-DSP ratio. Native bridge attributes are live views
of those fields. Worker mode 3 operates on the same storage and no longer
seeds or takes back these fields through its legacy snapshot; comparison
modes keep their existing snapshots. DSP execution updates the shared debt
and cycle estimate directly, including service continuation after a media
yield. Machine interrupt and console scheduling fields still use the existing
boundary and remain a separate integration task.

A worker script seeds deliberately wrong legacy clock/debt values and proves
native service ignores them. The boot regression compares the entire shared
board state as well as CPU, interrupt, DSP, codec and media results through a
DAA transition. All 43 selected worker/bridge/boot checks pass, with five
legacy call workloads deselected. No modem calls or performance measurements
were performed. A compiler error from a shadowed cycle-estimate local was
corrected before these checks passed.

## Shared machine service phases

`courier_emu/service_native.py` supplies permanent machine service storage and
live views for console polling, timer polling, the last frame/tick positions
and tick count. Standard machines with a native board adopt these views at
run entry while preserving object identity. The native worker reads and
updates the same fields; arming and take-back no longer copy these phases.
Comparison/custom machine paths retain the legacy snapshot when no shared
service model is attached.

The boot comparison now checks the full shared machine service buffer as
well as existing CPU, interrupt, DSP, codec and media evidence. A separate
script supplies deliberately stale legacy phase fields and verifies they
cannot affect native service. All 38 selected worker/boot checks pass; five
call workloads remain deselected. No modem calls or performance measurements
were made. Pending interrupt requests, the in-service stack and remaining
CPU/device I/O transitions are still migration work.

## Shared interrupt requests and in-service state (step 1)

The machine service buffer now also owns pending INT0/INT1/timer vectors,
timer delivery count, INT0 in-service state and the interrupt stack. Python
uses live scalar and list-compatible views; native entry and EOI processing
operate on the same storage. Arming, diagnostic resumption and take-back no
longer republish the shared interrupt data. The legacy worker snapshot stays
available for comparison paths without shared machine storage.

The stack retains the worker's 64-entry native limit. Python overflow entries
remain representable and preserve the existing fallback above that limit;
returning below it exposes the complete native prefix again. A targeted
script verifies native request priority and EOI while stale legacy vectors
remain untouched. Another checks overflow, removal and slice/list behavior.
The boot regression compares the entire expanded shared machine buffer.
All 40 selected worker/boot checks pass; five call workloads are deferred.
No modem calls or performance measurements were made. User-requested steps
2–4 (remaining device I/O, runtime finalization, then complete local validation)
remain outstanding.

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

Move RTP socket handling, media clocks and PCM queues into persistent C++
objects. Connect them directly to native exchange frame rendering, receive
conversion and the DSP's codec FIFO. Move the remaining codec/device service
and eligible CPU I/O transitions into the native board context so the normal
worker no longer republishes those devices at batch boundaries. Keep Python
SIP signalling, configuration, diagnostics and explicit reference models.

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

# Physical modem call from Cortex-A53

Success means courier-emu running on nanovax reports firmware-generated
`CONNECT` after negotiating with the physical Courier at extension 100.
Both endpoints must establish error correction (LAPM or MNP/ARQ). SIP answer,
local carrier detection, and uncorrected connections do not satisfy this
criterion. Error correction is also required in normal operation.

## Existing-settings baseline (2026-11-02)

The user updated and built `/home/kostik/work/courier-emu` at `6aeddab`.
The checkout is clean and the native configuration/build check passes.
The two parallel test services remain inactive. The unrelated VAX process
continues to use about 19% of a core; Asterisk remains running.

A temporary configuration retained the normal SIP server/target, extension
201 registration, PCMU, ports 5074/4014, transmit gain 0.25 and no synthetic
local echo. Speaker playback was disabled. The existing EEPROM was copied
to the capture directory; the original settings were never changed. Its
firmware ATI4 includes `&N6`, S34=129, S56=192 and S58=97, differing from the
current LAPM fixture. Both have S27=0 and S54=96.

An initial attempt returned NO CARRIER before placing a SIP call, with only
one digit decoded. The subsequent profiled attempt decoded 100, registered,
received SIP 180/200 and exchanged RTP with the ATA at 192.168.196.29.
The remote endpoint eventually sent BYE. No firmware CONNECT was observed
before the bounded 240-second capture ended; stopping the runtime returned
exit status zero. That status describes orderly shutdown, not call success.

The final diagnostic reports 547 line frames, or 54.7 seconds of modeled
line audio, in approximately 240 seconds of wall time. This whole-attempt
ratio (23% of real time) includes boot and setup, not just training. Peak
media lateness reached 182.832 seconds, with no pacing sleeps. The worker
averaged 102% CPU across proc samples, with temperature 82.3–86.5°C and
sampled frequency 600–1296 MHz. These data establish a severe throughput
shortfall under the tested conditions, not a precise fixed-clock deficit.

The receiver accumulated a peak of 398080 pending audio samples. It
received 3113 RTP packets and sent 630. There were no reported receive
underruns: backlog and delay, rather than a shortage of received audio,
are the visible problem. The board retired 188411903 x86 and 1876381235
DSP instructions by shutdown. CPU/DSP work must be measured in training;
previous idle/dialing benchmark gains do not establish real-time capacity.

A 49 Hz `cycles:u` profile of the actual worker, covering boot, dialing and
early training, captured 5093 samples with none lost. Flat DSO shares were
51.07% Python, 28.93% DSP library, 13.95% x86 library, 2.68% ctypes and 2.55%
libc. `_PyEval_EvalFrameDefault` accounts for 22.88%, x86 `run_batch` 11.23%,
and native timed resampling 1.20%. DSO shares cannot identify individual
Python functions and are not yet a prescription for a specific rewrite.

[Machine-readable baseline](physical-call-a53-results.json) preserves the
terminal output, peripheral diagnostics, profile totals and worker CPU,
temperature and frequency samples. Full temporary captures remain on
nanovax in `/tmp/courier-physical-a53-existing-3`; the initial failed attempt
is `/tmp/courier-physical-a53-20261102`. The initial attempt accidentally
profiled the console launcher rather than its execution child; that profile
is excluded from CPU conclusions. The corrected attempt profiles the child.

Next checks: compare the validated LAPM fixture without overwriting saved
settings, then obtain a Python function profile during actual SIP training.
A successful call has not yet been established on this A53 host.

## Fixture comparison and training function profile

The current LAPM fixture also decoded 100, received SIP answer and exchanged
RTP, but never reported firmware CONNECT. The remote peer sent BYE. The
runtime was then stopped manually, with 389 frames (38.9 seconds of modeled
audio), peak lag 151.687 seconds and 405920 pending receive samples. The
probe's generic `timeout` label does not describe a firmware result; no
NO CARRIER line was observed before shutdown. This comparison removes the
saved `&N6` restriction but does not resolve the throughput deficit.

A separate fixture call enabled cProfile by signal only after SIP answer,
recorded 19.871 seconds, then stopped deliberately. A temporary
`sitecustomize.py` wrapped the worker's run and installed start/stop signals;
no tracked remote source was modified. Instrumented timings locate work,
not unprofiled CPU shares. The profile contains 1060795 calls, including
4258 native x86 batches, 1381 Python-issued DSP steps, 2600 worker arming
calls, 2543 Python service callbacks and 28 complete line frames. Native
x86 calls take 4.923 seconds (including DSP work inside native polls), and
Python-issued native DSP stepping takes 3.566 seconds. Arming takes 0.926
seconds of self time. Line-audio extraction, buffer conversion and Python
clock/service bookkeeping are also substantial costs.

RTP polling takes 1.425 seconds cumulatively. Its receive generator invokes
scalar μ-law decoding 159200 times: 0.711 seconds in the decoder plus 0.452
seconds in the generator. Audio arrives at wall-clock speed even while the
emulator falls behind, so this cost grows with the accumulated backlog.
The fixture and function-profile summaries are retained in the
[machine-readable record](physical-call-a53-results.json). Full temporary
captures are `/tmp/courier-physical-a53-fixture-1` and
`/tmp/courier-physical-a53-profile-1` on nanovax.

## G.711 receive lookup

RTP reception now maps each octet through an immutable 256-entry table for
its negotiated law. C-level `map` iteration replaces the Python generator
and scalar decoder calls; the scalar functions remain the reference.
Codeword transport still preserves the original octets. No native source
or ABI changed, so the candidate reuses the user's existing native build.

`tools/benchmark_sip_receive.py` sends 10000 local 160-sample RTP packets per
repetition, four repetitions for each codec, and records process CPU time,
packet/sample counts and an audio hash. An isolated older package at
`60a6f2a` is compared with the candidate; no PBX is contacted. The measured
loop includes sockets, polling, deque operations and sample accumulation.

| Host/law | Before median CPU | After median CPU | Reduction |
| --- | ---: | ---: | ---: |
| Notebook PCMU | 0.804 s | 0.393 s | 51.2% |
| Notebook PCMA | 0.799 s | 0.412 s | 48.5% |
| A53 PCMU | 7.165 s | 3.316 s | 53.7% |
| A53 PCMA | 7.254 s | 3.286 s | 54.7% |

All packet counts, sample counts and hashes match. These sequential
before/after receive microbenchmarks do not establish full-call gains or
constant-clock A53 timing. [Raw results](rtp-receive-results.json) retain
every repetition. The focused SIP suite passes 31 tests, including complete
256-codeword domains in forward/reverse order for both laws and unmodified
CLEARMODE octets through actual UDP reception. The first sandboxed test
invocation could not create sockets; the loopback-enabled run passes.

The next control uses the existing paired-probe Bell 103 preset's
`S54=192B1&M0&B0&N1` through the firmware AT interface, on a temporary fixture.
Its purpose is to measure a simpler modulation's real-time demand. No carrier
is forced and the physical modem's configuration is not modified.

## Bell 103 control: local CONNECT is insufficient

The receive-optimized candidate in `/tmp/courier-call-candidate` ran the
Bell 103 preset against physical modem 100. Firmware acknowledged the AT
settings and ATI4 confirmed B1, &M0, &B0, &N1 and S54=192. It reported plain
`CONNECT` 100.505 seconds after process launch, about 66.5 seconds after the
dial command. The probe held the call for 12 more wall-clock seconds, then
stopped gracefully, sending SIP BYE. The final report has `online_mode=true`,
no forced connected event, no legacy carrier fallback, and zero data bytes.

This is **not a confirmed end-to-end modem connection**. The physical
modem's mgetty log records ATA at 19:01:04 local time and NO CARRIER at
19:02:06. The emulator report was written at 19:01:55, after the probe's
hangup. Physical ATI6 says `No Connection`, with last-call time zero; ATI11
reports unknown modulation and zero carrier frequencies/symbol rates.
Reading these existing logs did not require stopping mgetty or touching the
physical serial device. The caller's firmware can detect an answering
carrier without the physical answering modem acquiring the caller.

The candidate was still far below real time: 188 line frames, peak media
lag 90.016 seconds and 312640 pending receive samples. Incoming RTP counted
2444 packets against only 490 transmitted. The probe's `connect` label
means its local terminal criterion passed, not that the physical modem
connected; the machine-readable record retains this explicit verdict.
Full evidence is `/tmp/courier-physical-a53-bell103-1` on nanovax and
`/var/log/mgetty/{mg_ttyUSB0,statistics.ttyUSB0}.log` for the physical side.

The success criterion therefore remains unmet. Further work must reduce
training/media production cost, and future attempts must check the physical
side as well as the emulator's CONNECT line.

## Native terminal and catch-up pacing checks

An additional 20-second training probe counted every return from
`fast_clock_static`: all 2952 checks were eligible. The exchange/DSP static
gates were therefore not the source of the frequent Python handbacks in
that interval. The terminal polling deadline (8192 guest instructions) and
SIP pacing check (approximately 2 ms of modeled board time) forced Python
service even with no terminal input and a media timeline far behind wall time.

The scheduled native exchange worker now tests the plain SerialConsole FD
with nonblocking `poll`. It consumes no bytes and handles no output. Input,
EOF, HUP, invalid descriptors and other errors hand the service to Python;
only an empty poll advances the existing console debt/period. Pending
terminal output, lamp delivery and subclasses such as SerialSim retain the
Python boundary because their polls can have additional side effects.

For SIP pacing, a native check uses CLOCK_MONOTONIC and the same
`frame origin + buffered line samples / line rate` interpolation. A positive
lead yields before committing service, preserving the Python wait. A late
check advances only the pacing-check deadline, with no sleeping or skipped
guest work. Full media frames still return to Python. This is enabled only
when Python's actual clock implementation matches CLOCK_MONOTONIC.
`COURIER_NATIVE_IDLE_CHECKS=0` restores both previous boundaries.

The focused timer/read, worker, console/pacing, native interpreter and build
run passes 91 tests. An additional invalid-FD case passes with the existing
input/EOF and pacing checks. A 40M-instruction firmware comparison uses real
bidirectional console FDs, a local SIP sink, a deliberately past media
origin and a post-boot scheduled dial. CPU registers, full memory, timer
state, interrupt totals, DSP, serial/codec, exchange and line-service state
match, with native no-work counters explicitly exercised. Scheduled script
input is not firmware echo output, so the test verifies decoded digits 100
rather than expecting the command in the firmware result transcript.

The controlled CPU measurement uses this same workload and fixed 40M guest
instruction budget, including boot and dialing. No external subscriber is
contacted. One notebook run warms caches, followed by off/on/on/off runs;
mean process CPU falls from 8.483 to 6.819 seconds (19.6%). Each candidate
run performs 3826 native empty-console polls and 4486 native pacing checks.
The switches compare the paths in the same compiled candidate; this isolates
the scheduling change, not compiler-layout effects against an older library.

The native CAPI was forcibly rebuilt in `/tmp/courier-call-candidate` on
A53; the unchanged x86 module was copied from the user's build. Configuration
and ABI checks pass. `/proc/<worker>/maps` confirms both loaded modules come
from that isolated candidate. The user's checkout and native build are
unchanged.

A subsequent physical call used firmware `AT&M5`, and ATI4 confirmed &M5
before ATDT100. SIP answered, but the peer hung up without a modem
connection. The runtime was then stopped: 349 line frames in a 137.55-second
capture, peak lag 96.053 seconds, 3131 received and 900 transmitted RTP
packets. The native scheduler performed 13260 empty terminal checks and
15591 catch-up pacing checks. This remains a failed ARQ-only call; rates
from this attempt should not be directly compared with the earlier &M4
attempts as if the firmware settings were identical.

The A53 off/on run takes 67.700/51.076 CPU seconds; a separate reverse-order
on/off run takes 50.476/61.460 seconds. Their means are 64.580 versus 50.776
seconds, a 21.4% reduction. The two processes balance which implementation
pays cold setup, but temperature/governor variation still limits timing
precision. All four records match memory, CPU, timers, DSP, serial and
exchange state exactly. The same 3826/4486 native check counts occur on both
hosts. [All scheduler measurement records](native-idle-check-results.json)
include the discarded notebook warmup and both A53 orders.

`tools/benchmark_native_idle.py --warmup` reproduces the notebook workload;
`--order 0,1` and `--order 1,0` reproduce the two ARM orders. The retained
measurements used the older &M4 fixture; subsequent runs with the new &M5
profile should identify that settings change rather than merging results.
The benchmark remains an idle/dialing measurement, not a connected call.


## Required error correction and saved settings

Normal operation now requires ARQ (&M5), rather than &M4's optional error
correction. The new LAPM fixture matches original firmware after AT&M5&W:
byte 0x05 changes from 4 to 5, and checksum 0xad becomes 0xae. Runtime
migration validates the existing checksum, writes a unique exact backup,
and atomically replaces only the mode byte and checksum. It preserves
other settings, file ownership/permissions and configured symlinks. Existing
ARQ-only files are unchanged. Invalid files or failed backups are never
silently repaired or replaced. A configuration check reports pending
migration without writing files.

The configured notebook and nanovax EEPROMs were both migrated with backups,
as requested. Both changed only byte 0x05 (4 to 5) and byte 0x1ff (0x15 to
0x16). Their prior fixed-speed and other custom settings remain intact.
The nanovax backup is
`/home/kostik/work/courier-emu/artifacts/courier-emu-v32.nvram.pre-arq-zlynmowl.bak`;
the notebook backup is
`artifacts/courier-emu-v32.nvram.pre-arq-0twu3wk5.bak`. Backups remain local
and are excluded from Git. The configured EEPROM itself is already tracked,
so its two-byte migration is included in the policy commit.

The runtime/migration suite passes 25 tests, including idempotence, exact
backup retention, customized settings, symlinks, metadata, invalid checksums,
backup failure and replacement failure. A stale path assertion was corrected
to match the existing configured `courier-emu-v32.nvram` filename. The full
native SIP data regression with the new ARQ-only defaults passes: original
firmware at both ends negotiates LAPM/V.42bis and transfers exact marker
lines in both directions. This notebook regression is not a successful
physical A53 call.

The physical modem's saved settings were not changed. An attempted settings
inspection sent only AT, ATZ and ATI4; ATI4 did not complete, so no mode or
save command was issued. Mgetty restarted and acknowledged its normal ATZ
and AT&D2 initialization. The command log is retained at
`nanovax:/tmp/courier-physical-arq-policy-20261102/commands.json`.
Subsequent user instruction prohibits physical-modem settings changes;
all further work is confined to the emulator and calls through the existing
physical configuration. Temperature sampling on nanovax is also disabled
as requested.

## Rebuilt checkout and physical call, 2026-11-03

The user rebuilt the clean nanovax checkout at `e22ed4d`, including the
latest diagnostic buffering and conservative pacing default. Both parallel
emulator test services were inactive; the existing `mgetty.service` was
running. No emulator was already running. The old temporary probe had been
removed; the same bounded probe was restored under `/tmp` with an optional
read-only yield capture wrapper. It used a copy of the configured EEPROM,
confirmed &M5/&N6, S27=0 and S54=96, then dialed physical modem 100 with
experimental native waiting explicitly disabled.

SIP registration and INVITE succeeded, with 200/ACK and an RTP re-INVITE.
The physical modem logged RING and ATA at 09:26:31, then NO CARRIER/A_FAIL
at 09:27:33. The emulator reported BUSY after peer hangup. This was a failed
modem connection. Host/network unavailability did not cause this attempt's
failure. Earlier local pacing validation failures also involved only two
notebook loopback peers; nanovax availability cannot explain those.

The run lasted 123.05 seconds and delivered 302 100-ms line frames, or 30.2
seconds of modeled audio (24.5% of real time over the whole attempt,
including boot/setup). Worker CPU averaged 101.4% of one core. Peak media
lag reached 79.96 seconds, with a pending receive peak of 343840 samples.
The previous attempt's 280 frames in 119.84 seconds is not a controlled
comparison and establishes no significant whole-call speedup.

There were zero pacing waits and zero paced seconds. Enabling the native
wait experiment would therefore not exercise its changed path here; no
second physical call was made. Native yield attribution recorded 4750
unarmed snapshots, 1318 DSP transitions, 538 deadlines, 10 media edges and
one other service boundary. Rearming was attempted 6889 times, including
1303 declines. These are whole-attempt counts, not training-only counts.

The worker's user-cycle profile lost no samples. Flat shares were 46.48%
native C5x/devices, 31.25% Python and 18.70% native x86. The largest symbols
were traced x86 `run_batch` (15.25%) and Python evaluation (13.60%). Sample
shares are not CPU-time savings. They support investigating unarmed
snapshot boundaries and the actual DSP training workload rather than
positive-lead pacing for this saturated host.

No direct commands were sent to the physical modem by the probe. Its
existing mgetty answer/reinitialization routines ran unchanged. Saved
emulator configuration and physical configuration were not edited; no
temperatures were read. All probe/emulator processes stopped afterward.
Structured evidence is in `docs/physical-call-rebuilt-20261103.json`.
Full remote capture: `/tmp/courier-physical-rebuilt-20261103-092544`.
The error-corrected physical connection goal remains unmet.

## Training-only attribution and subsequent kernel work

A later slice of this same capture, correlated with the retained failure
journal's realtime/monotonic clock anchor, changes the optimization
priority. Safely inside modem training, C5x/device code accounts for 66.83%
of sampled user cycles, native x86 for 22.84%, and Python for 8.52%.
Two overlapping interior windows support that result. Whole-attempt Python
and yield totals include boot/setup and should not determine training
priorities. See `docs/a53-training-hotspots.md`.

Cached on-chip region checks in DSP delay-line operations are validated:
selected A53 MAC kernels improve roughly 9–13%, with exact state/counters,
69 focused checks, fixed-work boot equality and local LAPM/data transfer.
This is a kernel result, not a measured full-call gain. A separate x86
checkpoint-elision candidate is rejected because A53 memory/traced controls
regress by roughly 6–8%. Its runtime changes are removed. Details are in
`docs/dsp-delay-move-optimization.md` and `docs/x86-checkpoint-experiment.md`.
No additional physical call or nanovax deployment occurred in that work.

## Inspection optimizations rebuilt and called, 2026-11-03

Nanovax's clean `e22ed4d` checkout was merged with the committed notebook
work, preserving both histories as `86ba8ff`. The notebook was then
fast-forwarded to that same merge. `./build.sh` completed on nanovax and
loaded both native libraries. The C5x library SHA-256 is recorded in
`docs/physical-call-inspection-20261103.json`. No parallel emulator was
running; the two test services were inactive and normal mgetty was active.

One bounded call used the same probe and a temporary copy of the configured
EEPROM: &M5/&N6, S27=0 and S54=96. Experimental native pacing remained
disabled. SIP registered, negotiated 200/ACK and RTP, and physical mgetty
logged RING/ATA at 11:24:42. Physical training failed with NO CARRIER/A_FAIL
at 11:25:44. SIP BYE followed; the emulator eventually returned NO CARRIER
at approximately 177 seconds. Shutdown completed at 180.09 seconds. There
was no CONNECT or error-corrected connection.

The worker averaged 101.33% of one core. It processed 660 100-ms line frames
(66 seconds modeled audio), with peak lag 109.06 seconds and a pending
receive peak of 291040 samples. There were no pacing waits. The earlier
attempt processed 302 frames before returning BUSY at 123.05 seconds, so
whole-attempt frame rates compare different execution endpoints. No
controlled CPU reduction is established by those totals.

The SIP transport received the same 500640 PCMU octets in both attempts
(62.58 seconds). It transmitted 211200 octets this time (26.4 seconds),
versus 156800 previously (19.6 seconds). This is more delivered audio
during the physical session, still substantially below real time. It is
not proof of successful demodulation or ARQ negotiation.

A journal clock anchor places the interior training interval at monotonic
11345–11395, after ATA and before NO CARRIER. Period-weighted user-cycle
shares, with zero lost samples, are:

| Code | Earlier training slice | Updated training slice |
| --- | ---: | ---: |
| Native C5x/devices | 66.83% | 59.37% |
| Native x86 | 22.84% | 29.87% |
| Python | 8.52% | 8.84% |

The changed mix is consistent with reduced DSP overhead, but the slices
are not fixed-work replays and cannot quantify a speedup. The new
`try_repeat_mac` helper accounts for 2.15% of training samples, including
both eligibility checks and eligible kernels. Code inspection identifies
an avoidable call for unrepeated MACs: the repeat check currently lives
inside that out-of-line helper. Moving an eligibility check to the caller
is a narrow next candidate; its possible saving is only part of 2.15%.
Resampling accounts for 2.58%, and x86 `run_batch<true>` alone for 24.13%.
The broad native execution deficit remains the principal blocker.

Configured EEPROM and INI hashes match before and after. No physical
settings commands or temperature queries were issued. Existing mgetty
answer/reinitialization ran normally, and probe/emulator/perf processes
stopped. Native yield counters were not enabled, so their empty snapshot
is not interpreted as zero yields. Full evidence remains at
`nanovax:/tmp/courier-physical-inspection-20261103-1125`. The goal remains
unmet.

## Authorized lower-rate attempt after follow-up build

The user authorized lower rates using temporary emulator settings only.
After rebuilding both follow-up optimizations at `e204d19`, a short native
ARM comparison validated selective load/store inlining (see
`dsp-hot-inline-arm-results.json`). The saved emulator INI and EEPROM
were retained. The next probe copied the EEPROM and issued `AT&N3&M5`,
then confirmed &N3/&M5, S27=0 and S54=96 before dialing 100. The bundled
USR manual maps &N3 to 2400 bps. Error correction stayed mandatory.

SIP reached 200/ACK. Physical mgetty logged RING/ATA at 11:39:24 and
NO CARRIER/A_FAIL at 11:39:34. The emulator returned BUSY at approximately
72.9 seconds; shutdown finished at 74.00 seconds. No carrier connection
or ARQ negotiation succeeded. This physical training interval was much
shorter than the 9600-bps attempt; the cause of the earlier loss of
carrier is unproven.

Worker CPU averaged 101.60% of one core. The run processed 144 line frames
(14.4 modeled seconds), with peak lag 46.42 seconds and pending receive
peak 56240 samples. PCMU delivery was 30400 octets sent (3.8 seconds audio)
and 85840 received (10.73 seconds). There were zero pacing waits. The
lower requested bitrate did not eliminate the real-time deficit.

A strictly interior six-second interval at monotonic 12223–12229 contains
295 user-cycle samples, with none lost: 57.61% C5x/devices, 28.45% native
x86 and 11.52% Python. This short profile has limited precision and is
not a controlled comparison with the earlier, longer 9600-bps attempt.

Review of existing provisioning does not show S54=96 disabling V.22bis.
The retained S54 bits are documented as the V.34 3429-symbol workaround
and disabled optional V.8 call-indicate tone. Physical saved lower-rate
capabilities remain unverified: no direct commands or settings changes
were made to that modem. The early failure must not be attributed to a
specific physical setting without evidence. Further protocol diagnosis
needs correlated transmitted/received training audio, alongside the CPU
work; another bitrate-only trial would not distinguish these causes.

Original INI and EEPROM hashes still match; normal mgetty remains active
and probe/emulator/perf processes stopped. No temperatures were queried.
Structured results are in `physical-call-2400-20261103.json`; full capture
is `nanovax:/tmp/courier-physical-2400-20261103`. The requested established
connection remains unachieved.

## Lower-rate diagnostic audio capture

A further bounded 2400-bps/&M5 call on the unchanged updated build recorded
native modem-facing TX/RX WAVs and packets filtered to RTP port 4014. The
emulator returned BUSY at about 67 seconds. No connection was established.
Capture and probe processes finished; the remaining capture was explicitly
stopped after the call. Physical settings were not changed.

Both 8-kHz recordings contain 4.1 seconds. TX is exactly silent through
the first 3.1 seconds at 100-ms resolution, then has RMS around 12000.
RX rises from background RMS around 20 to answer-signal RMS around 3200
at approximately 1.6 seconds. These are recording offsets, not wall times
or protocol classifications. Packet timestamps span 10.02 seconds outbound
and 10.36 seconds inbound. Packet counts cannot be used directly because
the any-interface capture contains bridge/loopback duplicates.

This confirms delayed delivery and late onset of the emulator response.
It does not establish whether that response implements the correct
handshake. The next analysis must deduplicate RTP by stream/sequence and
map decoded waveform onset onto wall timestamps before attributing a
specific protocol failure. Evidence: nanovax `/tmp/courier-2400-diagnostic.pcap`,
`/tmp/courier-2400-diagnostic-audio-{tx,rx}.wav`, and
`/tmp/courier-physical-2400-diagnostic-20261103`. A credential-free copy is
retained on the notebook under `/tmp/courier-2400-diag`.

## Deduplicated diagnostic RTP timing

The captured PCMU streams were grouped by direction/SSRC and deduplicated
by RTP sequence/timestamp, retaining the first capture time. There are
518 packets in the physical stream (10.36 seconds), one initial packet
from the previous PBX stream, and 200 emulator packets (4 seconds).
Incoming physical packets have maximum interarrival gap 20.87 ms;
outgoing emulator packets have a maximum gap of 446.96 ms. Kernel capture
drops were zero. The transport report independently counts 200 sent and
519 received packets, agreeing with deduplication.

At packet RMS >500, physical signal onset is 11:45:35.691795 and emulator
signal onset is 11:45:41.887524 local time. A 200-ms receive window has a
strong 2100-Hz component on a 25-Hz frequency grid. The emulator response
therefore starts 6.196 seconds after physical answer-signal onset, only
2.485 seconds before incoming RTP ends. The transmitted modulation has
not been classified, so no handshake-content correctness claim is made.

This separates steady network input from irregular, delayed emulator
output. Further work should target training execution throughput rather
than add buffering or repeat bitrate-only calls. This does not exclude
additional protocol defects. Raw timing and capture hash are retained in
`physical-2400-rtp-correlation.json`. No new call was needed for this
analysis.

## Physical call with refined native block

The isolated refined A53 library was selected explicitly with the block
opt-in enabled. The temporary emulator EEPROM retained &M5/&N6 (mandatory
ARQ, 9600 bps). Existing configuration and EEPROM hashes were unchanged
afterward. No physical modem settings were changed.

The attempt failed: the physical modem reported NO CARRIER after about
62 seconds; the emulator returned BUSY during a 123.32-second probe.
The worker averaged 101.35% CPU. It sent 19.6 seconds of RTP audio while
receiving 62.58 seconds, and recorded 299 SIP frames with peak lateness
80.24 seconds. Pacing waits were zero. Real-time throughput remains
insufficient; no whole-call improvement is demonstrated by this attempt.

The connected-window hit counter rose monotonically from 536734 to
2070597 across 62 samples: 1533863 additional block executions, with
CBCR ef throughout. This establishes use during physical training.
It does not establish that the block dominates training cost.

A 48-second interior training profile attributes 65.42% of sampled user
cycles to DSP, 22.96% to x86 and 9.34% to Python, with zero lost samples.
The largest individual symbol is x86 run_batch<true> at 17.32%; DSP cost
is spread across handlers and dispatch. Full evidence and limitations
are in `physical-call-native-block-20261103.json`. Capture/probe processes
finished, and normal mgetty autoanswer remained active.

Next, match the notebook workload to this temporary 9600-bps ARQ profile
before selecting broader native blocks. The current successful notebook
loopback negotiates 31200 bps and need not exercise identical hot paths.

## Combined circular-span and condition-reuse attempt

The batch at 04ec08e was rebuilt into isolated library a28c9896… and
selected explicitly with the arithmetic-block opt-in. One call used the
same temporary copy of the emulator EEPROM, retaining mandatory ARQ and
9600 bps. INI and saved EEPROM hashes are unchanged afterward. No direct
physical modem commands were sent; normal mgetty handling remained active.

The physical modem answered at 14:04:35 and reported NO CARRIER/A_FAIL at
14:05:38. The emulator returned BUSY; the probe finished after 123.97
seconds. CPU averaged 101.22%, with 304 line frames, 19.8 seconds of
PCMU sent and 62.61 seconds received. Peak lateness reached 89.06 seconds.
There were no pacing waits or kernel packet-capture drops. The native
arithmetic block recorded 1563506 additional connected-window hits without
a reset. These data do not demonstrate a whole-call speedup or connection.

An interior 48-second profile attributes 66.76% of sampled user cycles to
DSP, 20.90% to x86 and 10.17% to Python, with no lost samples. Isolated
kernel gains remain distinct from the unresolved application throughput.
Structured evidence is in `physical-call-circular-condition-20261103.json`.

The saved emulator profile includes S34=129, S54=96, S56=192 and S58=97.
The earlier notebook --rate-index 6 fixture negotiated V.34 and matched
only fixed rate and ARQ, not these complete protocol restrictions. A
notebook-only check using a copy of the exact saved EEPROM also returns
NO CARRIER at both ends. This requires local profile/protocol diagnosis
in addition to A53 optimization. It does not yet identify a specific
register or establish whether the latest code caused the local failure;
a preserved-library control is the next check. Physical settings remain
outside the scope of these temporary emulator experiments.

The subsequent exact-profile notebook controls negotiate V.32 ARQ/LAPM.
The preserved older library loses part of one data marker and carrier;
the current build succeeds with exact bidirectional data both with the
block disabled and in one enabled repeat. Thus the first local failure
is intermittent and does not establish an optimization regression or
an intrinsically unusable saved profile. Preserve the complete profile
for future attribution; details are in `dsp-exact-profile-notebook.md`.

## Final native V.32 block batch call

The corrected native-entry build at 14033ef ran one physical attempt
using isolated library 66b5df81… and the unchanged temporary emulator
EEPROM profile. The native opt-in was enabled. The extra Python hit hook
was omitted; media/packet recording and 49-Hz perf sampling remained.
The normal library and saved configuration/EEPROM hashes are unchanged.

SIP registration and INVITE both received 200 responses. The physical
modem answered at 15:00:52 and reported NO CARRIER/A_FAIL at 15:01:03.
The emulator returned BUSY at about 67.6 seconds; the probe ended after
68.81 seconds. No error-corrected modem connection was established.
Worker CPU averaged 101.86% of one core. It sent 4.0 seconds of PCMU and received 10.48 seconds, with 145 line
frames and peak lateness 41.63 seconds. Pacing waits were zero. This is
a much shorter physical interval than the preceding 63-second attempt;
its totals cannot establish a throughput improvement or regression.

The six-second interior interval at monotonic 24311–24317 has 297 user
cycle samples, none lost: DSP/devices 53.58%, x86 26.18%, Python 14.53%.
The short interval and changed handshake stage limit precision and
comparison with older 48-second profiles. Physical native-body counts
were not collected without the Python hook. Kernel gains remain separate
from the unresolved initial-handshake throughput.

Deduplicated PCMU media contains 523 physical packets (10.46 seconds),
one initial PBX packet, and 200 outgoing packets (4.0 seconds). Physical
input has maximum packet gap 22.00 ms; output reaches 443.61 ms. With
decoded packet RMS >500, output activity starts 6.360 seconds after
physical input activity, leaving only 2.422 seconds before physical
input ends. This repeats the delayed-response pattern already observed
in the earlier diagnostic attempt. No outgoing modulation correctness
claim is made. A shorter timeout must not be attributed to a specific
physical setting or native arithmetic defect without further evidence.

Full results and timing method are in `physical-call-v32-native-20261103.json`.
All test/capture processes finished and normal mgetty remained active.
No direct physical modem commands or temperature queries were made.
The next optimization selection should cover the initial response phase
and quantify real interpreter work; short local trace windows and
accounted instruction totals alone can be misleading. IDLE fast-forward
also increments the historical instruction counter for skipped clocks,
so native-hit fractions of that total are not CPU-work fractions.

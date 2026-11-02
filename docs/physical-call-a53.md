# Physical modem call from Cortex-A53

Success means courier-emu running on nanovax reports firmware-generated
`CONNECT` after negotiating with the physical Courier at extension 100.
SIP answer alone does not satisfy this criterion.

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

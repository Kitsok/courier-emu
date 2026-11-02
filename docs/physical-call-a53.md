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

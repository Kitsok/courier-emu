# Analog Courier SIP validation

Observed on 2026-10-29 with analog403, native 80186/C5x execution, UDP SIP,
and PCMU. These are results from the tested calls, not guarantees for other
networks, firmware, or sustained transfers.

## Endpoints and provisioning

The notebook used `192.168.196.33`, SIP port 5074, and RTP port 4014. It called
extension 100 at the Cisco ATA `192.168.196.29:5060`. The physical Courier's
serial port was `nanovax:/dev/ttyUSB0`. The emulated board used supervisor
7.4.16 and DSP 3.1.2, without forced CONNECT or acquisition assistance.

The first call with the captured EEPROM's S27=48 reached SIP 200 and exchanged
RTP but ended with NO CARRIER at both modems. Calls with S27=0 established
V.34/LAPM/V.42bis. A successful normal-mgetty call changed only S27, keeping
the original timeout and three-ring answering.

Running `ATS27=0&W` in the original firmware changes exactly byte 0x29 from
0x30 to 0x00 and its checksum at 0x1ff from 0xbd to 0x8d. The
`idsdl403-lapm` fixture matches those firmware-written bytes exactly. It
preserves the remaining provisioning and is used only to create new settings;
existing EEPROM files are never replaced. The raw `idsdl403` fixture remains
available for historical diagnostic runs.

## Physical data tests

Both serial interfaces reported:

```text
CONNECT 26400/ARQ/V34/LAPM/V42BIS
```

For a controlled call, mgetty was stopped temporarily and the physical modem
set to first-ring autoanswer. The emulator used `ATS27=0S7=120`, then
`ATDT100`. The physical terminal sent `COURIER-PHYSICAL-READY\r\n`, which
arrived exactly. The emulator sent `COURIER-EMU-TEST\r\n`, which arrived
exactly and elicited `COURIER-PHYSICAL-ACK\r\n`, also received exactly.

The physical Courier's ATI6 reported 46 characters sent, 18 received, none
lost, LAPM SREJ 244/15, V42BIS 2048/32, and 26400/26400 bit/s. During the
14-second call it recorded 31 BLERs, zero blocks resent, and no retrains.
ATI11 reported V.34+, 2800/2800 symbols/s, SNR 35.2 dB, and 437 ms roundtrip
delay. Stopping the emulator ended the call; the physical settings were reset
with ATZ and mgetty was restored.

A normal-mgetty call using only `ATS27=0` also connected at 26400 and received
the readable BBS/MicroVAX greeting and `nanovax login:` prompt. One subsequent
fresh-default call connected but did not receive login text in its 10-second
observation window; that application's data check was unsuccessful.

A further controlled test used a newly seeded EEPROM, only `AT` and
`ATDT100`, and no register overrides. It connected at 26400/V34/LAPM/V42BIS.
The physical modem sent `PHYSICAL-DEFAULTS-READY\r\n`, received
`EMU-DEFAULTS-TEST\r\n`, and replied `PHYSICAL-DEFAULTS-ACK\r\n`. The
emulator received both physical strings exactly. Mgetty was restored after
this test as well. The Python launcher did not implement the AT parser,
error correction, or compression; payloads traversed the original firmware.

## Normal SIP line profile and incoming data

The normal launcher now uses transmit gain 0.25 at the SIP PCM boundary and
no synthetic local hybrid return. These settings are applied before board
construction; they do not force carrier or replace firmware protocols. They
are an empirically tested virtual-line profile, not a measurement of physical
board transfer gain. Direct diagnostic CLI defaults remain unchanged.

Two native Courier instances negotiated
`CONNECT 33600/ARQ/V34/LAPM/V42BIS` and exchanged complete
`CALLER-DATA-MARKER\r\n` / `ANSWERER-DATA-MARKER\r\n` strings in both
directions. The opt-in automated regression repeats this with unmodified
workers and temporary loopback SIP/RTP endpoints. An intermediate placement
of the production controls failed this regression; applying the controls at
board initialization and the shared PCM transmit boundary passed twice. The
full focused suite, including the data regression, passed 77 tests.

A physical incoming call used the temporary dial string 9095551030 from
`nanovax:/dev/ttyUSB0` to the notebook's SIP port 5074. Both terminals reported
`CONNECT 31200/ARQ/V34/LAPM/V42BIS`. The physical Courier received
`EMU-INCOMING-READY\r\n`; the emulator received
`PHYSICAL-INCOMING-TEST\r\n`, including the full line ending. The original
ATA dial plans were restored and verified after the test.

The final outgoing check dialed 100 from the normal launcher. The emulator
reported `CONNECT 12000/ARQ/V34/LAPM/V42BIS`; the physical Courier reported
`CONNECT 21600/ARQ/V34/LAPM/V42BIS`. Both received the complete opposite-end
`EMU-OUTGOING-TEST\r\n` and `PHYSICAL-OUTGOING-TEST\r\n` markers. Physical
ATI6 confirmed asymmetric speed 21600/12000, LAPM SREJ 244/15 and V42BIS
2048/32, with no resends, retrains or BLERs in the short data interval. ATI11
reported a 424 ms roundtrip delay and timing offset -6688 ppm; these results
do not establish clock-model accuracy or sustained-transfer reliability.

Not every physical attempt passed. One outgoing fixture failed to establish
verified autoanswer; the corrected fixture waits for fresh acknowledgements
and checks `ATS0?` before dialing. Another outgoing call soon after restoring
the ATA plan ended with NO CARRIER. A retry after a settling interval passed.
These failures are retained as operational observations, not hidden by the
successful marker checks.

## Evidence and limits

Local captures are under `/tmp/courier-physical-stage6`,
`/tmp/courier-physical-controlled`, `/tmp/courier-physical-mgetty`,
`/tmp/courier-physical-defaults`, and `/tmp/courier-defaults-data` on the
notebook. These temporary paths are operational evidence, not package inputs.

Native firmware tests also exercised incoming INVITE, RING, manual ATA,
ATS0=1 autoanswer, and outgoing keypress cancellation against loopback SIP.
Before the quiet line profile, a physical Courier-originated test reached SIP,
firmware RING and answer, but did not establish a data connection. Other attempts failed before SIP
with NO DIAL TONE; a hardware-to-hardware control call through `tio` connected
at 31200/V34/LAPM/V42bis. Temporary ATA routes were removed and the original
dial plans verified afterward.

Direct loopback tests with `modem-dsp-emu` originating to the analog Courier
reached SIP answer and V.34 training but failed LAPM establishment and exact
bidirectional marker checks. The final normal-profile test reported
`CONNECT 31200/V34/NONE` followed by unreadable data. This is not a successful
interoperability result. Interoperability with the Eicon emulator remains
unresolved; the physical and native Courier tests above are separate
successful cases.
The physical data checks were short marker transfers; they do not establish
long-duration stability or the maximum reliable transfer rate.

Later local evidence is under `/tmp/courier-pair-level-echo-long`,
`/tmp/courier-native-data-regression`, `/tmp/courier-physical-normal-incoming`,
and `/tmp/courier-physical-final-outgoing-settled`. Failed cases include
`/tmp/courier-eicon-incoming-2`, `/tmp/courier-eicon-final-incoming`, and
`/tmp/courier-physical-final-outgoing`. All are temporary local captures.

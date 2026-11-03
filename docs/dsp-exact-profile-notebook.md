# Match the complete physical-call emulator profile

The notebook loopback tool accepts --nvram PATH. It validates the source
EEPROM checksum and copies it into each temporary endpoint directory.
Existing runtime ARQ migration applies only to those copies. The source
file is unchanged. The answerer receives ATS0=1 as before; optional rate
selection remains available. The summary records source path and hash.
Definitive modem failures now stop the loop instead of idling until the
timeout. The original first check predates this early-stop change.

The actual saved profile has &M5/&N6, S34=129, S54=96, S56=192 and S58=97.
It negotiates V.32, whereas the default fixture with only &N6 negotiates
V.34. Matching rate and ARQ alone therefore did not match the protocol.
Use --nvram artifacts/courier-emu-v32.nvram for subsequent local diagnosis;
the current source hash matches nanovax's b405a1b8… EEPROM exactly.

The first current-build check with the block enabled returns NO CARRIER
at both ends. A preserved pre-arithmetic-inline library negotiates V.32
ARQ/LAPM on both ends, but loses part of one marker and then carrier.
The current combined build with the block disabled succeeds with exact
bidirectional data in 31.60 seconds. One repeated current-build check
with the block enabled also succeeds with exact data in 33.76 seconds.
Both successful runs negotiate 9600/ARQ/V32/LAPM/V42BIS.

These few checks establish a usable exact-profile workload and an
intermittent failure. They do not establish that an optimization caused
the first failure, prove a failure rate, or demonstrate stable physical
interoperability. Do not remove a candidate solely from the first failure,
or dismiss the failure because the repeat succeeds. Preserve this
uncertainty alongside the separate A53 throughput deficit.

Raw terminal results, windows and library identities are retained in
`dsp-exact-profile-notebook.json`. The source EEPROM hash is unchanged.
No additional physical call was made during these notebook checks.

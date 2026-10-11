# HST: two channels, one each way

HST is datapump slot 3 (see [datapump-slots.md](datapump-slots.md)). It lives
entirely in the 403's resident DSP bank and in the C52 mask ROM. This note is
what the code and a run of it establish, written as the spec a reimplementation
needs. Addresses are the 20.16 MHz resident (`courier-board-21210-capture-403`)
and the mask ROM dump `boot_rom.MASK_ROM`.

HST is the only slot whose two sides send *different signals*. V.23 is also
asymmetric, but both of its channels are FSK. Here each side installs its own
transmitter, and the two share nothing but the symbol-script engine.

## Measured

Running each entry the way `fsk_loopback` does, with `@26` left at `8320` (see
below), and recording `DXR` at the resident's 7200 Hz codec rate:

| entry | transmitter | carrier | baud | -20 dB span | rate |
|---|---|---|---|---|---|
| originate `c533` | `c967` -> `c9d2`/`ca05` | **350 Hz** | **200** | 258-444 Hz | 300 bps back channel |
| same, `0x6f` bit 12 set | | **375 Hz** | **300** | 258-480 Hz | 450 bps back channel |
| answer `c7fd` | `c992` -> `c9a5` | **1800 Hz** | **2400** | 556-3078 Hz | forward channel |

Baud is counted, not inferred: the symbol boundary `ca1b` runs 83 times in 3000
frames at 300 bps, 124 times at 450, and 999 times on the forward channel, with
one modulator call per frame. No host data was fed and the codec input was
silent, so the transmitters sent their start-up pattern. The squared back
channel shows its strongest line at *half* the baud (100 / 150 Hz). That is the
pattern repeating every two symbols, not the symbol rate, and it misled the
first reading.

## The symbol-script engine

Both transmitters take their symbols from a script. At each symbol boundary,
`ca1b` checks `@4a`. When it reaches zero, the engine copies the next three
words from the script at `@4d` into `@48` (the handler), `@49` (an argument)
and `@4a` (a duration in symbols), and then jumps to `@48`. A zero handler ends
the script. A training schedule is therefore data and can be read straight out.

## Forward channel

**Modulator.** `c9a5` is a 20-tap pulse shaper running at three samples per
symbol (`@4c` steps `0x14` up to `0x3c`). There is no carrier multiply, because
1800 Hz is fs/4: `@45` is decremented every sample, bit 0 picks the I or Q half
of the pulse table (`+0x14`), and bit 1 negates. That cycles I, Q, -I, -Q. The
codec stays at index 0, 7200 Hz.

**Mapping** (`cb4e`). The symbol index `@50` is looked up in mask ROM at
program `0x0240 + @50`: high byte I, low byte Q, both signed. The tables there
are the **V.17/V.32bis constellations, point for point, at scale x8**. Every
entry was checked against SpanDSP's `v17_v32bis_tx_constellation_maps.h`:

| ROM | points | SpanDSP table | rate (2400 baud) |
|---|---|---|---|
| `0x0248` | 4 | `v17_v32bis_4800_constellation` | 4800, uncoded |
| `0x0250` | 16 | `..._7200_constellation` | 7200 |
| `0x0260` | 32 | `..._9600_constellation` | 9600 |
| `0x0280` | 64 | `..._12000_constellation` | 12000 |
| `0x02c0` | 128 | `..._14400_constellation` | 14400 |
| `0x0340` | 256 | none (odd multiples of 4) | 16800 |
| `0x0244` | 4 | not SpanDSP's ABCD order | training |

The offset is computed rather than tabulated. For n bits per symbol, `cb3f`
adds `2 << n` to the encoder output, which lands on `0x250`, `0x260`, `0x280`,
`0x2c0` and `0x340` for n = 3 to 7. n = 2 goes through `cb34` and adds 8
instead. The 256-point table is the only one with no V.32bis counterpart.
16800 at 2400 baud is 7 data bits plus 1 trellis bit, which needs 256 points.

**Coding.**

* n = 2 is differentially encoded through mask-ROM `0x0450`
  (`(@50 << 2 | @5a) & 0xf`). This matches V.32's 4800 bps scheme.
* n >= 3 goes through a 32-entry table at `0x0460`, indexed by
  `(@50 << 3) + @5a` mod 32: the 2 low data bits added mod 4 to the previous
  state, then a lookup that returns the new state. The structure is V.32's
  differential encoder plus its 8-state convolutional encoder. **That the
  table equals V.32's has not been checked bit for bit.**
* Higher bits pass through uncoded (`@50 << 3 & 0x3e0`, then `>> 2`).

**Scrambler** (`cb92`). `@58:@59` is a 32-bit register. The n scrambled bits
are `(R >> 5) ^ R ^ data`, masked to n bits. They are inserted at bit 23 and
the register is shifted right by n (`SATL`, which is a right shift - see
`op_satl`). Output bit j therefore sees delays 23 and 18, so the polynomial is
**1 + x^-18 + x^-23**, V.32's GPC. HST uses it in whichever direction carries
the forward channel. Seeds: `0x001f7310` at the start of training (`cb09`).

**Training** (rate scripts `ca34`, `ca41`, ... `ca75`, chosen by `0x32a`):

| step | handler | argument | symbols | what it sends |
|---|---|---|---|---|
| 1 | `cafa` | 0 | 180 | index 0, the point (0,0): silence |
| 2 | `cafe` | `0202` | 72 | nibbles of the argument, one per symbol, + 8: alternating `0x24a`/`0x248` |
| 3 | `cb09` | 2 | 200, or `0c18` = 3096 at rates 3-5 | scrambled 2-bit symbols on the 4800 points; the input is the previous output |
| 4 | `cb1b` | n = 2..7 | 16, or 24 at rates 3-5 | data-rate symbols |
| - | `cb6e` | `@5c` | 37 at a time | data mode; `825f` refills every 37 symbols |

The second table (`c52d`: `ca37`, `ca44`, ...) starts each script one entry in,
skipping the silence. Tag `33` uses it, i.e. the side that turns around to
send the forward channel. The 3096-symbol step 3 (1.29 s) at rate indices 3-5
fits a longer equaliser training for 12000 and up. Why the tag `36` value is
stored as index + 8 in `@5c` is not resolved.

## Back channel

**Modulator.** `c9d2` and `ca05` alternate per sample, each writing the other
into `@1a`. Pulse shaping comes from a 36-entry table (`cbc1` at 300 bps,
`cbe5` at 450). A 32-bit phase in `@40`/`@41` advances by `@6c << 14` every
second sample: `0x638e` gives 349.97 Hz and `0x6aaa` gives 375.0 Hz. `0x6f`
bit 12 picks the pair, together with `@70` = 3 or 5. `ca05` adds `@70 + 1` to
`@4c` and ends the symbol at 72, so a symbol is 18 or 12 `ca05` calls, i.e. 36
or 24 samples: **200 or 300 baud**, as counted above. The entry also sets
`@04` to `0x038e` / `0x0555`, which is 100.0 / 150.0 Hz at 7200, half the
baud. What `@04` clocks has not been read.

**Mapping** (`caba`-`cace`). This is **differential 8-PSK**. The script
gives it 3 bits per symbol, which at 200 / 300 baud is 600 / 900 bit/s on the
line: twice the menu's 300 / 450. Whether data mode halves that (repetition,
coding, or 1.5 bits per symbol) is open. The 3 scrambled bits select a nibble of the packed constant
`0x43705261`:

| bits | 0 | 1 | 2 | 3 | 4 | 5 | 6 | 7 |
|---|---|---|---|---|---|---|---|---|
| phase step (x45 degrees) | 1 | 6 | 2 | 5 | 0 | 7 | 3 | 4 |

`@71 = (@71 + step) & 7` and `cbb1 + 2 x @71` gives (cos, sin). The eight
points are at 22.5 + 45k degrees, amplitude 12945 (`2eb8`/`135a` = 11960/4954).

**Scrambler** (`cba2`). The same register layout, but new bits are inserted at
bit 17 and the shift is a fixed 3. The taps are at R and R >> 3, so the delays
are 17 and 14: **1 + x^-14 + x^-17**, the V.22bis polynomial. Seed
`0x0001fd28` (`caa1`).

**Script** `ca82`: `caa1` with argument 3 for 17 symbols (the scrambler seed,
then 8-DPSK), then `caaf` with argument 0 for 1 symbol. `caaf` raises
`0x6f` bit 2 (the transmit-data enable) and sends the host message `03`
through `83b1`. After that, `cab5` runs per symbol on host data fetched by
`825f`. At 300 bps (bit 12 clear), `cad5` first sets `@4a` = 10.

## Mailbox tags

HST has a block of tags that no other modulation has:

| tag | handler | what it does |
|---|---|---|
| `32` | `c7ed` | installs the **back-channel** transmitter `c967`, then rejoins the answer entry at `c805` |
| `33` | `c51f` | installs the **forward** transmitter `c992`, then rejoins the originate entry at `c537` |
| `34` | `c506` | keeps only `0x6f` bit 12; picks a receiver rate script from `c519` by `@2a` |
| `37`, `39` | `c7d3`, `c7cd` | store a rate index below 6 into `0x32a` (37 also starts script `c7c2`) |
| `36` | `c7df` | `@5c` = index + 8 |
| `35`, `3a`, `3b` | `c963`, `c95f`, `c7e9` | park a script in `@4d`, or clear `@6f` bit 3 and rejoin `c805` |

Tags `32` and `33` give each side the opposite side's transmitter without a
restart. That is HST's channel reversal, since the high-speed direction
follows the data. What makes the supervisor send them is not read.

## Running it

* `@26` (data `0x326`) must stay at the cold start's `8320`. `fsk_loopback`
  clears it for FSK. Doing that here sends 8304's `bacc` to zero, and the slot
  runs a sixth as long and delivers nothing.
* All of HST's code, `c4f7` to about `ccdf`, lies inside both overlay 6
  (`9d00`-`ce31`) and overlay 7 (`b000`-`cd49`). HST therefore runs only from a
  freshly downloaded resident.
* The constellation, encoder and Gray tables are in the **mask ROM**, not the
  download. A harness without `boot_rom.install` transmits garbage points.

## Open

Needed before an interoperable reimplementation:

* the bit-exact `0x0460` trellis table against V.32's encoder;
* the receivers (`c4f7`, `c7a4` scripts): which channel each demodulates, and
  what they expect from the far end during training;
* how a call selects HST, i.e. the answer and detection sequence, and the
  supervisor's use of tags `32`-`3b`;
* how data is framed on each channel, i.e. the HST link layer above the
  datapump;
* the back channel's data-mode bits per symbol: 3-bit 8-DPSK at 200 / 300 baud
  is twice the rate the menu names;
* the menu's `12200`, which matches no symbol arithmetic and is probably only
  a label.

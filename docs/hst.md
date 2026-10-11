# HST: two channels, one each way

HST is datapump slot 3 (see [datapump-slots.md](datapump-slots.md)). It lives
entirely in the 403's resident DSP bank and in the C52 mask ROM. This note is
what the code and a run of it establish, written as the spec a reimplementation
needs. Addresses are the 20.16 MHz resident (`courier-board-21210-capture-403`)
and the mask ROM dump `boot_rom.MASK_ROM`.

HST is the only slot whose two sides send *different signals*. V.23 is also
asymmetric, but both of its channels are FSK. Here each side installs its own
transmitter, and the two share nothing but the symbol-script engine.

## Call roles and the loopback entries

The slot-3 entries in the `10`/`11` tables, `c533` (`9b48`) and `c7fd`
(`9b51`), are **analogue-loopback self-test** configurations, like the FSK
own-band entries in [fsk-modulation.md](fsk-modulation.md). Each one pairs a
transmitter with a receiver for the *same* channel. A call uses HST's own tags
instead:

| role | entry | transmits | receives |
|---|---|---|---|
| forward-channel sender | tag `33`, `c51f` | forward (`c992`) | back channel (script `c4f7`) |
| back-channel sender | tag `32`, `c7ed` | back channel (`c967`) | forward (script `c7a4`) |
| loopback | `c533` | back channel | back channel |
| loopback | `c7fd` | forward | forward |

This was established by running two cores in lockstep, each one's `DXR`
feeding the other's codec input. Results:

* **`c533` x `c7fd`:** neither receiver ever passes its first script step,
  because each hears the other channel.
* **`c533` x `c533` and `c7fd` x `c7fd`:** both receivers detect carrier.
* **`c51f` x `c7ed`:** a full start-up on both sides, with host messages
  logged at `83b1`:

| frame (7200 Hz) | tag `33` side | tag `32` side |
|---|---|---|
| 341 | | `2f` + rate `0`: forward carrier detected |
| 649 | `2f` + rate `0`: back-channel carrier detected | |
| 701 | | `04` |
| 820 | `03`: forward transmit data enabled | |
| 965 | | `02` |
| 1441 | | `03`: back-channel transmit data enabled |
| 2089 | `04` | |
| 2437 | `02` | |

What `04` and `02` mean is not read. The order on both sides, carrier, `04`,
`02`, suggests receiver training stages.

### Data across the pair

Each transmitter's host window (the `@57` ring, CBSR2-CBER2, as in
`fsk_loopback`) was fed a counting byte sequence, one byte per pointer
advance. Every word the other side delivered at `832f` was recorded.

**Forward channel: bit-exact, HDLC-stuffed.** The sender takes a byte every 12
frames, which is 4800 bps at 8 bits per byte. There are no start/stop bits:
the framer `@56` = `8264` is synchronous. Its stream is **HDLC bit-stuffed**,
with a 0 after every five 1s (the first breaks fall exactly after bytes `0x1f`
and `0x3f`), and `8264` carries the flag `0x7e` (`8278`). The receiver delivers
the raw stuffed bits, 2 per symbol, LSB first (`@26` = `8320`). Removing the
stuffing, **2332 of 2381 bytes arrive exact** over 30000 frames. The other 49
come through as all or mostly zeros, at a steady cadence of about one per 36
bytes, without losing alignment. That looks like the transmitter reading a
window slot before the harness filled it, rather than a line error, but this
has not been proven. Data mode needs no tag `36`: the transmitter stays on
`cb34` (n = 2) after training.

**Back channel: 3 bits on every other symbol.** In data mode the per-symbol
handler alternates between `cab5` (fetch, scramble, 8-DPSK phase step) and
`cae0`/`cae2`, which sends **I = Q = 0**. Only half the line symbols carry
data: 100 a second x 3 bits = **300 bps** (150 x 3 = **450** with `0x6f` bit
12). That closes the 600-versus-300 question, and it is the half-baud line the
squared signal showed. The sender takes a byte every 144 or 216 frames
(about 303 bps). The receiver delivers one 3-bit word per data symbol, mostly
72 frames apart (100/s), with occasional longer gaps. **The delivered bits do
not yet match what was sent.** Raw, phase-step mapped, inverse-mapped,
descrambled with 1 + x^-14 + x^-17, destuffed, and in either bit order, the
best variant finds 9 of 149 sent byte pairs, against 0-4 for a shuffled
control.

The `10`/`11` dispatchers have a call-mode twin (`9da6`, `a00d`, `9dc1`,
`a054`), but it branches only for V.22/V.22bis, Bell 103, V.21 and V.23.
HST's flag (`@26` bit 5) is not tested there. HST reaches its call roles only
through tags `32` and `33`.

## Measured

Running the loopback entries the way `fsk_loopback` does, with `@26` left at
`8320` (see below), and recording `DXR` at the resident's 7200 Hz codec rate.
The transmitters are the ones the call roles install:

| entry | transmitter | carrier | baud | -20 dB span | rate |
|---|---|---|---|---|---|
| `c533` | `c967` -> `c9d2`/`ca05` | **350 Hz** | **200** | 258-444 Hz | 300 bps back channel |
| same, `0x6f` bit 12 set | | **375 Hz** | **300** | 258-480 Hz | 450 bps back channel |
| `c7fd` | `c992` -> `c9a5` | **1800 Hz** | **2400** | 556-3078 Hz | forward channel |

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

**Read this as shared tables, not as HST derived from V.32bis.** HST shipped
before V.32 products, and long before V.32bis. What the ROM shows is that this
1990s firmware runs HST on one table set that the V.32 family and V.17 fax also
use. Other users of the same tables: the resident V.32 path (`bc8a`, `bcd2`,
`bff0`) and the fax datapumps (`e689`, `e6a3`). Whether 1986 HST coded its
symbols this way cannot be told from one firmware. **HST's 16800 table is its own, not V.32terbo's.** The resident has two
large-constellation schemes, and only HST uses `0x340`.

*Receive selector.* A jump table at `bee6`, indexed by `@2a`, loads the slicer
base `@28` per rate:

| index | n | `@28` | rate |
|---|---|---|---|
| 0 | 2 | - | 4800 |
| 1 | 3 | `0x250` | 7200 |
| 2 | 4 | `0x260` | 9600 trellis |
| 3 | 4 | - (slicer `bfc1`, table `0x440`) | 9600 uncoded |
| 4 | 5 | `0x280` | 12000 |
| 5 | 6 | `0x2c0` | 14400 |
| 6 | 7 | **`0x340`** | **16800** |
| 7-13 | 3-9 | none (slicer `c009`) | 7200-21600 |

*V.32 transmit* (`bbbd`, rate code `@49`). Codes 1-4 go through `bbf1`, the
same `index + (2 << n)` path HST uses, for n = 3-6 only. Codes 5 and up go
through `bc00`, with n = code - 3, up to 9. That path takes the trellis subset
(3 bits) to `c22a` for flags (bit 0: column, bit 1: negate Q, bit 2: negate I,
bit 3: swap). The uncoded bits index a 256-entry one-quadrant table at
**`c280` in the resident**, sorted by rising energy, in one-even-one-odd integer
coordinates. The point is then scaled by `@67` and **warped** by a polynomial
in r² (`bc2c`-`bc48`: `1566e000`, `1928`, `019f`, `000c`). `c009` is the
receiver's inverse: unwarp (`dcb3`, `15f9`, `1355`, `03c2`), rotate by
`@48`/`@49`, and fold into one quadrant. 256 entries x 4 rotations is 1024
points, i.e. 21600's 9 + 1 bits. Half the table is 19200's 512. Nothing here
needs a 512-point table, and the V.32 re-encoder's `0x7e0` mask is one bit
wider than HST's `0x3e0`.

No V.32 transmit path reaches `0x340`: V.32 16800 is code 10 through `c280`.
The two 256-point sets lie on the same lattice (45 degrees apart, inner
energies 2, 10, ... identical) but have different boundaries. `0x340` is
squarer and reaches energy 450, while `c280`'s inner 256 are a circle reaching
314. HST 16800 is a constellation of HST's own.

**The `bee6` selector is shared by V.32 and HST.** It is entered from the
receive-script step `bec4`. That step waits for `@20 == @21` on eight
consecutive symbols (`@29` counts down from 8), clears state, sends host
message `22` through `83b1`, and dispatches on `@2a`. `bec4` appears in V.32's
receive script (`b35a`) and in HST's forward-channel receive script `c7a4`, at
`c7c2`. `c7c2` is the script tail that tag `37` starts, and tag `38` is `bebe`,
which cancels the wait. So HST's forward channel is received on the same QAM
receiver V.32 uses, and index 6 / `0x340` is reached from there.

Every image here caps HST at 16800: the `CONNECT` strings run
4800/7200/9600/12000/14400/16800`/HST`. 21600 exists only as `/V32` and
`/VFC`, and 24000 only as `/VFC` and `/V34`. The `CONNECT` text says
`12000/HST`, so the menu's `12200` is a label typo. "HST" is also a link
protocol name next to `SYNC`, `NONE`, `MNP` and `LAPM` (`0x1b056`,
`0x1be6e`).

The offset is computed rather than tabulated. For n bits per symbol, `cb3f`
adds `2 << n` to the encoder output, which lands on `0x250`, `0x260`, `0x280`,
`0x2c0` and `0x340` for n = 3 to 7. n = 2 goes through `cb34` and adds 8
instead. The 256-point table is the only one with no V.32bis counterpart.
16800 at 2400 baud is 7 data bits plus 1 trellis bit, which needs 256 points.

**Coding.**

* n = 2 is differentially encoded through mask-ROM `0x0450`
  (`(@50 << 2 | @5a) & 0xf`). It is entry for entry SpanDSP's
  `v32bis_4800_differential_encoder`, transposed: `T[q << 2 | prev]` equals
  `enc[prev][q]`.
* n >= 3 goes through a 32-entry table at `0x0460`, indexed by
  `(@50 << 3) + @5a` mod 32. The 5-bit state packs the two differential bits
  (bits 3-4, so adding the data mod 4 is the differential encoder) and the
  convolutional state, whose top bit is the redundant bit. The output index is
  `((@50 << 3) & 0x3e0 | state) >> 2`.
* **This is V.32's encoder exactly.** Driving the ROM path and SpanDSP's
  `diff_and_convolutional_encode` with the same 3000 random symbols gives
  identical index streams at every n from 3 to 7. All 32 ROM states map one to
  one onto SpanDSP's (diff, convolution) pairs. For n = 7, SpanDSP's uncoded
  mask `(q << 1) & 0x78` has to widen to `0xf8`, because 16800 has one more
  uncoded bit than 14400. Nothing else changes.

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
skipping the silence. Tag `33`, the forward-channel sender's call role,
uses it. The 3096-symbol step 3 (1.29 s) at rate indices 3-5
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
line: twice the menu's 300 / 450. Data mode halves it with a zero symbol
between data symbols (see *Data across the pair*). The 3 scrambled bits select a nibble of the packed constant
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
| `32` | `c7ed` | call role: **back-channel** transmitter `c967` + forward receiver (joins `c805`, script `c7a4`) |
| `33` | `c51f` | call role: **forward** transmitter `c992` + back-channel receiver (joins `c537`, script `c4f7`) |
| `34` | `c506` | keeps only `0x6f` bit 12; picks a receiver rate script from `c519` by `@2a` |
| `37`, `39` | `c7d3`, `c7cd` | store a rate index below 6 into `0x32a` (37 also starts script `c7c2`) |
| `36` | `c7df` | `@5c` = index + 8 |
| `35`, `3a`, `3b` | `c963`, `c95f`, `c7e9` | park a script in `@4d`, or clear `@6f` bit 3 and rejoin `c805` |

Tags `32` and `33` are the call roles (above). Since the high-speed direction
follows the data, a channel reversal is presumably the supervisor re-issuing
the other tag. That, and what makes it send either, is not read.

## Receivers

**Back channel, script `c4f7`** (tag `33` side). It steps once per back-channel
symbol: 200 a second at 300 bps.

* `c5e8` x1 and `c5f0` x4 are carrier detect. Energy `@00:@02` must exceed `@0b`
  (`0x41e8`), then four times it; any miss restarts at `c4f7`. On success it
  sends `2f` and the rate index from `0x32a`.
* `c611` x16 initialises: `@06` = `0x90`, `@04` = `0xe4`, loop steps
  `@28`/`@29`/`@2c` = `0x800`/`0x200`/`0x40`, 16 words cleared at `0x240` and
  `0x400`, through the resident receiver routines the V.32 path also uses
  (`87fd`, `88b3`, `bd3d`, `bd43`).
* `c637` x5, `c640` x13, `c646` x37 and `c649` x400 settle the loops. Gains
  `@10`/`@11`/`@12` start at `1800`/`3000`/`1000`, then `@2c` = `0x78`, then
  `@10` drops to `0x800` for 400 symbols.

**Forward channel, script `c7a4`** (tag `32` side). Its per-sample handler
`c821` counts `@2b` down from 3, so the script steps 2400 times a second.

* `c83e` x16 (twice) and `c84c` x16 are energy tests: `@00 + @02` against
  `0x2a54`, with a sign test on `@34`.
* `c866` arms the per-symbol path `c88d` (demodulator `8a8c` with table
  `c950`).
* `c8d7` x19 sets the loop gains and `@0b` = `0x3aaf`, and sends `2f` plus the
  rate.
* `c8f8` x192: rate index 0 goes to `bef3` (4800). Indices 1-2 go through the
  shared `bee6` selector. Above that, it switches to script `c7b9`.
* The `bec4` tail at `c7c2` is the decision-directed lock described above.

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

* the back channel's delivered words: how the 3-bit decisions map back to
  data (the forward channel is bit-exact), and why some data symbols are not
  delivered;
* the 49 zeroed forward bytes, and whether they are the harness's window feed;
* host messages `04` and `02`;
* how a call selects HST, i.e. the answer and detection sequence, and the
  supervisor's use of tags `32`-`3b`;
* how data is framed on each channel, i.e. the HST link layer above the
  datapump;

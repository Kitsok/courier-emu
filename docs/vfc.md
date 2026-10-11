# V.FC: V.32's start-up, then six symbol rates

V.FC is datapump slot 1 (see [datapump-slots.md](datapump-slots.md)). It lives
in overlay 7 (`b000`-`cd49`), which collides with V.34's overlay 6 and with
HST's resident code. The same entry, `b000`, serves both sides. Overlay 7 is
frozen word for word from 1996 onward
([imodem-firmware-timeline.md](imodem-firmware-timeline.md)). Addresses are
the 403 image (`courier-board-21210-capture-403`).

The comparison that matters: HST and V.32 (including V.32terbo's 19200 and
USR's 21600) never leave **2400 baud**, and reach higher rates with bigger
constellations ([hst.md](hst.md)). V.FC reaches 28800 by **changing the symbol
rate**. It shares V.32's start-up machinery and nothing else above it.

## Rates

The `AT*C` menu (token-decoded, see datapump-slots.md) lists V.FC at 9600,
12000, 14400, 16800, 19200, 21600, 24000, 26400 and 28800 bps, originate and
answer. `CONNECT` strings carry `/VFC` up to 28800.

## Symbol rates

A table at `b049`, indexed by the word at data `0x870`, reads
`0078 0089 008c 0096 00a0 00ab`. That is 120, 137, 140, 150, 160, 171: **2400,
2743, 2800, 3000, 3200 and 3429 baud, divided by 20**, the same six symbol rates
V.34 uses. `b03d` turns the entry into `@6e` (`(v + 16) >> 5`). Like V.34's
overlay, V.FC writes the second symbol-rate index at data `0x35b` (`b155`,
`b4c7`). [codec-sample-rates.md](codec-sample-rates.md) has that as V.34's
outgoing-INFO index. Neither overlay calls the codec rate selector `8151`
itself.

Six-entry tables follow the same index:

| table | values | read |
|---|---|---|
| `cb35` | 40, 35, 48, 32, 30, 28 | not read |
| `cb3b` | 5, 5, 7, 5, 5, 5 | not read |
| `cb41` | `1999`, `1999`, `1249`, `1999`, `1999`, `1999` | not read |
| `cb47` | 3, 4, 4, 5, 5, 6 | not read |
| `cb6d` | 2, 2, 2, 1, 1, 0 | not read |
| `cb73` | `5d71`, `4986`, `3071`, `4496`, `320e`, `5951` | not read |

`cc81` is a six-column table, i.e. one column per symbol rate. `cc2d` holds 16
symmetric 5-tap filters (`0044 ff18 2148 ff18 0044`, ...), whose shape suggests
pre-emphasis. Neither has been confirmed.

## Start-up is V.32's

* **Bits.** V.FC calls the resident's V.32 scrambler `8cb7` (GPC or GPA by
  `0x6f` bit 0, as V.32 does) and the V.32 4800 differential encoder `8cd7`.
  At `c690`-`c6a3`, it sends scrambled 2-bit symbols onto the V.32 4800 points
  (`0x0240 + 8`, mask ROM). The receive side (`b89f`-`b8ac`) decodes the same
  set, through `0x0450` and `0x0248`.
* **Signal.** Run alone, with the overlay loaded over the resident after the
  cold start and entered at `b000`, the originator transmits for about 125 ms
  and then waits. The signal repeats every 12 samples, the second half the
  negative of the first. It decomposes into three equal tones at fs/12, fs/4
  and 5fs/12: **600, 1800 and 3000 Hz at 7200**. That is an 1800 Hz carrier
  with ±1200 Hz sidebands, a short repeating pattern at 2400 baud. After
  sample ~900 the content changes, and then it goes silent waiting for the far
  end.

Nothing else from the V.32 family is used. V.FC does not touch the mask-ROM
constellations above 4800 (`0x250`+), the resident quadrant mapper `bc00` /
`c280`, or the `bee6` receive selector.

## Data mode is V.34's structure

The per-symbol mapper is `c723`-`c78b`, writing I/Q to the transmit buffer at
`0x04b6`.

* **An 8-symbol mapping frame.** `@35` counts 0-7. Each symbol takes one byte
  of the frame buffer (`ar2`), high and low bytes alternating. `c1bf`, `c20e`
  and the six-entry tables size the frame per symbol rate (there is a 16-step
  `subc` division at `c229`).
* **Quadrant differential coding.** `@5a = (@5a + 2 bits) & 3`.
* **Point.** The rest of the byte, masked by `@3e = (1 << @25) - 1` and
  combined with the frame's high bits shifted by `@25`, plus a rotation-code
  offset from `cb2d` (`0 5 6 1 2 7 4 3`), indexes a **one-quadrant point table
  at `aeab`** (packed I/Q bytes). The point is then turned by one of four
  routines through `c804`: 0, (Q, -I), (-I, -Q), (-Q, I).
* **Trellis: 2D, V.32-style, not V.34's 4D.** The state advances on *every*
  symbol, from the 2 quadrant-differential bits. That differs from V.34, which
  steps once per 4D symbol (two 2D symbols) on 4 bits. The step (`c76f`-`c788`)
  XORs one tap word per set bit of `u = @36 | (@5a << 5)` into `B`, and keeps
  `(B ^ ((B >> 7) & (B >> 5) & 3)) & 0x1f`. The AND term makes it nonlinear,
  as V.32's code is. State bit 0 and the 2 quadrant bits pick one of 8
  subsets through `cb2d`. The two tap tables, chosen by `0x873` bit 1:
  * `cb5e` (`0064 0101 0002 0000 0000 0082 0103`) reaches 8 states and **is
    V.32's 8-state code**. Its redundant bit matches SpanDSP's V.32 encoder
    (`v17_convolutional_encoder`) on 2000 of 2000 random symbols, under a
    fixed state mapping.
  * `cb57` (`0070 0101 0002 0004 000a 008a 0103`) reaches all **32 states**.
    It agrees with V.32's code only at chance level (1068 of 2000), so it is
    a different, stronger code.
* **Precoding** (`c9c4`, after every point). A 3-tap complex FIR over past
  output, with coefficients at program `2056`/`2059` (not mask ROM, so
  presumably set in training). Its output is rounded onto a coarse lattice
  (`+ 0x400`, `& 0xf800`), and the rounding error is added to the point. This
  is the shape of V.34's precoder (9.6.4/V.34).
* **Nonlinear encoding** (`c9f7`, when `0x879` bit 10 is set). ζ comes from
  |x|² (scale `0x28f6`), and the point is multiplied by
  1 + `0aab`·ζ + `0089`·ζ² + `0003`·ζ³. At Q14 those are 1/6, 1/120 and
  1/5040, so **Φ = 1 + ζ/6 + ζ²/120 + ζ³/5040**. V.34 9.7 stops at ζ²/120
  (SpanDSP's `v34tx.c` has it that way too). V.FC carries one more term of
  the same series.

**The point table is V.34's superconstellation, ordered differently.** `aeab`
is in the *resident*, inside the range overlay 6 overwrites. It is on the
one-even-one-odd lattice; rotated 45 degrees, `(x + y, x - y)`, it lands on
V.34's odd lattice. Comparing with SpanDSP's `v34_superconstellation`
(Figure 5/V.34), with all four rotations applied:

| quarter entries | points | same set as V.34 |
|---|---|---|
| 4, 8 | 16, 32 | yes |
| 16, 32 | 64, 128 | no (8 and 16 points differ) |
| 48, 64, 96 | 192, 256, 384 | yes |
| 128-192 | 512-768 | no (8-24 differ) |
| 240 | 960 | yes |
| 256 | 1024 | no (8 differ) |
| **320** | **1280** | end of V.FC's table (`afeb` breaks the lattice) |

Every energy shell V.FC completes holds exactly V.34's points. The sizes that
differ are those that cut through a shell, where the two tables complete the
ring in a different order. V.FC's table is also not monotonic in energy, while
V.34's is. V.FC stops at 1280 points; V.34's goes to 1664, for 33600. **Same
lattice and shells, different index-to-point order**: on a scope the two look
alike, but a V.34 mapper cannot stand in for this table.

## Open

* the frame arithmetic in `c1bf`/`c20e` (how bits per 8-symbol frame follow
  from the symbol rate and data rate), and how it compares with V.34's
  shell mapping;
* the 32-state code's distance properties, and where the precoder taps come
  from;
* what the per-symbol-rate tables and the `cc2d` filter bank are;
* `cb65` (`aaaa aaab aaaf aabf aaff abff afff bfff`): eight 16-bit patterns,
  possibly rate signals;
* the codec rate V.FC programs for each symbol rate;
* what the far end has to send to get past the first 125 ms.

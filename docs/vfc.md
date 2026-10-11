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
`c280`, or the `bee6` receive selector. Its data-mode constellation is somewhere
in the overlay, not yet found.

## Open

* the data-mode mapping, and how 28800 fits at 3429 baud (8.4 bits per symbol
  implies fractional-bit mapping);
* what the per-symbol-rate tables and the `cc2d` filter bank are;
* `cb65` (`aaaa aaab aaaf aabf aaff abff afff bfff`): eight 16-bit patterns,
  possibly rate signals;
* the codec rate V.FC programs for each symbol rate;
* what the far end has to send to get past the first 125 ms.

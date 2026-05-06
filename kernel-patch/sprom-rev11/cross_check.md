# Cross-validation against canonical Broadcom SROM rev-11 layout

## What this document tracks

The patch series pins rev-11 byte offsets by value-matching `wl srdump`
against `wl nvram_dump` on a single reference board (DSL-3580L). The
authoritative source for the same offsets is Broadcom's own
`bcmsrom_tbl.h` (released GPLv2-with-linking-exception in `bcmdhd`,
asuswrt-merlin, and several vendor trees; see top-level README for
specific URLs).

Every `SSB_SPROM11_*` constant in `harness/ssb_regs.h` ought to match
the corresponding `SROM11_*` entry in `bcmsrom_tbl.h`. This file is the
ledger of those checks.

## Findings to date

### 1. IL0MAC / CCODE offset collision (open)

Two synth-mode vectors with non-zero `macaddr` and `ccode=0` reproduce
the same word collision on word 0x92:

- `make check-bcm4360usb` — `macaddr=00:90:4c:0e:60:11`, parser reads
  back `00:90:00:00:60:11` (bytes 2/3 zeroed).
- `make check-agcombo` — `macaddr=00:c0:02:01:07:24`, parser reads
  back `00:c0:00:00:07:24` (bytes 2/3 zeroed).

With the patch's current offsets:

    SSB_SPROM11_IL0MAC  = 0x0090   (3 u16 words at 0x90, 0x92, 0x94)
    SSB_SPROM8_CCODE    = 0x0092   (reused unchanged for rev 11)

word 0x92 is shared between byte 2/3 of il0mac and the entire ccode
field. The synth's `ccode=0` write zeroes the middle of the MAC, and
the parser reads back the corrupted value.

The hardware-real raw-mode vectors (DSL-3580L, D6220) do not surface
the collision because the SROM region 0x90..0x95 reads all-zero on
both boards (NVRAM macaddr comes from a separate CFE store; see
`extract_r11.c` rationale block). Two synth vectors on two distinct
boards reproducing the same byte-zeroing pattern at the same offsets
make this a structural offset bug, not a vector-specific artifact.

**Implication.** A real rev-11 SROM cannot store both fields if they
share a word. Either:

  (a) `SSB_SPROM11_IL0MAC` is not at 0x90 — the v2 fix's value-match
      against rev-8 + 4 was a false positive on a board with all-zero
      MAC bytes in SROM; or
  (b) `ccode` for rev 11 has a different offset than the rev-8
      `SROM8_CCODE = 0x92` and the patch is missing that fix.

**Resolution: case (b).** Excerpt from Broadcom `bcmsrom_tbl.h` rev-11
section:

    {"boardnum",  0xfffff800, 0,            SROM11_MACLO,  0xffff},
    {"macaddr",   0xfffff800, SRFL_ETHADDR, SROM11_MACHI,  0xffff},
    {"ccode",     0xfffff800, SRFL_CCODE,   SROM11_CCODE,  0xffff},
    {"regrev",    0xfffff800, 0,            SROM11_REGREV, 0x00ff},

`revmask = 0xfffff800` covers rev 11 (and forward). Four distinct
rev-11 constants: `MACLO` (boardnum, 1 word), `MACHI` (macaddr, 3
words via `SRFL_ETHADDR`), `CCODE` (1 word), `REGREV` (1 word, mask
`0x00ff`). The vendor decoder does not reuse `SROM8_CCODE` for rev 11.

Mapping to v2 patch nomenclature:

| v2 patch                  | vendor canonical | status |
|---|---|---|
| `SSB_SPROM11_IL0MAC = 0x90` (3 words 0x90,0x92,0x94) | `SROM11_MACHI` + 2 + 4 | numeric offset pending |
| reuse `SSB_SPROM8_CCODE = 0x92` for rev 11 | `SROM11_CCODE` (distinct) | **bug confirmed** |
| `regrev` via rev-8 path | `SROM11_REGREV` | numeric offset pending |
| no `boardnum` rev-11 entry | `SROM11_MACLO` | missing entry |

**Fix outline for v3:**

1. Introduce `SSB_SPROM11_MACHI`, `SSB_SPROM11_MACLO`,
   `SSB_SPROM11_CCODE`, `SSB_SPROM11_REGREV` with the numeric values
   from `bcmsrom.h` (or the leading `#define` block of
   `bcmsrom_tbl.h`); not in the table excerpt above.
2. Replace `SSB_SPROM11_IL0MAC` with `SSB_SPROM11_MACHI` in
   `bcma_sprom_extract_r11`, dropping the value-matched-via-rev-8+4
   derivation that produced 0x90.
3. Drop the rev-8 reuse for ccode and regrev on the rev-11 path; use
   the SROM11-specific offsets.
4. Add a `boardnum` extraction at `SSB_SPROM11_MACLO` (1 word).

Pending: the four numeric offsets. They are not in the `bcmsrom_tbl.h`
table body — typically defined in `bcmsrom.h` or in a leading
`#define` block of `bcmsrom_tbl.h`. Until they are sighted, the harness
synth-mode keeps the v2 collision as a red sentinel and v3 cannot be
emitted.

### 2. Rxgains bit-packing (verified self-consistent)

`bcma_sprom_unpack_rxgains()` decodes a packed byte as
`(trelnabyp<<7) | (triso<<3) | elnagain`. The bcm4360usb synth-mode
run encodes triplets `(3, 9, 1)` (5 GHz) and `(4, 9, 1)` (2.4 GHz) via
the inverse, then round-trips them through `extract_r11`:

    chain 0: rxgains_2g.{elnagain=4, triso=9, trelnabyp=1}  → PASS
    chain 0: rxgains_5gl.{elnagain=3, triso=9, trelnabyp=1} → PASS
    chain 1: same triplets                                  → PASS

The triplets come from a different chip family than the DSL-3580L (and
have non-saturated `triso=9`, not the 15 that swamps the DSL-3580L
dump), so the bit-width allocation has been exercised on values that
would expose any 0/1-bit shift error.

This is round-trip self-consistency, not external truth: synth and
parse both use the same encoding by construction. To anchor it
externally, look up the masks for `rxgains*elnagaina*` /
`rxgains*trisoa*` / `rxgains*trelnabypa*` in `bcmsrom_tbl.h` and
confirm they match `0x07 / 0x78 / 0x80` respectively.

### 3. ANTAVAIL / TXRXC / SUBBAND5GVER (verified by bcm4360usb)

These three offsets pass on the bcm4360usb synth-mode run with
non-degenerate inputs:

    aa2g=3, aa5g=3      → ANTAVAIL=0xA0  word 0x303 → PASS both halves
    txchain/rxchain=3   → TXRXC=0xA8     packed → PASS
    subband5gver=0x4    → 0xD6           PASS

DSL-3580L's `aa2g=0` made the bg-half check trivial; bcm4360usb fills
both halves and so confirms that ANTAVAIL packs `aa5g<<8 | aa2g` into
a single u16 at the v2-corrected byte offset. Same for TXRXC.

### 4. Per-chain power-info block stride (verified by bcm4360usb chains 0/1, D6220 chains 0/1/2)

The patch declares the per-chain block stride at 0x28 starting at 0xD8:

    SSB_SPROM11_PWR_INFO_CORE0 = 0x00D8
    SSB_SPROM11_PWR_INFO_CORE1 = 0x0100
    SSB_SPROM11_PWR_INFO_CORE2 = 0x0128

The bcm4360usb vector populates two chains with different `pa2ga` /
`pa5ga` arrays (chain 0 starts `0xff34, 0x19d6, 0xfccf`, chain 1
starts `0xff27, 0x1895, 0xfced`). Both chains round-trip cleanly,
confirming the stride is exactly 0x28 and not 0x26 or 0x2A — an
off-by-one would mix chain-0 `pa5ga` data into chain-1's `pa2ga` slot
and the diff would explode immediately.

Chain 2 stride is now independently verified by the D6220 board,
which populates all three chains with `pa5ga[12]` distinct word-by-word
from the DSL-3580L and an asymmetric `maxp5ga0=(72,70,86,0)` (vs
DSL's symmetric `(76,76,76,76)`). The D6220 chain-2 block at 0x128
parses cleanly against the NVRAM oracle on every per-chain field,
which would not happen if 0x128 were off by even one word.

## Status table

| Patch constant            | Value  | Verified by                | bcmsrom_tbl.h cross-check |
|---------------------------|--------|----------------------------|---------------------------|
| `SSB_SPROM11_IL0MAC`      | 0x0090 | DSL-3580L (region zero), D6220 (region zero — same CFE-store pattern) | **collision with CCODE** — see Finding 1 |
| `SSB_SPROM11_ANTAVAIL`    | 0x00A0 | DSL-3580L + D6220 (same payload — non-degenerate confirmation pending) + bcm4360usb (aa2g=3, aa5g=3) | not yet read from canonical |
| `SSB_SPROM11_TXRXC`       | 0x00A8 | DSL-3580L + D6220 (same payload) + bcm4360usb | not yet read from canonical |
| `SSB_SPROM11_SUBBAND5GVER`| 0x00D6 | DSL-3580L + D6220 + bcm4360usb     | not yet read from canonical |
| `SSB_SPROM11_PDOFFSET40MA`| 0x00CA | DSL-3580L + D6220                  | not yet read from canonical |
| `SSB_SPROM11_PWR_INFO_*`  | stride 0x28 from 0xD8 | DSL-3580L (3 chains) + D6220 (3 chains, distinct per-chain values) + bcm4360usb (2 chains) | not yet read from canonical |
| `SSB_SPROM11_PWR_RXGAINS{0,1}` | 0x08 / 0x0A in chain block | bcm4360usb non-saturated triplets | encoding masks not yet read from canonical |
| `SSB_SPROM11_PWR_PA2GA`        | 0x02 | both vectors | — |
| `SSB_SPROM11_PWR_MAXP5GA`      | 0x0C | DSL-3580L + D6220 (asymmetric (72,70,86,0) on D6220) + bcm4360usb | — |
| `SSB_SPROM11_PWR_PA5GA`        | 0x10 | DSL-3580L + D6220 (distinct word-by-word from DSL across all 3 chains) + bcm4360usb | — |
| `SSB_SPROM11_CCKBW202GPO`      | 0x150 | DSL-3580L + D6220 | — |
| `SSB_SPROM11_MCSBW{20,40,80,160}5G{L,M,H}PO` | 0x150..0x190 stride 4 | DSL-3580L + D6220 (NVRAM lacks `mcsbw160*` keys → INFO, the 20/40/80 entries pass) | — |
| Reused `SSB_SPROM8_BOARDREV`   | 0x0082 | DSL-3580L + D6220 (different `boardrev` value) + bcm4360usb; canonical revmask `0xffffff00` covers rev 11 | confirmed reuse |
| Reused `SSB_SPROM8_CCODE`      | 0x0092 | both hardware vectors (passing only because both NVRAM ccode are empty) | **suspect — overlaps IL0MAC region** |

## How to fill the canonical column

This document deliberately does not embed a transcription of the
rev-11 entries from `bcmsrom_tbl.h`. The file is large and its rev-11
section was past the truncation point of every fetch attempted at
write-time of this harness. To populate the column locally:

1. Clone one of:
   - `https://github.com/RMerl/asuswrt-merlin` (`release/src-rt-7.x.main/src/include/bcmsrom_tbl.h`)
   - `https://android.googlesource.com/kernel/common.git` at the `bcmdhd-3.10` branch
   - `https://github.com/StreamUnlimited/broadcom-bcmdhd-4359` (`include/bcmsrom_tbl.h`)
2. Grep `bcmsrom_tbl.h` for entries whose `revmask` has bit 11 set, e.g.
   `0x00000800` (rev 11 only) or `0xfffff800` (rev 11+):
       grep -E '0x[0-9a-fA-F]*8[0-9a-fA-F]{2}\b' bcmsrom_tbl.h
3. For each entry whose name appears in this document's status table,
   resolve its `off` macro via `bcmsrom_fmt.h` (also in `include/`) into
   a word offset, multiply by 2 to get the byte offset, and compare
   against the patch's value.
4. Update the right-hand column of the status table with the result.
5. If the IL0MAC vs. CCODE collision (Finding 1) resolves to a bug in
   one of the two offsets, fix `ssb_regs.h` and the patch hunk
   accordingly, then re-run `make check && make check-bcm4360usb`.

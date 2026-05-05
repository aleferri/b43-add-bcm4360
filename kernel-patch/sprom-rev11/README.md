# SROM revision 11 support — draft patch

**Target tree:** `torvalds/linux` master at commit `6d35786`
(verified: `git apply --check` passes clean).
**Status:** *DRAFT — NOT FOR SUBMISSION.*

The patch is stored here as a single file:

```
0001-ssb-bcma-firmware-SROM-revision-11-support.patch
```

It is a single-file consolidation of three logically independent
changes that nevertheless need to land together to be useful (struct
extension, NVRAM-key path, raw SROM extractor). The earlier
incremental version of the series — three separate `git format-patch`
files — lives in `superseded/` for reference; once this draft
graduates the superseded directory should be removed.

It will be `git format-patch`'d and sent to
`linux-wireless@vger.kernel.org` only **after** at least one of the
open verification points below is closed. Sending unvalidated SROM
extraction code to mainline would be irresponsible — none of this
can be exercised end-to-end until a board with rev 11 SROM actually
completes `op_init` under b43, and several offset proposals cannot
be uniquely pinned from the single reference dump.

## Why this patch exists

`drivers/bcma/sprom.c` accepts SROM revision 11 at validation
(`bcma_sprom_valid` allows `revision <= 11` since 2015) but the only
extractor in mainline is `bcma_sprom_extract_r8`, which is called for
rev 11 inputs unchanged. The result is that rev-11-specific fields
(`rxgains*`, `mcsbw80*`, `pdoffset*`, `subband5gver`, the femctrl
block, the per-chain `pa5ga[12]` polynomial coefficients, etc.) are
never read from a rev 11 SROM and remain zero in `struct ssb_sprom`.
Any in-tree driver that needs those fields — including a future b43
ac-PHY backend — sees an effectively empty board calibration.

The complementary path, `drivers/firmware/broadcom/bcm47xx_sprom.c`
(NVRAM-key fallback for ARM/MIPS Broadcom router SoCs), has partial
rev 11 coverage: `mcsbw20*po`, `noiselvl*`, `rxgainerr*`, `cdd/stbc/
cck` are mapped, but `rxgains*`, `sb20in*`, `mcsbw80*/160*`,
`pdoffset*`, `subband5gver`, and the femctrl block have no NVRAM
mapping — and there is no `bcm47xx_fill_sprom_path_r11` to handle
the per-chain rev 11 arrays.

## What the patch covers

Per the commit message, three changes consolidated:

1. **`struct ssb_sprom` extension** — appended fields for rev-11
   coverage (per-band rxgains triplets, FEM/PA control block,
   mcsbw80*po / mcsbw160*po / mcslr*po, sb20in*/sb40and80 hr/lr
   matrix, dot11agdup{hr,lr}po, dot11agofdmhrbw202gpo /
   ofdmlrbw202gpo, per-chain pdoffset*ma). `struct
   ssb_sprom_core_pwr_info` gains rev-11-shaped maxp2ga, maxp5ga[4],
   pa2ga[3], pa5ga[12]. No offset shift on existing fields, no ABI
   break.

2. **`drivers/firmware/broadcom/bcm47xx_sprom.c` NVRAM mapping** —
   `bcm47xx_sprom_fill_auto` gets the rev-11-only `ENTRY()` lines,
   plus a new `bcm47xx_fill_sprom_path_r11` for the per-chain
   comma-separated arrays (`rxgains*`, `pa5ga[12]`, `maxp5ga[4]`).
   Mechanical extension of an existing pattern — same macro, same
   style.

3. **`drivers/bcma/sprom.c` raw extractor** — `bcma_sprom_extract_r11`
   selected from `bcma_sprom_get` when the SPROM revision word reads
   as 11. The extractor decodes:

   - shared header (boardrev, MAC, antennas, txchain/rxchain,
     antswitch) via the existing SSB_SPROM8_* offsets;
   - subband5gver at byte 0xD6;
   - per-chain power info blocks at 0xD8 / 0x100 / 0x128
     (stride 0x28), full layout including the rxgains pack;
   - the rxgains bit-packing
     `byte = (trelnabyp << 7) | (triso << 3) | elnagain` with
     byte→sub-band assignment `RXGAINS0 lo=5gm, hi=5gh; RXGAINS1
     lo=2g, hi=5gl(UNII-1)`. Verified by cross-reference of `wl
     srdump` against `wl nvram_dump`;
   - per-chain pdoffset40ma triplet at byte 0xCA;
   - the rev-11 power-per-rate region (byte 0x150..0x190): a layout
     that differs from rev 9 — each 5 GHz sub-band has four
     consecutive u32 entries (mcsbw20/40/80/160) rather than two,
     and a pair of u16 (dot11agofdmhrbw202gpo, ofdmlrbw202gpo) sits
     between the 2.4 GHz BW40 entry and the 5 GHz BW20 entries.

## Test vector reference

The DSL-3580L reference dump is committed in `router-data/` of this
repository:

```
router-data/dsl3580l/wl1_nvram.txt    — `wl -i wl1 nvram_dump` output
router-data/dsl3580l/wl1_srom_raw.txt — `wl -i wl1 srdump`     output
```

Every offset pinned in the patch has been derived by exact byte-match
of a NVRAM nominal value against the raw SROM byte stream of the same
board. Three categories of fit:

- **Unique value-match** (high confidence): for each named field
  there exists exactly one byte offset in the raw SROM whose bytes
  match the NVRAM-declared value, and the field's neighbours fit the
  expected struct layout. All offsets pinned in the patch are in
  this category.

- **Saturated/zero values, encoding fits across positions** (medium
  confidence): the rxgains bit-packing on the reference board has
  three of four bytes saturated (0xff or 0x00). The fourth byte
  (5gl=0xb3) uniquely fits `(b<<7)|(t<<3)|e` with the NVRAM-declared
  triplet (3,6,1). The encoding is committed because it fits all
  four observed bytes uniformly and matches every chain, but a
  second board with non-saturated 5gm/5gh and non-zero 2g rxgains
  would harden it further.

- **Region byte 0x190..0x1B0 reads all zero** (cannot disambiguate
  from a single dump): mcslr*po, sb20in40/sb20in80and160 hr/lr,
  sb40and80 hr/lr, dot11agdup{hr,lr}po, pdoffset80ma. Listed as
  TODO in the extractor; reachable only via the bcm47xx_sprom NVRAM
  fallback until a second rev-11 board pins the offsets.

## Open before sending upstream

1. **Cross-board confirmation of the v2 offset fixes for IL0MAC,
   ANTAVAIL, TXRXC.** v1 of this patch reused the `SSB_SPROM8_*`
   offsets for these three header fields. The offline harness in
   `harness/` (compiles the parser in userspace, diffs every
   populated field against `wl nvram_dump`) showed the rev-8
   offsets produce wrong values on the DSL-3580L: aa{2,5}g, txchain,
   rxchain, antswitch and the SROM-side MAC actually live at +4 / +6
   / +4 byte past the rev-8 positions. v2 introduces
   `SSB_SPROM11_IL0MAC=0x90`, `SSB_SPROM11_ANTAVAIL=0xA0`,
   `SSB_SPROM11_TXRXC=0xA8`, pinned on this single board; a second
   rev-11 dump pair would either confirm them or reveal further
   per-board variation.

2. Cross-board confirmation of:
   - rxgains decoding by reading registers `0x6f9/0x8f9/0xaf9` bits
     14:8 against the populator output for at least one sub-band
     change, *or* by collecting a `wl srdump`/`wl nvram_dump` pair
     on a second rev-11 board with non-saturated rxgains;
   - the all-zero region's offset assignment by collecting a dump
     pair on a second board with non-zero values in that region
     (`mcslr*po`, `sb20in*`, `sb40and80*`, `dot11agdup*po`,
     `pdoffset80ma`, plus the femctrl context block).

3. Bring-up reaches probe + RX path on UNII-1 ch.36 in the b43-ac
   scaffolding. This is the in-tree consumer that exercises the
   extractor end-to-end. The offline harness has already validated
   the decode side against `wl nvram_dump` as oracle (77 PASS / 0
   FAIL on the DSL-3580L); bring-up additionally validates that
   the consumer can act on those values, which is a different and
   independent check.

4. Hauke Mehrtens (bcm47xx maintainer) and Rafał Miłecki (bcma) are
   the natural reviewers. Rafał has historical context on SROM rev
   11 from the 2015 Ian Kent thread (the prior attempt that did not
   land). Reference that thread in the cover letter to avoid
   re-treading.

The harness lives in `harness/`; see its README for build/run and
for how to contribute a test vector from another board.

# BCM4352-family DMA translation quirk — patch

**Target tree:** `torvalds/linux` master, verified `git apply --check`
passes clean.
**Status:** *DRAFT — pending end-to-end bring-up confirmation on
DSL-3580L hardware.*

The patch is stored here as a single file:

```
0001-b43-dma-BCM4352-family-BCMA-quirk-for-DMA-translatio.patch
```

Single-hunk-conceptually change to `drivers/net/wireless/broadcom/b43/dma.c`
that overrides the DMA translation value and placement for BCM4352-family
chips on BCMA hosts (chip_id `0x4352`, device-ids including `0x43b3`
DSL-3580L). No change to shared bus code (`drivers/bcma/core.c` is
intentionally not touched).

## Why this patch exists

The first MVP bring-up attempt on the DSL-3580L (kernel-patch
scaffolding applied, sprom-rev11 patch applied, firmware loaded,
rxgain_init applied) crashes inside the b43 IRQ handler at the very
first DMA descriptor fetch:

```
b43-phy1: Loading firmware version 784.2 (2012-08-15 21:43:22)
b43-phy1: phy-ac: rxgain_init applied (2 cores, UNII-1 5gl, sprom rev 11)
b43-phy1 ERROR: Fatal DMA error: 0x00001000, 0x00000000, 0x00000000, \
                                  0x00000000, 0x00000000, 0x00000000
b43-phy1: Controller RESET (DMA error) ...
[loops]
```

Decoding (see `dma.c` mainline `B43_DMAIRQ_FATALMASK` and the
Broadcom DMA engine bit assignments inherited from N-PHY-era
`sb_dma.h`):

- `dma_reason[0] = 0x00001000` = bit 12 set = `I_DE`
  (Descriptor Error) on the **RX** engine (controller index 0).
- `dma_reason[1..5] = 0` — no TX channel has been used yet; the
  fatal fires before any `xmit` attempt.

The RX engine, after `b43_mac_enable()`, tries to fetch its first
descriptor from `RXRINGHI:RXRINGLO` and faults on the bus.

### What mainline b43 writes

`b43_dma_init()` on BCMA + DMA64 reads `BCMA_IOST` to confirm the
core advertises DMA64, then:

- `dma->translation = bcma_core_dma_translation(bdev)`
  → `BCMA_DMA_TRANSLATION_DMA64_CMT = 0x80000000` (per
  `drivers/bcma/core.c`, the `HOSTTYPE_PCI + DMA64` arm).
- `dma->translation_in_low = b43_dma_translation_in_low_word()`
  → `false` (the BCMA case is not in the SSB-only allow-list and
  falls through to `return false`).

`b43_dma_address()` then computes, with `dma_addr_t` being 32-bit
on the BCM63xx MIPS host (`upper_32_bits(dmaaddr) == 0`):

```
addrlo  = lower_32_bits(ringbase)                       (unchanged)
addrhi  = (0 & ~0xC0000000) | 0x80000000  =  0x80000000
addrext = (0 &  0xC0000000) >> 30          =  0
```

so `dmacontroller_setup()` writes

```
RXRINGLO = ringbase
RXRINGHI = 0x80000000
```

The chip emits PCIe master transactions toward `0x80000000_<ringbase>`.
The PCIe RC on the BCM63xx SoC has no inbound window that recognises
that 64-bit-CMT prefix; the transaction is master-aborted; the chip
surfaces it as `I_DE`.

### What the OEM blob writes

Static disassembly of `wlDSL-3580_EU.o_save` (D-Link DSL-3580L OEM
firmware 6.30) extracts:

- **`_dma_ddtable_init` @0x10678** unconditionally writes:
  ```
  RXRINGLO = ringbase + pi->translation_low      (offset 8 of rxd64 base)
  RXRINGHI = pi->translation_high                (offset 12)
  ```
  Same pattern for the TX path (offsets shifted by the rxd64/txd64
  base distinction). When the resulting address has its top 2 bits
  clear (the usual case for a 32-bit MIPS host), the addrext branch
  at `@0x10700` is skipped and the simple add-and-store path runs.

- **`dma_attach` @0x14860..0x14894** dispatches the
  `(translation_low, translation_high)` pair on `sih->chip` with an
  explicit allow-list:
  ```
  chipid ∈ { 0x4322, 0x10f6, 0xa8d5, 0xa8df, 0xa867, 0xa868, 0xa8d6 }
    → (translation_low, translation_high) = (0x80000000, 0)
  default — INCLUDING chip 0x4352  (4352-family) —
    → (translation_low, translation_high) = (0x40000000, 0)
  ```

So for the DSL-3580L (chipnum `0x4352`):

```
RXRINGLO = ringbase | 0x40000000      (low addr → "+" reduces to "|")
RXRINGHI = 0
```

The BCM63xx PCIe RC's inbound window recognises the `0x40000000`
prefix (the DMA32_CMT scheme) and translates it back to DRAM.

### Mapping back to b43

Two specific lines in `dma.c` need to be aware of the chip family:

| Concern | mainline today | what 4352-family needs |
|---|---|---|
| value of `dma->translation` | `bcma_core_dma_translation()` → `0x80000000` (`DMA64_CMT`) | `0x40000000` (`DMA32_CMT`) |
| placement (`translation_in_low`) | `false` (HIGH word) for any BCMA-DMA64 | `true` (LOW word) |

Both diverge from defaults that are correct for the chip families
`bcma_core_dma_translation()` was originally written for (BCM4322
on x86 PCIe and friends). The mainline behaviour stays the default;
the new behaviour is gated on `chip_id == 0x4352`.

## What the patch does

Two related changes in `drivers/net/wireless/broadcom/b43/dma.c`,
no other files touched:

1. **New static inline `b43_is_bcm4352_family(dev)`** — single
   predicate, used in both call sites for consistency. Block comment
   above it carries the provenance and the OEM disassembly offsets,
   so the rationale lives next to the gate.

2. **`b43_dma_translation_in_low_word()`** — extra check after the
   existing SSB special case: if 4352-family, return `true`. This
   moves the translation bits from the HIGH word into the LOW word
   in `b43_dma_address()`, and clears the HIGH word entirely on
   write (since `upper_32_bits(dma_addr_t)` is 0 on a 32-bit host).

3. **`b43_dma_init()`** — in the `case B43_BUS_BCMA:` arm, dispatch
   on `b43_is_bcm4352_family()` and substitute
   `BCMA_DMA_TRANSLATION_DMA32_CMT` for the value
   `bcma_core_dma_translation()` would have returned. All other
   chips on BCMA continue to use the function's return value
   unchanged.

`drivers/bcma/core.c` is **not** modified. Hard requirement: shared
bus-level code stays neutral; chip quirks live in the driver that
owns the chip.

## Verification status

- **Static**: patch applies clean against current `torvalds/master`
  (verified `git apply --check`).
- **Disassembly cross-check**: offsets `0x10678` (`_dma_ddtable_init`),
  `0x14860..0x14894` (`dma_attach` chip dispatch), and the
  `_dma_rxinit` call graph at `0x13354` re-extracted from
  `wlDSL-3580_EU.o_save` with `mips-linux-gnu-objdump -EB -dr`. The
  explicit allow-list `{ 0x4322, 0x10f6, 0xa8d5, 0xa8df, 0xa867,
  0xa868, 0xa8d6 }` is verbatim from `dma_attach @0x143f8..0x14444`.
- **Runtime (RX path)**: pending. The originating bug report
  (`Fatal DMA error: 0x00001000, 0x0, 0x0, 0x0, 0x0, 0x0` looping)
  is the one this patch is meant to clear. Expected confirmation:
  no fatal during `modprobe b43`, and `iw wlan1 scan freq 5180`
  returns beacons from the AP `D-Link DSL-3580L_5G` (BSSID
  `D8:FE:E3:E2:A1:3E`).
- **Runtime (TX path)**: pending. The same `dma->translation` value
  is consumed by `b43_dma_address()` for the TX ring setup
  (`b43_setup_dmaring(..., for_tx=1)` and the TX path in
  `dmacontroller_setup`). If the OEM `dma_attach` quirk holds
  symmetrically for TX — and the disassembly shows it does, the
  same `pi->translation_low/high` pair is consumed by `dma64_txinit`
  via `_dma_ddtable_init` — the patch covers TX as well, and the
  first associate-request DMA (post-scan) should go through clean.
  Cross-check: a second `Fatal DMA error` with
  `dma_reason[1..4] != 0` (i.e. on a TX channel rather than RX)
  after applying this patch would invalidate the symmetric
  assumption and point to a separate TX-side quirk.

## Apply order on the bring-up tree

This patch is independent of the `sprom-rev11/` patch. They touch
disjoint files (`drivers/net/wireless/broadcom/b43/dma.c` here vs
`drivers/{ssb,bcma}/sprom.c`, `drivers/firmware/broadcom/bcm47xx_sprom.c`,
`include/linux/ssb/ssb.h` for sprom-rev11) and either can be applied
first. In the recommended bring-up sequence on the DSL-3580L:

1. `sprom-rev11/0001-*.patch` — without it, `bcma_sprom_extract_r8`
   silently leaves the rev-11-only fields zero and the AC-PHY
   `rxgain_init` runs on uninitialised SROM data.
2. `dma-4352-translation/0001-*.patch` (this patch) — without it,
   even with a correctly populated SROM and `rxgain_init` applied,
   the controller faults on the first RX descriptor fetch.
3. The `kernel-patch/{new_files,existing_files}` AC-PHY scaffolding
   per `kernel-patch/README.md`.

## Open before sending upstream

1. **TX-path runtime confirmation**, per the verification matrix above.
   Until at least one associate cycle completes on the DSL-3580L,
   the symmetric-TX assumption stays as a TODO comment in the
   commit message rather than a verified claim.

2. **Second board cross-check.** The disassembly shows
   `dma_attach`'s chip dispatch reads `sih->chip` (not the PCI
   device id), so the same `(0x40000000, 0)` path applies to all
   4352-family chips: D6220 (BCM43b3, OEM 7.14.89), agcombo (BCM4360,
   OEM 7.14.43). Confirming the same fatal pattern disappears on
   either of those boards under the same patch would pin the chip
   family scope (rather than the DSL-3580L specifically).
   `router-data/d6220/` and `router-data/agcombo/` already carry
   the static dumps; bring-up on at least one of them gives the
   runtime side.

3. **Upstream framing.** The 4352-family chip-id check is empirically
   correct but the underlying mechanism — "the BCM63xx PCIe RC only
   advertises a DMA32_CMT inbound window" — would ideally be
   detected automatically rather than gated on the wireless chip
   id. Rafał Miłecki (bcma maintainer) would be the right reviewer
   for that discussion; framing this patch as a b43 workaround until
   a bus-level capability check exists is the pragmatic path.

The dma-4352-translation patch and the sprom-rev11 patch are the two
blockers between the kernel-patch scaffolding and a working probe.
With both applied, the next failure (if any) will surface during
either firmware ucode init, the rxgain table population, or the
first associate handshake — i.e. moves the conversation from "DMA
engine won't even fetch" to actual PHY/firmware bring-up territory.

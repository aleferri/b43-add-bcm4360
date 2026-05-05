# bcma_sprom_extract_r11 — offline differential test harness

Userspace harness that compiles `bcma_sprom_extract_r11()` from
`../0001-ssb-bcma-firmware-SROM-revision-11-support.patch` against a
small kernel shim and diffs every populated field against the matching
NVRAM nominal value. Validates the parser without needing to bring up
the radio: the comparison is between two independent decoders of the
same raw SROM (the new open-source parser vs. the Broadcom vendor
decoder that produced `nvram_dump`).

Used during the v1 → v2 round of the patch to pin down that
`SSB_SPROM8_IL0MAC/ANTAVAIL/TXRXC` are NOT correct for rev 11 on the
DSL-3580L, leading to the introduction of the
`SSB_SPROM11_IL0MAC/ANTAVAIL/TXRXC` constants in v2.

## Build and run

```
$ make                     # builds ./test
$ make check               # runs against ../../../router-data/wl1_*.txt
$ make check-bcm4360usb    # runs the synth-mode round-trip on the
                           # bcm4360usb reference NVRAM (see below)
```

To run against another vector:

```
$ ./test path/to/srom_dump.txt path/to/nvram_dump.txt
```

To run a NVRAM-only synth-mode round-trip on any wl1_nvram-style file:

```
$ ./test --synth path/to/nvram.txt
```

Output is line-per-field PASS/FAIL/INFO with a final summary. Exit
status is 0 if no FAIL occurred. Current state on the committed
DSL-3580L vector: 77 PASS, 0 FAIL, 2 INFO (the two INFO are
SROM-vs-NVRAM source divergences for `il0mac` and `country_code`,
both legitimate and explained inline in the output).

## Synth-mode round-trip (NVRAM-only second vector)

When a `wl srdump` is not available for a candidate board but its
nominal NVRAM is published (typically as a `defaultsromvars_*[]`
string in some vendor's `bcmsrom.c`), `--synth` synthesizes a raw
SROM image from the NVRAM using the patch's offsets/encoding, then
runs `extract_r11` against it. The diff against the original NVRAM
verifies:

- structural completeness — every NVRAM key the parser declares is
  recoverable;
- encoding self-consistency — bit packs/unpacks survive reflection,
  exposing off-by-one shifts on non-degenerate triplets the
  DSL-3580L's saturated values would mask;
- per-chain stride and per-band byte assignment within a chain
  block — populated chain mismatches FAIL immediately on stride
  errors.

What it does *not* do is cross-validate offsets against an external
source: synth and parse share offsets by construction. For canonical
checks against `bcmsrom_tbl.h`, see `../cross_check.md`.

The committed second vector is `vectors/bcm4360usb.nvram`, BCM4360
USB defaults from asuswrt-merlin / landonf/bhnd_nvram_fmt — same chip
family as the DSL-3580L target but with non-saturated `triso=9` and
`aa2g=3` populated. Running `make check-bcm4360usb` exercises the
2 GHz header path and the rxgains encoding on inputs the DSL-3580L
cannot reach.

The bcm4360usb run currently exposes one finding the single-board
test missed: `SSB_SPROM11_IL0MAC=0x90` and the reused
`SSB_SPROM8_CCODE=0x92` overlap on word 0x92, so a real rev-11 SROM
cannot store both fields at those offsets simultaneously. See
Finding 1 in `../cross_check.md`.

## Contributing a new test vector

The whole point of this harness is to let the OpenWrt / linux-wireless
community contribute dumps from other rev-11 boards without bring-up.
On a router with the Broadcom `wl` tool:

```
$ wl -i wl1 srdump     > srom_<board>.txt
$ wl -i wl1 nvram_dump > nvram_<board>.txt
$ ./test srom_<board>.txt nvram_<board>.txt
```

Post the output (and the dumps if you can share them) to the patch
thread on linux-wireless. Boards with any of the following are
particularly useful — see `../README.md` for the full priority list:

- non-zero values in the `0x190..0x1B0` region;
- non-saturated rxgains;
- chip variants other than BCM4352;
- contradictions to the `IL0MAC=0x90 / ANTAVAIL=0xA0 / TXRXC=0xA8`
  positions pinned in v2.

## Files

- `extract_r11.c` — the parser body, derived from the patch (see
  comment at top of the file for the explicit list of differences).
- `kernel_shim.h` — userspace shim: typedefs, `cpu_to_be16`,
  `BUILD_BUG_ON`, `ARRAY_SIZE`, and `SPOFF/SPEX/SPEX32` byte-identical
  to `drivers/bcma/sprom.c` upstream.
- `ssb_sprom.h` — minimal mock of `struct ssb_sprom` and
  `struct bcma_bus`.
- `ssb_regs.h` — `SSB_SPROM*` byte offsets, including the rev-11
  additions from v2 of the patch. Header documents which constants
  came from upstream verbatim and which were verified via sparse
  checkout.
- `data_load.{h,c}` — text parsers for the two dump files.
- `synth_srom.{h,c}` — encoder counterpart of `extract_r11`. Used by
  `--synth` mode to construct a raw SROM image from a NVRAM-only
  vector. Mirrors the parser's hand-written, bcma-style field handling
  per the patch series' commitment to that convention.
- `vectors/` — additional test vectors (NVRAM-only). `bcm4360usb.nvram`
  ships with the harness as the second reference vector.
- `test.c` — table of field checks plus the diff/summary driver.
  Supports both `srom+nvram` mode (default) and `--synth nvram` mode.
- `Makefile` — `make` builds, `make check` runs against the committed
  DSL-3580L vector at `../../../router-data/`, `make check-bcm4360usb`
  runs the bcm4360usb synth-mode round-trip.

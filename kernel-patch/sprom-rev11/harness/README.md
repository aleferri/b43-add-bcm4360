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
$ make            # builds ./test
$ make check      # runs against ../../../router-data/wl1_*.txt
```

To run against another vector:

```
$ ./test path/to/srom_dump.txt path/to/nvram_dump.txt
```

Output is line-per-field PASS/FAIL/INFO with a final summary. Exit
status is 0 if no FAIL occurred. Current state on the committed
DSL-3580L vector: 77 PASS, 0 FAIL, 2 INFO (the two INFO are
SROM-vs-NVRAM source divergences for `il0mac` and `country_code`,
both legitimate and explained inline in the output).

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
- `test.c` — table of field checks plus the diff/summary driver.
- `Makefile` — `make` builds, `make check` runs against the committed
  DSL-3580L vector at `../../../router-data/`.

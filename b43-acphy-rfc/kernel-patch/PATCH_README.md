# b43 AC-PHY scaffolding patch — README

This is **NOT a working driver**. It is a structured set of empty
functions, with comments that tell you exactly what each block of
register writes is supposed to do and where to look for the values.

## What the patch does

```
 drivers/net/wireless/broadcom/b43/Makefile        |   2 +
 drivers/net/wireless/broadcom/b43/phy_ac.c        | +449 -2
 drivers/net/wireless/broadcom/b43/phy_ac.h        |  +70
 drivers/net/wireless/broadcom/b43/radio_2069.c    |  +83 (new)
 drivers/net/wireless/broadcom/b43/radio_2069.h    |  +57 (new)
 drivers/net/wireless/broadcom/b43/tables_phy_ac.c |  +68 (new)
 drivers/net/wireless/broadcom/b43/tables_phy_ac.h |  +18 (new)
```

After applying you have:

* every `Must not be NULL` member of `struct b43_phy_operations`
  (per `phy_common.h`) populated — `init`, `prepare_structs`,
  `phy_read`, `phy_write`, `software_rfkill`, `switch_analog`,
  `switch_channel`;
* the file split into the same sections as `b43/phy_ht.c`;
* placeholder companion files for radio init/channel-table and
  PHY init tables;
* 28 TODOs, each pointing at a concrete next step.

The Kconfig dependency on `BROKEN` stays in place. The device will
still not Tx/Rx. It will, however, finish probe instead of crashing,
because the PHY ops the b43 core dereferences are no longer NULL.

## What the patch does NOT do

* Actually program the radio. `b43_radio_2069_init()` is a no-op.
* Switch channels for real. The channel table in `radio_2069.c` is
  empty, so `switch_channel()` returns `-ESRCH`.
* Load PHY tables. `b43_phy_ac_tables_init()` is a no-op.
* Provide the firmware. `ucode42`/`ac1initvals42` is still required
  from outside (and no open-source equivalent exists).

## Applicability

The line numbers in the `@@` headers are indicative. Apply with:

```
cd <linux>
git apply --3way --reject 0001-b43-AC-PHY-flesh-out-stubs.patch
```

If `--3way` complains about offsets, fall back to applying the new
files (radio_2069, tables_phy_ac) directly with `cp`, then apply the
`phy_ac.{c,h}` and `Makefile` hunks manually. The patch is meant to be
read more than blindly applied.

## Where to find the missing values

Suggested order of attack, easiest → hardest:

1. **Resolve the placeholder register offsets** (`0xFFFF` in
   `phy_ac.h`: RFCTL1, RF_SEQ_*, AFE_C{1,2}{,_OVER}, TEST). These can
   often be matched from `bcm-v4.sipsolutions.net` PHY register pages,
   or by tracing live MMIO writes from `wl.ko` with `mmiotrace`.

2. **Populate the channel table in `radio_2069.c`.** Every channel
   needs the BW1..BW6 PHY values and a per-core radio register set.
   The cleanest source is `wlc_phy_chanspec_radio2069_set()` in the
   open Broadcom hybrid `wl` source if you can locate a copy that
   still ships PHY code (most do not — that path is blob-only in
   newer hybrids).

3. **Populate the PHY init tables** in `tables_phy_ac.c`. Same
   provenance problem. If running in a VM with the wl driver, an
   MMIO trace during init captures every `(table_id, offset, value)`.

4. **Implement `radio_2069_init()`** in `radio_2069.c`. This is the
   PLL bring-up — equivalent of `b43_radio_2059_init()`.

5. **Fill in `b43_phy_ac_op_init()` phases (3) (4) (7) (9) (11)** in
   `phy_ac.c`. Phase (11) (TX power) is the largest and the one most
   likely to need SPROM rev-11 parsing fixes in `bcma`.

## Citations

* `phy_common.h` — definitive list of mandatory vs optional ops.
* `phy_ht.c`     — closest open b43-side template.
* `brcmsmac/phy/phy_n.c` — the only open Broadcom PHY init flow in
  mainline. AC inherits the *shape* of N's init (tables → AFE →
  classifier → idle TSSI cal → TX power setup → enable), not the values.
* Original 2015 stub: `linux-wireless` archive,
  `[PATCH] b43: AC-PHY: prepare place for developing new PHY support`,
  Rafał Miłecki, 25 Jan 2015.

## What this is honestly worth

This patch removes the NULL-deref crash and gives the file a shape.
That's it. The hard part — recovering the register values and the
channel/table data, and getting an open `ucode42` — is untouched.
Rafał Miłecki's 2015 estimate ("weeks or months") still stands; this
scaffolding shaves off perhaps a couple of days of "where do I even put
this" work for whoever picks it up.

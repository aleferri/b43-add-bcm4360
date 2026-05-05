# kernel-patch

Material to merge into the in-tree b43 driver to flesh out the AC-PHY
stub. **Not** a unified diff — `existing_files/` carries snippets
keyed by `INSERT IN ...` headers.

## Layout

```
kernel-patch/
├── README.md                       — this file
├── new_files/                      — drop into drivers/net/wireless/broadcom/b43/
│   ├── radio_2069.c                  (new file, ~83 lines)
│   ├── radio_2069.h                  (new file, ~57 lines)
│   ├── tables_phy_ac.c               (new file, 266 lines — bulk write
│   │                                   path + 3/24 rev0 tables populated)
│   └── tables_phy_ac.h               (new file, 23 lines)
└── existing_files/                 — additions snippets to merge by hand
    ├── Makefile.additions            (1 block)
    ├── phy_ac.h.additions            (7 blocks)
    └── phy_ac.c.additions            (11 blocks)
```

Files in `existing_files/` are **not** standalone source.  Each is a
sequence of code blocks; every block carries an `INSERT IN ...` header
naming an "AFTER existing line:" anchor and a "BEFORE existing line:"
anchor that you can grep for in the kernel tree.  The blocks are in
the order they should appear in the destination file.

## Assembly procedure

```sh
cd <linux-tree>
# 1. Drop in the four new files.
cp <bundle>/kernel-patch/new_files/*  drivers/net/wireless/broadcom/b43/

# 2. For each *.additions, walk it block by block and paste each block
#    between its anchor lines.
$EDITOR  drivers/net/wireless/broadcom/b43/Makefile
$EDITOR  drivers/net/wireless/broadcom/b43/phy_ac.h
$EDITOR  drivers/net/wireless/broadcom/b43/phy_ac.c

# 3. Build.  Kconfig CONFIG_B43_PHY_AC stays BROKEN; this is RFC
#    scaffolding and the device still won't TX/RX.
make M=drivers/net/wireless/broadcom/b43
```

A merge is a few minutes of paste-and-anchor-grep work.  No `git apply`
involved.

## What this scaffolding gets you

* Every `Must not be NULL` member of `struct b43_phy_operations` is
  populated (per `phy_common.h`): `init`, `prepare_structs`,
  `phy_read`, `phy_write`, `software_rfkill`, `switch_analog`,
  `switch_channel`.
* `phy_ac.c` is split into the same sections as `phy_ht.c` (Radio,
  RF, Various PHY ops, Channel switching, Basic PHY ops, R/W, ops
  struct).
* `tables_phy_ac.{c,h}` is wired end-to-end: `b43_actab_write_bulk()`
  writes through TABLE_ID/OFFSET/DATA_LO/DATA_HI; the descriptor
  array `b43_phy_ac_tables_rev0[]` carries 24 `TBL_POPULATED()`
  entries (no `TBL_TODO()` remaining), and `b43_phy_ac_tables_init()`
  walks the array under the table-write gate.
* `radio_2069.{c,h}` provides `b43_radio_2069_channel_setup()`
  (the inlined chanspec dispatcher) and the `channeltab_e_radio2069`
  schema. The 20-op power-on sequence `b43_radio_2069_init()` lives
  in `phy_ac.c.additions` and is invoked from `op_init`. The chantab
  carries 4 entries (UNII-1 channels 36/40/44/48), extracted by
  `extract_chan_tuning_2069_GE16.py --band 5g`.
* `b43_phy_ac_op_switch_channel()` gates at the band level: 2.4 GHz
  is rejected with -EOPNOTSUPP on this board (`aa2g=0`); 5 GHz is
  range-checked to UNII-1 (36..48) before reaching the chantab.
* The probe completes instead of crashing — the previous NULL-deref
  on `->init` and `->software_rfkill` is gone.

## What does NOT work

* **SPROM rev 11 parser** (blocker upstream of this scaffolding).
  This board's wl1 SROM is rev 11; mainline `drivers/ssb/sprom.c` and
  `drivers/bcma/sprom.c` reject it with `Unsupported SPROM revision: 11`
  before `op_init` is even called. Extending `struct ssb_sprom` and the
  rev 11 parser is prerequisite for everything below; see top-level
  `../README.md` §"Blocker #1".
* **RX gain table population** — `b43_phy_ac_rxgain_init()` runs but
  leaves tables 0x44/0x45 unpopulated. The new strategy (top-level
  README §"Strategia rxgain") is two-track and SROM-driven (no longer
  a runtime port of the ~600 MIPS instructions of
  `wlc_phy_rxgainctrl_set_gaintbls_acphy`):
  - **(a) Primary:** read `rxgains5g{,m,h}{elnagain,triso,trelnabyp}a*`
    from the rev 11–extended `struct ssb_sprom`, compute
    `gainctx[i] = (e + t + b) << 1` (working hypothesis from a single
    UNII-1 data-point — top-level README open question), feed the
    table writes.
  - **(b) Safety-net:** static `u16[]` capture of tables 0x44/0x45
    via `wl phytable` on the OEM blob with the chip associated to
    UNII-1 ch.36 OFDM 6 Mbit; A/B oracle for (a).

  Both tracks gate on the SPROM rev 11 parser (a needs the extended
  struct, b is independent but committed once we have a clean baseline
  to compare against).
* `wlc_phy_radio2069_rccal` (chip-agnostic) is referenced as TODO in
  the `software_rfkill` ON path — RC calibration not strictly
  required for the OFDM 6 Mbit MVP.
* Channels other than 36, 40, 44, 48 (UNII-1): `b43_chantab_r2069[]`
  covers only those four for the MVP. UNII-2/2e/3 are out of scope —
  empirically rejected by the OEM firmware on this hardware (working
  hypothesis: regulatory; see top-level README §"Implicazione
  fondamentale"). Adding more sub-bands is a re-run of
  `extract_chan_tuning_2069_GE16.py --band 5g` plus paste, gated on
  resolving the rejection upstream.
* 2.4 GHz on this board: impossible (`aa2g=0`). The chip family
  itself supports it; testing 2.4 GHz needs a different BCM4352
  board with antennas wired (e.g. consumer PCIe card).
  `b43_phy_ac_bphy_init()` is kept in `phy_ac.c.additions` BLOCK 8
  for that case but is dead code on the DSL-3580L.
* `ucode42`/`ac1initvals42` firmware still required from outside
  (see `firmware/` in this bundle for local extraction; for users,
  `firmware-b43-installer` distro path).

## Verified findings folded into this scaffolding

These are bits of analysis that have already been resolved on the
proprietary blob. Per-function disasm citations live as inline
comments at the call sites. For raw extraction outputs (per-chip
TSV/C and diff reports), see `../reverse-output/by-chip/`.

### num_cores (PHY reg 0x0B) and the per-core gate

`B43_PHY_AC_NUM_CORES` is kept as a compile-time `2` for static array
sizing.  The runtime hardware value lives in PHY register `0x0B`
masked with `0x07`, set during attach in the wl blob.

`tables_phy_ac.c` already gates the per-core descriptor entries
against the compile-time `NUM_CORES` via the `u8 core` field added to
`struct b43_phy_ac_table_desc` (sentinel `TBL_SHARED = 0xff` for
chip-wide tables).  When `num_cores` becomes a runtime field on
`struct b43_phy_ac`, replace the macro reference in the loop with
`dev->phy.ac->num_cores` — the descriptor field already carries the
right per-core information. Without this gate, populating the 9
`*_core2` entries on a 2x2 board would have written to inexistent
register pages.

### phytbl_info layout (verified, no swaps)

Descriptor is `[ptr, len, id, off, width]`, 5×u32, 20 bytes.  The
arrays in `reverse-output/acphy_tables_full.c` are extracted with
this layout and the comment headers (`id=…, len=…, off=…, width=…`)
are in the right order. The `.name` strings in the descriptor table
match (without the `acphy_` prefix and `_rev0` suffix) the symbol
names in `reverse-output/acphy_tables_index.txt`.

### PHY-table-write gate (reg 0x19E, bit 0x0002)

The wl blob wraps every PHY-table write and every RF-control override
in this exact sequence:

```
saved = phy_reg_read(0x19E)
phy_reg_mod(0x19E, mask=0x0002, val=0x0002)   /* set bit 0x2 */
... do the writes ...
phy_reg_mod(0x19E, mask=0x0002, val=saved & 0x0002)   /* restore */
```

The two helpers `b43_phy_ac_tbl_write_lock()` /
`b43_phy_ac_tbl_write_unlock()` in `tables_phy_ac.c` implement this.
They are file-local for now — the only current caller is
`b43_phy_ac_tables_init` itself.  When the rfctrl_override family
lands in `phy_ac.c` (also a caller in the wl source) they will be
promoted to a shared header.

The naming `TBL_WRITE_GATE` is a working label.  The exact hardware
semantic ("PHY clock freeze" / "table-write enable" / "override
gate") is not confirmed and would need an MMIO trace; for the
mechanical implementation, the name is irrelevant — the call
sequence is unambiguous.

### `0xFFFF` register-define safety

Two PHY register offsets remain unidentified
(`B43_PHY_AC_TEST`, `B43_PHY_AC_RF_SEQ_MODE`).  Rather than carrying
them as `0xFFFF` placeholders — which compile silently and would
silently access a real PHY register at offset `0xFFFF` — the
`#define`s are commented out (`/* #define ... 0x???? */`) with a
block of explanation inline.  As a runtime backstop,
`b43_phy_ac_op_read` and `b43_phy_ac_op_write` assert
`B43_WARN_ON(reg == 0xFFFF)` so any literal that slips through is
caught at runtime instead of corrupting register 0xFFFF.  Same
choice for `R2069_C1`/`C2`/`ALL` in `radio_2069.h` (used only for
cluster2, itself a TODO).

## Citations

* `phy_common.h` — definitive list of mandatory vs optional ops.
* `phy_ht.c`     — closest open b43-side template.
* `brcmsmac/phy/phy_n.c` — the only open Broadcom PHY init flow in
  mainline.  AC inherits the *shape* of N's init (tables → AFE →
  classifier → idle TSSI cal → TX power setup → enable), not the
  values.
* Original 2015 stub: `linux-wireless` archive,
  `[PATCH] b43: AC-PHY: prepare place for developing new PHY support`,
  Rafał Miłecki, 25 Jan 2015.

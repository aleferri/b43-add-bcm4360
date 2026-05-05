// SPDX-License-Identifier: GPL-2.0-or-later
/*
 * Broadcom B43 wireless driver
 * AC-PHY RX gain init: port of wlc_phy_rxgainctrl_set_gaintbls_acphy
 * (wlDSL-3580_EU.o_save @0x4285c).
 *
 * Scope: 5 GHz UNII-1, "default" chip-id path (i.e. NOT 0x4360 / 0x4352;
 * 0x43b3 lands here). 2.4 GHz path is included as dead code under
 * __maybe_unused for boards with aa2g != 0.
 *
 * What runs:
 *   - outer RFCTL1 + table-write gate bracket;
 *   - per-core: 3 phy_reg_mod (gainctx-driven), 4 chip-pinned phy_reg_write,
 *     scaffolded 0x44/0x45 table writes (resolver currently NULL → no
 *     writes), trailing reg-649 mod for core > 0;
 *   - epilogue: pin RFCTL1=364, restore gates.
 *
 * What does NOT run yet: the body of b43_phy_ac_rxgain_tbl_source().
 * See its comment block.
 *
 * Cross-refs in the repo:
 *   reverse-output/rxgain/{00_INDEX.md, 03_disasm_annotated.txt,
 *                          04_call_inventory.txt}
 *   top-level README.md §"Strategia rxgain rivista"
 */

#include "b43.h"
#include "phy_ac.h"
#include "tables_phy_ac.h"

/**************************************************
 * Base constants from .rodata 0x17758..0x177b8
 **************************************************/

/* 2.4 GHz block (dead on aa2g=0 boards). */
static const u8 b43_phy_ac_rxgain_const2_2g[12] __maybe_unused = {
	0x02, 0x02, 0x02, 0x02, 0x02, 0x02, 0x02, 0x02, 0x02, 0x02, 0x00, 0x00,
};
static const u8 b43_phy_ac_rxgain_const7_2g[12] __maybe_unused = {
	0x07, 0x07, 0x07, 0x07, 0x07, 0x07, 0x07, 0x07, 0x07, 0x07, 0x00, 0x00,
};
static const s8 b43_phy_ac_rxgain_delta0_2g[8] __maybe_unused = {
	-8, -8, -5, -2,  2,  5,  9,  0,
};
static const s8 b43_phy_ac_rxgain_delta1_2g[8] __maybe_unused = {
	-5, -5,  1,  7, 13, 20,  0,  0,
};
static const s8 b43_phy_ac_rxgain_delta2_2g[8] __maybe_unused = {
	-3, -3,  3,  9, 15, 22,  0,  0,
};
static const s8 b43_phy_ac_rxgain_delta3_2g[8] __maybe_unused = {
	-2, -2,  4, 10, 16, 23,  0,  0,
};

/* 5 GHz block (active band). */
static const u8 b43_phy_ac_rxgain_const2_5g[12] __maybe_unused = {
	0x02, 0x02, 0x02, 0x02, 0x02, 0x02, 0x02, 0x02, 0x02, 0x02, 0x00, 0x00,
};
static const u8 b43_phy_ac_rxgain_const3_5g[12] __maybe_unused = {
	0x03, 0x03, 0x03, 0x03, 0x03, 0x03, 0x03, 0x03, 0x03, 0x03, 0x00, 0x00,
};
static const s8 b43_phy_ac_rxgain_delta0_5g[8] __maybe_unused = {
	-8, -8, -4, -1,  2,  5,  9,  0,
};
static const s8 b43_phy_ac_rxgain_delta1_5g[8] __maybe_unused = {
	-1, -1,  6, 12, 18, 25,  0,  0,
};

/**************************************************
 * Per-core phy_reg_write sequence (default chipid)
 **************************************************/

/*
 * Fixed immediates from the blob's per-core loop. {4360, 4352} family
 * uses page-1 mirrors (0x173b/0x1726).
 */
struct b43_phy_ac_rxgain_chip_write {
	u16 reg;
	u16 val;
};

static const struct b43_phy_ac_rxgain_chip_write
b43_phy_ac_rxgain_chip_writes_default[4] = {
	{ 0x073b, 24 },
	{ 0x0726, 12 },
	{ 0x073b, 44 },
	{ 0x0726, 12 },
};

/**************************************************
 * Tables 0x44 / 0x45 writes — scaffolding
 **************************************************/

/*
 * The 10 per-core wlc_phy_table_write_acphy calls (all width=8). Lifted
 * from reverse-output/rxgain/04_call_inventory.txt; addresses are the
 * disasm low-byte for cross-ref. Items 7..9 are a second pass after the
 * chip-id check pair @0x42f74/0x42fa0.
 *
 * The OOL tail @0x430dc (id=0x0b, len=3, off=11) is reached via
 * tail-call from elsewhere in the blob and is NOT scaffolded here —
 * add it when an op-trace confirms it runs on this board.
 */
struct b43_phy_ac_rxgain_tbl_write {
	u16 id;
	u16 offset;
	u8  len;
	u8  blob_addr_lo;
};

static const struct b43_phy_ac_rxgain_tbl_write
b43_phy_ac_rxgain_tbl_writes_5g[10] = {
	{ 0x44,   0,   2,  0x5c },	/* @0x42b5c */
	{ 0x44,   8,   6,  0xf8 },	/* @0x42bf8 */
	{ 0x44,  16,   7,  0x94 },	/* @0x42c94 */
	{ 0x44,  32,  10,  0xb4 },	/* @0x42cb4 */
	{ 0x45,  32,  10,  0xd4 },	/* @0x42cd4 */
	{ 0x45,   8,   1,  0x20 },	/* @0x42d20 */
	{ 0x45,  16,   1,  0x40 },	/* @0x42d40 */
	{ 0x44,  16,   7,  0xe8 },	/* @0x42fe8  -- second pass */
	{ 0x44,  32,  10,  0x08 },	/* @0x43008 */
	{ 0x45,  32,  10,  0x28 },	/* @0x43028 */
};

/*
 * Source resolver for one rxgain table write. Returns NULL to skip.
 *
 * Inputs to the eventual body (per-core, see file header & README):
 *   - rxgains_5gl from the SROM (elnagain, triso, trelnabyp)[core];
 *   - @core_gainctx = (rxgains.triso[core] + 4) << 1, the cached byte
 *     that set_gaintbls_acphy reads at pi+168 + 911 + 3*core;
 *   - block_B base/delta arrays declared above.
 *
 * Wiring strategies (top-level README §"Strategia rxgain rivista"):
 *   (a) runtime populator combining the inputs above per the blob's
 *       per-core flow (8 table_read + 9 memcpy + 10 table_write);
 *   (b) static `wl phytable` capture of 0x44/0x45 on the OEM blob,
 *       indexed by (id, offset, len).
 *
 * Open question: whether the second pass (descriptor entries 7..9)
 * is additive or strict re-write. Disambiguate from a `wl phytable`
 * capture before committing (a).
 */
static const u8 *
b43_phy_ac_rxgain_tbl_source(const struct b43_phy_ac_rxgain_tbl_write *w,
			     unsigned int core,
			     u16 core_gainctx)
{
	(void)w;
	(void)core;
	(void)core_gainctx;
	return NULL;
}

static void
b43_phy_ac_rxgain_table_writes(struct b43_wldev *dev,
			       unsigned int core,
			       u16 core_gainctx)
{
	size_t i;

	for (i = 0; i < ARRAY_SIZE(b43_phy_ac_rxgain_tbl_writes_5g); i++) {
		const struct b43_phy_ac_rxgain_tbl_write *w =
			&b43_phy_ac_rxgain_tbl_writes_5g[i];
		const u8 *src = b43_phy_ac_rxgain_tbl_source(w, core,
							     core_gainctx);

		if (!src)
			continue;
		b43_actab_write_bulk(dev, w->id, w->offset, 8, w->len, src);
	}
}

/**************************************************
 * RX gain init
 **************************************************/

#define RXGAIN_RFCTL_GATE_BIT	0x0002

void b43_phy_ac_rxgain_init(struct b43_wldev *dev)
{
	const struct ssb_sprom *sprom = dev->dev->bus_sprom;
	const struct ssb_sprom_rxgains *rxgains;
	u16 saved_tblwr, saved_rfctl;
	unsigned int core;
	size_t i;

	saved_tblwr = b43_phy_ac_tbl_write_lock(dev);
	saved_rfctl = b43_phy_read(dev, B43_PHY_AC_RFCTL1);
	b43_phy_set(dev, B43_PHY_AC_RFCTL1, RXGAIN_RFCTL_GATE_BIT);

	/*
	 * MVP target is UNII-1 only. When op_switch_channel widens to
	 * UNII-2/3, dispatch on dev->phy.channel (or phy[218]&0x3800
	 * like the blob) to pick rxgains_5g{m,h}.
	 */
	rxgains = &sprom->rxgains_5gl;

	for (core = 0; core < B43_PHY_AC_NUM_CORES; core++) {
		/*
		 * gainctx = (rxgains.triso[core] + 4) << 1
		 * Verified at wlc_phy_attach_acphy @0x46a48..0x46a5c (5g
		 * triso store @offset 796). The cache byte at pi+168 + 911
		 * + 3*core is what the three target regs read back.
		 *
		 * elnagain and trelnabyp are also cached (offsets 910, 912)
		 * but feed b43_phy_ac_rxgain_tbl_source(), not these.
		 */
		u8 triso = rxgains->triso[core];
		u16 gainctx = (u16)((triso + 4) << 1);

		b43_phy_maskset(dev, 1785, (u16)~0x7f00,
				(u16)(gainctx << 8));
		b43_phy_maskset(dev, 2297, (u16)~0x7f00,
				(u16)(gainctx << 8));
		b43_phy_maskset(dev, 2809, (u16)~0x7f00,
				(u16)(gainctx << 8));

		for (i = 0; i < ARRAY_SIZE(b43_phy_ac_rxgain_chip_writes_default); i++) {
			const struct b43_phy_ac_rxgain_chip_write *w =
				&b43_phy_ac_rxgain_chip_writes_default[i];

			b43_phy_write(dev, w->reg, w->val);
		}

		b43_phy_ac_rxgain_table_writes(dev, core, gainctx);

		/* Reg 649 only fires for core > 0 in the blob (@0x42f3c). */
		if (core > 0)
			b43_phy_maskset(dev, 649, (u16)~0x7f00,
					(u16)(gainctx << 8));
	}

	/* Pin RFCTL1=364 (verified @0x43084), restore gates. */
	b43_phy_write(dev, B43_PHY_AC_RFCTL1, 364);
	b43_phy_maskset(dev, B43_PHY_AC_RFCTL1,
			(u16)~RXGAIN_RFCTL_GATE_BIT,
			saved_rfctl & RXGAIN_RFCTL_GATE_BIT);

	b43_phy_ac_tbl_write_unlock(dev, saved_tblwr);

	b43dbg(dev->wl,
	       "phy-ac: rxgain_init run (%u cores, UNII-1, sprom rev %u; 0x44/0x45 inert)\n",
	       (unsigned int)B43_PHY_AC_NUM_CORES,
	       (unsigned int)sprom->revision);
}

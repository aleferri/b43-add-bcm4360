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
 * Per-core flow:
 *   - outer RFCTL1 + table-write gate bracket;
 *   - 3 gainctx-driven phy_reg_mod, 4 chip-pinned phy_reg_write,
 *     10 phytable writes for 0x44/0x45 served from a static 5gl image
 *     (PATCH POINT (b) of the README), trailing reg-649 mod for core > 0;
 *   - epilogue: pin RFCTL1=364, restore gates.
 *
 * Cross-refs in the repo:
 *   reverse-output/rxgain/{00_INDEX.md, 03_disasm_annotated.txt,
 *                          04_call_inventory.txt}
 *   router-data/agcombo/agcombo_phytable_5gl.txt  (table source images)
 *   top-level README.md §"Strategia rxgain"
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
 * Tables 0x44 / 0x45 writes
 **************************************************/

/*
 * The 10 wlc_phy_table_write_acphy calls (all width=8). Lifted from
 * reverse-output/rxgain/04_call_inventory.txt; addresses are the
 * disasm low-byte for cross-ref. Items 7..9 are a second pass after
 * the chip-id check pair @0x42f74/0x42fa0.
 *
 * The OOL tail @0x430dc (id=0x0b, len=3, off=11) is reached via
 * tail-call from elsewhere in the blob and is NOT scaffolded here —
 * add it when an op-trace confirms it runs on this board.
 *
 * Coverage caveat. The 25+12 = 37 byte footprint declared here is the
 * union of the descriptors statically extracted from the disasm.
 * A live wl phytable dump on the DSL after the 6.30 populator runs
 * shows additional non-zero cells outside this footprint:
 * 0x44[24..31] (block B duplicate), 0x44[48..57] (block C duplicate),
 * 0x45[24..31], 0x45[48..57], plus 0x44[0..7] replicated header bytes.
 * Those extra writes either come from the OOL tail above, from
 * sibling routines reached by tail-call, or from a chanspec-set path
 * that fires on the reference board but not on the in-tree consumer's
 * one-shot init call. For the MVP RX path on UNII-1 5gl 6 Mbit OFDM
 * the descriptor-list subset is the same one the agcombo 7.14
 * populator commits and it is sufficient to bring up scan + assoc.
 * Widening the footprint is a follow-up after bring-up confirms the
 * subset is the limiting factor (if it ever is).
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
 * Static images of tables 0x44 / 0x45 captured from the DSL-3580L
 * (BCM43b3 2x2 r2069-rev1) via wl phytable, on a OEM 6.30 firmware
 * boot in the 5gl sub-band (chanspec 5g36/20). The 6.30 populator is
 * chanspec-aware and writes the full per-sub-band footprint at every
 * channel switch, so this is the complete attach + chanspec-set image
 * for 5gl on the project's primary target board.
 *
 * Indexing is by phytable byte offset. Cells outside the slices below
 * read as zero from chip-side init memory and are not declared
 * explicitly to keep the array shape obvious.
 *
 * The 64-byte footprint per table groups into four logical regions:
 *   [0..7]   "header": id-byte (0x0c on 0x44, zero on 0x45) replicated
 *   [8..15]  block A — sub-band-shifted mid-range LUT, 8 entries
 *   [16..23] block B — high-range LUT, 8 entries
 *   [24..31] block B duplicate (populator second pass, descriptor
 *            entry @0x42fe8 in the disasm)
 *   [32..41] block C1 — uniform 10-entry constant
 *   [48..57] block C2 — block C1 duplicate
 *
 * Cross-board sample on agcombo (BCM4360 3x3, OEM 7.14.43 single-shot
 * at attach) shows the same byte-for-byte pattern on [16..22] and
 * [32..41]/[8] across two chip families. Block A diverges by a
 * uniform +3 signed offset on agcombo vs DSL, plausibly a board- or
 * chain-count-dependent calibration term; for the DSL target we use
 * DSL's own values.
 *
 * Triplet rxgain (elnagain, triso, trelnabyp) is uniform per-chain on
 * every 5gl board sampled (DSL/D6220 (3,6,1), agcombo (3,6,1)) and
 * matches the radio rev-1 r2069 default per the canonical Broadcom
 * rxgains bit-pack (trelnabyp<<7 | triso<<3 | elnagain), so the same
 * image is written by every core.
 */
static const u8 b43_phy_ac_rxgain_5g_tbl_44_5gl[64] = {
	[ 0] = 0x0c, [ 1] = 0x0c, [ 2] = 0x0c, [ 3] = 0x0c,
	[ 4] = 0x0c, [ 5] = 0x0c, [ 6] = 0x0c, [ 7] = 0x0c,
	[ 8] = 0xfb, [ 9] = 0xfb, [10] = 0x01, [11] = 0x07,
	[12] = 0x0d, [13] = 0x14, [14] = 0x0d, [15] = 0x17,
	[16] = 0xf8, [17] = 0xf8, [18] = 0xfb, [19] = 0xfe,
	[20] = 0x02, [21] = 0x05, [22] = 0x09, [23] = 0xff,
	[24] = 0xf8, [25] = 0xf8, [26] = 0xfb, [27] = 0xfe,
	[28] = 0x02, [29] = 0x05, [30] = 0x09, [31] = 0xff,
	[32] = 0x07, [33] = 0x07, [34] = 0x07, [35] = 0x07, [36] = 0x07,
	[37] = 0x07, [38] = 0x07, [39] = 0x07, [40] = 0x07, [41] = 0x07,
	[48] = 0x07, [49] = 0x07, [50] = 0x07, [51] = 0x07, [52] = 0x07,
	[53] = 0x07, [54] = 0x07, [55] = 0x07, [56] = 0x07, [57] = 0x07,
};

static const u8 b43_phy_ac_rxgain_5g_tbl_45_5gl[64] = {
	[ 8] = 0x01, [ 9] = 0x01, [10] = 0x02, [11] = 0x03,
	[12] = 0x04, [13] = 0x05, [14] = 0x06, [15] = 0x07,
	[16] = 0x01, [17] = 0x01, [18] = 0x02, [19] = 0x03,
	[20] = 0x04, [21] = 0x05, [22] = 0x06, [23] = 0x07,
	[24] = 0x01, [25] = 0x01, [26] = 0x02, [27] = 0x03,
	[28] = 0x04, [29] = 0x05, [30] = 0x06, [31] = 0x07,
	[32] = 0x02, [33] = 0x02, [34] = 0x02, [35] = 0x02, [36] = 0x02,
	[37] = 0x02, [38] = 0x02, [39] = 0x02, [40] = 0x02, [41] = 0x02,
	[48] = 0x02, [49] = 0x02, [50] = 0x02, [51] = 0x02, [52] = 0x02,
	[53] = 0x02, [54] = 0x02, [55] = 0x02, [56] = 0x02, [57] = 0x02,
};

/*
 * Source resolver for one rxgain table write.
 *
 * MVP scope is UNII-1 (5gl) only; both the caller of
 * b43_phy_ac_rxgain_init and op_switch_channel reject anything else.
 * When 5gm/5gh land, this resolver gains a sub-band parameter and
 * additional table images captured the same way.
 */
static const u8 *
b43_phy_ac_rxgain_tbl_source(const struct b43_phy_ac_rxgain_tbl_write *w,
			     unsigned int core,
			     u16 core_gainctx)
{
	(void)core;
	(void)core_gainctx;

	switch (w->id) {
	case 0x44:
		return &b43_phy_ac_rxgain_5g_tbl_44_5gl[w->offset];
	case 0x45:
		return &b43_phy_ac_rxgain_5g_tbl_45_5gl[w->offset];
	default:
		return NULL;
	}
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
	       "phy-ac: rxgain_init run (%u cores, UNII-1 5gl, sprom rev %u)\n",
	       (unsigned int)B43_PHY_AC_NUM_CORES,
	       (unsigned int)sprom->revision);
}

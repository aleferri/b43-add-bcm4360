// SPDX-License-Identifier: GPL-2.0-or-later
/*
 * Broadcom B43 wireless driver
 * 2069 radio — per-channel tuning table, lookup, and apply.
 *
 * The 2069 is the radio paired with the AC-PHY in the BCM4352 family
 * (chip-id space {0x4352, 0x4348, 0x4333, 0x43A2, 0x43B0, 0x43B3}).
 * The current target of this scaffold is the DSL-3580L (chip 0x43b3,
 * 2x2 MIMO).
 *
 * MVP scope on this board: 5 GHz UNII-1 only (channels 36/40/44/48).
 * The DSL-3580L wl1 SROM declares aa2g=0 (no 2.4 GHz antennas wired);
 * empirically, `wl chanspec 2g6/20` is rejected on this hardware. The
 * 2.4 GHz coverage of the unit is provided by wl0 (BCM6362, N-PHY,
 * out of scope). UNII-2/2e/3 are also rejected by the OEM firmware
 * (working hypothesis: regulatory; see top-level README,
 * §"Implicazione fondamentale"); UNII-1 is the only sub-band reliably
 * reachable for bring-up.
 *
 * The static table b43_chantab_r2069[] below was extracted from
 * `chan_tuning_2069rev_GE16` in the D-Link DSL-3580 GPL drop wl ELF
 * by reverse-tools/extract_chan_tuning_2069_GE16.py --band 5g.
 * The blob stores 77 entries of 94 bytes each (47 u16): channel,
 * freq, 39 u16 of radio register payload, then 6 u16 of BW filter
 * coefficients.
 *
 * The dispatcher that maps each of those u16 to a 2069 register
 * address was found in the same blob, INLINED inside
 * wlc_phy_chanspec_set_acphy() at 0x50d9c (no separate
 * wlc_phy_chanspec_radio2069_setup function exists for this radio,
 * unlike 2055/2056/2057/20671). The mapping below mirrors cluster1
 * of that function (range 0x50f24..0x51664), which executes for all
 * chip variants and covers all 45 write_radio_reg() calls — the full
 * radio_raw[39] plus bw1..bw6.
 *
 * Two further programming passes exist in the blob:
 *   - cluster2 (0x52130..0x52718): writes the same offsets to a
 *     different set of register addresses, presumably the "core 1"
 *     companion registers in 3-chain MIMO. Not needed for the
 *     single-stream MVP target (6 Mbps OFDM on channel 36); still TODO.
 *   - block s5 (0x529ac..0x52a08): writes bw1..bw6 to PHY registers
 *     0x0371..0x0376 via phy_reg_write. Statically unreachable on
 *     0x43b3 — gate `pi[0xc0] == 2` is never true (pi[0xc0] holds
 *     the PCI device ID, never the literal 2). Not emitted.
 *
 * See reverse-output/r2069_chan_writes_map.txt for the per-write audit.
 */

#include "b43.h"
#include "phy_ac.h"
#include "radio_2069.h"

static const struct b43_phy_ac_channeltab_e_radio2069
b43_chantab_r2069[] = {
	{ /* chan  36, 5180 MHz — primary MVP target (UNII-1) */
		.channel = 36,
		.freq    = 5180,
		.phy_regs = {
			.bw1 = 0x081c, .bw2 = 0x0818, .bw3 = 0x0814,
			.bw4 = 0x01f9, .bw5 = 0x01fa, .bw6 = 0x01fb,
		},
		.radio_raw = {
			0x0005, 0x001c, 0x0a09, 0x0d85, 0x00b8, 0xab94,
			0x02e2, 0xae51, 0x0000, 0x0488, 0x0cf8, 0x0000,
			0x000b, 0x1d6f, 0x1f00, 0x0780, 0x0000, 0x0000,
			0x049c, 0x3507, 0x0005, 0x0005, 0x0637, 0xffff,
			0xffff, 0xd268, 0x0001, 0x0000, 0x2000, 0x007f,
			0x0000, 0x0070, 0x00bb, 0x0555, 0x0099, 0x0068,
			0x0fac, 0xf0ff, 0x18ce,
		},
	},
	{ /* chan  40, 5200 MHz */
		.channel = 40,
		.freq    = 5200,
		.phy_regs = {
			.bw1 = 0x0824, .bw2 = 0x0820, .bw3 = 0x081c,
			.bw4 = 0x01f7, .bw5 = 0x01f8, .bw6 = 0x01f9,
		},
		.radio_raw = {
			0x0005, 0x001c, 0x0a09, 0x0d93, 0x00b9, 0x621c,
			0x02e5, 0x8871, 0x0000, 0x0488, 0x0cf8, 0x0000,
			0x000b, 0x1d6f, 0x1f00, 0x0780, 0x0000, 0x0000,
			0x049c, 0x3507, 0x0005, 0x0005, 0x0637, 0xffff,
			0xffff, 0xd268, 0x0001, 0x0000, 0x2000, 0x007f,
			0x0000, 0x0070, 0x00ab, 0x0444, 0x0099, 0x0067,
			0x0eac, 0xe0ff, 0x18ce,
		},
	},
	{ /* chan  44, 5220 MHz */
		.channel = 44,
		.freq    = 5220,
		.phy_regs = {
			.bw1 = 0x082c, .bw2 = 0x0828, .bw3 = 0x0824,
			.bw4 = 0x01f5, .bw5 = 0x01f6, .bw6 = 0x01f7,
		},
		.radio_raw = {
			0x0005, 0x001c, 0x0a09, 0x0da1, 0x00ba, 0x18a4,
			0x02e8, 0x6291, 0x0000, 0x0488, 0x0cf8, 0x0000,
			0x000b, 0x1d6f, 0x1f00, 0x0780, 0x0000, 0x0000,
			0x049c, 0x3507, 0x0005, 0x0005, 0x0638, 0xffff,
			0xffff, 0xd268, 0x0001, 0x0000, 0x2000, 0x007f,
			0x0000, 0x0070, 0x00aa, 0x0333, 0x0099, 0x0057,
			0x0eac, 0xe0ff, 0x18cd,
		},
	},
	{ /* chan  48, 5240 MHz */
		.channel = 48,
		.freq    = 5240,
		.phy_regs = {
			.bw1 = 0x0834, .bw2 = 0x0830, .bw3 = 0x082c,
			.bw4 = 0x01f3, .bw5 = 0x01f4, .bw6 = 0x01f5,
		},
		.radio_raw = {
			0x0005, 0x001c, 0x0a09, 0x0dad, 0x00ba, 0xcf2c,
			0x02eb, 0x3cb1, 0x0000, 0x0488, 0x0cf8, 0x0000,
			0x000b, 0x1d6f, 0x1f00, 0x0780, 0x0000, 0x0000,
			0x049c, 0x3507, 0x0005, 0x0005, 0x0638, 0xffff,
			0xffff, 0xd268, 0x0001, 0x0000, 0x2000, 0x007f,
			0x0000, 0x0070, 0x009a, 0x0222, 0x0099, 0x0057,
			0x0dac, 0xd0ff, 0x18cd,
		},
	},
};

const struct b43_phy_ac_channeltab_e_radio2069 *
b43_phy_ac_get_channeltab_e_r2069(struct b43_wldev *dev, u16 freq)
{
	unsigned int i;

	(void)dev;
	for (i = 0; i < ARRAY_SIZE(b43_chantab_r2069); i++) {
		if (b43_chantab_r2069[i].freq == freq)
			return &b43_chantab_r2069[i];
	}
	return NULL;
}

/*
 * Per-entry write list. Each row maps a slot of the channel-table
 * entry to the 2069 register address that consumes it. Order matches
 * the blob's execution order in wlc_phy_chanspec_set_acphy() cluster1
 * (file offsets 0x50f24..0x51664). All writes go through
 * b43_radio_write — even the bw1..bw6 entries, which despite their
 * "phy_regs" location in the struct end up at radio addresses on this
 * code path.
 */
struct r2069_chan_write {
	u16 reg;     /* 2069 radio register address */
	s16 raw_idx; /* index into entry->radio_raw[], or -1..-6 for bw1..bw6 */
};

#define BW(N)	(-(N))   /* encodes phy_regs.bwN as raw_idx = -N */

static const struct r2069_chan_write r2069_chan_writes[] = {
	{ 0x08e8,  0 }, { 0x08e9,  1 }, { 0x08e5,  2 }, { 0x08e4,  3 },
	{ 0x08ee,  4 }, { 0x08ef,  5 }, { 0x08cc,  6 }, { 0x08cd,  7 },
	{ 0x08ed,  8 }, { 0x08f3,  9 }, { 0x08de, 10 }, { 0x0925, 11 },
	{ 0x08e3, 12 }, { 0x08e2, 13 }, { 0x08df, 14 }, { 0x088c, 15 },
	{ 0x088d, 16 }, { 0x088e, 17 }, { 0x08e1, 18 }, { 0x08e0, 19 },
	{ 0x08d1, 20 }, { 0x08d2, 21 }, { 0x08d4, 22 }, { 0x08cf, 23 },
	{ 0x08d0, 24 }, { 0x089a, 25 }, { 0x009c, 26 }, { 0x009d, 27 },
	{ 0x009e, 28 }, { 0x009f, 29 }, { 0x00a1, 30 }, { 0x00a2, 31 },
	{ 0x00a3, 32 }, { 0x00a4, 33 }, { 0x0924, 34 }, { 0x002f, 35 },
	{ 0x0062, 36 }, { 0x0065, 37 }, { 0x006f, 38 },
	{ 0x092c, BW(1) }, { 0x092d, BW(2) }, { 0x012b, BW(3) },
	{ 0x0037, BW(4) }, { 0x0063, BW(5) }, { 0x0069, BW(6) },
};

static u16 r2069_pick_value(const struct b43_phy_ac_channeltab_e_radio2069 *e,
			    s16 raw_idx)
{
	if (raw_idx >= 0)
		return e->radio_raw[raw_idx];
	switch (raw_idx) {
	case BW(1): return e->phy_regs.bw1;
	case BW(2): return e->phy_regs.bw2;
	case BW(3): return e->phy_regs.bw3;
	case BW(4): return e->phy_regs.bw4;
	case BW(5): return e->phy_regs.bw5;
	case BW(6): return e->phy_regs.bw6;
	}
	return 0;
}

void b43_radio_2069_channel_setup(struct b43_wldev *dev,
	const struct b43_phy_ac_channeltab_e_radio2069 *e)
{
	unsigned int i;

	if (!e)
		return;

	for (i = 0; i < ARRAY_SIZE(r2069_chan_writes); i++) {
		const struct r2069_chan_write *w = &r2069_chan_writes[i];
		b43_radio_write(dev, w->reg, r2069_pick_value(e, w->raw_idx));
	}

	/*
	 * The blob has a second BW-coefficient block (s5 @0x529ac..0x52a08)
	 * gated by `pi[0xc0] == 2`, where pi[0xc0] is the PCI device ID
	 * (populated in wlc_phy_attach @0x69280). The ID is never 2 on any
	 * chip-id this binary admits, so the block is statically unreachable
	 * — pass1 (the loop above) is the only runtime path. Same `pi[0xc0]`
	 * field appears in resetcca and switch_analog: in case a future
	 * caller needs the skip-rfseq variant, thread a bool argument
	 * instead of reintroducing a check at offset 0xc0.
	 */

	/*
	 * TODO: cluster2 (0x52130..0x52718 in the blob) issues a second
	 * pass to a different set of register addresses, which on a
	 * 3-chain MIMO chip is the core-1 companion. For single-stream
	 * 6 Mbps OFDM we expect cluster1 alone to be sufficient; if
	 * channel switch turns out flaky after this lands, that pass
	 * is the next thing to add.
	 */
}

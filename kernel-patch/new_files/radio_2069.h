/* SPDX-License-Identifier: GPL-2.0-or-later */
#ifndef B43_RADIO_2069_H_
#define B43_RADIO_2069_H_

#include <linux/types.h>

struct b43_wldev;

/*
 * Per-core register routing for the 2069 radio.
 *
 * On the 2057/2059 radios (used by N-PHY and HT-PHY) the radio register
 * space is split per chain (R20XX_C1, R20XX_C2, R20XX_C3) plus an "ALL"
 * routing that broadcasts a write to every core. The 2069 follows the
 * same scheme.
 *
 * The three #defines below are intentionally COMMENTED OUT until their
 * real values are recovered. The reason is defensive: defining
 * R2069_C1 = 0xFFFF (or any other sentinel) would create a quiet
 * landmine — someone porting a snippet of the form
 *   b43_radio_write(dev, R2069_C1 | 0x146, val);
 * from radio_2057.h / radio_2059.h would compile cleanly and then
 * write to a real radio register at address 0xFFFF | 0x146 = 0xFFFF
 * (or similar), which is well within the radio's 16-bit address space
 * and might map to actual hardware.
 *
 * The single-stream MVP path (cluster1 in radio_2069.c) does not need
 * these prefixes — it writes flat 16-bit addresses (0x08e8, 0x08e9, …)
 * extracted from the inlined dispatcher in wlc_phy_chanspec_set_acphy().
 * The C1/C2/ALL routing is needed for cluster2 (the per-core companion
 * registers used in 3-chain MIMO), which is itself listed as a TODO
 * inside b43_radio_2069_channel_setup(). When cluster2 is implemented,
 * uncomment these and fill in the real prefixes — typically the upper
 * bits of the register address, 0x000/0x100/0x200/0x300 in the
 * 2057/2059 family.
 */
/* #define R2069_C1   0x???? */
/* #define R2069_C2   0x???? */
/* #define R2069_ALL  0x???? */

/*
 * One PHY-side row in the per-channel table. The fields here mirror
 * struct b43_phy_ht_channeltab_e_phy used by b43_phy_ht_channel_setup().
 * The HT version contains exactly the BW1..BW6 values; AC will need
 * more once VHT bandwidth handling is added (40/80 MHz secondary
 * channel offset, etc).
 */
struct b43_phy_ac_channeltab_e_phy {
	u16 bw1;
	u16 bw2;
	u16 bw3;
	u16 bw4;
	u16 bw5;
	u16 bw6;
};

/*
 * One row of the per-channel table for the 2069 radio.
 *
 * The layout below mirrors the on-blob `chan_tuning_2069rev_GE16` array
 * (94 bytes / 47 u16 per entry) used by wlc_phy_chan2freq_acphy() in
 * the proprietary wl driver. The field meanings are:
 *   - u16[0]    = channel number     → .channel
 *   - u16[1]    = freq in MHz        → .freq
 *   - u16[2..40]  = radio register payload → .radio_raw[39]
 *   - u16[41..46] = BW filter coeffs → .phy_regs.bw1..bw6
 *
 * The dispatcher that maps each .radio_raw[k] to a 2069 register
 * address was recovered from the same wl ELF as the table itself: it
 * is INLINED inside wlc_phy_chanspec_set_acphy() (range 0x50f24..0x51664
 * in wlDSL-3580_EU.o_save), there is no separate
 * wlc_phy_chanspec_radio2069_setup() symbol — unlike for the 2055/
 * 2056/2057/20671 radios, where such a symbol does exist. The mapping
 * is encoded in r2069_chan_writes[] in radio_2069.c; see also
 * reverse-output/r2069_chan_writes_map.txt for the audited cluster
 * boundaries and the (raw_idx → reg) table in source order.
 *
 * Despite the field name, the .phy_regs.bw1..bw6 values end up at
 * RADIO addresses (0x092c..0x0069) on this code path, not at PHY
 * addresses. The "phy_regs" name is historical, kept for symmetry
 * with struct b43_phy_ht_channeltab_e_phy. The blob has a parallel
 * block s5 that writes the same BW values to PHY regs 0x0371..0x0376
 * under a `pi[0xc0] == 2` gate, but that gate is never true on
 * BCM4352-family chips (pi[0xc0] holds the PCI device ID), so the
 * block is statically unreachable and not emitted.
 */
struct b43_phy_ac_channeltab_e_radio2069 {
	u8  channel;
	u16 freq;
	u16 radio_raw[39];
	struct b43_phy_ac_channeltab_e_phy phy_regs;
};

const struct b43_phy_ac_channeltab_e_radio2069 *
b43_phy_ac_get_channeltab_e_r2069(struct b43_wldev *dev, u16 freq);

void b43_radio_2069_channel_setup(struct b43_wldev *dev,
	const struct b43_phy_ac_channeltab_e_radio2069 *e);

#endif /* B43_RADIO_2069_H_ */

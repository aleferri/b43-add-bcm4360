/* SPDX-License-Identifier: GPL-2.0-or-later */
#ifndef B43_RXGAIN_PHY_AC_H_
#define B43_RXGAIN_PHY_AC_H_

struct b43_wldev;

/*
 * AC-PHY RX gain init.
 *
 * Skeleton port of wlc_phy_rxgainctrl_set_gaintbls_acphy
 * (wlDSL-3580_EU.o_save @ 0x4285c). MVP target on this board is
 * 5 GHz UNII-1 OFDM 6 Mbit (block_B path); 2.4 GHz block_A is
 * unreachable (aa2g=0). Scope is narrow by design — see
 * rxgain_phy_ac.c file header for what is and is not ported, and
 * for the SROM-driven plan to populate tables 0x44/0x45.
 *
 * Call from b43_phy_ac_op_init() AFTER b43_phy_ac_tables_init() and
 * AFTER b43_phy_ac_mode_init(): tables_init populates the 24 init
 * tables this function does NOT touch (0x40-0x42, 0x47-0x48, etc.),
 * and mode_init has already set up the chip-dispatched register page
 * for the 0x43b3 default path.
 */
void b43_phy_ac_rxgain_init(struct b43_wldev *dev);

#endif /* B43_RXGAIN_PHY_AC_H_ */

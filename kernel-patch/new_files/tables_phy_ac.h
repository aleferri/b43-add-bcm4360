/* SPDX-License-Identifier: GPL-2.0-or-later */
#ifndef B43_TABLES_PHY_AC_H_
#define B43_TABLES_PHY_AC_H_

#include <linux/types.h>

struct b43_wldev;

/*
 * Load the AC-PHY init tables into the PHY's table memory.
 *
 * Iterates a static descriptor array and calls b43_actab_write_bulk()
 * for each populated entry, with the table-write gate
 * (B43_PHY_AC_REG_TBL_WRITE_GATE bit B43_PHY_AC_TBL_WRITE_GATE_LOCK)
 * held across the whole sequence.
 *
 * All 24 rev-0 descriptor entries are populated; the matching arrays
 * are defined in tables_phy_ac.c (extracted from
 * reverse-output/acphy_tables_full.c).
 */
void b43_phy_ac_tables_init(struct b43_wldev *dev);

/*
 * Bulk write into one of the AC-PHY's internal tables.
 *
 * Promoted from file-local to driver-internal for the rxgain runtime
 * port (see rxgain_phy_ac.c) — second caller of the same primitive.
 * Callers must hold the table-write gate.
 *
 *   @id, @offset: table id and starting entry offset
 *   @width:       8, 16 or 32 bits per entry
 *   @len:         number of entries
 *   @data:        u8/u16/u32 array, element type must match @width
 */
void b43_actab_write_bulk(struct b43_wldev *dev,
			  u16 id, u16 offset, u8 width,
			  size_t len, const void *data);

/*
 * Save+set / restore of bit 0x0002 of B43_PHY_AC_REG_TBL_WRITE_GATE
 * (PHY reg 0x19E). Promoted alongside b43_actab_write_bulk(). The
 * lock helper returns the prior content of the bit so the unlock can
 * restore it.
 */
u16  b43_phy_ac_tbl_write_lock(struct b43_wldev *dev);
void b43_phy_ac_tbl_write_unlock(struct b43_wldev *dev, u16 saved);

#endif /* B43_TABLES_PHY_AC_H_ */

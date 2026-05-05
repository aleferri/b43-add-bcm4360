/* ================================================================
 * extract_init_acphy.py --chip default — output per-chip
 * Sorgente: wlDSL-3580_EU.o_save (MIPS BE, DSL-3580L, chip 0x43b3)
 * Funzione: wlc_phy_init_acphy
 * mode writes per il path "default": 4
 * bphy writes (chip-agnostic):              16
 *
 * (d) RMW chip_id|0x100 / chip_id|0x400 non sono estraibili staticamente
 *     e non compaiono in questo file. Vedi mode_init() del legacy emit.
 * ================================================================ */

static void b43_phy_ac_mode_init_default(struct b43_wldev *dev)
{
	b43_phy_write(dev, 0x0410, 0x0077);  /* @0x0005331c */
	b43_phy_write(dev, 0x0728, 0x0080);  /* @0x000534c0 */
	b43_phy_write(dev, 0x0720, 0x0180);  /* @0x000534e8 */
	b43_phy_write(dev, 0x0721, 0x5000);  /* @0x00053538 */
}

/* bphy_init: chip-agnostic (path post-radar_detect_init) */
static void b43_phy_ac_bphy_init_default(struct b43_wldev *dev)
{
	b43_phy_write(dev, 0x033a, 0x0395);  /* @0x000536ac */
	b43_phy_write(dev, 0x033b, 0x0395);  /* @0x000536bc */
	b43_phy_write(dev, 0x033e, 0x0395);  /* @0x000536cc */
	b43_phy_write(dev, 0x033f, 0x0395);  /* @0x000536dc */
	b43_phy_write(dev, 0x0342, 0x0395);  /* @0x000536ec */
	b43_phy_write(dev, 0x0343, 0x0395);  /* @0x000536fc */
	b43_phy_write(dev, 0x0346, 0x0395);  /* @0x0005370c */
	b43_phy_write(dev, 0x0347, 0x0395);  /* @0x0005371c */
	b43_phy_write(dev, 0x033c, 0x0315);  /* @0x0005372c */
	b43_phy_write(dev, 0x033d, 0x0315);  /* @0x0005373c */
	b43_phy_write(dev, 0x0340, 0x0315);  /* @0x0005374c */
	b43_phy_write(dev, 0x0341, 0x0315);  /* @0x0005375c */
	b43_phy_write(dev, 0x0344, 0x0315);  /* @0x0005376c */
	b43_phy_write(dev, 0x0345, 0x0315);  /* @0x0005377c */
	b43_phy_write(dev, 0x0348, 0x0315);  /* @0x0005378c */
	b43_phy_write(dev, 0x0349, 0x0315);  /* @0x0005379c */
}

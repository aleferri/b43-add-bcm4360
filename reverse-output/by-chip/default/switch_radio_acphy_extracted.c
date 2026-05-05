/* ================================================================
 * extract_switch_radio_acphy.py --chip default
 * Sorgente: wlDSL-3580_EU.o_save (MIPS BE, DSL-3580L, chip 0x43b3)
 * Funzione: wlc_phy_switch_radio_acphy @0x4582c
 * Op count: on=19 off=11
 *
 * Output backing per software_rfkill. Il body sotto è una
 * proiezione statica del path scelto; verificare con audit a
 * mano prima del commit nel kernel-patch.
 *
 * extern_call → wlc_phy_radio2069_pwron_seq / mini_pwron_seq_rev16:
 * portate da extract_radio2069_init.py; qui sono solo
 * placeholders, non re-emette le sequenze.
 * ================================================================ */

static void b43_phy_ac_op_software_rfkill(struct b43_wldev *dev,
                                          bool blocked)
{
	if (blocked) {
		b43_phy_write(dev, 0x073e, 0x0000);  /* @0x00045c6c */
		b43_phy_write(dev, 0x0739, 0x0000);  /* @0x00045c94 */
		b43_phy_write(dev, 0x073a, 0x0000);  /* @0x00045cbc */
		b43_phy_write(dev, 0x0725, 0x1fff);  /* @0x00045ce4 */
		b43_phy_write(dev, 0x0729, 0x0000);  /* @0x00045d0c */
		b43_phy_write(dev, 0x0721, 0xffff);  /* @0x00045d34 */
		b43_phy_write(dev, 0x0728, 0x0000);  /* @0x00045d5c */
		b43_phy_write(dev, 0x0720, 0x03ff);  /* @0x00045d88 */
		b43_phy_write(dev, 0x0408, 0x0000);  /* @0x00045d98 */
		b43_phy_write(dev, 0x0417, 0x0000);  /* @0x00045da8 */
		b43_phy_write(dev, 0x0416, 0x0001);  /* @0x00045de8 */
		return;
	}

	/* @0x0004588c: extern call → wlc_phy_radio2069_pwron_seq (porting separato) */
	b43_radio_set(dev, 0x08f2, 0x0040);  /* @0x000458dc */
	b43_radio_set(dev, 0x08f2, 0x0080);  /* @0x00045908 */
	b43_radio_maskset(dev, 0x08f5, ~0x0600, 0x0000);  /* @0x00045934 */
	b43_radio_maskset(dev, 0x08f5, ~0x1800, 0x0000);  /* @0x00045960 */
	b43_radio_set(dev, 0x095b, 0x0001);  /* @0x0004598c */
	b43_radio_write(dev, 0x095c, 0x0000);  /* @0x000459bc */
	b43_radio_write(dev, 0x095d, 0x0000);  /* @0x000459e4 */
	b43_radio_write(dev, 0x095e, 0x0000);  /* @0x00045a0c */
	b43_radio_write(dev, 0x095f, 0x0000);  /* @0x00045a34 */
	b43_radio_maskset(dev, 0x0810, ~0x0001, 0x0000);  /* @0x00045a64 */
	udelay(1);  /* @0x00045a70 */
	b43_radio_set(dev, 0x0810, 0x0001);  /* @0x00045aa0 */
	udelay(10);  /* @0x00045af0 */
	b43_radio_maskset(dev, 0x095b, ~0x0001, 0x0000);  /* @0x00045b6c */
	b43_radio_maskset(dev, 0x08f2, ~0x0040, 0x0000);  /* @0x00045b98 */
	b43_radio_maskset(dev, 0x08f2, ~0x0080, 0x0000);  /* @0x00045bc4 */
	b43_radio_maskset(dev, 0x0810, ~0x0001, 0x0000);  /* @0x00045bf0 */
	/* @0x00045c00: extern call → wlc_phy_radio2069_rccal (porting separato) */
}

/* ================================================================
 * extract_radio2069_init.py --chip default — output per-chip
 * Sorgente: wlDSL-3580_EU.o_save (MIPS BE, DSL-3580L, chip 0x43b3)
 * Funzione: wlc_phy_radio2069_pwron_seq
 * Op count per il path "default": 20
 *
 * RMW non estraibili staticamente (chip-id-indipendenti):
 *   1. @451f4: saved_728 & 0x7e7f -> b43_phy_mask(dev,0x0728,0x7e7f)
 *   2. @45214: old_0x720 | 0x180  -> b43_phy_set(dev,0x0720,0x0180)
 *   3. @456c8: saved_728 | 0x180  -> b43_phy_set(dev,0x0728,0x0180)
 *   4. epilog: saved_728 & ~0x100 -> b43_phy_mask(dev,0x0728,~0x0100)
 * ================================================================ */

static void b43_radio_2069_init_default(struct b43_wldev *dev)
{

	/* --- Prologo: PHY register writes --- */
	b43_phy_write(dev, 0x0415, 0x0000);  /* @0x00045194 */
	b43_phy_write(dev, 0x040e, 0x0000);  /* @0x000451a4 */
	b43_phy_write(dev, 0x040c, 0x2000);  /* @0x000451b4 */
	b43_phy_write(dev, 0x0408, 0x0000);  /* @0x000451c4 */
	b43_phy_write(dev, 0x0417, 0x0000);  /* @0x000451d4 */
	b43_phy_write(dev, 0x0416, 0x000d);  /* @0x000451e4 */

	/* RMW 1+2 (chip-id-indipendenti, da prologue) */
	b43_phy_mask(dev, 0x0728, 0x7e7f);  /* @0x000451f4 */
	b43_phy_set(dev,  0x0720, 0x0180);  /* @0x00045214 */
	b43_phy_write(dev, 0x0408, 0x0007);  /* @0x00045228 */

	/* --- Setup + udelay(100) --- */
	udelay(100);  /* @0x00045234 */
	b43_phy_write(dev, 0x0408, 0x0006);  /* @0x00045244 */

	/* --- Corpo: radio 2069 init + epilogo --- */
	b43_radio_set(dev, 0x097f, 0x0800);  /* @0x000452a0 */
	b43_radio_set(dev, 0x097f, 0x4000);  /* @0x000452b4 */
	b43_radio_set(dev, 0x0980, 0x0800);  /* @0x000452c8 */
	b43_radio_set(dev, 0x097f, 0x8000);  /* @0x000452dc */
	b43_radio_set(dev, 0x097f, 0x1000);  /* @0x000452f0 */
	b43_radio_set(dev, 0x097f, 0x0004);  /* @0x00045304 */
	b43_radio_set(dev, 0x0407, 0x0002);  /* @0x00045438 */
	b43_phy_write(dev, 0x0417, 0x000d);  /* @0x000456a4 */
	b43_phy_write(dev, 0x0408, 0x0002);  /* @0x000456b4 */
	/* RMW 3 */
	b43_phy_set(dev, 0x0728, 0x0180);  /* @0x000456c8 */
	udelay(100);  /* @0x000456d0 */
	b43_phy_write(dev, 0x0417, 0x0004);  /* @0x000456e0 */

	/* RMW 4: epilogo tail — clear bit 0x100 di PHY 0x728 */
	b43_phy_mask(dev, 0x0728, ~0x0100);
}

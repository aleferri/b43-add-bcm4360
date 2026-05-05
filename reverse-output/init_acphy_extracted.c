/* ================================================================
 * extract_init_acphy.py — output automatico
 * Sorgente: wlDSL-3580_EU.o_save (MIPS BE, BCM4360 3x3)
 *
 * Table-write gate @0x000535d0
 * radar_detect_init jalr @0x00053698
 * phy_reg_write register: s1
 * Chip-dispatch blocks trovati: 12
 * ================================================================
 *
 * SEZIONE 1: Mode-bit clears (fase 3 di op_init)
 * Da inserire in b43_phy_ac_op_init() dopo b43_phy_ac_tables_init().
 * Sequenza estratta da wlc_phy_init_acphy, sezione pre-table-lock.
 *
 * Struttura:
 *   a) 1 write costante upfront (reg 0x410)
 *   b) N write chip-dispatch: reg dipende da chip, val=0 per tutti
 *   c) 3 write costanti finali (AFE, EXTG)
 *   d) 2 RMW chip-ID-in-value (non estraibili staticamente — skip MVP)
 */

static void b43_phy_ac_mode_init(struct b43_wldev *dev)
{
	/* (a) Write costante upfront */
	b43_phy_write(dev, 0x0410, 0x0077);  /* @0x0005331c */

	/* (b) Chip-dispatch: zeroing di registri AFE/RF per pagina corretta.
	 * BCM4352 (laptop) usa pagina 0x1xxx, generic/BCM4360 usa 0x0xxx.
	 * Tutti scrivono 0 — la differenza è solo nel register address.
	 * Per il driver b43 usiamo dev->phy.ac->num_cores per scegliere,
	 * oppure leggiamo i PCI device ID. Per il MVP usiamo BCM4352.
	 */
	/* 12 blocchi chip-dispatch trovati. */

#if 0  /* BCM4352 (schede laptop — reg page 0x1xxx) */
	b43_phy_write(dev, 0x173e, 0x0000);  /* @0x00053358 — 4360=0x173e generic=0x073e */
	b43_phy_write(dev, 0x1725, 0x0000);  /* @0x00053380 — 4360=0x1725 generic=0x0725 */
	b43_phy_write(dev, 0x1722, 0x0000);  /* @0x000533a8 — 4360=0x1722 generic=0x0722 */
	b43_phy_write(dev, 0x1723, 0x0000);  /* @0x000533d0 — 4360=0x1723 generic=0x0723 */
	b43_phy_write(dev, 0x1724, 0x0000);  /* @0x000533f8 — 4360=0x1724 generic=0x0724 */
	b43_phy_write(dev, 0x1725, 0x0000);  /* @0x00053420 — 4360=0x1725 generic=0x0725 */
	b43_phy_write(dev, 0x1726, 0x0000);  /* @0x00053448 — 4360=0x1726 generic=0x0726 */
	b43_phy_write(dev, 0x1727, 0x0000);  /* @0x00053470 — 4360=0x1727 generic=0x0727 */
	b43_phy_write(dev, 0x1750, 0x0000);  /* @0x00053498 — 4360=0x1750 generic=0x0750 */
	b43_phy_write(dev, 0x1728, 0x0080);  /* @0x000534c0 — 4360=0x1728 generic=0x0728 */
	b43_phy_write(dev, 0x1720, 0x0180);  /* @0x000534e8 — 4360=0x1720 generic=0x0720 */
	b43_phy_write(dev, 0x1729, 0x0000);  /* @0x00053510 — 4360=0x1729 generic=0x0729 */
#endif

#if 0  /* Generic (reg page 0x0xxx) */
	b43_phy_write(dev, 0x073e, 0x0000);  /* @0x00053358 — 4352=0x173e 4360=0x173e */
	b43_phy_write(dev, 0x0725, 0x0000);  /* @0x00053380 — 4352=0x1725 4360=0x1725 */
	b43_phy_write(dev, 0x0722, 0x0000);  /* @0x000533a8 — 4352=0x1722 4360=0x1722 */
	b43_phy_write(dev, 0x0723, 0x0000);  /* @0x000533d0 — 4352=0x1723 4360=0x1723 */
	b43_phy_write(dev, 0x0724, 0x0000);  /* @0x000533f8 — 4352=0x1724 4360=0x1724 */
	b43_phy_write(dev, 0x0725, 0x0000);  /* @0x00053420 — 4352=0x1725 4360=0x1725 */
	b43_phy_write(dev, 0x0726, 0x0000);  /* @0x00053448 — 4352=0x1726 4360=0x1726 */
	b43_phy_write(dev, 0x0727, 0x0000);  /* @0x00053470 — 4352=0x1727 4360=0x1727 */
	b43_phy_write(dev, 0x0750, 0x0000);  /* @0x00053498 — 4352=0x1750 4360=0x1750 */
	b43_phy_write(dev, 0x0728, 0x0080);  /* @0x000534c0 — 4352=0x1728 4360=0x1728 */
	b43_phy_write(dev, 0x0720, 0x0180);  /* @0x000534e8 — 4352=0x1720 4360=0x1720 */
	b43_phy_write(dev, 0x0729, 0x0000);  /* @0x00053510 — 4352=0x1729 4360=0x1729 */
#endif

	/* (c) Write costanti finali */
	b43_phy_write(dev, 0x0728, 0x0080);  /* @0x000534c0 */
	b43_phy_write(dev, 0x0720, 0x0180);  /* @0x000534e8 */
	/* SALAME: 0x0721 = 0x5000 appare invariante rispetto al chip nel blob
	 * DSL-3580 (addiu a2,zero,20480 prima del jalr, path non condizionato
	 * dal chip-ID dispatch). Ma non è stato verificato su un secondo blob.
	 * Prima di considerare questo valore affidabile, cross-checkare su un
	 * blob LE (es. ASUS RT-AC66U wl_apsta.o) con lo stesso script:
	 *   python3 extract_init_acphy.py <altro_blob.disr>
	 * e confrontare l'indirizzo e il valore della write a reg 0x0721.
	 * Se il secondo blob produce un valore diverso, questo è chip-specifico
	 * e va trattato come i 12 blocchi chip-dispatch in sezione (b). */
	b43_phy_write(dev, 0x0721, 0x5000);  /* @0x00053538 — VERIFICARE su secondo blob */

	/* (d) RMW con chip_id|0x100 / chip_id|0x400 — non estraibili staticamente.
	 * Il blob scrive (chip_id OR 0x100) in reg 0x72a e (chip_id OR 0x400) in 0x725.
	 * Per il MVP, questi registri rimangono al default hardware. */
}


/* ================================================================
 * SEZIONE 2: bphy_init (fase 9 di op_init)
 * Inserire in b43_phy_ac_bphy_init(), chiamato da b43_phy_ac_op_init()
 * se b43_current_band(dev->wl) == NL80211_BAND_2GHZ.
 *
 * Estratte dalla sezione post-wlc_phy_radar_detect_init di
 * wlc_phy_init_acphy. Valori costanti (niente chip-dispatch).
 * Queste sono le write ai filtri CCK / BPHY compat registers.
 * ================================================================ */

static void b43_phy_ac_bphy_init(struct b43_wldev *dev)
{
	/* Sequenza estratta da wlc_phy_init_acphy post-radar_detect_init.
	 * Registri 0x33a-0x349: BPHY CCK filter coefficients per 2.4 GHz.
	 * Pattern: coppie (high_val=0x395, high_val=0x395, low_val=0x315, low_val=0x315)
	 * ripetute 4 volte (una per core/path in configurazione 3x3).
	 */
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

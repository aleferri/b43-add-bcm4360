# ROADMAP — da scaffolding a 1 Mbps CCK su 4360

Riformulazione operativa: **1 Mbit verificato = solo 802.11b CCK su 2.4 GHz,
canale fisso, 1x1, niente OFDM/HT/VHT, niente cal**. Il rate 1 Mbps è
BPSK/DBPSK con 20 MHz channel — non tocca quasi nulla del PHY-AC moderno
e quasi tutto del bphy compat sotto. Questo cambia drasticamente la
priorità rispetto a "far funzionare il PHY-AC". Metà dei pezzi
considerati critici nello scaffolding diventano post-MVP.

I tier sono in ordine decrescente di criticità.

---

## Tier 0 — Blocker assoluti

### 0.1 — Firmware `ucode42` estraibile

**Verifica:** non in Ghidra. Si guarda `b43-fwcutter` (sorgente
`fwcutter.c`, tabella `extract_list`) e si controlla se conosce già il
pattern per tirare l'ucode AC dal `wl.ko`/`wl_cm.o`.

**SALAME**: i fwcutter recenti probabilmente non lo conoscono — l'ultimo
upstream attivo è del 2014, prima del PHY-AC mainline. Va probabilmente
esteso con un nuovo entry per "ucode42" e "ac1initvals42". Pattern
plausibile: il blob inizia con un magic Broadcom seguito da metadata
di lunghezza, già documentato per le altre famiglie ucode in fwcutter.

**Impatto se non risolto:** driver morto. Senza microcode il MAC b43
non si avvia, niente probe completo. È il primo lavoro da fare e va
fatto fuori dal kernel — è un tool userland.

**Implementazione:** aggiungere a fwcutter le entry per il blob AC del
wl con cui si lavora, generare il file in `linux-firmware`,
sottometterlo come patch separata. Se l'ucode AC ha checksum/firma
diversi e fwcutter non lo prende, il piano salta e bisogna ripensare.

**Stima:** 1-3 giorni. **Va fatto come PRIMA cosa, prima ancora di
toccare il kernel.**

### 0.2 — Numero di core RF realmente attivo

**Verifica in Ghidra:** aprire `wlc_phy_init_acphy`. Cercare i loop
tipo `for (i = 0; i < N; i++) { … core[i] … }` o costanti come
`PHY_CORE_NUM`/`NUM_RFCORES`. Più semplice: aprire
`wlc_phy_set_regtbl_on_band_change_acphy` (è già nello script v1) e
contare quante volte itera il blocco di scritture per-core, oppure
leggere la struct `phy_info_t` e il campo `num_cores`/`numtxchain`/
`numrxchain`.

**Impatto se sbagliato:** se assumi 3 e ne ha 1 (BCM4352 laptop), gli
init scrivono a registri `_C2`/`_C3` inesistenti — alcuni cadono nel
vuoto, altri in registri usati per altro = comportamento erratico,
anche niente RX. Se assumi 1 e ne ha 3, perdi 2/3 della catena RX =
SNR pessimo, ma associate fattibile.

**Implementazione:** aggiungere `num_cores` come campo in
`struct b43_phy_ac` letto da SPROM al probe (rev 11 ha `nss_2g`/`nss_5g`
o simili). Tutti i loop nei vari op_init e op_switch_channel devono
iterare `[0..num_cores)` non `[0..3)`. **Per il MVP 1 Mbit forzare
num_cores=1** per la prima fase; quando funziona si alza.

**Stima:** mezza giornata di Ghidra + 30 minuti di patch.

### 0.3 — Layout della struct phytbl_info confermato

**Verifica in Ghidra:** aprire qualsiasi funzione che fa
`wlc_phy_table_write_acphy(&desc[i])` (probabilmente `wlc_phy_init_acphy`
o `wlc_phy_tbl_init_acphy`). Decompiler mostra `desc[i].field0`,
`desc[i].field4`, ecc. e li passa in ordine ad a1, a2, a3, stack.
Quell'ordine è la verità.

**Impatto se sbagliato:** le 25 tabelle estratte hanno `id` e `off`
invertiti (o simili), e la patch carica la tabella RX EVM all'indirizzo
della MCS, ecc. → niente RX possibile.

**Implementazione:** se diverso da quello che ho assunto, è una
sostituzione cieca dei nomi nel descriptor extractor + rerun.

**Stima:** 15 minuti. Fallo prima di scrivere `b43_phy_ac_tables_init`.

---

## Tier 1 — Per arrivare a `ifconfig wlan0 up` senza dmesg pieno di WARN

### 1.1 — Bit semantics di reg 0x19e

**Verifica in Ghidra:** aprire `wlc_phy_set_tbl_on_reset_acphy` o
`wlc_phy_clip_det_acphy` (entrambi nel map). Il pattern
`read 0x19e → mod 0x19e mask=0x2 val=0x2 → … → mod 0x19e mask=0x2 val=<saved>`
è quasi certamente "freeze del PHY clock" o "lock table access".
Il decompiler dovrebbe mostrare un `BCM_REFERENCE` o un commento; se no,
cross-reference con la stringa "table" o "lock" vicino a quel reg.

**Impatto:** compare in 64 punti del codice mappato, di cui ~15 sono
table writes. Se sbagli la polarità del bit (1=lock vs 0=lock), tutti
gli accessi tabella avvengono mentre il PHY li ignora → tutte le
tabelle NON vengono caricate → driver inerte ma "compila e probe-completa".

**SALAME:** il bit 0x2 è quasi certamente "PHY override / disable
hardware-driven access" basandomi sull'analogia con HT_BBCFG bit
RSTCCA/RSTRX, ma la conferma serve.

**Implementazione:** helper `b43_phy_ac_lock_phy(dev, true/false)` che
fa il save+set / restore del bit, chiamato da `b43_phy_ac_tables_init`
e da ogni op che scrive registri sensibili.

**Stima:** 1 ora di Ghidra + 30 minuti di patch.

### 1.2 — Offset RFCTL1, AFE_C1/C2 (i tre 0xFFFF della patch)

**Verifica in Ghidra:** aprire `wlc_phy_radio_2069_switch` o
`wlc_phy_*_pwrup_acphy`. Le funzioni di radio enable scrivono i
registri RFCTL prima del radio init. AFE_C{1,2}_{,_OVER} appaiono in
tutte le `wlc_phy_*_afe_*_acphy` e in `_clip_det_acphy`.

**Impatto:** gli `0xFFFF` nei guard `if (X == 0xFFFF) skip` fanno sì
che `software_rfkill(false)` non porti il radio up = no carrier. Per
1 Mbit **questi devono essere reali**, non skippati. Senza RFCTL1 il
radio resta in reset.

**Implementazione:** sostituire i `#define` 0xFFFF con i valori veri
(saranno offset nel range PHY 0x000-0xfff). Togliere i guard.

**Stima:** 2 ore di Ghidra per i 5-6 registri principali.

### 1.3 — Init sequence base — quale pezzo davvero serve per 1 Mbit

**Verifica in Ghidra:** aprire `wlc_phy_init_acphy`. Saltare le sezioni
che fanno `wlc_phy_cal_*`, `wlc_phy_papd_*`, `wlc_phy_iqcal_*`. Tenere:
tables_init, AFE bring-up, classifier (CCK only), bphy_init.

**Impatto:** l'init reale di `wl` fa decine di fasi per via di OFDM/HT/
VHT/calibrazioni. Per 1 Mbit CCK ne servono ~5. Ridurre lo scope qui è
la differenza tra "1 settimana di porting" e "3 mesi".

**SALAME:** stima a spanne — l'init di `phy_ht.c` è ~250 righe; la
versione minima per CCK basale stimo ~80 righe. Numero non misurato.

**Implementazione:** nel `b43_phy_ac_op_init` riempire solo le fasi
(2), (4), (9) dello scaffold attuale, lasciando le altre come
`/* TODO post-MVP */`. La fase (9) bphy_init è cruciale e va replicata
da `phy_ht.c` quasi tale e quale (è la programmazione dei filtri CCK
in `B43_PHY_N_BMODE(0x88..)`).

---

## Tier 2 — Per arrivare ad associate con un AP

### 2.1 — Channel table per 2069, almeno per i canali 2.4 GHz

**Verifica in Ghidra:** aprire `wlc_phy_chanspec_radio2069_set` (probabile
nome). Decompiler mostra un `switch(freq)` con case per 2412, 2417,
2422, …, 2484. Per ogni case: ~15 register writes. Per il MVP basta
canale 1 (2412) o canale 6 (2437) — uno solo.

**Impatto:** senza channel table `b43_phy_ac_op_switch_channel` ritorna
`-ESRCH` e il driver rifiuta di sintonizzarsi. Niente associate. Per
1 Mbit basta un canale.

**Implementazione:** popolare `radio_2069.c` con una sola entry (canale 6,
2437 MHz) e i suoi 15 register write. Resto delle entry come TODO.

**Stima:** 2-3 ore di Ghidra per estrarre il case del solo 2437.

### 2.2 — Spur avoidance

**Verifica in Ghidra:** aprire `wlc_phy_spuravoid_acphy`. Pattern simile
a `b43_phy_ht_spur_avoid` (PLL frac update + TSF clk frac).

**Impatto:** sui canali 13/14 senza spur avoidance hai interferenza di
clock visibile. Sul canale 6 in pratica è ininfluente. Per il MVP
**lo skippi dichiaratamente** (`/* TODO: only relevant for ch 13/14 */`).
Submitter non si lamenta perché il driver è già `BROKEN` in Kconfig.

**Stima:** 0 nel MVP.

### 2.3 — TX power: valore di default, niente calibrazione

**Verifica in Ghidra:** aprire `wlc_phy_tx_power_ctl_setup_acphy`. La
parte interessante è "qual è il valore di default per il registro
`TXPCTL_TARG_PWR`" che produce qualcosa di simile a 14 dBm conservativi
per CCK.

**Impatto:** a 1 Mbit con TX power "qualunque purché ≥ 0 dBm" associate
funziona se l'AP è a 5 metri. Per la submit upstream l'output di
`iw dev wlan0 link` mostrerà un TX power randomico — non bloccante
perché il Kconfig è BROKEN.

**Implementazione:** `recalc_txpower` resta no-op (già lo è). Aggiungere
nel `op_init` un singolo `phy_reg_write(TXPCTL_TARG_PWR, 0x...)` con il
valore default trovato.

**Stima:** 1 ora di Ghidra per estrarre il default.

### 2.4 — RX gain table

**Verifica in Ghidra:** aprire `wlc_phy_rxgainctrl_set_gaintbls_acphy`
(è nella mappa). Le tabelle 0x44/0x45 lette a blocchi sono RX gain. Se
sono in `acphy_rxgain_*` simboli (vedi symbol dump), si estraggono col
descriptor extractor estendendolo per fixed-symbol lookups. Se invece
sono costruite runtime (più probabile, perché dipendono da SPROM),
allora vanno copiate come funzione.

**Impatto:** **questo è il vero blocker per RX a 1 Mbit**. Senza RX
gain corretto, il PHY riceve rumore o signal saturato, niente decode
CCK. Con AGC/gain "default cattivi" puoi avere -90 dBm sensitivity
invece di -97, ma per associate con AP a 5 metri basta.

**Implementazione:** per il MVP, se l'RX gain table è statica nei
simboli `acphy_rxgain_5g_*` ecc., estrarla con script. Se è runtime,
replicare la funzione `wlc_phy_rxgainctrl_set_gaintbls_acphy` riga
per riga.

**Stima:** 1 giorno se statica, 2-3 giorni se runtime. **È il punto su
cui spenderei più tempo nel piano.**

---

## Tier 3 — Per il submit upstream credibile

### 3.1 — SPROM rev 11 parsing in `bcma`

**Verifica:** leggere `drivers/bcma/sprom.c` corrente in mainline. Quasi
certamente non parsifica rev 11 (i dmesg degli utenti dicono "Unsupported
SPROM revision: 11"). I campi che servono sono `txchain`, `rxchain`,
`core_pwr_info`, `boardflags2`, `ag0/ag1`.

**Impatto:** senza SPROM parsata, `dev->bus_sprom` ha campi a zero o
defaults. TX power calc fallisce o produce zero. Per il MVP a 1 Mbit
con un singolo TX power default si può anche bypassare, ma per submit
upstream è meglio averla.

**Implementazione:** patch separata su `bcma`. Indipendente dal resto.

**Stima:** 2-3 giorni (perché bisogna documentare il layout rev 11 dal
`wl_cm.o` o da OpenWrt, in entrambi i casi è reverse).

### 3.2 — Tabelle band-specific rimaste fuori dei descriptor

**Verifica in Ghidra:** per ognuno dei ~10 simboli `acphy_txgain_*`
orfani, cercare i caller con cross-reference. Tipicamente saranno in
funzioni come `wlc_phy_*_band_*_acphy`.

**Impatto per 1 Mbit:** se MVP fissa banda 2.4 GHz e canale 6, ne
servono 1-2 al massimo (la txgain 2g default). Se ci si limita anche
più (TX power fisso non da tabella), nessuna.

**Implementazione:** ignorate per il MVP, aggiunte quando si vuole 5 GHz.

**Stima:** 0 nel MVP.

### 3.3 — Provenance e licensing dei dati estratti

**Verifica:** ogni tabella in `tables_phy_ac.c` deve riportare nel
commento: nome simbolo originale, file binario, hash.
Esempio:
```c
/* extracted from acphy_mcs_tbl_rev0 in wlDSL-3580_EU.o
 * (sha256:...) by extract_acphy_tables_from_descriptor.py v2 */
```

**Impatto:** **per submit upstream è non negoziabile**. Kalle Valo (o
chi prende la patch) chiederà da dove vengono i numeri. La risposta
"dal blob proprietario, estratti con uno script, non sono codice ma
dati hardware" passa più facilmente se la trail è documentata.

**Implementazione:** modificare lo script per emettere il commento di
provenance.

**Stima:** 30 minuti. **Va fatto prima del submit.**

### 3.4 — Test bench e dimostrabilità

**Verifica:** nessuna in Ghidra; questo è lavoro di laboratorio.

**Impatto:** la submission upstream con allegato `dmesg` che mostra
associate + 1 Mbit ping = 100x più convincente di qualsiasi patch
"RFC scaffolding". **Senza questo, il follow-up sperato non arriva.**

**Implementazione:** serve un router/laptop con la scheda (BCM4360 PCIe
o SoC con AC), kernel patched, `wpa_supplicant` su un AP 2.4 GHz
isolato. Output minimo: `iw dev wlan0 link` + `ping -c 100 192.168.x.1`
con loss < 50%.

**Stima:** 1 giorno se l'hardware è disponibile.

---

## Tier 4 — Esplicitamente fuori scope MVP

In ordine di rinvio post-submit, da scrivere come "future work" nella
commit message:

- **VHT 80 MHz**: tutta `B43_PHY_AC_BBCFG_RSTRX` + spur avoid + BW3..BW6
  specifiche per 80 MHz.
- **5 GHz operation**: tabelle `acphy_txgain_epa_5g_*` e channel table
  2069 per 5180-5825.
- **2x2/3x3 MIMO**: alza `num_cores`, popola tutti i loop per-core.
- **PAPD compensation** (id 0x47/0x67/0x87 e 0x48/0x68/0x88): è cal di
  linearizzazione dell'amplificatore. Per CCK non serve, per OFDM
  HT/VHT a piena banda sì.
- **TX power calibration vera** (idle TSSI, target setup, regs 0x14XX):
  impatta solo la qualità del TX, non la connessione.
- **Periodic work** `pwork_15sec`/`pwork_60sec`: monitoraggio termico/
  cal periodica. Skippabile.

---

## Rotta concreta da qui a un submit (in ordine)

1. **fwcutter ucode42** — è la cartina al tornasole. Se non si estrae,
   tutto si ferma. *(1-3 giorni)*
2. Verifica Ghidra dei tre punti del Tier 0 (num_cores, descriptor
   layout, ucode availability check). *(1 giorno)*
3. Risolvere i `0xFFFF` nella patch (RFCTL1, AFE, RF_SEQ, TEST).
   *(2-3 giorni)*
4. Capire reg 0x19e e implementare `b43_phy_ac_lock_phy`.
   *(mezza giornata)*
5. Scrivere `b43_actab_write_bulk` e popolare `b43_phy_ac_tables_init`
   con le 25 tabelle estratte. *(1 giorno)*
6. Estrarre il singolo canale 2437 dalla `wlc_phy_chanspec_radio2069_set`.
   Popolare quella entry in `radio_2069.c`. *(1 giorno)*
7. Implementare l'init minima (tables → AFE → classifier CCK-only →
   bphy_init). *(2-3 giorni)*
8. RX gain table — il punto difficile. *(3-5 giorni a seconda di
   statica/runtime)*
9. Test su hardware: associate + ping. *(1-2 giorni di tweaking)*
10. Pulizia, provenance comments, commit message, RFC submit a
    `linux-wireless`. *(1 giorno)*

**Totale: 3-4 settimane di lavoro a tempo pieno per una persona, se
l'hardware è disponibile.** Se 0.1 (firmware) fallisce, il piano si
ferma e bisogna pensare ad altre vie (per esempio sbloccare l'estrazione
con tool diversi).

**SALAME**: la stima 3-4 settimane è basata su esperienza analoga di
driver wireless reverse, non su misurazione di questo lavoro specifico.
Molto dipende dalla qualità del decompilato Ghidra (se i simboli sono
buoni come sembra dal symtab, è ragionevole; se ci sono indirezioni a
tabelle di puntatori a funzioni, raddoppia).

---

## Framing strategico per la submit

La submit più strategica non è **"ho fatto funzionare il PHY-AC"**, che
è troppo grosso da revieware. È:

> "ho fatto funzionare CCK 1 Mbps su 4360 con un init di 200 righe e
> queste 25 tabelle estratte; ecco il diff vs lo stub di Miłecki del
> 2015 che era fermo da 11 anni"

Quel framing attira tre tipi di gente:

1. chi ha 4352/4360 nel cassetto e vuole giocare,
2. chi è interessato al reverse engineering Broadcom in generale,
3. **il più importante:** Rafał Miłecki stesso, che potrebbe rivedersi
   nel suo lavoro e tornare.

La differenza tra silenzio totale e qualche reply su lkml è quasi
solo nel framing della commit message.

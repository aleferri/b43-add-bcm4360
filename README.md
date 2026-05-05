# b43 BCM4352-family / 0x43b3 (PHY-AC) — DSL-3580L

Re-target del repo `b43-add-bcm4360` originale alla luce della scoperta
che l'hardware del DSL-3580L **non** è BCM4360 ma BCM4352-family con
chip ID `acphychipid = 0x43b3`. Il binario `wlDSL-3580_EU.o_save` resta
la fonte per il reverse, ma le code-path estratte sono rifatte con
dispatch chip corretto.

## Stato del bring-up dopo verifica hardware diretta

Le precedenti versioni di questo README pianificavano un MVP "2.4 GHz
canale 6 CCK 1×1" basato su una lettura *parziale* delle informazioni
del board, ottenute da `router_info.txt`. Una sessione di sondaggio
diretto via `wl -i wl1 ...` sul DSL-3580L ha rivelato che quel piano è
fisicamente irrealizzabile su questo hardware. Il MVP è stato
ricalibrato di conseguenza.

### Quello che il chip target è davvero

Letto via `wl -i wl1 revinfo` e `wl -i wl1 nvram_dump` (vedi
§"Provenance" in fondo):

| Campo | Valore | Rilevanza |
|---|---|---|
| `vendor:device` | `0x14e4:0x43b3` | conferma target del repo |
| `chipnum / chiprev / corerev` | `0x4352 / 0x3 / 0x2a` | BCM4352-family conferma |
| `radiorev` | `0x42069000` | Radio 2069 |
| `phytype` | `0xb` (= AC-PHY) | conferma path acphy |
| `phyrev` | `0x1` | rev 1 (early AC) |
| `boardid` | `0x668` | **non** `0x513` (quello era wl0) |
| `boardrev` | `0x1353` (display "P353") | **non** "P230" |
| `sromrev` | **`11`** | vedi §"SROM rev 11: groundwork preparato" |
| `aa2g / aa5g` | `0 / 3` | vedi §"Implicazione fondamentale" |
| `txchain / rxchain` | `3 / 3` | 2×2, conferma `num_cores=2` |
| `subband5gver` | `0x4` | <span style="color:red">**SALAME**</span>: il valore non è uno standard UNII-1/2/2e/3 noto a chi scrive; significato esatto da chiudere |
| `boardflags / boardflags2` | `0x10000000 / 0x2` | board fixup minimale |
| `femctrl` | `6` | FEM controller mode board-specific |
| `epagain2g / epagain5g` | `0 / 0` | nessun PA esterno extra |

### Implicazione fondamentale: il chip è 5 GHz only su questo board

`aa2g=0` significa che il SROM dichiara **zero antenne disponibili
sulla 2.4 GHz**. Empiricamente, i tentativi di portare il chip su
canali 2.4 GHz via `wl chanspec 2g6/20` falliscono. La 2.4 GHz del
DSL-3580L è coperta da wl0 (BCM6362, N-PHY, fuori scope). Il chip
target wl1 fa solo 5 GHz.

Conseguenza: **il MVP "2.4 GHz CCK 1Mbit" del piano originale non è
eseguibile su questo hardware**. Quello che l'iterazione precedente del
README chiamava "post-MVP §Estensione 5 GHz" è in realtà l'unico MVP
possibile.

Una limitazione operativa aggiuntiva: anche dentro la 5 GHz, il
chanspec `5g100/20` (UNII-2 extended) viene rifiutato con `Bad
Channel`. <span style="color:red">**SALAME**</span> — la causa
candidata è una restrizione regulatory locale al firmware OEM
(`ccode=` vuoto + `regrev=0` non basta a sbloccare DFS); meno
probabile ma non escluso, è il significato di `subband5gver=0x4`. Il
risultato pratico è che la sub-banda affidabile per il bring-up è
**UNII-1 (canali 36-48)**.

## Obiettivo MVP rivisto

Probe pulito + `ifconfig wlan1 up` + scan passivo + associate su AP
5 GHz canale 36 + 6 Mbit OFDM 1×1, su BCM4352-family **incluso**
0x43b3 (DSL-3580L). Tester di riferimento: l'AP `D-Link DSL-3580L_5G`
che il router stesso espone su BSSID `D8:FE:E3:E2:A1:3E`, channel 36
80 MHz, VHT80 capable.

Out of scope per MVP: HT/VHT, MIMO, calibrazioni reali, 40/80 MHz,
UNII-2/2e/3 (DFS).

## SROM rev 11: groundwork preparato (`kernel-patch/sprom-rev11/`)

Le iterazioni precedenti di questo README dichiaravano "Blocker #1:
SPROM rev 11" sostenendo che la mainline `b43`/`bcma`/`ssb` rifiuta la
rev 11 con `Unsupported SPROM revision: 11`. <span
style="color:blue">**TONNO**</span> — l'audit del torvalds/linux master
corrente (commit `6d35786`) mostra che `bcma_sprom_valid` accetta rev
11 dal 2015 (Rafał Miłecki). Quello che effettivamente *manca* è
diverso: l'unico estrattore implementato è `bcma_sprom_extract_r8`,
chiamato indistintamente per rev 8/9/10/11. Per una SROM rev 11 questo
estrattore popola solo i campi a layout condiviso e lascia a zero tutti
quelli rev-11-only (`rxgains_*`, `subband5gver`, il blocco femctrl,
`mcsbw80*po`, `mcsbw160*po`, le matrici `sb20in*`/`sb40and80`,
`pdoffset*`, e per ogni chain `maxp2ga`, `maxp5ga[4]`, `pa2ga[3]`,
`pa5ga[12]`).

Per coprire il gap è in `kernel-patch/sprom-rev11/` una serie di tre
patch DRAFT contro mainline:

| | File | Obiettivo |
|---|---|---|
| 0001 | `include/linux/ssb/ssb.h` | Estende `struct ssb_sprom` e `struct ssb_sprom_core_pwr_info` con i campi rev 11 dimostrati dal dump NVRAM del DSL-3580L. Tutto appeso, zero shift su campi esistenti, no-op per rev ≤ 10. |
| 0002 | `drivers/firmware/broadcom/bcm47xx_sprom.c` | NVRAM key→field mapping per i nuovi campi rev 11 (`ENTRY()` mask `0x00000800`) + nuova `bcm47xx_fill_sprom_path_r11` per i campi per-chain CSV. Helper `nvram_read_u{8,16}_array` per i payload comma-separated come `pa5ga0=0xff4d,0x1690,...`. |
| 0003 | `drivers/bcma/sprom.c`, `include/linux/ssb/ssb_regs.h` | Skeleton `bcma_sprom_extract_r11` con dispatch da `bcma_sprom_get`. Estrae solo i campi i cui offset byte sono verificabili 1:1 contro il dump del DSL-3580L (header condiviso con rev 8 + per-chain block stride 0x28 + `subband5gver`). Tutto il resto resta TODO con elenco esplicito. |

Stato della serie: **DRAFT, NON da inviare**. Le patch applicano in
sequenza pulita (`git am`) sul `master` corrente. La serie va
mantenuta nel repo finché:

1. Il bring-up MVP raggiunge probe + RX su UNII-1 ch.36 (cioè il
   resto di questo README), così c'è almeno un consumer in-tree
   testabile dei nuovi campi.
2. Il decoder rxgains nel chain block (vedi §"Strategia rxgain
   rivista" e §"Open questions residue") viene chiuso o lasciato
   esplicitamente come TODO con motivazione documentata.

L'invio anticipato è esplicitamente fuori discussione: mandare a
`linux-wireless` un estrattore rev 11 mai esercitato end-to-end è da
irresponsabili.

Vantaggio collaterale, già operativo localmente: con la patch 0001
applicata, il porting rxgain (sotto) riceve `rxgains_5g{l,m,h}` e
`pa5ga[12]` per nome, niente costanti hardcoded.

## Strategia rxgain — SROM-driven

Tutti gli input del calcolo rxgain sono campi SROM nominali esposti dal
blob:

```
rxgains5gelnagaina{0,1,2}    rxgains5gtrisoa{0,1,2}    rxgains5gtrelnabypa{0,1,2}
rxgains5gmelnagaina{0,1,2}   rxgains5gmtrisoa{0,1,2}   rxgains5gmtrelnabypa{0,1,2}
rxgains5ghelnagaina{0,1,2}   rxgains5ghtrisoa{0,1,2}   rxgains5ghtrelnabypa{0,1,2}
noiselvl5ga{0,1,2}           rxgainerr5ga{0,1,2}        (entrambi array di 4 per sub-band)
```

Più gli analoghi `2g` (azzerati su questo board, `aa2g=0`).

### Formula populator (register-side)

Audit statico su `wlDSL-3580_EU.o_save`: il populator è inline in
`wlc_phy_attach_acphy @0x4660c`. Allocata `osl_malloc(1452)` su
`pi[168]`, zero-init, poi 6 `phy_getintvar` su nomi SROM templated
(`rxgains{2,5}g{eln,triso,trelnabyp}aN` — label `$LC12..$LC17` in
`.rodata.str1.4`). Le tre trasformazioni store-side sono
field-specific, non simmetriche:

```
910 + 3*core: (sprom_elnagain  + 3) << 1
911 + 3*core: (sprom_triso     + 4) << 1   <- letto dai 3 phy_reg_mod
912 + 3*core:  sprom_trelnabyp                  (raw)
```

Stride 12 fra le sub-band: i base sono 783 (2g), 795 (5gl), 807 (5gm),
819 (5gh).

Verificato sul disasm @0x46a48..0x46a5c (path 5g triso, store @off 796
ovvero 795+3·1):

```
   46a48:  andi   v0, v0, 0xff       ; SROM byte-clamp
   46a4c:  addiu  v0, v0, 4          ; +4
   46a58:  sll    v0, v0, 0x1        ; <<1
   46a5c:  sb     v0, 796(v1)        ; store cache
```

I 3 `phy_reg_mod` di `set_gaintbls_acphy` leggono solo `911 + 3*core`,
quindi cachano **solo `triso`**. `elnagain` e `trelnabyp` sono cachati
ma alimentano le 11 `wlc_phy_table_write_acphy` su id 0x44/0x45 (table
body, vedi sotto).

Formula committata in `b43_phy_ac_rxgain_init`:
`gainctx = (rxgains.triso[core] + 4) << 1`.

### Strategia per le table 0x44 / 0x45

Lo skeleton in `kernel-patch/new_files/rxgain_phy_ac.c` espone le 10
write per-core come array statico
`b43_phy_ac_rxgain_tbl_writes_5g[]` con un singolo resolver
`b43_phy_ac_rxgain_tbl_source()`. Resolver attualmente ritorna NULL —
nessuna write. Due strade per popolarlo, non alternative:

1. **Runtime populator SROM-driven** (PATCH POINT (a) nel resolver).
   Combina `rxgains_5gl.{elnagain, triso, trelnabyp}[core]` + i
   `block_B` base/delta arrays di `.rodata` + il return degli 8
   `wlc_phy_table_read_acphy` per riprodurre il body del per-core loop
   del blob. Da decodificare via disasm walk del body 0x42a8c..0x4307b.
2. **Dump statico via `wl phytable`** (PATCH POINT (b)). Capture di
   0x44/0x45 sul chip associato in stato MVP (channel 36, OFDM 6 Mbit)
   come `static const u8[]` indicizzati per `(id, offset, len)`.
   Richiede hardware. Anche oracolo di test per la (1).

Path block_A (2.4 GHz): dead code marcato `__maybe_unused` in
`rxgain_phy_ac.c`.

### SROM-side: encoding rxgains nei due word del chain block

Indipendente dal populator register-side. Cross-reference fra il dump
nominale (`nvram_dump`) e l'array byte grezzo (`srdump`): i 9 valori
rxgains per chain (4 sub-band × 3 fields, 12 byte) finiscono in due
word `srom[112,113]` per il chain 0 (analoghi per chain 1, 2 con
stride 20 word). Con assegnazione byte → sub-band `(5gm, 5gh, 2g, 5gl)`
regge l'encoding `value = (b<<7) | (t<<3) | e`:

```
5gm: e=7, t=15, b=1 → 0xff   (low byte di srom[112] = 0xff ✓)
5gh: e=7, t=15, b=1 → 0xff   (high byte di srom[112] = 0xff ✓)
2g:  e=0, t=0,  b=0 → 0x00   (low byte di srom[113] = 0x00 ✓)
5gl: e=3, t=6,  b=1 → 0xb3   (high byte di srom[113] = 0xb3 ✓)
```

<span style="color:red">**SALAME**</span> — gli unici byte
*informativi* sono `5gl=0xb3` (gli altri tre sono saturi a `0xff` o
zero), quindi l'encoding non è univocamente determinato. Encodings
alternativi che *casualmente* danno 0xb3 sui valori `(3, 6, 1)`
restano possibili. Disambiguazione richiede un secondo board della
famiglia 4352 con triplet rxgains diversi, o un read-back diretto dei
register `0x6f9 / 0x8f9 / 0xaf9` bits 14:8 dopo che il populator del
kernel ha girato — siccome la formula register-side legge solo
`triso`, serve specificamente un board con `triso` non saturo né
zero. `elnagain` / `trelnabyp` vanno testati indirettamente via le
table 0x44/0x45.

Finché `bcma_sprom_extract_r11` non popola `rxgains_5gl.triso[]`,
`triso` legge zero, `gainctx = (0+4)<<1 = 8`, e la high-byte dei tre
register rxgains è forzata a `0x08`. Sull'AP-tester sotto a 6 Mbit
OFDM (~50 cm dal client, 80 dB di link budget di troppo) è plausibile
che funzioni comunque, ma è da validare empiricamente.

## Bring-up MVP rivisto

Prerequisiti: kernel locale con `B43_PHY_AC=y` (rimosso `BROKEN`)
**+ patch series `sprom-rev11/` applicate** (le tre patch DRAFT in
`kernel-patch/sprom-rev11/` da applicare con `git am` sul kernel di
test), firmware in `/lib/firmware/b43/`, DSL-3580L sacrificabile, AP
target `D-Link DSL-3580L_5G` (cioè il router stesso) acceso su channel
36, seriale TTY.

1. **Smoke test**: `modprobe b43`. Verificare in dmesg:
   - PCI ID `0x14e4:0x43b3` detected su bus PCIe (su BCM63xx il bus è
     1, vedi `revinfo`)
   - chipid registrato = `0x4352` (chip family) con device `0x43b3`
   - SROM extract clean (la mainline accetta rev 11 dal 2015 anche
     senza queste patch; la differenza con le patch applicate è che
     i campi `ssb_sprom.subband5gver`, `ssb_sprom.rxgains_5gl.*`,
     `core_pwr_info[i].pa5ga[*]` sono popolati anziché zero —
     verificabile via debugfs/printk se utile)
   - sromrev = 11 letto correttamente
   - boardrev = 0x1353, boardid = 0x668
   - `num_cores = 2`
   - I 24 PHY init tables caricate senza WARN_ON
   - Radio 2069 power-on senza timeout
2. **`ifconfig wlan1 up`**: op_init deve completare clean. Se ucode
   timeout, controllare `RF_SEQ_STATUS` polling (200ms budget).
3. **Scan passivo** su 5 GHz UNII-1: `iw wlan1 scan freq 5180 5200
   5220 5240`. BSSID `D8:FE:E3:E2:A1:3E` deve apparire → RX path
   funziona a livello base.
4. **Associate** a `D-Link DSL-3580L_5G` con WPA2-PSK, forzando il
   client lato a 6 Mbit OFDM 20 MHz (no HT, no VHT). Failure più
   probabile: rxgain map sbagliata → AP non risponde all'auth/assoc.
   Compilare con `B43_DEBUG=y` per logs dettagliati. A questo punto la
   safety net Strategia 2 (table dump statico) può essere sostituita
   alla Strategia 0 SROM-driven per isolare se il problema è la
   formula populator.
5. **Ping 6 Mbit OFDM**: MVP raggiunto.

## Open questions residue

### Encoding rxgains nei due word del chain block (SROM-side)

Vedi §"Strategia rxgain — SROM-side" e il commento TODO di
`bcma_sprom_extract_r11` in `kernel-patch/sprom-rev11/0003-*.patch`.

### Significato di `subband5gver = 0x4`

Non corrisponde a un valore documentato pubblicamente nei `subband5gver`
di mainline (0=no5g, 1=US/EU/JP unified, 2=US, 3=EU, 4=?). <span
style="color:red">**SALAME**</span> — l'ipotesi che `0x4` sia un value
custom di una build OEM D-Link/Broadcom è plausibile ma non
verificabile senza accesso a documentazione interna o a un secondo
firmware OEM. Per il MVP non rileva (il bring-up sta su UNII-1, che è
band-agnostic). Per il post-MVP serve chiuderlo.

### `wl phytable` formato output

Il dump di table 0x44/0x45 mostra valori del tipo `0x0c000044`,
`0xfb000044`, dove il byte basso ripete il table id e il dato
significativo è in un altro byte. <span
style="color:red">**SALAME**</span> — l'interpretazione "byte alto =
data, byte basso = id echo, padding intermedio" è inferenza dal pattern
osservato; lettere alternative possibili includono "valore signed 32
bit con la maschera applicata sui bit alti per chip-specific reason".
Da chiudere prima di committare il dump come ground truth statico,
testando la stessa entry con `width=8` vs `width=16` vs `width=32`.

### Co-load con 0x435F integrated

Invariato rispetto alla revisione precedente. Il kernel deve poter
caricare b43 per *entrambi* i core (PCIe AC wl1 + SoC integrato wl0
N-PHY). I MAC sono già differenziati (`:3D` per wl0, `:3E` per wl1),
quindi il rischio di collisione `wlanN` è gestibile. Testabile solo a
bring-up reale.

## Post-MVP

### TX power control reale

Tutti i parametri richiesti sono nel SROM rev 11 estratto e — con la
serie patch `sprom-rev11/` applicata localmente — leggibili per nome
da `struct ssb_sprom` / `struct ssb_sprom_core_pwr_info`:

```
core_pwr_info[i].maxp2ga, maxp5ga[4]
core_pwr_info[i].pa2ga[3], pa5ga[12]
sprom->mcsbw{20,40,80,160}{2g,5gl,5gm,5gh}po
sprom->cckbw202gpo, cckbw20ul2gpo
sprom->pdoffset{2g40ma,40ma,80ma}[3]
```

Implementabile come §7r.5 del commento `op_init` originale, con la
differenza che ora i numeri vengono via `struct ssb_sprom` non da
hardcoding.

### OFDM HT / VHT — 5 GHz UNII-1

Estensione naturale del MVP OFDM 6 Mbit. Le 24 init tables coprono già
OFDM (`tx_evm`, `mcs`, `noise_shaping`); il path PHY è il punto da
auditare per "late PHY writes" OFDM-specific. Il <span
style="color:red">**SALAME**</span> della precedente revisione su
"eventuale coda OFDM in `wlc_phy_init_acphy` non ancora estratta"
resta valido.

### Nuovi sub-band 5 GHz (UNII-2/2e/3)

Bloccato dalla restrizione `Bad Channel` osservata. Se è regulatory:
risolvibile cambiando `ccode`/`regrev` sul chip o aggirando il
controllo nel kernel-patch. Se è `subband5gver=0x4`-related: serve
prima chiuderne il significato.

### 2.4 GHz su questo board

Impossibile: `aa2g=0`. La 2.4 GHz va testata su un board diverso della
famiglia 4352 (es. un BCM4352 PCIe card consumer con antenne 2.4 GHz
cablate). Fuori scope DSL-3580L.

### Submission upstream della serie `sprom-rev11/`

Pre-condizioni elencate nel README della serie:
`kernel-patch/sprom-rev11/README.md`. In sintesi: bring-up MVP a probe
+ RX, decoder rxgains chiuso o esplicitamente lasciato come TODO
documentato, cover letter che cita il thread Ian Kent 2015 per non
ricalpestare la stessa strada con Hauke Mehrtens (bcm47xx) e Rafał
Miłecki (bcma).

## Cosa è fatto (verificato)

- Tooling reverse chip-aware (path 0x43b3 vs `{4352, 4360, default}`)
  con diff per-funzione in `reverse-output/by-chip/`. Audit completo
  contro il path 0x43b3 di `radio_2069_init`,
  `radio_2069_channel_setup`, `switch_analog`, `reset_cca`,
  `mode_init`, `software_rfkill`: discrepanze risolte inline nel
  kernel-patch con citazione dell'offset disasm.
- `b43_phy_ac_rxgain_init`: prologue/epilogue, 4 `phy_reg_write`
  chip-default pinnati, calcolo `gainctx = (triso+4)<<1` applicato
  ai register canonici 1785/2297/2809/649, e scaffolding delle 10
  `wlc_phy_table_write_acphy` su id 0x44/0x45 (array statico +
  resolver con due PATCH POINTS — runtime populator e static dump).
  Resolver torna NULL: tabelle 0x44/0x45 inerti finché un dump o il
  populator non viene cablato.
- `kernel-patch/existing_files/{Makefile,phy_ac.h,phy_ac.c}.additions`
  riorientati a 5 GHz UNII-1: dispatch `op_switch_channel` rifiuta
  2.4 GHz con `-EOPNOTSUPP` (`aa2g=0` board-specific), range-check
  su UNII-1 36..48, `b43_chantab_r2069[]` popolato con
  `extract_chan_tuning_2069_GE16.py --band 5g`.
- SROM rev 11 dump completo del chip target verificato e committato
  in `router-data/`: `wl1_nvram.txt` (160 righe, dump nominale per
  nome) + `wl1_srom_raw.txt` (30 righe, 240 word raw BE).
  Cross-reference nome→valore→offset eseguibile localmente.
- `wl phytable` / `wl phyreg` confermati funzionanti su questo blob —
  via di acquisizione runtime aperta per ground truth.
- Serie patch DRAFT `kernel-patch/sprom-rev11/` (3 patch + README)
  contro mainline `master` `6d35786`: applica con `git am` in
  sequenza, non testata end-to-end. Trattenuta nel repo finché il
  bring-up non rende esercitabile l'estrazione.

## Provenance

I valori "verified" in questo README provengono da una sessione
diretta sul DSL-3580L target con firmware OEM `wl0: Jul 8 2013
13:52:55 version 6.30.102.7.cpe4.12L07.0`, attraverso:

- `wl -i wl1 nvram_dump` → SROM rev 11 nominale (campi per nome)
- `wl -i wl1 srdump` → SROM raw byte-level (240 word, BE byte stream)

I dump completi sono committati in `router-data/`:

```
router-data/wl1_nvram.txt        — output di `wl -i wl1 nvram_dump`
router-data/wl1_srom_raw.txt     — output di `wl -i wl1 srdump`
```

Il file `bcm43b3_3580l_map.bin` (480 byte, root del repo) è una
versione binaria del SROM, congruente coi 240 word di
`router-data/wl1_srom_raw.txt` salvo lo stato del CRC (high byte di
word 233): il `.bin` è di una snapshot anteriore, il `.txt` è il
dump corrente. Per il cross-reference nome→valore→offset il
testuale è la fonte affidabile.

Non ancora committati ma utili per chiudere le aperture residue:

- `wl -i wl1 revinfo` → header chip identificativo (chipnum,
  chiprev, corerev, radiorev, phytype, phyrev, boardid, sromrev).
  La maggior parte di questi campi è già citata nel README per
  valore — lo sarebbe per consolidare la provenance.
- `wl -i wl1 phyreg <off>` per `off ∈ {0x6f9, 0x8f9, 0xaf9}` →
  bits 14:8 sono il `gainctx` runtime per ciascun core. Necessario
  per chiudere la SALAME register-side della formula populator
  rxgain (vedi §"Open questions: formula populator"). Da prendere
  con il chip associato a un AP UNII-1, dopo che il driver OEM
  ha fatto girare il populator.

## Rigenerare gli output reverse

```sh
mips-linux-gnu-objdump -dr --no-show-raw-insn -M no-aliases \
    wlDSL-3580_EU.o_save > /tmp/wl.disr
python3 reverse-tools/run_quad_modal.py /tmp/wl.disr
```

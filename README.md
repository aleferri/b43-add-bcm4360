# b43 BCM4352-family / 0x43b3 (PHY-AC) — DSL-3580L

Porting `b43` per la generazione AC-PHY rev 1 r2069, target principale
DSL-3580L (BCM4352-family `0x43b3`, 2×2, 5 GHz only). Reverse a partire
dal binario `wlDSL-3580_EU.o_save`; le code-path estratte sono rifatte
con dispatch chip-aware su `{4352, 4360, default}`. Sample hardware
secondario sotto `router-data/`: D6220 (BCM43b3, ramo OEM 7.14.89) e
agcombo (BCM4360, ramo OEM 7.14.43, dual-band 3×3).

## Stato del bring-up

Hardware target sondato direttamente via `wl -i wl1 ...` su tre board
indipendenti della generazione AC-PHY rev 1 / r2069 (DSL-3580L,
Netgear D6220, agcombo). Vedi §"Provenance" in fondo. Il MVP è 5 GHz
UNII-1 sul DSL-3580L; la 2.4 GHz su questo board è coperta da wl0
(BCM6362 N-PHY, fuori scope).

### Quello che il chip target è davvero

Letto via `wl -i wl1 revinfo` e `wl -i wl1 nvram_dump`:

| Campo | Valore | Rilevanza |
|---|---|---|
| `vendor:device` | `0x14e4:0x43b3` | conferma target del repo |
| `chipnum / chiprev / corerev` | `0x4352 / 0x3 / 0x2a` | BCM4352-family conferma |
| `radiorev` | `0x42069000` | Radio 2069 |
| `phytype` | `0xb` (= AC-PHY) | conferma path acphy |
| `phyrev` | `0x1` | rev 1 (early AC) |
| `boardid` | `0x668` | **non** `0x513` (quello era wl0) |
| `boardrev` | `0x1353` (display "P353") | |
| `sromrev` | **`11`** | vedi §"SROM rev 11" |
| `aa2g / aa5g` | `0 / 3` | vedi §"Implicazione fondamentale" |
| `txchain / rxchain` | `3 / 3` | 2×2, conferma `num_cores=2` |
| `subband5gver` | `0x4` | partizione 5 GHz a 4 segmenti, confini 5250 / 5500 / 5745 MHz (da NVRAM sample BCM43569A2 in `armbian/firmware`, `nvfam-bcm43569a2-phy.txt`) |
| `boardflags / boardflags2` | `0x10000000 / 0x2` | board fixup minimale |
| `femctrl` | `6` | FEM controller mode board-specific |
| `epagain2g / epagain5g` | `0 / 0` | nessun PA esterno extra |

### Implicazione fondamentale: il chip è 5 GHz only su questo board

`aa2g=0` significa che il SROM dichiara **zero antenne disponibili
sulla 2.4 GHz**. Il chip target wl1 fa solo 5 GHz; la 2.4 GHz del
DSL-3580L è coperta da wl0 (BCM6362, N-PHY, fuori scope). L'MVP è
5 GHz UNII-1.

Sub-banda usata per il bring-up MVP: **UNII-1 (canali 36-48)** per
ortogonalità rispetto alle DFS reali. Nessuna restrizione regulatory
osservabile su UNII-1 da userspace: `wl -i wl1 chanspec` accetta
`5g36/20`, `5g36/80`, `5g40/80` sul DSL sotto firmware OEM 6.30 (e
analogamente sul agcombo sotto 7.14.43, dove anche `5g100/20` —
UNII-2e — passa). Il path mainline `b43`/`cfg80211` userà comunque
la regdb del kernel, indipendente dal blob OEM.

## Obiettivo MVP

Probe pulito + `ifconfig wlan1 up` + scan passivo + associate su AP
5 GHz canale 36 + 6 Mbit OFDM 1×1, su BCM4352-family **incluso**
0x43b3 (DSL-3580L). Tester di riferimento: l'AP `D-Link DSL-3580L_5G`
che il router stesso espone su BSSID `D8:FE:E3:E2:A1:3E`, channel 36
80 MHz, VHT80 capable.

Out of scope per MVP: HT/VHT, MIMO, calibrazioni reali, 40/80 MHz,
UNII-2/2e/3 (DFS).

## SROM rev 11: groundwork preparato (`kernel-patch/sprom-rev11/`)

`bcma_sprom_valid` mainline accetta rev 11 dal 2015 (Rafał Miłecki,
torvalds/linux `6d35786`). Quello che manca è l'estrattore: l'unico
implementato è `bcma_sprom_extract_r8`, chiamato indistintamente per
rev 8/9/10/11. Per una SROM rev 11 questo popola solo i campi a layout
condiviso e lascia a zero tutti quelli rev-11-only (`rxgains_*`,
`subband5gver`, il blocco femctrl, `mcsbw80*po`, `mcsbw160*po`, le
matrici `sb20in*`/`sb40and80`, `pdoffset*`, e per ogni chain `maxp2ga`,
`maxp5ga[4]`, `pa2ga[3]`, `pa5ga[12]`).

Per coprire il gap è in `kernel-patch/sprom-rev11/` una **patch DRAFT
v2** contro mainline (`0001-ssb-bcma-firmware-SROM-revision-11-support.patch`).
Single-file consolidation di tre cambi logicamente indipendenti che
però devono atterrare insieme per essere utili:

| Componente | File toccato | Obiettivo |
|---|---|---|
| (a) struct extension | `include/linux/ssb/ssb.h` | Estende `struct ssb_sprom` e `struct ssb_sprom_core_pwr_info` con i campi rev 11 dimostrati dal dump NVRAM del DSL-3580L. Tutto appeso, zero shift su campi esistenti, no-op per rev ≤ 10. |
| (b) NVRAM-key path | `drivers/firmware/broadcom/bcm47xx_sprom.c` | NVRAM key→field mapping per i nuovi campi rev 11 (`ENTRY()` mask `0x00000800`) + nuova `bcm47xx_fill_sprom_path_r11` per i campi per-chain CSV. Helper `nvram_read_u{8,16}_array` per i payload comma-separated come `pa5ga0=0xff4d,0x1690,...`. |
| (c) raw extractor | `drivers/bcma/sprom.c`, `include/linux/ssb/ssb_regs.h` | `bcma_sprom_extract_r11` con dispatch da `bcma_sprom_get`. Estrae header (offset rev-11-specifici `IL0MAC`/`ANTAVAIL`/`TXRXC` introdotti da v2), per-chain block stride 0x28, `subband5gver`, `pdoffset40ma`, region power-per-rate `0x150..0x190`. Region `0x190..0x1B0` resta TODO documentato. |

Stato: **DRAFT, NON da inviare**. La patch applica pulita (`git am`)
sul `master` corrente. Va mantenuta nel repo finché:

1. Il bring-up MVP raggiunge probe + RX su UNII-1 ch.36 (cioè il
   resto di questo README), così c'è almeno un consumer in-tree
   testabile dei nuovi campi.
2. Il decoder rxgains nel chain block (vedi §"Strategia rxgain"
   e §"Open questions residue") viene chiuso o lasciato
   esplicitamente come TODO con motivazione documentata.

L'invio anticipato è esplicitamente fuori discussione: mandare a
`linux-wireless` un estrattore rev 11 mai esercitato end-to-end è da
irresponsabili.

Vantaggio collaterale, già operativo localmente: con la patch
applicata, il porting rxgain (sotto) riceve `rxgains_5g{l,m,h}` e
`pa5ga[12]` per nome, niente costanti hardcoded.

## Strategia rxgain

Tutti gli input del calcolo rxgain sono campi SROM nominali esposti dal
blob:

```
rxgains5gelnagaina{0,1,2}    rxgains5gtrisoa{0,1,2}    rxgains5gtrelnabypa{0,1,2}
rxgains5gmelnagaina{0,1,2}   rxgains5gmtrisoa{0,1,2}   rxgains5gmtrelnabypa{0,1,2}
rxgains5ghelnagaina{0,1,2}   rxgains5ghtrisoa{0,1,2}   rxgains5ghtrelnabypa{0,1,2}
noiselvl5ga{0,1,2}           rxgainerr5ga{0,1,2}        (entrambi array di 4 per sub-band)
```

Più gli analoghi `2g`, che non sono usati dal populator del firmware
OEM neanche su board dual-band attivo (vedi §"Table 0x44 / 0x45").

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

### Table 0x44 / 0x45

Le 10 write per-core di `wlc_phy_table_write_acphy` su id 0x44/0x45
(width=8) sono in `b43_phy_ac_rxgain_tbl_writes_5g[]` di
`kernel-patch/new_files/rxgain_phy_ac.c`. Il resolver
`b43_phy_ac_rxgain_tbl_source()` serve la slice `[offset, offset+len)`
da due immagini statiche `b43_phy_ac_rxgain_5g_tbl_{44,45}_5gl[64]`
catturate via `wl phytable` sul DSL-3580L sotto OEM 6.30, sub-band
5gl (vedi `router-data/dsl3580l/wl1_phytable_5gl.txt`).

Il populator OEM 6.30 è chanspec-aware e popola il footprint completo
ad ogni channel switch; le immagini DSL sono lo stato post-populator
in 5g36/20. Il populator OEM 7.14 è single-shot ad attach-time (vedi
agcombo `router-data/agcombo/agcombo_phytable_5gl.txt`) e scrive un
sottoinsieme delle stesse immagini — i blocchi `[24..31]` e `[48..57]`
mancano sull'agcombo perché il 7.14 non fa il "second pass" dei
descriptor `@0x42fe8`/`@0x43008`/`@0x43028` ad attach-time.

Cross-board byte-per-byte:

- block B `[16..22]` di 0x44: identico DSL vs agcombo (BCM43b3 vs
  BCM4360, due famiglie chip).
- block A `[8..13]` di 0x44: differisce di un offset signed uniforme
  +3 su agcombo (0xfe vs 0xfb, 0x04 vs 0x01, ...). Plausibilmente
  termine di calibrazione board- o chain-count-dipendente; per il
  porting DSL si usano i valori DSL.
- block C `[32..41]`/[48..57]` di 0x44: tutti `0x07`, identici dove
  agcombo li scrive (il 6.30 li scrive due volte, il 7.14 una).
- 0x45: tre repliche del ramp `01 01 02 03 04 05 06 07` agli offset
  8/16/24, due blocchi `02*10` agli offset 32/48; agcombo ne ha solo
  un sottoinsieme.

Triplet rxgain `(elnagain, triso, trelnabyp)` per chain è
default-radio-side: identico per i tre chain del 3×3 agcombo, identico
fra agcombo (BCM4360) e DSL/D6220 (BCM4352-family). L'immagine 5gl
serve dunque tutti i chain senza per-chain stride.

Nota di copertura: il `b43_phy_ac_rxgain_tbl_writes_5g[]` descriptor
list copre 25+12 = 37 byte (sottoinsieme che il populator 7.14
agcombo committa). Il footprint reale del 6.30 sul DSL è più ampio
(le slice duplicate citate sopra). Per il bring-up MVP RX 6 Mbit OFDM
il sottoinsieme è probabilmente sufficiente — è quello che fa
funzionare il radio sull'agcombo. Estendere il descriptor list ai
duplicati è un follow-up se bring-up dimostra che il sottoinsieme è
limitante.

Quando `op_switch_channel` si estende a 5gm/5gh il resolver guadagna
un parametro sub-band e altre due immagini statiche, da catturare
con la stessa procedura sul DSL forzando la chanspec sulla sub-band
desiderata e rileggendo le table — il 6.30 rifa il populator quindi
non serve reboot.

Path block_A (2.4 GHz): dead code marcato `__maybe_unused` in
`rxgain_phy_ac.c`. Confermato che il populator 2g del firmware OEM non
passa per i campi SROM `rxgains2g*` neanche su un board dual-band
attivo (agcombo, `aa2g=7`, `rxgains2g*=0` su tutti i chain).

### SROM-side: encoding rxgains nei due word del chain block

I 9 valori rxgains per chain (4 sub-band × 3 fields, 12 byte) finiscono
in due word `srom[112,113]` per chain 0 (analoghi per chain 1, 2 con
stride 20 word). Encoding canonico per byte (Broadcom `bcmsrom_tbl.h`
rev-11 mask):

| bit  | 5g_ (per byte high) | 2g_ / 5gm (per byte low) |
|---|---|---|
| 7   | trelnabyp | trelnabyp |
| 6:3 | triso (4 bit) | triso (4 bit) |
| 2:0 | elnagain (3 bit) | elnagain (3 bit) |

`value = (trelnabyp << 7) | (triso << 3) | elnagain`. Byte assignment
per sub-band:

```
word 112 (RXGAINS1, path offset 4):  high byte = 5gh, low byte = 5gm
word 113 (RXGAINS,  path offset 5):  high byte = 5gl, low byte = 2g
```

Decodifica del DSL/D6220/agcombo (`srom[112]=0xffff, srom[113]=0xb300`):

```
5gh: 0xff → e=7,  t=15, b=1
5gm: 0xff → e=7,  t=15, b=1
5gl: 0xb3 → e=3,  t=6,  b=1
2g:  0x00 → e=0,  t=0,  b=0
```

Cross-check runtime su due board 7.x: `phyreg 0x{6,8,a}f9` bits 14:8 =
`0x16` su D6220 (7.14.89) e agcombo (7.14.43), formula `(triso+4)<<1+2`
⇒ triso=6 — consistente con `0xb3` decodificato.

Triplet rxgain default radio-side: i tre board sampleati (DSL-3580L
2×2 BCM43b3, D6220 2×2 BCM43b3, agcombo 3×3 BCM4360) hanno triplet
identico `(3, 6, 1)/(7, 15, 1)/(7, 15, 1)/(0, 0, 0)` per
`(5gl, 5gm, 5gh, 2g)` per *ogni* chain. È una proprietà del radio rev
1 r2069, non una calibrazione board-specific.

## Bring-up MVP

Prerequisiti: kernel locale con `B43_PHY_AC=y` (rimosso `BROKEN`)
**+ patch `sprom-rev11/0001-*.patch` applicata** (DRAFT v2 da
applicare con `git am` sul kernel di test), firmware in
`/lib/firmware/b43/`, DSL-3580L sacrificabile, AP target
`D-Link DSL-3580L_5G` (cioè il router stesso) acceso su channel
36, seriale TTY.

1. **Smoke test**: `modprobe b43`. Verificare in dmesg:
   - PCI ID `0x14e4:0x43b3` detected su bus PCIe (su BCM63xx il bus è
     1, vedi `revinfo`)
   - chipid registrato = `0x4352` (chip family) con device `0x43b3`
   - SROM extract clean: con la patch `sprom-rev11/` applicata i campi
     `ssb_sprom.subband5gver`, `ssb_sprom.rxgains_5gl.*`,
     `core_pwr_info[i].pa5ga[*]` sono popolati (verificabile via
     debugfs/printk se utile)
   - sromrev = 11
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
   Compilare con `B43_DEBUG=y` per logs dettagliati.
5. **Ping 6 Mbit OFDM**: MVP raggiunto.

## Open questions residue

### Co-load con 0x435F integrated

Il kernel deve poter caricare b43 per *entrambi* i core (PCIe AC wl1
+ SoC integrato wl0 N-PHY). I MAC sono già differenziati (`:3D` per
wl0, `:3E` per wl1), quindi il rischio di collisione `wlanN` è
gestibile. Testabile solo a bring-up reale.

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
auditare per "late PHY writes" OFDM-specific. <span
style="color:red">**SALAME**</span> — possibile coda OFDM in
`wlc_phy_init_acphy` non ancora estratta dal disasm; va verificata
prima di committare l'estensione.

### Nuovi sub-band 5 GHz (UNII-2/2e/3)

Lato kernel mainline il regulatory passa per la regdb del kernel,
indipendente dal blob OEM. Estensione richiede dump phytable 0x44/0x45
per le sub-band 5gm e 5gh come fatto per 5gl in `router-data/agcombo/`.
Il blob 6.30 è l'oracolo naturale perché rifa il populator a chanspec
switch (verificato sul disasm DSL); il blob 7.14 è single-shot e
congela al sub-band attach-time, quindi richiederebbe un boot dedicato
per ognuna delle sub-band aggiuntive.

### 2.4 GHz su questo board

Impossibile: `aa2g=0`. Vale per tutto il reference design BCM43b3
(verificato anche sul D6220), non solo per il DSL-3580L. La 2.4 GHz va
testata su un chip diverso della stessa generazione che dichiari
`aa2g != 0`, ad esempio l'agcombo (BCM4360 dual-band 3×3, vedi
`router-data/agcombo/`). Fuori scope DSL-3580L.

### Allineamento driver 7.14 (Netgear D6220, agcombo)

La motivazione operativa del progetto è che il blob OEM per il D-Link
6.30 sul DSL-3580L soffre di disconnessioni frequenti in uso reale; il
porting `b43`/mainline è il percorso minimo per ottenere una piattaforma
affidabile (eventualmente sotto OpenWrt). Il bring-up MVP segue il
6.30 audit-ato perché è la riferimento del repo. Il ramo 7.14 mostra
evoluzioni concrete che vale considerare in post-MVP:

- **`wlc_phy_set_trloss_reg_acphy` separato** (a `0xa1ff8` nel
  `wlD6220.o`) — extract della parte register-write rxgain ctx fuori da
  `wlc_phy_rxgainctrl_set_gaintbls_acphy`. Refactor mainline-friendly,
  vale considerare la stessa separazione nel `b43_phy_ac_*`.
- **Correzione `+2` runtime** sul gainctx (audit @`0xa20fc` in
  `router-data/d6220/wlD6220_set_trloss_reg_acphy.disasm`, presente sia
  in 7.14.43 sia in 7.14.89 — proprietà del ramo 7.14, non un fix
  late). ~1 dB di rxgain ctx in più. Da valutare se replicare in
  mainline solo dopo che dati di campo dimostrano differenza misurabile
  sul link budget reale.
- **Cache layout 7.14 rifattorizzato** — `cache[1164]/[1166] +
  sprom[(core+730)*4 + 3]` invece del singolo `cache[911]`
  pre-trasformato del 6.30. <span style="color:red">**SALAME**</span> —
  identità algebrica col vecchio `(triso+4)<<1` regge sui data point
  runtime osservati (phyreg `0x16` su due build 7.14 distinti per
  triso=6 5gl), non formalmente verificata via disasm del populator
  attach-time 7.14. Non bloccante per il porting.
- **Populator single-shot ad attach-time** (verificato register-side e
  table-side su 7.14.43 e 7.14.89). Il porting `b43` chiama
  `b43_phy_ac_rxgain_init` solo da `op_init` ed è coerente.

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
  ai register canonici 1785/2297/2809/649, e le 10
  `wlc_phy_table_write_acphy` su id 0x44/0x45 servite da due immagini
  statiche `b43_phy_ac_rxgain_5g_tbl_{44,45}_5gl[]` catturate via
  `wl phytable` su BCM4360 reference (vedi
  `router-data/agcombo/agcombo_phytable_5gl.txt`). Resolver torna le
  slice corrette per id ∈ {0x44, 0x45}, NULL per altri id.
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
- Patch DRAFT v2 `kernel-patch/sprom-rev11/0001-*.patch` (single-file
  consolidation, vedi §"SROM rev 11" sopra) contro mainline `master`
  `6d35786`: applica con `git am`, non testata end-to-end. Trattenuta
  nel repo finché il bring-up non rende esercitabile l'estrazione.
- Harness userspace in `kernel-patch/sprom-rev11/harness/` che
  compila `bcma_sprom_extract_r11()` contro un kernel shim e diffa
  ogni campo popolato vs `wl nvram_dump`. Stato corrente con il fix
  v3 scoped (`SSB_SPROM11_CCODE = 0x0096`, vedi `cross_check.md`):
  `make check` (DSL raw) **77 PASS / 0 FAIL / 2 INFO**;
  `make check-d6220` (D6220 raw) **74 PASS / 0 FAIL / 5 INFO**;
  `make check-bcm4360usb` (synth) **clean** (Finding 1 collision
  fixed); `make check-agcombo` (synth, BCM4360 3×3 dual-band)
  **75 PASS / 0 FAIL / 4 INFO**.
- Cross-board confirmation su tre board indipendenti (DSL-3580L 2×2
  BCM43b3, D6220 2×2 BCM43b3, agcombo 3×3 BCM4360): stride per-chain
  0x28 e offset header reggono uniformemente; triplet rxgain
  `(3,6,1)/(7,15,1)/(7,15,1)/(0,0,0)` per `(5gl,5gm,5gh,2g)` identico
  fra tutti, default radio-side r2069 rev 1; populator OEM 7.14
  single-shot ad attach-time (verificato via phyreg e phytable invariant
  di chanspec).

## Provenance

I valori "verified" in questo README provengono da sessioni dirette su
tre board reali della stessa generazione AC-PHY rev 1 / r2069:

```
router-data/dsl3580l/      D-Link DSL-3580L, BCM43b3 2x2, OEM 6.30.102.7
                           wl1_nvram.txt + wl1_srom_raw.txt
router-data/d6220/         Netgear D6220, BCM43b3 2x2, OEM 7.14.89.14
                           wl1_*.txt + wlD6220_set_trloss_reg_acphy.disasm
                           Vedi router-data/d6220/README.md
router-data/agcombo/       BCM4360 reference 3x3, OEM 7.14.43.21
                           agcombo_*.txt + agcombo_phytable_5gl.txt
                           Vedi router-data/agcombo/README.md
```

Per il cross-reference nome→valore→offset SROM il testuale
`wl1_srom_raw.txt` (240 word BE per riga di word) è la fonte
affidabile su DSL e D6220. Su agcombo `srdump` ritorna zero (blob
implementa solo nvram_dump per la SROM nominale), quindi il
cross-reference offset-side per agcombo è derivato dagli altri due
board sotto stessa sromrev.

## Rigenerare gli output reverse

```sh
mips-linux-gnu-objdump -dr --no-show-raw-insn -M no-aliases \
    wlDSL-3580_EU.o_save > /tmp/wl.disr
python3 reverse-tools/run_quad_modal.py /tmp/wl.disr
```

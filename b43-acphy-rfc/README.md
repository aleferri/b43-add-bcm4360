# b43-acphy-rfc

Materiale di lavoro per portare il PHY-AC del driver Linux `b43` da
"stub-che-crasha" (stato dal 2015) a "minimo connesso a 1 Mbps CCK".

L'obiettivo dichiarato di questo bundle **non** è 802.11ac a piena banda.
È portare il driver al punto in cui:

- il probe completa senza NULL deref;
- `ifconfig wlan0 up` non logga errori;
- è possibile associarsi a un AP 2.4 GHz e inviare/ricevere a 1 Mbps CCK
  su un canale fisso, in 1x1, su un BCM4360/BCM4352;
- la patch è in forma di RFC sottomettibile a `linux-wireless`, con
  provenance dei dati documentata e cita lo stub di Rafał Miłecki del
  2015 come base.

Tutto il resto (5 GHz, OFDM/HT/VHT, MIMO, calibrazioni reali, 80 MHz)
è esplicitamente fuori scope per questo bundle e va in "future work".

## Cosa c'è dentro

```
b43-acphy-rfc/
├── README.md                 — questo file
├── ROADMAP.md                — i 4 tier di lavoro residuo, con priorità
├── kernel-patch/             — la patch RFC scaffolding sul kernel
│   ├── 0001-b43-AC-PHY-flesh-out-stubs.patch
│   └── PATCH_README.md       — come applicarla, cosa fa, cosa NON fa
├── reverse-tools/            — gli script di estrazione dal blob wl
│   ├── extract_phy_writes_v2.py
│   └── extract_acphy_tables_from_descriptor.py
└── reverse-output/           — output degli script su un wl MIPS BE 3x3
    ├── acphy_map_full.txt    — mappa per-funzione di tutte le call helper
    ├── acphy_tables_full.c   — 25 tabelle PHY-AC estratte, pronte da incollare
    └── acphy_tables_index.txt
```

## Da dove partire

1. Leggi `ROADMAP.md` per capire dove siamo e cosa manca.
2. `kernel-patch/PATCH_README.md` spiega lo stato della patch e come applicarla.
3. `reverse-tools/` contiene gli script Python; sono autonomi, hanno bisogno
   solo di `pyelftools` e di un disassemblato fatto con
   `mips-linux-gnu-objdump -dr --no-show-raw-insn -M no-aliases <wl.o>`.
4. `reverse-output/` è quello che è uscito sul blob da cui ho lavorato
   (un `wl` MIPS BE per BCM4360 3x3, da un router Broadcom). Su un blob
   diverso, gli stessi script producono output equivalente — la struttura
   `acphytbl_info_rev{0,2}` è la stessa.

## Disclaimer importante

Questo materiale non è destinato a essere applicato direttamente upstream
così com'è. È **scaffolding pedagogico + dati estratti**. Per arrivare a
un submit credibile mancano i passaggi del Tier 0 e Tier 1 della
ROADMAP, che richiedono Ghidra e hardware fisico per testarli.

I numeri delle tabelle in `acphy_tables_full.c` sono dati hardware
estratti da un blob proprietario Broadcom; il consenso storico nel
progetto b43 è che siano riproducibili (è la stessa logica per cui
b43-fwcutter ha potuto estrarre il firmware ucode), ma per un submit
upstream la decisione finale spetta al maintainer.

## Premessa che ha generato tutto

Il PHY-AC del driver b43 è SoftMAC (non FullMAC come spesso si ripete
per errore). Lo stub esiste in mainline dal gennaio 2015, non è mai
stato completato, e il `Kconfig` lo marca `BROKEN` da allora. Lo stub
crasha al probe perché alcune ops obbligatorie sono NULL. Il primo
lavoro di questo bundle è stato sostituire quei NULL con scheletri
documentati; il secondo è stato estrarre i dati statici dal blob
proprietario.

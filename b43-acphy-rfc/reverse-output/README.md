# reverse-output

Output prodotto dagli script di `reverse-tools/` su un blob `wl` MIPS BE
specifico (un router Broadcom DSL-3580, BCM4360 3x3 variant, kernel
proprietario non in distribuzione). Su un blob diverso, gli stessi
script producono output di forma equivalente: la struttura
`acphytbl_info_rev{0,2}` è la stessa per tutti i firmware AC della
famiglia 4360.

## acphy_tables_full.c

**45 KB, 663 righe, 25 tabelle del PHY-AC.** È il deliverable
principale del lavoro di estrazione. Pronto da incollare in
`tables_phy_ac.c` della patch scaffolding, eventualmente prefissando
i nomi simbolo con `b43_` per coerenza upstream.

Tabelle coperte:

| classe                | id              | width | core      |
|-----------------------|-----------------|------:|-----------|
| MCS index             | 0x1             |  16   | shared    |
| TX EVM                | 0x2             |   8   | shared    |
| Noise shaping         | 0x3             |  32   | shared    |
| RX EVM shaping        | 0x4             |   8   | shared    |
| Phase track           | 0x5             |  32   | shared (rev0+rev2) |
| SQ threshold          | 0x6             |  32   | shared    |
| Estimated power LUT   | 0x40/0x60/0x80  |  16   | core 0/1/2 |
| IQ LUT                | 0x41/0x61/0x81  |  32   | core 0/1/2 |
| LO Feedthrough LUT    | 0x42/0x62/0x82  |  16   | core 0/1/2 |
| PAPD comp RF power    | 0x40/0x60/0x80  |  16   | core 0/1/2 |
| PAPD comp epsilon     | 0x47/0x67/0x87  |  32   | core 0/1/2 |
| PAPD cal scalars      | 0x48/0x68/0x88  |  32   | core 0/1/2 |

NB: id 0x40/0x60/0x80 compaiono due volte (Estimated power LUT e
PAPD comp RF power): l'init le scrive in due fasi diverse. Lo stride
0x20 sugli id è il pattern per-core (id_core_n = id_core_0 + n*0x20),
**conferma 3x3 RF cores per questo dump**.

## acphy_tables_index.txt

Indice tabellare leggibile dei due descriptor array:

- `acphytbl_info_rev0`: 24 entries → 24 tabelle
- `acphytbl_info_rev2`: 12 entries → 12 tabelle (parzialmente sovrapposte
  con rev0; tabelle distinte: `nvadj_tbl_rev2`, `phasetrack_tbl_rev2`)

Tabelle uniche dumpate: 25 (alcune condivise tra rev0 e rev2).

## acphy_map_full.txt

**161 KB.** Mappa per-funzione delle call helper PHY/radio su tutto il
binario: 3767 funzioni scansionate, 645 con call riconosciute, 2935
call totali. Una riga per call, formato:

```
funzione_chiamante:
  <addr>  helper_name(arg1=val, arg2=val, ...)
```

Argomenti immediati noti come `0x140`, `0x19e`. Argomenti runtime come
`?`. Puntatori a simboli statici come `&sym` o `&sym+0x10`. Stack args
(slot 5+) come valore se trackato, `?` altrimenti.

Da usare come reference quando si apre una funzione in Ghidra: la
mappa ti dice cosa aspettarti di vedere prima di disassemblare.

## Provenance dei dati

I numeri nelle tabelle sono dati hardware estratti dal blob
proprietario via uno script Python deterministico. Lo script (in
`reverse-tools/`) legge le sezioni `.rodata`/`.data` dell'ELF
`wl.o`, segue le relocations standard MIPS, e formatta come C array.

Per il submit upstream, ogni tabella in `tables_phy_ac.c` dovrebbe
riportare nel commento il simbolo originale, il file binario, e il
suo hash. Vedi ROADMAP punto 3.3.

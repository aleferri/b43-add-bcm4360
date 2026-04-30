# reverse-tools

Script Python per estrarre dati statici dal driver Broadcom `wl` MIPS BE.

## Prerequisiti

- `python3` >= 3.8
- `pyelftools`: `pip install pyelftools --break-system-packages`
- `binutils-mips-linux-gnu` per il disassemblato:
  `apt install binutils-mips-linux-gnu`

## Workflow

```sh
# 1. Disassembla con relocations inline
mips-linux-gnu-objdump -dr --no-show-raw-insn -M no-aliases wl.o > wl.disr

# 2. Estrazione descriptor-driven (preferita): cammina acphytbl_info_rev{0,2}
#    nella .rodata e dumpa le 25 tabelle init come C array.
python3 extract_acphy_tables_from_descriptor.py wl.o output_dir/

# 3. Mappa per-funzione di tutte le call helper PHY/radio. Utile per leggere
#    il flusso e capire le funzioni da approfondire in Ghidra.
python3 extract_phy_writes_v2.py wl.disr wl.o output_dir/ [--filter acphy]
```

## extract_acphy_tables_from_descriptor.py

Identifica i due simboli `acphytbl_info_rev0` e `acphytbl_info_rev2`,
li interpreta come array di `struct {void *ptr; uint len, id, off, width;}`
da 20 byte ciascuno, segue le `R_MIPS_32` reloc sui campi `ptr`, e dumpa
ogni tabella puntata come C array con la `width` corretta (8/16/32 bit).

Output:
- `acphy_tables_full.c` — i 25 array C pronti da incollare;
- `acphy_tables_index.txt` — indice tabellare per id/len/off/width/simbolo.

**SALAME**: assume layout `(ptr, len, id, off, width)` di 4 byte ciascuno.
Va verificato in Ghidra prima di fidarsi (vedi ROADMAP punto 0.3). Se
l'ordine dei campi è diverso, lo script va aggiornato di una riga
(`>5I` con riordino dei field name).

## extract_phy_writes_v2.py

Pre-pass di analisi statica: per ogni funzione del binario, riconosce le
chiamate alle helper PHY/radio (~20 simboli noti come `phy_reg_write`,
`wlc_phy_table_write_acphy`, `mod_radio_reg`, ecc.) ricostruendo i
valori degli argomenti `a1/a2/a3` e dello stack frame al call site.

Capabilities:
- pairing di `R_MIPS_HI16` + `R_MIPS_LO16` → `SymPtr(sym, addend)`
- tracking degli store sullo stack (`sw rX, off(sp)` per off in {16,20,24,28})
  per recuperare gli argomenti 5°/6°/7°/8° passati via stack in o32
- invalidazione dei caller-saved a ogni `jal/jalr`
- dump del payload via pyelftools quando `arrptr` è risolvibile come
  simbolo statico in `.rodata`/`.data`

Limiti dichiarati:
- niente memory tracking (load da `lw r,off(rs)` → `?`)
- niente cross-call propagation (saved regs `s*` invalidati prudenzialmente)
- assume MIPS BE — per LE basta cambiare `'big'` in `'little'` in due punti

Output:
- `acphy_map.txt` — una riga per call helper riconosciuta
- `acphy_tables.c` — payload di table writes con `arrptr` statico
- `acphy_dump_diagnostics.txt` — perché alcune call sono state skippate

## Numero alla mano (sul blob a cui ho lavorato)

- 99 funzioni `acphy*` → 63 con call helper riconosciute → 279 call totali
- 3767 funzioni totali nel binario → 645 con call helper → 2935 call totali
- 25 tabelle init coperte dai descriptor (sufficienti per il MVP CCK)
- ~10 tabelle `acphy_txgain_*` orfane (band-specific, post-MVP)

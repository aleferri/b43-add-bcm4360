# radio2069_init_extracted — diff per-chip

Confronto del set di operazioni estratte (tuple `_ops.tsv`)
attraverso i 4 path chip-aware. Ogni "sezione" qui è una
singola tupla (riga del TSV); il diff è a livello di insieme,
non di sequenza — l'ordine non altera il risultato.

## Sintesi

| metric | valore |
|---|---:|
| op count `default` | 20 |
| op count `4352` | 20 |
| op count `4360` | 20 |
| op count `43b3` | 16 |
| tuple uniche totali | 27 |
| ✅ chip-agnostic (in tutti e 4) | 9 |
| 🟡 43b3 == default ≠ {4352,4360} | 6 |
| 🔴 43b3 anomalo (vedi sotto) | 12 |
| ⚪ altri pattern (audit secondario) | 0 |

## ✅ Verified chip-agnostic

| addr | type | field1 | field2 | field3 |
|---|---|---|---|---|
| 0x00045194 | phy_write | 0x0415 | 0x0000 |  |
| 0x000451a4 | phy_write | 0x040e | 0x0000 |  |
| 0x000451b4 | phy_write | 0x040c | 0x2000 |  |
| 0x000451c4 | phy_write | 0x0408 | 0x0000 |  |
| 0x000451d4 | phy_write | 0x0417 | 0x0000 |  |
| 0x000451e4 | phy_write | 0x0416 | 0x000d |  |
| 0x00045228 | phy_write | 0x0408 | 0x0007 |  |
| 0x00045234 | udelay | 100 |  |  |
| 0x00045244 | phy_write | 0x0408 | 0x0006 |  |

## 🟡 43b3 prende il path default (ok per regression)

| addr | type | field1 | field2 | field3 |
|---|---|---|---|---|
| 0x000452a0 | radio_maskset | 0x097f | 0x0800 | 0x0800 |
| 0x000452b4 | radio_maskset | 0x097f | 0x4000 | 0x4000 |
| 0x000452c8 | radio_maskset | 0x0980 | 0x0800 | 0x0800 |
| 0x000452dc | radio_maskset | 0x097f | 0x8000 | 0x8000 |
| 0x000452f0 | radio_maskset | 0x097f | 0x1000 | 0x1000 |
| 0x00045304 | radio_maskset | 0x097f | 0x0004 | 0x0004 |

## 🔴 43b3 anomalo — da investigare

| addr | type | field1 | field2 | field3 |
|---|---|---|---|---|
| 0x00045330 | radio_maskset | 0x096b | 0x0800 | 0x0800 |
| 0x0004540c | radio_maskset | 0x096b | 0x0004 | 0x0004 |
| 0x00045438 | radio_maskset | 0x0407 | 0x0002 | 0x0002 |
| 0x00045438 | radio_maskset | 0x0807 | 0x0002 | 0x0002 |
| 0x000456a4 | phy_write | 0x0417 | 0x000d |  |
| 0x000456b4 | phy_write | 0x0408 | 0x0002 |  |
| 0x000456d0 | udelay | 100 |  |  |
| 0x000456e0 | phy_write | 0x0417 | 0x0004 |  |
| 0x00045770 | radio_maskset | 0x096b | 0x4000 | 0x4000 |
| 0x00045794 | radio_maskset | 0x096c | 0x0800 | 0x0800 |
| 0x000457b8 | radio_maskset | 0x096b | 0x8000 | 0x8000 |
| 0x000457dc | radio_maskset | 0x096b | 0x1000 | 0x1000 |

---

Generato da `reverse-tools/run_quad_modal.py`. Per
rigenerare:

```sh
mips-linux-gnu-objdump -dr --no-show-raw-insn -M no-aliases \
    wlDSL-3580_EU.o_save > /tmp/wl.disr
python3 reverse-tools/run_quad_modal.py /tmp/wl.disr
```

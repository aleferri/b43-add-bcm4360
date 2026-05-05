# switch_radio_acphy_extracted — diff per-chip

Confronto del set di operazioni estratte (tuple `_ops.tsv`)
attraverso i 4 path chip-aware. Ogni "sezione" qui è una
singola tupla (riga del TSV); il diff è a livello di insieme,
non di sequenza — l'ordine non altera il risultato.

## Sintesi

| metric | valore |
|---|---:|
| op count `default` | 30 |
| op count `4352` | 30 |
| op count `4360` | 30 |
| op count `43b3` | 30 |
| tuple uniche totali | 53 |
| ✅ chip-agnostic (in tutti e 4) | 7 |
| 🟡 43b3 == default ≠ {4352,4360} | 23 |
| 🔴 43b3 anomalo (vedi sotto) | 23 |
| ⚪ altri pattern (audit secondario) | 0 |

## ✅ Verified chip-agnostic

| addr | type | field1 | field2 | field3 |
|---|---|---|---|---|
| off | 0x00045d98 | phy_write | 0x0408 | 0x0000 |
| off | 0x00045da8 | phy_write | 0x0417 | 0x0000 |
| off | 0x00045de8 | phy_write | 0x0416 | 0x0001 |
| on | 0x0004588c | extern_call | wlc_phy_radio2069_pwron_seq |  |
| on | 0x00045a70 | udelay | 0x0001 |  |
| on | 0x00045af0 | udelay | 0x000a |  |
| on | 0x00045c00 | extern_call | wlc_phy_radio2069_rccal |  |

## 🟡 43b3 prende il path default (ok per regression)

| addr | type | field1 | field2 | field3 |
|---|---|---|---|---|
| off | 0x00045c6c | phy_write | 0x073e | 0x0000 |
| off | 0x00045c94 | phy_write | 0x0739 | 0x0000 |
| off | 0x00045cbc | phy_write | 0x073a | 0x0000 |
| off | 0x00045ce4 | phy_write | 0x0725 | 0x1fff |
| off | 0x00045d0c | phy_write | 0x0729 | 0x0000 |
| off | 0x00045d34 | phy_write | 0x0721 | 0xffff |
| off | 0x00045d5c | phy_write | 0x0728 | 0x0000 |
| off | 0x00045d88 | phy_write | 0x0720 | 0x03ff |
| on | 0x000458dc | radio_maskset | 0x08f2 | 0x0040 |
| on | 0x00045908 | radio_maskset | 0x08f2 | 0x0080 |
| on | 0x00045934 | radio_maskset | 0x08f5 | 0x0600 |
| on | 0x00045960 | radio_maskset | 0x08f5 | 0x1800 |
| on | 0x0004598c | radio_maskset | 0x095b | 0x0001 |
| on | 0x000459bc | radio_write | 0x095c | 0x0000 |
| on | 0x000459e4 | radio_write | 0x095d | 0x0000 |
| on | 0x00045a0c | radio_write | 0x095e | 0x0000 |
| on | 0x00045a34 | radio_write | 0x095f | 0x0000 |
| on | 0x00045a64 | radio_maskset | 0x0810 | 0x0001 |
| on | 0x00045aa0 | radio_maskset | 0x0810 | 0x0001 |
| on | 0x00045b6c | radio_maskset | 0x095b | 0x0001 |
| on | 0x00045b98 | radio_maskset | 0x08f2 | 0x0040 |
| on | 0x00045bc4 | radio_maskset | 0x08f2 | 0x0080 |
| on | 0x00045bf0 | radio_maskset | 0x0810 | 0x0001 |

## 🔴 43b3 anomalo — da investigare

| addr | type | field1 | field2 | field3 |
|---|---|---|---|---|
| off | 0x00045d88 | phy_write | 0x1720 | 0x03ff |
| off | 0x00045e00 | phy_write | 0x173e | 0x0000 |
| off | 0x00045e20 | phy_write | 0x1739 | 0x0000 |
| off | 0x00045e40 | phy_write | 0x173a | 0x0000 |
| off | 0x00045e60 | phy_write | 0x1725 | 0x1fff |
| off | 0x00045e80 | phy_write | 0x1729 | 0x0000 |
| off | 0x00045ea0 | phy_write | 0x1721 | 0xffff |
| off | 0x00045ec0 | phy_write | 0x1728 | 0x0000 |
| on | 0x000458dc | radio_maskset | 0x08ea | 0x0040 |
| on | 0x00045908 | radio_maskset | 0x08ea | 0x0080 |
| on | 0x00045934 | radio_maskset | 0x08ed | 0x0600 |
| on | 0x00045960 | radio_maskset | 0x08ed | 0x1800 |
| on | 0x0004598c | radio_maskset | 0x0548 | 0x0001 |
| on | 0x000459bc | radio_write | 0x0549 | 0x0000 |
| on | 0x000459e4 | radio_write | 0x054a | 0x0000 |
| on | 0x00045a0c | radio_write | 0x054b | 0x0000 |
| on | 0x00045a34 | radio_write | 0x054c | 0x0000 |
| on | 0x00045a64 | radio_maskset | 0x040b | 0x0001 |
| on | 0x00045aa0 | radio_maskset | 0x040b | 0x0001 |
| on | 0x00045b6c | radio_maskset | 0x0548 | 0x0001 |
| on | 0x00045b98 | radio_maskset | 0x08ea | 0x0040 |
| on | 0x00045bc4 | radio_maskset | 0x08ea | 0x0080 |
| on | 0x00045bf0 | radio_maskset | 0x040b | 0x0001 |

---

Generato da `reverse-tools/run_quad_modal.py`. Per
rigenerare:

```sh
mips-linux-gnu-objdump -dr --no-show-raw-insn -M no-aliases \
    wlDSL-3580_EU.o_save > /tmp/wl.disr
python3 reverse-tools/run_quad_modal.py /tmp/wl.disr
```

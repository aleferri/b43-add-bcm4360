# init_acphy_extracted — diff per-chip

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
| op count `43b3` | 20 |
| tuple uniche totali | 23 |
| ✅ chip-agnostic (in tutti e 4) | 17 |
| 🟡 43b3 == default ≠ {4352,4360} | 3 |
| 🔴 43b3 anomalo (vedi sotto) | 3 |
| ⚪ altri pattern (audit secondario) | 0 |

## ✅ Verified chip-agnostic

| phase | addr | reg | val |
|---|---|---|---|
| bphy | 0x000536ac | 0x033a | 0x0395 |
| bphy | 0x000536bc | 0x033b | 0x0395 |
| bphy | 0x000536cc | 0x033e | 0x0395 |
| bphy | 0x000536dc | 0x033f | 0x0395 |
| bphy | 0x000536ec | 0x0342 | 0x0395 |
| bphy | 0x000536fc | 0x0343 | 0x0395 |
| bphy | 0x0005370c | 0x0346 | 0x0395 |
| bphy | 0x0005371c | 0x0347 | 0x0395 |
| bphy | 0x0005372c | 0x033c | 0x0315 |
| bphy | 0x0005373c | 0x033d | 0x0315 |
| bphy | 0x0005374c | 0x0340 | 0x0315 |
| bphy | 0x0005375c | 0x0341 | 0x0315 |
| bphy | 0x0005376c | 0x0344 | 0x0315 |
| bphy | 0x0005377c | 0x0345 | 0x0315 |
| bphy | 0x0005378c | 0x0348 | 0x0315 |
| bphy | 0x0005379c | 0x0349 | 0x0315 |
| mode | 0x0005331c | 0x0410 | 0x0077 |

## 🟡 43b3 prende il path default (ok per regression)

| phase | addr | reg | val |
|---|---|---|---|
| mode | 0x000534c0 | 0x0728 | 0x0080 |
| mode | 0x000534e8 | 0x0720 | 0x0180 |
| mode | 0x00053538 | 0x0721 | 0x5000 |

## 🔴 43b3 anomalo — da investigare

| phase | addr | reg | val |
|---|---|---|---|
| mode | 0x000534c0 | 0x1728 | 0x0080 |
| mode | 0x000534e8 | 0x1720 | 0x0180 |
| mode | 0x00053538 | 0x1721 | 0x5000 |

---

Generato da `reverse-tools/run_quad_modal.py`. Per
rigenerare:

```sh
mips-linux-gnu-objdump -dr --no-show-raw-insn -M no-aliases \
    wlDSL-3580_EU.o_save > /tmp/wl.disr
python3 reverse-tools/run_quad_modal.py /tmp/wl.disr
```

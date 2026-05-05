# firmware/ — AC42 firmware files for development testing

Tre file firmware estratti dal blob `wlDSL-3580_EU.o_save` (D-Link DSL-3580
GPL drop), pronti da copiare in `/lib/firmware/b43/` per testare il driver
b43 PHY-AC mentre lo si sviluppa. Il firmware (ucode AC42 build 784.2 +
init values) è chip-agnostic all'interno della famiglia BCM4352
(`{0x4352, 0x4348, 0x4333, 0x43A2, 0x43B0, 0x43B3}`), quindi è
riusabile per il target 0x43b3 (DSL-3580L) anche se l'estrazione è
stata fatta dal binario di un router con quel chip.

```
ucode42.fw           40024 B   PHY-AC microcode 784.2 (build 2012-08-15 21:43:22)
ac1initvals42.fw      3442 B   AC PHY rev 1 init values (610 IVs)
ac1bsinitvals42.fw     368 B   AC PHY rev 1 band-switch init values (73 IVs)
```

`SHA256SUMS` per verifica integrità.

## Provenance

- **Sorgente:** `wlDSL-3580_EU.o_save` (incluso al livello superiore del bundle),
  md5 `29083101b54f9a1c0ee45a74b6f9eff2`, MIPS BE ELF non strippato dal
  GPL drop ufficiale di D-Link per il DSL-3580.
- **Estrazione:** `extract.py` in questa cartella, basato sui simboli
  `d11ucode42`, `d11ac1initvals42`, `d11ac1bsinitvals42` esposti
  nella `.rodata` del wl.o.
- **Build identity dell'ucode:** `784.2`, lettura confermata sia dai
  simboli `d11ucode_bom{major,minor}` (4 coppie tutte coerenti) sia dal
  disassemblaggio del payload (opcode `0x378` con op3∈{0,1,2,3}) che
  produce `version=784, revision=2, date=2012-08-15, time=21:43:22`.

## Path di produzione (per gli utenti finali)

Questi file **non sono per la distribuzione**. Sono materiale di
sviluppo locale.  Un utente con un chip Broadcom AC42 (BCM4352-family,
inclusi 0x4352/0x4348/0x4333/0x43A2/0x43B0/0x43B3) che voglia usare il
driver b43 dovrebbe seguire il path standard:

- **Debian/Ubuntu:** `apt install firmware-b43-installer`
  (scarica e estrae automaticamente il tarball ASUS RT-AC66U).
- **Arch:** `b43-firmware` AUR (stesso tarball).
- **Manuale:** scarica `broadcom-wl-6.30.163.46.tar.bz2` da un mirror
  affidabile e lancia `b43-fwcutter wl_apsta.o` upstream — fwcutter
  conosce già quel blob (md5 `29c8a47094fbae342902d84881a465ff`) e
  produce `ucode42.fw` con la stessa build identity 784.2.

`extract.py` è solo per chi parte da un wl.o BE diverso (router OEM)
e non vuole / non può procurarsi il tarball ASUS.

## Note sull'identità byte-per-byte con il path standard

Il microcode 784.2 dovrebbe essere byte-identico fra il path standard
(LE blob → fwcutter swap → BE wire format) e questo bundle (BE blob
→ copia diretta → BE wire format), perché entrambi i blob includono
la stessa build canonica Broadcom (timestamp identico al secondo).
Non è stato verificato direttamente con un `cmp`: il verificare
richiederebbe scaricare e estrarre il tarball ASUS; chi vuole farlo
trova istruzioni nel README di livello superiore del progetto.
Eventuali differenze byte sarebbero comunque accidentali (compressione
diversa, tooling diverso) e non semantiche.

## Riproduzione locale

```sh
# da questa cartella, oppure ovunque tu abbia il blob
python3 extract.py ../../wlDSL-3580_EU.o_save -o /tmp/out
sha256sum /tmp/out/*.fw
diff <(sha256sum /tmp/out/*.fw | awk '{print $1}') \
     <(awk '{print $1}' SHA256SUMS)
```

Lo script richiede solo `python3` e `binutils` (`objdump`, `readelf`).
È volutamente BE-only — per blob LE c'è `b43-fwcutter` upstream che
fa già il lavoro meglio.

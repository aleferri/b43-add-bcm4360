#!/usr/bin/env python3
# extract.py — re-extract AC42 firmware from a non-stripped BE wl.o ELF.
#
# This is a backup / pedagogical tool.  The recommended path for getting
# the same .fw files in production is to install firmware-b43-installer
# (Debian/Ubuntu) or run upstream b43-fwcutter against the ASUS RT-AC66U
# tarball broadcom-wl-6.30.163.46.tar.bz2.  Use this script only when you
# need to reproduce the extraction from a different (BE) wl.o, e.g. the
# D-Link DSL-3580 GPL drop the rest of this project is built around.
#
# LE blobs are intentionally rejected: for those, fwcutter is the right
# tool and already knows the entries.

import argparse, re, struct, subprocess, sys
from pathlib import Path

WANTED = [
    # (sym,                     out_name,             type)
    ('d11ucode42',              'ucode42.fw',         'u'),
    ('d11ac1initvals42',        'ac1initvals42.fw',   'i'),
    ('d11ac1bsinitvals42',      'ac1bsinitvals42.fw', 'i'),
]

def objdump(args):
    return subprocess.check_output(['objdump'] + args, text=True).splitlines()

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('elf')
    ap.add_argument('-o', '--outdir', default='.')
    a = ap.parse_args()

    if 'big endian' not in subprocess.check_output(['readelf', '-h', a.elf], text=True):
        sys.exit("error: this script handles BE wl.o only; for LE use b43-fwcutter")

    # .rodata file offset
    ro_rx = re.compile(r'\d+\s+\.rodata\s+\S+\s+\S+\s+\S+\s+([0-9a-fA-F]+)')
    rodata_off = next(int(m.group(1), 16)
                      for ln in objdump(['--headers', a.elf])
                      if (m := ro_rx.match(ln.strip())))

    # Symbol table → addr/size for things we care about
    sym_rx = re.compile(r'([0-9a-fA-F]+)\s+g\s+O\s+\.rodata\s+([0-9a-fA-F]+)\s+(\S+)')
    syms = {m.group(3): (int(m.group(1), 16), int(m.group(2), 16))
            for ln in objdump(['-t', a.elf])
            if (m := sym_rx.match(ln.strip()))}

    # Sanity: read ucode build identity (any of the bom* pairs will do)
    blob = Path(a.elf).read_bytes()
    for maj_sym, min_sym in [('d11ucode_bommajor',      'd11ucode_bomminor'),
                             ('d11ucode_gt15_bommajor', 'd11ucode_gt15_bomminor')]:
        if maj_sym in syms and min_sym in syms:
            maj = struct.unpack('>I', blob[rodata_off + syms[maj_sym][0]:][:4])[0]
            mnr = struct.unpack('>I', blob[rodata_off + syms[min_sym][0]:][:4])[0]
            print(f"# ucode build identity: {maj}.{mnr}  (from {maj_sym})")
            break

    out = Path(a.outdir); out.mkdir(parents=True, exist_ok=True)
    for sym, name, typ in WANTED:
        if sym not in syms:
            print(f"skip {sym}: not in .rodata", file=sys.stderr); continue
        addr, size = syms[sym]
        raw = blob[rodata_off + addr:][:size]

        if typ == 'u':
            # On a BE wl.o the ucode is already stored in BE word order, which
            # is the wire format b43 expects. Copy verbatim.
            payload, count = raw, len(raw)
        else:
            # Convert struct iv stream to b43_iv stream, dropping 0xffff sentinel.
            buf = bytearray(); count = 0
            for i in range(0, size, 8):
                reg, sz, val = struct.unpack_from('>HHI', raw, i)
                if reg == 0xFFFF and sz == 0:
                    break
                if reg & 0x8000:    sys.exit(f"bad IV reg 0x{reg:x}")
                if sz == 4:         buf += struct.pack('>HI', reg | 0x8000, val)
                elif sz == 2:       buf += struct.pack('>HH', reg, val & 0xFFFF)
                else:               sys.exit(f"bad IV size {sz}")
                count += 1
            payload = bytes(buf)

        # b43 fw_header: type(1), ver(1), pad(2), be32 size
        hdr = struct.pack('>BBBBI', ord(typ), 0x01, 0, 0, count)
        (out / name).write_bytes(hdr + payload)
        print(f"wrote {out/name}  ({len(hdr)+len(payload)} B)")

if __name__ == '__main__':
    main()

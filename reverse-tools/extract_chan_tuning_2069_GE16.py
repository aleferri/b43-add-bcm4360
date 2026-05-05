#!/usr/bin/env python3
# extract_chan_tuning_2069_GE16.py
#
# Read the chan_tuning_2069rev_GE16 array from a non-stripped BE wl ELF
# and emit it as a C array compatible with the b43 driver.
#
# What this script *can* tell you (verified against the blob):
#   - the channel number              (offset  0, u16)
#   - the center frequency in MHz     (offset  2, u16)
#   - the six BW filter values        (offset 82..92, six u16)
#
# What it *cannot* tell you, because the blob included here does not
# contain wlc_phy_chanspec_radio2069_setup() — only the lookup function
# wlc_phy_chan2freq_acphy() — is which radio register receives which of
# the 36 u16 in the middle (offset 4..80). Those values are emitted as
# a raw u16 array; once the setup function is recovered (e.g. from the
# ASUS RT-AC66U LE wl_apsta blob) we can replace the raw[] field with
# named sub-fields like b43_phy_ht uses (radio_syn_pll_vcocal1, etc).

import argparse, re, struct, subprocess, sys
from pathlib import Path

SYM = 'chan_tuning_2069rev_GE16'
STRIDE = 94          # verified: 7238 bytes / 77 entries
ENTRIES = 77
N_U16 = STRIDE // 2   # 47


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('elf')
    ap.add_argument('--band', choices=['2g', '5g', 'all'], default='2g',
                    help="which subset to emit (default: 2g, channels 1..14)")
    a = ap.parse_args()

    if 'big endian' not in subprocess.check_output(
            ['readelf', '-h', a.elf], text=True):
        sys.exit("error: BE wl.o only; for LE the symbol may be exposed differently")

    headers = subprocess.check_output(
        ['mips-linux-gnu-objdump', '--headers', a.elf], text=True)
    data_off = next(int(m.group(1), 16)
                    for ln in headers.splitlines()
                    if (m := re.match(
                        r'\s*\d+\s+\.data\s+\S+\s+\S+\s+\S+\s+([0-9a-fA-F]+)',
                        ln)))

    syms = subprocess.check_output(
        ['mips-linux-gnu-objdump', '-t', a.elf], text=True)
    m = re.search(rf'([0-9a-fA-F]+)\s+g\s+O\s+\.data\s+([0-9a-fA-F]+)\s+{SYM}\b',
                  syms)
    if not m:
        sys.exit(f"error: symbol {SYM} not found")
    addr, size = int(m.group(1), 16), int(m.group(2), 16)
    if size != STRIDE * ENTRIES:
        sys.exit(f"error: unexpected size 0x{size:x}, expected 0x{STRIDE*ENTRIES:x}")

    blob = Path(a.elf).read_bytes()
    tbl = blob[data_off + addr: data_off + addr + size]

    print('/* chan_tuning_2069rev_GE16 — partial extraction.')
    print(' *')
    print(' * Provenance: BE wl.o ELF, symbol "%s",' % SYM)
    print(' *             extracted by extract_chan_tuning_2069_GE16.py.')
    print(' *')
    print(' * Layout per entry (94 bytes, 47 u16, BE):')
    print(' *   [ 0]  channel              (u16)')
    print(' *   [ 1]  freq_mhz             (u16)')
    print(' *   [ 2..40]  raw radio/PHY payload — registers TBD')
    print(' *   [41..46]  bw1..bw6 PHY filter coefficients (u16)')
    print(' */')
    print()
    print('static const struct b43_phy_ac_channeltab_e_radio2069')
    print('b43_chantab_r2069[] = {')

    for i in range(ENTRIES):
        e = tbl[i*STRIDE:(i+1)*STRIDE]
        u16 = struct.unpack('>47H', e)
        chan, freq = u16[0], u16[1]
        if a.band == '2g' and not (1 <= chan <= 14):
            continue
        if a.band == '5g' and chan < 36:
            continue
        if chan == 0:
            continue
        raw = u16[2:41]   # 39 u16 of unidentified radio payload
        bw  = u16[41:47]  # 6 u16 of PHY-side BW filter
        print(f'\t{{ /* chan {chan:>3}, {freq} MHz */')
        print(f'\t\t.channel = {chan},')
        print(f'\t\t.freq    = {freq},')
        print(f'\t\t.phy_regs = {{')
        print(f'\t\t\t.bw1 = 0x{bw[0]:04x}, .bw2 = 0x{bw[1]:04x}, '
              f'.bw3 = 0x{bw[2]:04x},')
        print(f'\t\t\t.bw4 = 0x{bw[3]:04x}, .bw5 = 0x{bw[4]:04x}, '
              f'.bw6 = 0x{bw[5]:04x},')
        print(f'\t\t}},')
        print(f'\t\t.radio_raw = {{')
        # 39 u16 in 6-per-line format
        for k in range(0, len(raw), 6):
            row = raw[k:k+6]
            print('\t\t\t' + ', '.join(f'0x{v:04x}' for v in row) + ',')
        print(f'\t\t}},')
        print(f'\t}},')
    print('};')


if __name__ == '__main__':
    main()

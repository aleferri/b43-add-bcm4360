#!/usr/bin/env python3
# extract_r2069_chan_writes_map.py
#
# Reconstruct the (entry_offset → 2069 register) mapping by scanning
# the disassembly of wlc_phy_chanspec_set_acphy() in a non-stripped
# BE wl ELF. For each lhu a2,OFF(BASE) we look forward (and a bit
# backward) for the matching li a1,IMM that sets the radio register
# address before the jalr to write_radio_reg.
#
# Usage: prerequisite is having the disassembly already saved at
# /tmp/chanspec_disasm.txt:
#   mips-linux-gnu-objdump -d wlDSL-3580_EU.o_save #     --start-address=0x50d9c --stop-address=0x53298 #     > /tmp/chanspec_disasm.txt
#   python3 extract_r2069_chan_writes_map.py
#
# Output lists three clusters by base register: s2 (main loop, runs
# for all chips), s7 (small 4360-specific sub-loop), s5 (4360 extra
# pass). For the b43 driver we use cluster1 of s2 (range 50f00-516ff).

import re
from collections import defaultdict

lines_raw = open('/tmp/chanspec_disasm.txt').read().splitlines()

# Parse into list of (addr, mnemonic, args)
parsed = []
for line in lines_raw:
    m = re.match(r'\s+([0-9a-f]+):\s+[0-9a-f]+\s+(\S+)\s*(.*)', line)
    if m:
        parsed.append((int(m.group(1),16), m.group(2).strip(), m.group(3).strip()))

# Build addr → idx map
idx_by_addr = {p[0]: i for i, p in enumerate(parsed)}

def find_a1_value(start_idx, max_forward=10, max_backward=8):
    """Search +/- around start_idx (lhu) for `li a1, IMM` between lhu and jalr."""
    # Look forward: from lhu+1 until we see a jalr (and 1 delay slot)
    saw_jalr = 0
    for i in range(start_idx + 1, min(start_idx + max_forward + 1, len(parsed))):
        addr, mn, args = parsed[i]
        if mn in ('jalr', 'jr', 'j', 'b', 'beq', 'bne', 'beqz', 'bnez'):
            saw_jalr += 1
            if saw_jalr >= 1:
                # one more instr (delay slot) then stop
                if saw_jalr == 1:
                    continue
                break
        # match `li a1, IMM`
        if mn == 'li':
            mm = re.match(r'a1,(-?\d+|0x[0-9a-fA-F]+)$', args)
            if mm:
                try: return int(mm.group(1), 0) & 0xFFFF
                except: pass
        # match `addiu a1, zero, IMM`
        if mn == 'addiu':
            mm = re.match(r'a1,zero,(-?\d+|0x[0-9a-fA-F]+)$', args)
            if mm:
                try: return int(mm.group(1), 0) & 0xFFFF
                except: pass
        if mn == 'ori':
            mm = re.match(r'a1,zero,(-?\d+|0x[0-9a-fA-F]+)$', args)
            if mm:
                try: return int(mm.group(1), 0) & 0xFFFF
                except: pass
    # Look backward
    for i in range(start_idx - 1, max(start_idx - max_backward - 1, -1), -1):
        addr, mn, args = parsed[i]
        if mn in ('jalr', 'jr', 'j'):
            break
        if mn == 'li':
            mm = re.match(r'a1,(-?\d+|0x[0-9a-fA-F]+)$', args)
            if mm:
                try: return int(mm.group(1), 0) & 0xFFFF
                except: pass
        if mn in ('addiu', 'ori'):
            mm = re.match(r'a1,zero,(-?\d+|0x[0-9a-fA-F]+)$', args)
            if mm:
                try: return int(mm.group(1), 0) & 0xFFFF
                except: pass
    return None

results = []
for i, (addr, mn, args) in enumerate(parsed):
    if mn != 'lhu':
        continue
    mm = re.match(r'(\w+),(-?\d+)\((\w+)\)', args)
    if not mm:
        continue
    dst, off, base = mm.group(1), int(mm.group(2)), mm.group(3)
    if base in ('s2','s5','s7') and 4 <= off <= 92 and dst == 'a2':
        ra = find_a1_value(i)
        results.append((addr, base, off, ra))

groups = defaultdict(list)
for addr, base, off, ra in results:
    groups[base].append((addr, off, ra))

for base in ['s2','s7','s5']:
    g = groups.get(base, [])
    if not g: continue
    g.sort()
    print(f"=== base={base}: {len(g)} entry reads ===")
    for addr, off, ra in g:
        s = f"0x{ra:04x}" if ra is not None else "  ???"
        print(f"  @0x{addr:x}  u16[{off//2:>2}] (off={off:>2})  →  reg={s}")
    print()

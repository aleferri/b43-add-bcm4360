#!/usr/bin/env python3
# extract_chanspec_helper_calls.py
#
# Per-call audit of wlc_phy_chanspec_set_acphy(). For every recognised
# call to a phy_reg_*/_radio_reg_* helper, recover the (helper, args)
# tuple by following the symbol-pointer dataflow.
#
# Why this exists alongside extract_phy_writes_v2.py:
#
#   chanspec_set_acphy is exceptional in two ways. First, it loads
#   helper symbols (notably phy_reg_write) once into callee-saved
#   s-registers and reuses them across many `jalr s2` in tight loops;
#   v2's analyse() calls pending.clear() after every jalr, so it loses
#   the s-reg helper mapping and only sees the very first call.
#   Second, the function spills a couple of helper pointers onto the
#   stack ("sw v0,60(sp)") and reloads them later via "lw v0,60(sp);
#   jalr v0" — v2 doesn't track stack-resident helper pointers.
#
# Both extensions here are narrow:
#
#   1. CALLEE_SAVED state survives jalr; only CALLER_SAVED is wiped.
#      Sound under MIPS o32 ABI for a callee-conformant blob.
#
#   2. "sw rX,off(sp)" of a SymPtr-to-helper is recorded, and a later
#      "lw rY,off(sp)" restores rY to that SymPtr.
#
# This is a linear scan, NOT a CFG walk. When a basic block reassigns
# s2 between branches, calls reachable only via the alternate path
# may show up with helper=None (we still record them so the operator
# can audit). For chanspec_set_acphy this missed pass at 0x529ac (the
# 4360-specific phy-reg pass; same six writes as 0x51c4c on the other
# branch) was cross-checked by hand against a literal grep of
# "addiu a1,zero,IMM" in the disasm.
#
# Usage:
#   python3 extract_chanspec_helper_calls.py <wl.o> <output_file>

import re
import subprocess
import sys
from collections import namedtuple, OrderedDict

FUNC_NAME = 'wlc_phy_chanspec_set_acphy'

HELPERS = {
    'phy_reg_read':         ('reg',),
    'phy_reg_write':        ('reg', 'val'),
    'phy_reg_or':           ('reg', 'val'),
    'phy_reg_and':          ('reg', 'mask'),
    'phy_reg_mod':          ('reg', 'mask', 'val'),
    'phy_reg_write_wide':   ('reg', 'val'),
    'phy_reg_read_wide':    ('reg',),
    'read_radio_reg':       ('reg',),
    'write_radio_reg':      ('reg', 'val'),
    'and_radio_reg':        ('reg', 'mask'),
    'or_radio_reg':         ('reg', 'val'),
    'mod_radio_reg':        ('reg', 'mask', 'val'),
}

CALLER_SAVED = {'v0','v1','a0','a1','a2','a3',
                't0','t1','t2','t3','t4','t5','t6','t7','t8','t9'}

SymPtr = namedtuple('SymPtr', ['sym', 'addend'])

RE_INSN  = re.compile(r'^\s*([0-9a-f]+):\s+(\S+)(?:\s+(.*))?$')
RE_RELOC = re.compile(r'^\s+([0-9a-f]+):\s+(R_MIPS_\S+)\s+(\S+)\s*$')


class Insn:
    __slots__ = ('addr', 'mnem', 'operands', 'reloc')
    def __init__(self, addr, mnem, operands):
        self.addr, self.mnem, self.operands = addr, mnem, operands
        self.reloc = None


def get_func_bounds(elf_path, name):
    from elftools.elf.elffile import ELFFile
    with open(elf_path, 'rb') as f:
        for s in ELFFile(f).get_section_by_name('.symtab').iter_symbols():
            if s.name == name:
                return s['st_value'], s['st_value'] + s['st_size']
    raise SystemExit(f'symbol {name} not found in {elf_path}')


def disasm(elf_path, lo, hi):
    return subprocess.check_output(
        ['mips-linux-gnu-objdump', '-dr', '--no-show-raw-insn',
         '-M', 'no-aliases',
         f'--start-address=0x{lo:x}', f'--stop-address=0x{hi:x}',
         elf_path], text=True).splitlines()


def parse(lines):
    insns = []
    last = None
    for line in lines:
        m = RE_RELOC.match(line)
        if m and last is not None and last.reloc is None:
            last.reloc = (m.group(2), m.group(3))
            continue
        m = RE_INSN.match(line)
        if m:
            ins = Insn(int(m.group(1), 16), m.group(2),
                       (m.group(3) or '').strip())
            insns.append(ins)
            last = ins
    return insns


def parse_imm(s):
    s = s.strip()
    try:
        if s.startswith(('0x', '-0x', '+0x')): return int(s, 16)
        return int(s, 10)
    except ValueError:
        return None


def split_ops(s):
    return [x.strip() for x in s.split(',')] if s else []


def step(state, hi_state, stack_helpers, ins):
    """Apply one instruction's effect on register/stack state."""
    ops = split_ops(ins.operands)

    if ins.mnem == 'lui' and len(ops) == 2:
        rd, imm = ops
        v = parse_imm(imm)
        if ins.reloc and ins.reloc[0] == 'R_MIPS_HI16':
            hi_state[rd] = ins.reloc[1]
            state[rd] = SymPtr(ins.reloc[1], 0)
        else:
            state[rd] = ((v & 0xffff) << 16) if v is not None else None
            hi_state.pop(rd, None)
        return

    if ins.mnem in ('addiu', 'daddiu') and len(ops) == 3:
        rd, rs, imm = ops
        v = parse_imm(imm)
        if ins.reloc and ins.reloc[0] == 'R_MIPS_LO16':
            state[rd] = SymPtr(ins.reloc[1], v if v else 0)
            hi_state.pop(rd, None)
            return
        if rs == 'zero':
            state[rd] = (v & 0xffffffff) if v is not None else None
        else:
            sv = state.get(rs)
            if isinstance(sv, SymPtr) and v is not None:
                state[rd] = SymPtr(sv.sym, sv.addend + v)
            elif isinstance(sv, int) and v is not None:
                state[rd] = (sv + v) & 0xffffffff
            else:
                state[rd] = None
        hi_state.pop(rd, None)
        return

    if ins.mnem == 'ori' and len(ops) == 3:
        rd, rs, imm = ops
        v = parse_imm(imm)
        if rs == 'zero':
            state[rd] = (v & 0xffff) if v is not None else None
        else:
            sv = state.get(rs)
            state[rd] = ((sv | (v & 0xffff)) & 0xffffffff
                        if isinstance(sv, int) and v is not None else None)
        hi_state.pop(rd, None)
        return

    if ins.mnem == 'move' and len(ops) == 2:
        state[ops[0]] = state.get(ops[1])
        hi_state.pop(ops[0], None)
        return

    if ins.mnem in ('addu', 'or') and len(ops) == 3:
        rd, rs, rt = ops
        if   rs == 'zero': state[rd] = state.get(rt)
        elif rt == 'zero': state[rd] = state.get(rs)
        else:              state[rd] = None
        hi_state.pop(rd, None)
        return

    if ins.mnem == 'sw' and len(ops) == 2:
        rs = ops[0]
        m = re.match(r'(-?\d+)\(sp\)', ops[1])
        if m:
            off = int(m.group(1))
            sv = state.get(rs)
            if isinstance(sv, SymPtr) and sv.sym in HELPERS:
                stack_helpers[off] = sv.sym
            else:
                stack_helpers.pop(off, None)
        return

    if ins.mnem == 'lw' and len(ops) == 2:
        rd = ops[0]
        m = re.match(r'(-?\d+)\(sp\)', ops[1])
        if m:
            off = int(m.group(1))
            sym = stack_helpers.get(off)
            state[rd] = SymPtr(sym, 0) if sym else None
        else:
            state[rd] = None
        hi_state.pop(rd, None)
        return

    if ins.mnem.startswith(('jal', 'jr', 'b', 'j')):
        return

    if ops:
        rd = ops[0]
        if rd not in ('zero', 'sp', 'fp', 'ra', 'gp', 'at', 'k0', 'k1'):
            state[rd] = None
            hi_state.pop(rd, None)


def invalidate_caller_saved(state, hi_state):
    for r in CALLER_SAVED:
        state.pop(r, None)
        hi_state.pop(r, None)


def fmt_arg(v):
    if v is None: return '?'
    if isinstance(v, SymPtr):
        return f"&{v.sym}+{v.addend:#x}" if v.addend else f"&{v.sym}"
    if isinstance(v, int):
        if v < 0: v &= 0xffffffff
        return f"0x{v:x}"
    return str(v)


def analyse(insns):
    state, hi_state, stack_helpers = {}, {}, {}
    calls = []
    i, n = 0, len(insns)
    while i < n:
        ins = insns[i]
        if ins.mnem in ('jalr', 'jal'):
            if i + 1 < n:
                step(state, hi_state, stack_helpers, insns[i + 1])

            helper = None
            if ins.mnem == 'jalr':
                sv = state.get(ins.operands.strip())
                if isinstance(sv, SymPtr) and sv.sym in HELPERS and sv.addend == 0:
                    helper = sv.sym
            else:
                if ins.reloc and ins.reloc[1] in HELPERS:
                    helper = ins.reloc[1]

            if helper:
                args = OrderedDict()
                regs = ('a1', 'a2', 'a3')
                for slot, name in enumerate(HELPERS[helper]):
                    args[name] = state.get(regs[slot]) if slot < 3 else None
                calls.append((ins.addr, helper, args))

            invalidate_caller_saved(state, hi_state)
            i += 2
            continue

        step(state, hi_state, stack_helpers, ins)
        i += 1
    return calls


def main():
    if len(sys.argv) != 3:
        print(f"usage: {sys.argv[0]} <wl.o> <output_file>", file=sys.stderr)
        sys.exit(1)
    elf, out_path = sys.argv[1], sys.argv[2]

    lo, hi = get_func_bounds(elf, FUNC_NAME)
    insns = parse(disasm(elf, lo, hi))
    calls = analyse(insns)

    by_helper = OrderedDict()
    for _, h, _ in calls:
        by_helper[h] = by_helper.get(h, 0) + 1

    lines = [
        f"# helper-call audit of {FUNC_NAME}",
        f"# function range: 0x{lo:x}..0x{hi:x} ({hi - lo} bytes)",
        f"# total recognised calls: {len(calls)}",
        "# by helper:",
    ]
    for h in sorted(by_helper):
        lines.append(f"#   {h:24s} {by_helper[h]:3d}")
    lines.append("")
    lines.append("# in execution order:")
    for addr, helper, args in calls:
        argstr = ', '.join(f"{k}={fmt_arg(v)}" for k, v in args.items())
        lines.append(f"  0x{addr:08x}  {helper:18s} {argstr}")

    with open(out_path, 'w') as f:
        f.write('\n'.join(lines) + '\n')
    print(f"wrote {out_path}: {len(calls)} calls "
          f"({len(by_helper)} distinct helpers)")


if __name__ == '__main__':
    main()

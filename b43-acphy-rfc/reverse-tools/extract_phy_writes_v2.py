#!/usr/bin/env python3
# extract_phy_writes_v2.py
#
# v2 of the static-MMIO extractor. On top of v1 it can now:
#
#   - Pair MIPS R_MIPS_HI16 + R_MIPS_LO16 relocations to recognise pointer
#     loads like "lui rX, %hi(sym); addiu rX, rX, %lo(sym)" and tag rX as
#     SymPtr(sym, addend).
#   - Track stack writes: "sw rX, off(sp)" for off in {16,20,24,28} so that
#     5th/6th/7th/8th arguments (passed via stack in MIPS o32) become visible
#     at the call site.
#   - Open the ELF file directly (pyelftools) and dump the bytes pointed to
#     by SymPtr arguments, formatted as C arrays sized by len*width/8.
#
# Output: same per-function map as v1, plus a separate dump file
# acphy_tables.c with one C array per recognised wlc_phy_table_write_acphy
# call whose arrptr resolves to a static symbol in .rodata/.data.

import re, sys, os
from collections import namedtuple
from elftools.elf.elffile import ELFFile

# --- helpers we care about ----------------------------------------------------
HELPERS = {
    'phy_reg_read'        : ('reg',),
    'phy_reg_write'       : ('reg', 'val'),
    'phy_reg_and'         : ('reg', 'mask'),
    'phy_reg_or'          : ('reg', 'val'),
    'phy_reg_mod'         : ('reg', 'mask', 'val'),
    'phy_reg_write_wide'  : ('reg', 'val'),
    'phy_reg_read_wide'   : ('reg',),
    'phy_reg_write_array' : ('count', 'arrptr'),  # (pi, count, arr) — arr is the table
    'phy_reg_gen'         : ('reg', 'mask', 'val'),
    'write_phy_channel_reg': ('reg', 'val'),
    'wlc_mod_phyreg_bulk' : ('count', 'arrptr'),
    'read_radio_reg'      : ('reg',),
    'write_radio_reg'     : ('reg', 'val'),
    'and_radio_reg'       : ('reg', 'mask'),
    'or_radio_reg'        : ('reg', 'val'),
    'mod_radio_reg'       : ('reg', 'mask', 'val'),
    'xor_radio_reg'       : ('reg', 'val'),
    # 5 args: (pi, id, len, off, width, ptr). a0=pi, a1=id, a2=len, a3=off,
    # then 16(sp)=width, 20(sp)=ptr.
    'wlc_phy_table_write_acphy': ('id', 'len', 'off', 'width', 'arrptr'),
    'wlc_phy_table_read_acphy' : ('id', 'len', 'off', 'width', 'arrptr'),
}

# Caller-saved regs in MIPS o32 ABI.
CALLER_SAVED = set([
    'v0','v1','a0','a1','a2','a3',
    't0','t1','t2','t3','t4','t5','t6','t7','t8','t9',
])

# Stack offsets for arg slots 5, 6, 7, 8 in o32.
STACK_ARG_OFFSETS = {16: 4, 20: 5, 24: 6, 28: 7}  # off(sp) -> arg index (1-based)

# --- regexes -----------------------------------------------------------------
RE_FUNC   = re.compile(r'^([0-9a-f]+) <([^>]+)>:\s*$')
RE_INSN   = re.compile(r'^\s*([0-9a-f]+):\s+(\S+)(?:\s+(.*))?$')
RE_RELOC  = re.compile(r'^\s+([0-9a-f]+):\s+(R_MIPS_\S+)\s+(\S+)\s*$')

# --- value types -------------------------------------------------------------
SymPtr = namedtuple('SymPtr', ['sym', 'addend'])

# --- per-instruction record --------------------------------------------------
class Insn:
    __slots__ = ('addr','mnem','operands','reloc')
    def __init__(self, addr, mnem, operands):
        self.addr = addr
        self.mnem = mnem
        self.operands = operands
        self.reloc = None

# --- parsing -----------------------------------------------------------------
def parse_disasm(path):
    cur_name = None
    cur_list = []
    last_insn = None
    with open(path, 'r') as f:
        for line in f:
            m = RE_FUNC.match(line)
            if m:
                if cur_name is not None:
                    yield cur_name, cur_list
                cur_name = m.group(2)
                cur_list = []
                last_insn = None
                continue
            m = RE_RELOC.match(line)
            if m and last_insn is not None:
                last_insn.reloc = (m.group(2), m.group(3))
                continue
            m = RE_INSN.match(line)
            if m:
                ins = Insn(int(m.group(1), 16), m.group(2), (m.group(3) or '').strip())
                cur_list.append(ins)
                last_insn = ins
                continue
    if cur_name is not None:
        yield cur_name, cur_list

# --- value tracking ---------------------------------------------------------
def parse_imm(s):
    s = s.strip()
    try:
        if s.startswith(('0x','-0x','+0x')):
            return int(s, 16)
        return int(s, 10)
    except ValueError:
        return None

def split_ops(s):
    return [x.strip() for x in s.split(',')] if s else []

def step(state, hi_state, ins):
    """Update register-state for one instruction. state[reg] can be:
       - None (unknown),
       - int (32-bit immediate value),
       - SymPtr(sym, addend).
       hi_state[reg] tracks pending HI16 relocation symbol on a register
       whose lui hasn't been completed by a matching LO16 yet.
    """
    ops = split_ops(ins.operands)

    if ins.mnem == 'lui' and len(ops) == 2:
        rd, imm = ops
        v = parse_imm(imm)
        if ins.reloc and ins.reloc[0] == 'R_MIPS_HI16':
            # Pending HI half of a symbol pointer load.
            hi_state[rd] = ins.reloc[1]
            state[rd] = SymPtr(ins.reloc[1], 0)  # tentative
        else:
            state[rd] = ((v & 0xffff) << 16) if v is not None else None
            hi_state.pop(rd, None)
        return

    if ins.mnem in ('addiu','daddiu') and len(ops) == 3:
        rd, rs, imm = ops
        v = parse_imm(imm)
        if ins.reloc and ins.reloc[0] == 'R_MIPS_LO16':
            # Completing a HI16+LO16 pair: rd becomes a SymPtr.
            sym = ins.reloc[1]
            addend = v if v is not None else 0
            state[rd] = SymPtr(sym, addend)
            hi_state.pop(rd, None)
            return
        # Plain addiu.
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
            if isinstance(sv, int) and v is not None:
                state[rd] = (sv | (v & 0xffff)) & 0xffffffff
            else:
                state[rd] = None
        hi_state.pop(rd, None)
        return

    if ins.mnem in ('addu','or') and len(ops) == 3:
        rd, rs, rt = ops
        if rs == 'zero':
            state[rd] = state.get(rt)
        elif rt == 'zero':
            state[rd] = state.get(rs)
        else:
            state[rd] = None
        hi_state.pop(rd, None)
        return

    if ins.mnem == 'move' and len(ops) == 2:
        rd, rs = ops
        state[rd] = state.get(rs)
        hi_state.pop(rd, None)
        return

    if ins.mnem.startswith(('jal','jr','b','j')):
        return  # control flow handled elsewhere

    # Store instructions: their first operand is the SOURCE, not the
    # destination. Don't invalidate it.
    if ins.mnem in ('sw','sh','sb','sd','sc','swl','swr','swc1','sdc1'):
        return

    # Anything else: invalidate the destination if it looks like one.
    if ops:
        rd = ops[0]
        if rd not in ('zero','sp','fp','ra','gp','at','k0','k1'):
            state[rd] = None
            hi_state.pop(rd, None)

def maybe_track_stack_store(state, stack_state, ins):
    """If ins is 'sw rX, off(sp)' with off in our stack-arg window, record."""
    if ins.mnem != 'sw':
        return
    ops = split_ops(ins.operands)
    if len(ops) != 2:
        return
    rs = ops[0]
    m = re.match(r'(-?\d+)\(sp\)', ops[1])
    if not m:
        return
    off = int(m.group(1))
    if off in STACK_ARG_OFFSETS:
        stack_state[off] = state.get(rs)

def invalidate_caller_saved(state, hi_state):
    for r in CALLER_SAVED:
        state[r] = None
        hi_state.pop(r, None)

# --- call detection ---------------------------------------------------------
def fmt(v):
    if v is None: return '?'
    if isinstance(v, SymPtr):
        if v.addend == 0:
            return f"&{v.sym}"
        return f"&{v.sym}+{v.addend:#x}"
    if isinstance(v, str): return v
    if v < 0: v &= 0xffffffff
    return f"0x{v:x}"

def analyse(insns):
    state = {}
    hi_state = {}
    stack_state = {}
    pending = {}  # reg -> helper symbol
    calls = []

    i = 0
    n = len(insns)
    while i < n:
        ins = insns[i]

        if ins.mnem in ('jalr','jal'):
            # Apply the delay slot first (architecturally executes before branch lands).
            if i + 1 < n:
                step(state, hi_state, insns[i+1])
                maybe_track_stack_store(state, stack_state, insns[i+1])

            helper = None
            if ins.mnem == 'jalr':
                target_reg = ins.operands.strip()
                helper = pending.get(target_reg)
            else:  # 'jal' direct
                if ins.reloc and ins.reloc[1] in HELPERS:
                    helper = ins.reloc[1]

            if helper and helper in HELPERS:
                arg_names = HELPERS[helper]
                arg_regs = ['a1','a2','a3']
                args = {}
                for slot, name in enumerate(arg_names):
                    if slot < len(arg_regs):
                        args[name] = state.get(arg_regs[slot])
                    else:
                        # Stack arg: slot=3 -> 16(sp), slot=4 -> 20(sp), ...
                        sp_off = 16 + (slot - 3) * 4
                        args[name] = stack_state.get(sp_off)
                calls.append((ins.addr, helper, args))

            invalidate_caller_saved(state, hi_state)
            pending.clear()
            stack_state.clear()
            i += 2
            continue

        # Helper-pointer materialisation.
        if (ins.mnem == 'addiu'
                and ins.reloc
                and ins.reloc[0] == 'R_MIPS_LO16'
                and ins.reloc[1] in HELPERS):
            ops = split_ops(ins.operands)
            if len(ops) == 3:
                pending[ops[0]] = ins.reloc[1]

        step(state, hi_state, ins)
        maybe_track_stack_store(state, stack_state, ins)
        i += 1

    return calls

# --- ELF data extraction -----------------------------------------------------
class ElfData:
    """Minimal ELF reader: maps symbol name -> bytes."""
    def __init__(self, path):
        self.path = path
        self.symbols = {}   # name -> (section_name, offset, size)
        self.sections = {}  # section_name -> bytes
        with open(path, 'rb') as f:
            elf = ELFFile(f)
            for s in elf.iter_sections():
                if s.header['sh_flags'] & 0x2:  # SHF_ALLOC
                    self.sections[s.name] = s.data()
            symtab = elf.get_section_by_name('.symtab')
            if symtab is None:
                return
            for sym in symtab.iter_symbols():
                if sym.entry['st_shndx'] in ('SHN_UNDEF','SHN_ABS','SHN_COMMON'):
                    continue
                shndx = sym.entry['st_shndx']
                if not isinstance(shndx, int):
                    continue
                section = elf.get_section(shndx)
                if section is None:
                    continue
                self.symbols[sym.name] = (section.name,
                                          sym.entry['st_value'],
                                          sym.entry['st_size'])

    def get_bytes(self, sym_name, addend, length):
        if sym_name not in self.symbols:
            return None, "symbol not found"
        sect, off, size = self.symbols[sym_name]
        if sect not in self.sections:
            return None, f"section {sect} not loaded"
        start = off + addend
        end = start + length
        data = self.sections[sect]
        if end > len(data):
            return None, f"out of bounds (sym in {sect}, off={off:#x}+{addend:#x}, want {length} bytes)"
        return data[start:end], None

def fmt_table_c(name, data, width_bits, len_count, hint=""):
    """Format a byte buffer as a C array of u16/u32 (big-endian). 12 per line."""
    if width_bits == 16:
        ctype = 'u16'
        step_bytes = 2
        per_line = 12
    elif width_bits == 32:
        ctype = 'u32'
        step_bytes = 4
        per_line = 6
    elif width_bits == 8:
        ctype = 'u8'
        step_bytes = 1
        per_line = 16
    else:
        ctype = 'u8'
        step_bytes = 1
        per_line = 16

    words = []
    for i in range(0, len(data), step_bytes):
        chunk = data[i:i+step_bytes]
        if len(chunk) < step_bytes:
            break
        v = int.from_bytes(chunk, 'big')
        words.append(v)

    out = []
    if hint:
        out.append(f"/* {hint} */")
    out.append(f"static const {ctype} {name}[{len_count}] = {{")
    for i in range(0, len(words), per_line):
        line = ', '.join(f"0x{w:0{step_bytes*2}x}" for w in words[i:i+per_line])
        out.append(f"\t{line},")
    out.append("};")
    return '\n'.join(out)

# --- main --------------------------------------------------------------------
def main():
    if len(sys.argv) < 4:
        print(f"usage: {sys.argv[0]} <wl.disr> <wl.o> <output_dir> [--filter SUB]", file=sys.stderr)
        sys.exit(1)

    disr = sys.argv[1]
    elf_path = sys.argv[2]
    outdir = sys.argv[3]
    flt = None
    args = sys.argv[4:]
    for k in range(len(args)):
        if args[k] == '--filter' and k + 1 < len(args):
            flt = args[k+1]
        elif args[k].startswith('--filter='):
            flt = args[k].split('=',1)[1]

    os.makedirs(outdir, exist_ok=True)
    elf = ElfData(elf_path)

    map_path = os.path.join(outdir, 'acphy_map.txt')
    tables_path = os.path.join(outdir, 'acphy_tables.c')
    diag_path = os.path.join(outdir, 'acphy_dump_diagnostics.txt')

    n_funcs = n_calls = n_funcs_with_calls = 0
    n_tables_dumped = 0
    n_tables_skipped = 0

    seen_tables = {}  # (sym, addend, length, width) -> (caller, args)

    with open(map_path, 'w') as fmap, \
         open(tables_path, 'w') as ftab, \
         open(diag_path, 'w') as fdiag:

        ftab.write("/* Autogenerated from extract_phy_writes_v2.py.\n")
        ftab.write(" * Source: " + os.path.basename(elf_path) + "\n")
        ftab.write(" * Each table is named after the .rodata symbol it was\n")
        ftab.write(" * extracted from, prefixed with the calling function for\n")
        ftab.write(" * context. Width assumption: 16 bits per entry unless the\n")
        ftab.write(" * extractor saw a different width on stack[16(sp)].\n")
        ftab.write(" */\n\n")

        for name, insns in parse_disasm(disr):
            if flt and flt not in name:
                continue
            n_funcs += 1
            calls = analyse(insns)
            if not calls:
                continue
            n_funcs_with_calls += 1
            n_calls += len(calls)

            fmap.write(f"{name}:\n")
            for addr, helper, ar in calls:
                argstr = ', '.join(f"{k}={fmt(v)}" for k, v in ar.items())
                fmap.write(f"  {addr:08x}  {helper}({argstr})\n")

                # Table-dump opportunity?
                if helper in ('wlc_phy_table_write_acphy','wlc_phy_table_read_acphy'):
                    arrptr = ar.get('arrptr')
                    width = ar.get('width')
                    length = ar.get('len')
                    if not isinstance(arrptr, SymPtr) or not isinstance(length, int):
                        n_tables_skipped += 1
                        fdiag.write(f"{name} @ {addr:08x}: skip "
                                    f"(arrptr={fmt(arrptr)}, len={fmt(length)}, "
                                    f"width={fmt(width)})\n")
                        continue
                    w = width if isinstance(width, int) and width in (8,16,32) else 16
                    nbytes = length * (w // 8)
                    data, err = elf.get_bytes(arrptr.sym, arrptr.addend, nbytes)
                    key = (arrptr.sym, arrptr.addend, length, w)
                    if data is None:
                        n_tables_skipped += 1
                        fdiag.write(f"{name} @ {addr:08x}: read failed for "
                                    f"&{arrptr.sym}+{arrptr.addend:#x} "
                                    f"({nbytes} bytes): {err}\n")
                        continue
                    if key in seen_tables:
                        continue  # already emitted
                    seen_tables[key] = name
                    n_tables_dumped += 1

                    safe = re.sub(r'[^A-Za-z0-9_]', '_', arrptr.sym)
                    if arrptr.addend:
                        safe += f"_at_{arrptr.addend:x}"
                    hint = (f"called from {name}, "
                            f"id={fmt(ar.get('id'))}, "
                            f"len={length:#x}, "
                            f"off={fmt(ar.get('off'))}, "
                            f"width={w} ({helper})")
                    ftab.write(fmt_table_c(safe, data, w, length, hint))
                    ftab.write("\n\n")
            fmap.write("\n")

    print(f"# {n_funcs} functions scanned, {n_funcs_with_calls} contain calls, "
          f"{n_calls} calls total.")
    print(f"# Tables dumped: {n_tables_dumped}, skipped: {n_tables_skipped}.")
    print(f"# Files: {map_path}, {tables_path}, {diag_path}")

if __name__ == '__main__':
    main()

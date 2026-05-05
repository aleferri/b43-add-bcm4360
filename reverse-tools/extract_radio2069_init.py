#!/usr/bin/env python3
# extract_radio2069_init.py
#
# Estrae wlc_phy_radio2069_pwron_seq dal blob MIPS BE wlDSL-3580_EU.o_save
# e genera il corpo di b43_radio_2069_init() per
# kernel-patch/existing_files/phy_ac.c.additions.
#
# La funzione ha tre sezioni:
#
#   1. PROLOGO — write PHY statiche + RMW su 0x720/0x728 (prima dell'osl_delay)
#   2. CORPO  — blocchi mod_radio_reg con chip-dispatch BCM4360/BCM4352/0x43b3/generic
#               (dopo il secondo osl_delay, dove s3 = osl_delay non più phy_reg_read)
#   3. EPILOGO — restore 0x728, secondo osl_delay, tail write
#
# Ogni operazione tracciata:
#   phy_reg_write(pi, REG, VAL)  → b43_phy_write(dev, REG, VAL)
#   phy_reg_read(pi, REG)         → usata solo per RMW (non emessa direttamente)
#   mod_radio_reg(pi, REG, MASK, VAL) → b43_radio_maskset(dev, REG, ~MASK, VAL)
#   osl_delay(US)                 → udelay(US)
#
# Uso:
#   mips-linux-gnu-objdump -dr --no-show-raw-insn -M no-aliases \
#       wlDSL-3580_EU.o_save > /tmp/wl_full.disasm
#   python3 extract_radio2069_init.py /tmp/wl_full.disasm

import argparse, os, re, sys

# Chip ID constants (vedi README.md).
# 0x43b3 è il target reale del DSL-3580L; 4360 e 4352 restano per regression
# e per leggere i dispatch espliciti che il binario fa contro quelle costanti.
CHIP_43B3 = 0x43b3   # 17331 — DSL-3580L (target attuale)
CHIP_4352 = 0x4352   # 17234
CHIP_4360 = 0x4360   # 17248 — non più target, mantenuto per regression
CHIP_4352_FAMILY = (0x4352, 0x4348, 0x4333, 0x43A2, 0x43B0, 0x43B3)

# ---------------------------------------------------------------------------
# Parsing (identico a extract_init_acphy.py)
# ---------------------------------------------------------------------------

def parse_func(path, func_name):
    lines = open(path).readlines()
    start = end = None
    for i, l in enumerate(lines):
        if f'<{func_name}>:' in l:
            start = i
        if start and i > start + 5 and re.match(r'^[0-9a-f]+ <', l):
            end = i
            break
    if start is None:
        raise ValueError(f'{func_name} not found')
    if end is None:
        end = len(lines)
    result = []
    last = None
    for l in lines[start:end]:
        m = re.match(r'\s+[0-9a-f]+:\s+(R_MIPS_\S+)\s+(\S+)', l)
        if m and last is not None:
            if last[3] is None:
                last[3] = (m.group(1), m.group(2))
            continue
        m = re.match(r'\s*([0-9a-f]+):\s+(\S+)(?:\s+(.*))?$', l)
        if m:
            ins = [int(m.group(1), 16), m.group(2),
                   (m.group(3) or '').strip(), None]
            result.append(ins)
            last = ins
    return result

def split_ops(s):
    return [x.strip() for x in s.split(',')] if s else []

def branch_target(s):
    s = s.strip()
    if '<' in s:
        s = s[:s.index('<')].strip()
    try:
        return int(s, 16)
    except ValueError:
        return None

def imm(s):
    s = s.strip()
    if '<' in s:
        s = s[:s.index('<')].strip()
    if not s:
        return None
    try:
        if s.startswith(('0x', '-0x', '+0x')):
            return int(s, 16)
        if re.fullmatch(r'[0-9a-fA-F]+', s):
            if re.search(r'[a-fA-F]', s):
                return int(s, 16)
            v_dec = int(s, 10)
            v_hex = int(s, 16)
            return v_hex if v_dec > 65535 else v_dec
        return int(s, 10)
    except ValueError:
        return None

# ---------------------------------------------------------------------------
# Tracciamento registri
# ---------------------------------------------------------------------------

def track_reg(state, ins):
    addr, mnem, ops_str, reloc = ins
    ops = split_ops(ops_str)

    if mnem == 'lui' and len(ops) == 2:
        rd, imm_s = ops
        v = imm(imm_s)
        if reloc and 'LO16' not in reloc[0]:
            state[rd] = ('sym_hi', reloc[1])
        else:
            state[rd] = ((v & 0xffff) << 16) if v is not None else None

    elif mnem in ('addiu', 'daddiu') and len(ops) == 3:
        rd, rs, imm_s = ops
        v = imm(imm_s)
        if reloc and 'LO16' in reloc[0]:
            state[rd] = ('sym', reloc[1])
        elif rs == 'zero':
            state[rd] = (v & 0xffffffff) if v is not None else None
        else:
            sv = state.get(rs)
            if isinstance(sv, int) and v is not None:
                state[rd] = (sv + v) & 0xffffffff
            elif isinstance(sv, tuple) and sv[0] == 'sym_hi' and v is not None:
                state[rd] = ('sym', sv[1])
            else:
                state[rd] = None

    elif mnem == 'ori' and len(ops) == 3:
        rd, rs, imm_s = ops
        v = imm(imm_s)
        if rs == 'zero':
            state[rd] = (v & 0xffff) if v is not None else None
        else:
            sv = state.get(rs)
            if isinstance(sv, int) and v is not None:
                state[rd] = (sv | (v & 0xffff)) & 0xffffffff
            else:
                state[rd] = None

    elif mnem == 'andi' and len(ops) == 3:
        rd, rs, imm_s = ops
        v = imm(imm_s)
        sv = state.get(rs)
        if isinstance(sv, int) and v is not None:
            state[rd] = sv & (v & 0xffff)
        else:
            state[rd] = None

    elif mnem == 'xori' and len(ops) == 3:
        # parte 1/3 dell'idiom "branch se rs == IMM" che il
        # compilatore Broadcom emette sui dispatch per chip-id. Salviamo la
        # coppia (rs_originale, IMM) come stato compound: il sltiu successivo
        # la promuove a 'eq_test', che la beq finale legge.
        rd, rs, imm_s = ops
        v = imm(imm_s)
        sv = state.get(rs)
        if isinstance(sv, int) and v is not None:
            # Caso valutabile: rs è già int. Manteniamo anche il valore xor-ato
            # cosi' un sltiu(.,1) più avanti darà il bool corretto via il path int.
            state[rd] = (sv ^ (v & 0xffff)) & 0xffffffff
            # In più, registriamo la "memory" dell'origine per i casi in cui
            # rs è iniettato come chip_choice e il path-tracer voglia decidere
            # senza passare dalla codifica numerica.
            # Non strettamente necessario qui (il valore int basta), ma ci tiene
            # uniformi col caso symbolic sotto.
        elif v is not None:
            # rs è simbolico/None: ricordiamo l'idiom per la sltiu successiva.
            state[rd] = ('xori_eq', rs, v & 0xffff)
        else:
            state[rd] = None

    elif mnem == 'sltiu' and len(ops) == 3:
        # parte 2/3. `sltiu rd, rs, 1` ⟺ rd = (rs == 0).
        # Se rs è il risultato di un xori precedente, promuoviamo a 'eq_test'
        # con il riferimento all'rs originario e all'IMM testato.
        rd, rs, imm_s = ops
        v = imm(imm_s)
        sv = state.get(rs)
        if v == 1 and isinstance(sv, tuple) and sv[0] == 'xori_eq':
            _, orig_rs, target_imm = sv
            state[rd] = ('eq_test', orig_rs, target_imm)
        elif v == 1 and isinstance(sv, int):
            # rs noto: il bool è risolvibile staticamente.
            state[rd] = 1 if (sv & 0xffffffff) == 0 else 0
        elif v is not None and isinstance(sv, int):
            state[rd] = 1 if (sv & 0xffffffff) < (v & 0xffffffff) else 0
        else:
            state[rd] = None

    elif mnem in ('addu', 'or') and len(ops) == 3:
        rd, rs, rt = ops
        if rs == 'zero':
            state[rd] = state.get(rt)
        elif rt == 'zero':
            state[rd] = state.get(rs)
        else:
            state[rd] = None

    elif mnem == 'move' and len(ops) == 2:
        rd, rs = ops
        state[rd] = state.get(rs)

    elif mnem in ('sw', 'sh', 'sb', 'lh', 'lb', 'lhu', 'lbu', 'lw'):
        # lw nel delay slot: non possiamo iniettare chip_choice qui (track_reg
        # non conosce chip_choice). Il chip-injection avviene nel loop principale
        # di trace_path. Se dst è un registro callee-saved non lo tocchiamo,
        # altrimenti lo azzeriamo (il loop lo sovrascriverà prima del prossimo uso).
        if mnem == 'lw' and ops:
            dst = ops[0]
            if dst not in ('zero', 'sp', 'fp', 'ra', 'gp', 'at', 'k0', 'k1'):
                state[dst] = None

    elif ops:
        rd = ops[0]
        if rd not in ('zero', 'sp', 'fp', 'ra', 'gp', 'at', 'k0', 'k1'):
            state[rd] = None

# ---------------------------------------------------------------------------
# Trace con chip-choice
# ---------------------------------------------------------------------------

def trace_path(insns, chip_choice, phy_write_reg, mod_radio_reg_sym,
               osl_delay_sym):
    """
    Esegue tracciamento lineare con branch decision forzata per chip_choice.
    Ritorna lista di Operation(type, addr, args...).
    """
    # Sentinella per i load da acphychipid: track_reg la inietta, la branch
    # decision la confronta con CHIP_4352/CHIP_4360.
    _CHIP_INJECT = chip_choice  # None per path generic
    addr_to_idx = {ins[0]: i for i, ins in enumerate(insns)}
    state = {'zero': 0}  # MIPS $zero è sempre 0
    ops_out = []
    visited = set()
    pc = 0

    def sym_matches(reg, sym_name):
        v = state.get(reg)
        if isinstance(v, tuple) and 'sym' in v[0]:
            return sym_name in v[1]
        return False

    def is_chip_id_ptr(reg):
        """True se il registro contiene l'indirizzo di acphychipid."""
        v = state.get(reg)
        return isinstance(v, tuple) and 'sym' in v[0] and 'acphychipid' in v[1]

    def invalidate_caller_saved():
        for r in ('v0','v1','a0','a1','a2','a3',
                  't0','t1','t2','t3','t4','t5','t6','t7','t8','t9'):
            state[r] = None

    steps = 0
    while pc < len(insns) and steps < 30000:
        steps += 1
        if pc in visited:
            break
        visited.add(pc)

        addr, mnem, ops_str, reloc = insns[pc]
        ops = split_ops(ops_str)

        # Special: lw vX, 0(base) where base = acphychipid ptr → inject chip_choice
        if mnem == 'lw' and len(ops) == 2:
            dst = ops[0]
            m_base = re.match(r'0\((\w+)\)', ops[1])
            if m_base and is_chip_id_ptr(m_base.group(1)):
                state[dst] = chip_choice  # chip ID injection
            else:
                state[dst] = None
            pc += 1
            continue

        addr, mnem, ops_str, reloc = insns[pc]
        ops = split_ops(ops_str)

        if mnem in ('beq', 'bne') and len(ops) == 3:
            rs, rt, tgt_s = ops
            tgt = branch_target(tgt_s)
            rs_val = state.get(rs)
            rt_val = state.get(rt)
            taken = None

            if chip_choice is not None:
                # Caso classico: rs/rt = (chip_choice, IMM) come due int.
                if isinstance(rs_val, int) and isinstance(rt_val, int):
                    taken = (rs_val == rt_val) if mnem == 'beq' else (rs_val != rt_val)
                elif isinstance(rs_val, int) or isinstance(rt_val, int):
                    const = rs_val if isinstance(rs_val, int) else rt_val
                    if const in (CHIP_4360, CHIP_4352, CHIP_43B3):
                        is_eq = (chip_choice == const)
                    else:
                        is_eq = None
                    if is_eq is not None:
                        taken = is_eq if mnem == 'beq' else not is_eq
                # idiom xori-sltiu-beq.
                # Dopo `xori v0, $rs, IMM; sltiu v0, v0, 1`, lo stato di v0
                # è ('eq_test', rs_orig, IMM): vale 1 sse rs_orig == IMM.
                # `beq v0, zero, target`  → branch (taken) se v0 == 0
                #                          → branch se rs_orig != IMM
                # `bne v0, zero, target`  → branch se rs_orig == IMM
                else:
                    eq_state = None
                    other_val = None
                    if isinstance(rs_val, tuple) and rs_val[0] == 'eq_test':
                        eq_state = rs_val
                        other_val = rt_val
                    elif isinstance(rt_val, tuple) and rt_val[0] == 'eq_test':
                        eq_state = rt_val
                        other_val = rs_val
                    if eq_state is not None and other_val == 0:
                        _, orig_rs, target_imm = eq_state
                        # Risolviamo il valore di orig_rs nello stato corrente:
                        # se è il chip_choice iniettato (acphychipid) sarà già int.
                        orig_val = state.get(orig_rs)
                        if isinstance(orig_val, int):
                            orig_eq_imm = (orig_val == target_imm)
                            if mnem == 'beq':
                                # branch se v0 == 0, cioè se orig != imm
                                taken = not orig_eq_imm
                            else:
                                taken = orig_eq_imm

            # delay slot always executes
            if pc + 1 < len(insns):
                track_reg(state, insns[pc + 1])

            if taken is True and tgt is not None:
                tidx = addr_to_idx.get(tgt)
                if tidx is not None and tidx not in visited:
                    pc = tidx
                    continue
            elif taken is False:
                pc += 2
                continue
            else:
                pc += 2
                continue

        elif mnem == 'j' and len(ops) == 1:
            tgt = branch_target(ops[0])
            if pc + 1 < len(insns):
                track_reg(state, insns[pc + 1])
            if tgt is not None:
                tidx = addr_to_idx.get(tgt)
                if tidx is not None and tidx not in visited:
                    pc = tidx
                    continue
            # Target already visited or not found: stop this path
            break

        elif mnem == 'jr' and len(ops) == 1:
            if ops[0] == 'ra':
                break
            # tail call: t9=s1=phy_reg_write (epilogo)
            if pc + 1 < len(insns):
                track_reg(state, insns[pc + 1])
            reg = ops[0]
            if reg == phy_write_reg or sym_matches(reg, 'phy_reg_write'):
                a1 = state.get('a1')
                a2 = state.get('a2')
                if isinstance(a1, int) and isinstance(a2, int):
                    ops_out.append(('phy_write', addr, a1, a2))
            break

        elif mnem == 'jalr' and len(ops) >= 1:
            reg = ops[0]
            # delay slot
            if pc + 1 < len(insns):
                track_reg(state, insns[pc + 1])

            a0 = state.get('a0')
            a1 = state.get('a1')
            a2 = state.get('a2')
            a3 = state.get('a3')

            if reg == phy_write_reg or sym_matches(reg, 'phy_reg_write'):
                if isinstance(a1, int) and isinstance(a2, int):
                    ops_out.append(('phy_write', addr, a1, a2))

            elif sym_matches(reg, 'phy_reg_read'):
                pass  # RMW handled implicitly (v0 becomes None after invalidate)

            elif sym_matches(reg, 'mod_radio_reg') or sym_matches(reg, mod_radio_reg_sym):
                if isinstance(a1, int) and isinstance(a2, int) and isinstance(a3, int):
                    ops_out.append(('radio_maskset', addr, a1, a2, a3))
                elif isinstance(a1, int):
                    ops_out.append(('radio_maskset', addr, a1, a2, a3))

            elif sym_matches(reg, 'osl_delay') or sym_matches(reg, osl_delay_sym):
                delay_us = state.get('a0')
                if isinstance(delay_us, int):
                    ops_out.append(('udelay', addr, delay_us))

            elif sym_matches(reg, 'wlc_phy_init_radio_prefregs_allbands'):
                ops_out.append(('prefregs_allbands', addr))

            invalidate_caller_saved()
            pc += 2
            continue

        else:
            track_reg(state, insns[pc])

        pc += 1

    return ops_out

# ---------------------------------------------------------------------------
# Identificazione registri funzione
# ---------------------------------------------------------------------------

def find_func_regs(insns):
    """
    Trova i registri salvati per phy_reg_write, phy_reg_read,
    mod_radio_reg, osl_delay cercando i load HI16+LO16 nella funzione.
    """
    regs = {}
    for addr, mnem, ops_str, reloc in insns:
        if reloc and 'LO16' in reloc[0]:
            sym = reloc[1]
            ops = split_ops(ops_str)
            if ops:
                rd = ops[0]
                if sym in ('phy_reg_write', 'phy_reg_read', 'mod_radio_reg',
                           'osl_delay', 'acphychipid',
                           'wlc_phy_init_radio_prefregs_allbands'):
                    regs[sym] = rd
    return regs

# ---------------------------------------------------------------------------
# Output C
# ---------------------------------------------------------------------------

def fmt_op(op):
    t = op[0]
    addr = op[1]
    if t == 'phy_write':
        _, addr, reg, val = op
        return (f'\tb43_phy_write(dev, 0x{reg:04x}, 0x{val:04x});'
                f'  /* @{addr:#010x} */')
    elif t == 'radio_maskset':
        _, addr, reg, mask, val = op
        if mask is None or val is None:
            return f'\t/* @{addr:#010x}: radio_maskset reg=0x{reg:04x} mask=? val=? */'
        if mask == val:
            return (f'\tb43_radio_set(dev, 0x{reg:04x}, 0x{mask:04x});'
                    f'  /* @{addr:#010x} */')
        return (f'\tb43_radio_maskset(dev, 0x{reg:04x}, ~0x{mask:04x}, 0x{val:04x});'
                f'  /* @{addr:#010x} */')
    elif t == 'udelay':
        _, addr, us = op
        return f'\tudelay({us});  /* @{addr:#010x} */'
    elif t == 'prefregs_allbands':
        return f'\t/* @{op[1]:#010x}: wlc_phy_init_radio_prefregs_allbands: phy_rev 3/4 */'
    return f'\t/* unknown op: {op} */'


def op_tsv_row(op):
    """Riga TSV machine-readable di una op. Usata dal diff report (§0.4).

    Formato: addr<TAB>type<TAB>field1<TAB>field2<TAB>field3
    Campi mancanti = stringa vuota. Nessun escape: i campi sono numerici o
    label note. Hex con 0 padding per ordinamento testuale stabile.
    """
    t = op[0]
    addr = op[1]
    addr_s = f'0x{addr:08x}'
    if t == 'phy_write':
        _, _, reg, val = op
        return f'{addr_s}\tphy_write\t0x{reg:04x}\t0x{val:04x}\t'
    if t == 'radio_maskset':
        _, _, reg, mask, val = op
        m = '?' if mask is None else f'0x{mask:04x}'
        v = '?' if val  is None else f'0x{val:04x}'
        return f'{addr_s}\tradio_maskset\t0x{reg:04x}\t{m}\t{v}'
    if t == 'udelay':
        _, _, us = op
        return f'{addr_s}\tudelay\t{us}\t\t'
    if t == 'prefregs_allbands':
        return f'{addr_s}\tprefregs_allbands\t\t\t'
    return f'{addr_s}\tunknown\t{op!r}\t\t'


def emit_c_for_chip(ops, chip_label, out):
    """Emette il body di b43_radio_2069_init() per UN chip.

    A differenza di emit_c() classico, non fa side-by-side: produce la
    sequenza pulita per il chip richiesto. Le 4 RMW chip-id-indipendenti
    (vedi commento header) sono emesse sempre nelle stesse posizioni.
    """
    p = lambda *a: print(*a, file=out)
    p('/* ================================================================')
    p(' * extract_radio2069_init.py --chip {} — output per-chip'.format(chip_label))
    p(' * Sorgente: wlDSL-3580_EU.o_save (MIPS BE, DSL-3580L, chip 0x43b3)')
    p(' * Funzione: wlc_phy_radio2069_pwron_seq')
    p(f' * Op count per il path "{chip_label}": {len(ops)}')
    p(' *')
    p(' * RMW non estraibili staticamente (chip-id-indipendenti):')
    p(' *   1. @451f4: saved_728 & 0x7e7f -> b43_phy_mask(dev,0x0728,0x7e7f)')
    p(' *   2. @45214: old_0x720 | 0x180  -> b43_phy_set(dev,0x0720,0x0180)')
    p(' *   3. @456c8: saved_728 | 0x180  -> b43_phy_set(dev,0x0728,0x0180)')
    p(' *   4. epilog: saved_728 & ~0x100 -> b43_phy_mask(dev,0x0728,~0x0100)')
    p(' * ================================================================ */')
    p('')
    p(f'static void b43_radio_2069_init_{chip_label}(struct b43_wldev *dev)')
    p('{')

    prev_section = None
    inserted_rmw = set()

    for op in ops:
        addr = op[1]

        if 0x451f4 not in inserted_rmw and addr >= 0x45228:
            p('')
            p('\t/* RMW 1+2 (chip-id-indipendenti, da prologue) */')
            p('\tb43_phy_mask(dev, 0x0728, 0x7e7f);  /* @0x000451f4 */')
            p('\tb43_phy_set(dev,  0x0720, 0x0180);  /* @0x00045214 */')
            inserted_rmw.add(0x451f4)

        if 0x456c8 not in inserted_rmw and addr >= 0x456d0:
            p('\t/* RMW 3 */')
            p('\tb43_phy_set(dev, 0x0728, 0x0180);  /* @0x000456c8 */')
            inserted_rmw.add(0x456c8)

        if   addr < 0x45234: section = 'prologue'
        elif addr < 0x45250: section = 'setup'
        else:                section = 'body'

        if section != prev_section:
            labels = {
                'prologue': '/* --- Prologo: PHY register writes --- */',
                'setup':    '/* --- Setup + udelay(100) --- */',
                'body':     '/* --- Corpo: radio 2069 init + epilogo --- */',
            }
            p('')
            p(f'\t{labels[section]}')
            prev_section = section

        p(fmt_op(op))

    p('')
    if 0x456c8 not in inserted_rmw:
        # Path con meno op (es. 43b3) può non raggiungere la soglia di
        # inserimento intra-loop. La RMW 3 è chip-id-indipendente per
        # spec, quindi la emettiamo qui prima del tail. Se il binario
        # 43b3 NON la fa davvero, va rimossa manualmente in fase di
        # audit dei call site.
        p('\t/* RMW 3 (fallback: path non ha raggiunto la soglia intra-loop) */')
        p('\tb43_phy_set(dev, 0x0728, 0x0180);  /* @0x000456c8 */')
    p('\t/* RMW 4: epilogo tail — clear bit 0x100 di PHY 0x728 */')
    p('\tb43_phy_mask(dev, 0x0728, ~0x0100);')
    p('}')


def emit_c(generic_ops, ops_4352, ops_4360):
    print("/* ================================================================")
    print(" * extract_radio2069_init.py — output automatico")
    print(" * Sorgente: wlDSL-3580_EU.o_save (MIPS BE, DSL-3580L, chip 0x43b3,")
    print(" *           BCM4352-family, 2x2 — vedi README.md §re-target)")
    print(" * Funzione: wlc_phy_radio2069_pwron_seq")
    print(f" * Op: generic={len(generic_ops)} BCM4352={len(ops_4352)} BCM4360={len(ops_4360)}")
    print(" *")
    print(" * RMW non estraibili staticamente (inserite manualmente):")
    print(" *   1. @451f4: saved_728 & 0x7e7f -> b43_phy_mask(dev,0x0728,0x7e7f)")
    print(" *   2. @45214: old_0x720 | 0x180  -> b43_phy_set(dev,0x0720,0x0180)")
    print(" *   3. @456c8: saved_728 | 0x180  -> b43_phy_set(dev,0x0728,0x0180)")
    print(" *   4. epilog: saved_728 & ~0x100 -> b43_phy_mask(dev,0x0728,~0x0100)")
    print(" * ================================================================ */")
    print()
    print("static void b43_radio_2069_init(struct b43_wldev *dev)")
    print("{")

    primary = ops_4352 if ops_4352 else (ops_4360 if ops_4360 else generic_ops)
    gen_by_addr = {op[1]: op for op in generic_ops}
    r60_by_addr = {op[1]: op for op in ops_4360}

    prev_section = None
    inserted_rmw = set()

    for op in primary:
        addr = op[1]

        if 0x451f4 not in inserted_rmw and addr == 0x45228:
            print()
            print("\t/* RMW 1+2: dalla sequenza di prologue wlc_phy_radio2069_pwron_seq.")
            print("\t * Il blob salva PHY 0x728, lo azzera parzialmente e setta 0x720 | 0x180.")
            print("\t * Non serve leggere il valore: usiamo mask/set diretti. */")
            print("\tb43_phy_mask(dev, 0x0728, 0x7e7f);  /* @0x000451f4 */")
            print("\tb43_phy_set(dev,  0x0720, 0x0180);  /* @0x00045214 */")
            inserted_rmw.add(0x451f4)

        if 0x456c8 not in inserted_rmw and addr == 0x456d0:
            print("\t/* RMW 3: restore di PHY 0x728 con bit 0x180 settato */")
            print("\tb43_phy_set(dev, 0x0728, 0x0180);  /* @0x000456c8 */")
            inserted_rmw.add(0x456c8)

        if addr < 0x45234:
            section = 'prologue'
        elif addr < 0x45250:
            section = 'setup'
        else:
            section = 'body'

        if section != prev_section:
            labels = {
                'prologue':  '/* --- Prologo: PHY register writes --- */',
                'setup':     '/* --- Setup + udelay(100) --- */',
                'body':      '/* --- Corpo: radio 2069 init + epilogo --- */',
            }
            print()
            print(f'\t{labels[section]}')
            prev_section = section

        line = fmt_op(op)
        op_60 = r60_by_addr.get(addr)
        note = ''
        if op_60 and op[2:] != op_60[2:]:
            if op[0] == 'radio_maskset' and len(op_60) >= 5:
                note = f'  /* BCM4360: reg=0x{op_60[2]:04x} */'
            elif op[0] == 'phy_write' and len(op_60) >= 4:
                note = f'  /* BCM4360: reg=0x{op_60[2]:04x} val=0x{op_60[3]:04x} */'
        print(line + note)

    print()
    print("\t/* RMW 4: epilogo tail — clear bit 0x100 di PHY 0x728 */")
    print("\tb43_phy_mask(dev, 0x0728, ~0x0100);")
    print("}")
    print()

    extra_gen = [op for op in generic_ops if op[1] not in {o[1] for o in ops_4352}]
    if extra_gen:
        print("/* Op nel path generico non presenti in BCM4352:")
        for op in extra_gen:
            print(f" * {fmt_op(op).strip()}")
        print(" */")


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

# Mappatura chip-label CLI -> chip_choice da passare a trace_path().
# 'default' = nessun ramo chip-aware preso (== None internamente).
_CHIP_CHOICE = {
    'default': None,
    '4352':    CHIP_4352,
    '4360':    CHIP_4360,
    '43b3':    CHIP_43B3,
}

def main():
    ap = argparse.ArgumentParser(
        description='Estrae wlc_phy_radio2069_pwron_seq dal blob MIPS BE.')
    ap.add_argument('disr', help='disasm objdump (wl.disr)')
    ap.add_argument('--chip', choices=sorted(_CHIP_CHOICE),
                    help='emetti solo il path del chip indicato. '
                         'Se omesso: comportamento legacy (emit_c side-by-side).')
    ap.add_argument('--out-dir', metavar='DIR',
                    help='scrivi <tool>_output.c e <tool>_ops.tsv in DIR. '
                         'Richiede --chip. Senza --out-dir: stdout.')
    args = ap.parse_args()

    if args.out_dir and not args.chip:
        ap.error('--out-dir richiede --chip')

    insns = parse_func(args.disr, 'wlc_phy_radio2069_pwron_seq')
    print(f'/* wlc_phy_radio2069_pwron_seq: {len(insns)} istruzioni */', file=sys.stderr)

    regs = find_func_regs(insns)
    print(f'/* registri trovati: {regs} */', file=sys.stderr)

    phy_wr  = regs.get('phy_reg_write', 's1')
    mod_rr  = regs.get('mod_radio_reg', 's5')
    osl_d   = regs.get('osl_delay', 's3')

    # Modalità per-chip: un solo path proiettato.
    if args.chip:
        chip_choice = _CHIP_CHOICE[args.chip]
        ops = trace_path(insns, chip_choice, phy_wr, mod_rr, osl_d)
        print(f'/* ops[{args.chip}]: {len(ops)} */', file=sys.stderr)

        if args.out_dir:
            os.makedirs(args.out_dir, exist_ok=True)
            base = 'radio2069_init_extracted'
            with open(os.path.join(args.out_dir, base + '.c'), 'w') as f:
                emit_c_for_chip(ops, args.chip, f)
            with open(os.path.join(args.out_dir, base + '_ops.tsv'), 'w') as f:
                f.write('addr\ttype\tfield1\tfield2\tfield3\n')
                for op in ops:
                    f.write(op_tsv_row(op) + '\n')
        else:
            emit_c_for_chip(ops, args.chip, sys.stdout)
        return

    # Modalità legacy (default): comportamento invariato.
    generic_ops = trace_path(insns, None,       phy_wr, mod_rr, osl_d)
    ops_4352    = trace_path(insns, CHIP_4352,  phy_wr, mod_rr, osl_d)
    ops_4360    = trace_path(insns, CHIP_4360,  phy_wr, mod_rr, osl_d)
    ops_43b3    = trace_path(insns, CHIP_43B3,  phy_wr, mod_rr, osl_d)

    print(f'/* ops: generic={len(generic_ops)} 4352={len(ops_4352)} '
          f'4360={len(ops_4360)} 43b3={len(ops_43b3)} */', file=sys.stderr)
    if {tuple(o[1:]) for o in ops_43b3} != {tuple(o[1:]) for o in ops_4352}:
        print('/* NOTE: path 43b3 diverge da 4352 — vedi diff per-chip in reverse-output/by-chip/ */',
              file=sys.stderr)
    if {tuple(o[1:]) for o in ops_43b3} != {tuple(o[1:]) for o in ops_4360}:
        print('/* NOTE: path 43b3 diverge da 4360 — vedi diff per-chip in reverse-output/by-chip/ */',
              file=sys.stderr)
    print(file=sys.stderr)

    emit_c(generic_ops, ops_4352, ops_4360)

if __name__ == '__main__':
    main()

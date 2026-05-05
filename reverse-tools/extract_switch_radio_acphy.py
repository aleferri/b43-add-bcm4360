#!/usr/bin/env python3
# extract_switch_radio_acphy.py
#
# Estrae wlc_phy_switch_radio_acphy @0x4582c dal blob MIPS BE
# wlDSL-3580_EU.o_save e produce due sequenze di operazioni:
# il path "on" (a1 != 0) e il path "off" (a1 == 0). La funzione
# implementa la software_rfkill di phy_ac.
#
# Pattern riconosciuto: dispatch chip-id INLINE (non via
# phy_reg_write_array). Per ogni call site:
#
#   lw    v0, 0(s1)          # s1 = acphychipid sym
#   addiu v1, zero, 17248    # 4360
#   beq   v0, v1, ...        # if 4360 → goto block_4360
#   addiu v1, zero, 17234    # 4352
#   beq   v0, v1, ...        # if 4352 → goto label (skip default-store)
#   addiu a1, zero, REG_X    # delay slot: default reg
#   addiu a1, zero, REG_Y    # fall-through: 43b3 (overwrite)
#   ...                      # eventuale block_4360 fa j label + delay-store
# label:
#   addu  a0, s0, zero       # a0 = pi
#   addiu a2, zero, MASK     # mask
#   jalr  s3                 # mod_radio_reg / write_radio_reg / ...
#   addiu a3, zero, VAL      # delay slot: val
#
# Differenze rispetto a extract_radio2069_init.py:
#   - param projection per `a1` (on/off) — la funzione ha due branch top-level
#   - helper aggiuntivo: write_radio_reg
#   - emette TSV con colonna `phase` (on/off)
#
# Uso (per-chip, integrazione run_quad_modal):
#   python3 extract_switch_radio_acphy.py /tmp/wl.disr \
#       --chip 43b3 --out-dir reverse-output/by-chip/43b3
#
# Output: switch_radio_acphy_extracted.{c,_ops.tsv}

import argparse, os, re, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _disasm_lib as D

FUNC = 'wlc_phy_switch_radio_acphy'
BASE = 'switch_radio_acphy_extracted'

# Helper conosciuti che vogliamo tracciare. La signature segue lo schema
# (rd, ...) MIPS-O32 con argomenti in a0..a3:
#   phy_reg_write    (pi, reg, val)
#   phy_reg_mod      (pi, reg, mask, val)             # RMW completa
#   phy_reg_read     (pi, reg) -> v0                   # lettura per RMW manuale
#   mod_radio_reg    (pi, reg, mask, val)
#   write_radio_reg  (pi, reg, val)
#   read_radio_reg   (pi, reg) -> v0
#   osl_delay        (us)
#   wlapi_bmac_phyclk_fgc (pi, on)
#
# Ogni jalr ad uno di questi simboli viene emesso come record. Alcuni
# (read_*, phy_reg_read) introducono RMW: lasciamo il dst v0 come None
# per invalidare i tentativi successivi di tracciare valori derivati.

KNOWN_HELPERS = {
    # name → (op_type, arg_regs_in_order)
    # arg_regs è la lista esatta di registri MIPS da cui leggere gli args.
    # Per helper che prendono `pi` come primo arg, salta a0 e usa a1..a3.
    # Per helper senza pi (osl_delay), parte da a0.
    'phy_reg_write':         ('phy_write',     ['a1', 'a2']),
    'phy_reg_mod':           ('phy_mod',       ['a1', 'a2', 'a3']),
    'mod_radio_reg':         ('radio_maskset', ['a1', 'a2', 'a3']),
    'write_radio_reg':       ('radio_write',   ['a1', 'a2']),
    'osl_delay':             ('udelay',        ['a0']),
    'wlapi_bmac_phyclk_fgc': ('phyclk_fgc',    ['a1']),
    # phy_reg_read / read_radio_reg: presenza ma non emessi
    # come op (sono lato lettura di RMW manuali).
}
RMW_READS = {'phy_reg_read', 'read_radio_reg'}


def trace_path(insns, chip_choice, on_choice, func_map):
    """Cammina la funzione proiettando chip_choice sul lw da acphychipid
    e on_choice (0|1) sul registro a1 all'ingresso.

    func_map: dict {addr: func_name} per risolvere puntatori a funzione
    costruiti via .text reloc (lui+addiu).

    Ritorna: list[Op], Op = (type, addr, *args).
    """
    addr_to_idx = {ins[0]: i for i, ins in enumerate(insns)}

    # Stato iniziale: zero=0, a1 = on_choice (parametro). a0 (pi)
    # non ci serve come valore numerico, lo lasciamo None: nessun
    # confronto con costanti dipenderà da a0.
    state = {'zero': 0}
    if on_choice is not None:
        state['a1'] = on_choice & 1

    ops_out = []
    visited = set()
    # Coda di branch indecidibili (target_idx) il cui target non è ancora
    # stato visitato. Permette al tracer di uscire dai polling loop in
    # cui le condizioni dipendono da valori non noti staticamente: quando
    # la fall-through riporta a un nodo già visitato, prendiamo la
    # branch indecidibile più recente per proseguire oltre il loop.
    deferred = []
    pc = 0
    steps = 0
    BUDGET = 50000

    while pc < len(insns) and steps < BUDGET:
        steps += 1
        if pc in visited:
            # Rewind: prova a proseguire da una branch indecidibile non
            # ancora seguita (tipicamente l'uscita del polling loop).
            while deferred:
                ti = deferred.pop()
                if ti not in visited:
                    pc = ti
                    break
            else:
                break
            if pc in visited:
                break
        visited.add(pc)

        addr, mnem, ops_str, reloc = insns[pc]
        ops = D.split_ops(ops_str)

        # Chip-id injection: lw rd, 0(rs) con reloc R_MIPS_LO16 acphychipid.
        # Riconosciamo direttamente dalla reloc dell'istruzione di load — è
        # cosi' che il linker materializza l'accesso al global PIC. Più
        # robusto che ispezionare lo stato di `rs`.
        if mnem == 'lw' and len(ops) == 2:
            dst = ops[0]
            if (reloc and reloc[0].endswith('LO16')
                    and reloc[1] == 'acphychipid'):
                state[dst] = chip_choice
            else:
                state[dst] = None
            pc += 1
            continue

        if mnem in ('beq', 'bne') and len(ops) == 3:
            rs, rt, tgt_s = ops
            tgt = D.branch_target(tgt_s)
            taken = _decide_branch(state, mnem, rs, rt)

            # delay slot esegue sempre
            if pc + 1 < len(insns):
                D.track_reg(state, insns[pc + 1])

            if taken is True and tgt is not None:
                ti = addr_to_idx.get(tgt)
                if ti is not None and ti not in visited:
                    pc = ti
                    continue
                # Target già visitato (loop) o fuori dalla funzione →
                # fall-through (vedi `if pc in visited` sopra per il
                # rewind tramite deferred).
            elif taken is None and tgt is not None:
                # Branch indecidibile: salva il target come fallback
                # per il rewind quando il path lineare si esaurisce.
                ti = addr_to_idx.get(tgt)
                if ti is not None and ti not in visited:
                    deferred.append(ti)
            pc += 2
            continue

        if mnem == 'j' and len(ops) == 1:
            tgt = D.branch_target(ops[0])
            if pc + 1 < len(insns):
                D.track_reg(state, insns[pc + 1])
            if tgt is not None:
                ti = addr_to_idx.get(tgt)
                if ti is not None and ti not in visited:
                    pc = ti
                    continue
            break

        if mnem == 'jr' and len(ops) == 1:
            if pc + 1 < len(insns):
                D.track_reg(state, insns[pc + 1])
            # Tail call ad helper noto?
            sym = D.sym_of(state, ops[0])
            if sym in KNOWN_HELPERS:
                _emit_helper_call(ops_out, addr, sym, state)
            break

        if mnem == 'jalr' and len(ops) >= 1:
            # delay slot
            if pc + 1 < len(insns):
                D.track_reg(state, insns[pc + 1])

            sym = D.sym_of(state, ops[0])
            target_int = state.get(ops[0]) if isinstance(state.get(ops[0]), int) else None
            if sym in KNOWN_HELPERS:
                _emit_helper_call(ops_out, addr, sym, state)
            elif sym in RMW_READS:
                pass  # invalidiamo v0 sotto, nient'altro
            elif sym is not None:
                # Simbolo non in KNOWN_HELPERS: chiamata a funzione esterna
                # nota per nome (non risolveremo gli args).
                ops_out.append(('extern_call', addr, sym))
            elif target_int is not None and target_int in func_map:
                # Puntatore a funzione costruito via .text reloc
                # (lui+addiu su .text). func_map risolve all'ID nominale.
                ops_out.append(('extern_call', addr, func_map[target_int]))

            D.invalidate_caller_saved(state)
            pc += 2
            continue

        # Default: aggiorna stato e avanza
        D.track_reg(state, insns[pc])
        pc += 1

    return ops_out


def _decide_branch(state, mnem, rs, rt):
    """Decide un beq/bne. Ritorna True/False/None.

    Coperti:
      1. rs e rt entrambi int                 → confronto diretto
      2. eq_test idiom (xori-sltiu) vs zero  → risolto se orig è int
    Tutto il resto → None (fall-through).
    """
    rs_val = state.get(rs)
    rt_val = state.get(rt)

    if isinstance(rs_val, int) and isinstance(rt_val, int):
        eq = (rs_val == rt_val)
        return eq if mnem == 'beq' else not eq

    # eq_test idiom
    eq_state = other_val = None
    if isinstance(rs_val, tuple) and rs_val[0] == 'eq_test':
        eq_state, other_val = rs_val, rt_val
    elif isinstance(rt_val, tuple) and rt_val[0] == 'eq_test':
        eq_state, other_val = rt_val, rs_val
    if eq_state is not None and other_val == 0:
        _, orig_rs, target_imm = eq_state
        orig_val = state.get(orig_rs)
        if isinstance(orig_val, int):
            orig_eq_imm = (orig_val == target_imm)
            # beq v0,zero,target taken se v0==0 ⟺ orig != imm
            return (not orig_eq_imm) if mnem == 'beq' else orig_eq_imm

    return None


def _emit_helper_call(ops_out, addr, sym, state):
    """Crea un record Op leggendo gli argomenti dai registri specificati
    in KNOWN_HELPERS[sym]. Argomenti non-int (None / simbolici) → None."""
    op_type, arg_regs = KNOWN_HELPERS[sym]
    args = []
    for reg in arg_regs:
        v = state.get(reg)
        args.append(v if isinstance(v, int) else None)
    ops_out.append((op_type, addr, *args))


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def fmt_arg(v, hex_width=4):
    if v is None:
        return '?'
    return f'0x{v:0{hex_width}x}'


def fmt_op_c(op):
    """Una riga C nello stile delle altre extract_*. dev/blocked si assumono."""
    t, addr = op[0], op[1]
    a = lambda i, w=4: fmt_arg(op[2 + i] if 2 + i < len(op) else None, w)
    cmt = f'  /* @{addr:#010x} */'
    if t == 'phy_write':
        return f'\tb43_phy_write(dev, {a(0)}, {a(1)});{cmt}'
    if t == 'phy_mod':
        # phy_reg_mod(pi, reg, mask, val): sostituisce i bit indicati da mask
        # con val. b43_phy_maskset(dev, reg, mask_keep, val): mask_keep = ~mask.
        if op[3] is None or op[4] is None:
            return f'\t/* @{addr:#010x}: phy_mod reg={a(0)} mask=? val=? */'
        return f'\tb43_phy_maskset(dev, {a(0)}, ~{a(1)}, {a(2)});{cmt}'
    if t == 'radio_maskset':
        if op[3] is None or op[4] is None:
            return f'\t/* @{addr:#010x}: radio_maskset reg={a(0)} mask=? val=? */'
        if op[3] == op[4]:
            return f'\tb43_radio_set(dev, {a(0)}, {a(1)});{cmt}'
        return f'\tb43_radio_maskset(dev, {a(0)}, ~{a(1)}, {a(2)});{cmt}'
    if t == 'radio_write':
        return f'\tb43_radio_write(dev, {a(0)}, {a(1)});{cmt}'
    if t == 'udelay':
        v = op[2]
        return f'\tudelay({v if v is not None else "/*?*/"});{cmt}'
    if t == 'phyclk_fgc':
        v = op[2]
        return f'\tb43_phy_force_clock(dev, {v if v is not None else "/*?*/"});{cmt}'
    if t == 'extern_call':
        return f'\t/* @{addr:#010x}: extern call → {op[2]} (porting separato) */'
    return f'\t/* unknown op: {op} */'


def op_tsv_row(phase, op):
    """phase\\taddr\\ttype\\tfield1\\tfield2\\tfield3"""
    t, addr = op[0], op[1]
    addr_s = f'0x{addr:08x}'
    fields = list(op[2:])
    # Normalizza a 3 campi
    while len(fields) < 3:
        fields.append(None)
    fields = fields[:3]
    f_strs = []
    for f in fields:
        if f is None:
            f_strs.append('')
        elif isinstance(f, int):
            f_strs.append(f'0x{f:04x}')
        else:
            f_strs.append(str(f))
    return f'{phase}\t{addr_s}\t{t}\t' + '\t'.join(f_strs)


def emit_c_for_chip(ops_on, ops_off, chip_label, out):
    p = lambda *a: print(*a, file=out)
    p('/* ================================================================')
    p(f' * extract_switch_radio_acphy.py --chip {chip_label}')
    p(' * Sorgente: wlDSL-3580_EU.o_save (MIPS BE, DSL-3580L, chip 0x43b3)')
    p(' * Funzione: wlc_phy_switch_radio_acphy @0x4582c')
    p(f' * Op count: on={len(ops_on)} off={len(ops_off)}')
    p(' *')
    p(' * Output backing per software_rfkill. Il body sotto è una')
    p(' * proiezione statica del path scelto; verificare con audit a')
    p(' * mano prima del commit nel kernel-patch.')
    p(' *')
    p(' * extern_call → wlc_phy_radio2069_pwron_seq / mini_pwron_seq_rev16:')
    p(' * portate da extract_radio2069_init.py; qui sono solo')
    p(' * placeholders, non re-emette le sequenze.')
    p(' * ================================================================ */')
    p('')
    p('static void b43_phy_ac_op_software_rfkill(struct b43_wldev *dev,')
    p('                                          bool blocked)')
    p('{')
    p('\tif (blocked) {')
    for op in ops_off:
        p('\t' + fmt_op_c(op))
    p('\t\treturn;')
    p('\t}')
    p('')
    for op in ops_on:
        p(fmt_op_c(op))
    p('}')


def main():
    ap = argparse.ArgumentParser(
        description=f'Estrae {FUNC} dal blob MIPS BE.')
    ap.add_argument('disr', help='disasm objdump (wl.disr)')
    ap.add_argument('--chip', choices=sorted(D.CHIP_CHOICE),
                    help='proietta il dispatch sul chip indicato. '
                         'Senza --chip: solo statistiche.')
    ap.add_argument('--out-dir', metavar='DIR',
                    help=f'scrivi {BASE}.c e {BASE}_ops.tsv in DIR. '
                         'Richiede --chip.')
    args = ap.parse_args()

    if args.out_dir and not args.chip:
        ap.error('--out-dir richiede --chip')

    insns = D.parse_func(args.disr, FUNC)
    func_map = D.build_func_addr_map(args.disr)
    print(f'/* {FUNC}: {len(insns)} istruzioni */', file=sys.stderr)

    chip_choice = D.CHIP_CHOICE.get(args.chip) if args.chip else None
    ops_on  = trace_path(insns, chip_choice, on_choice=1, func_map=func_map)
    ops_off = trace_path(insns, chip_choice, on_choice=0, func_map=func_map)
    print(f'/* {args.chip or "no-chip"}: on={len(ops_on)} off={len(ops_off)} */',
          file=sys.stderr)

    if args.out_dir:
        os.makedirs(args.out_dir, exist_ok=True)
        with open(os.path.join(args.out_dir, BASE + '.c'), 'w') as f:
            emit_c_for_chip(ops_on, ops_off, args.chip, f)
        with open(os.path.join(args.out_dir, BASE + '_ops.tsv'), 'w') as f:
            f.write('phase\taddr\ttype\tfield1\tfield2\tfield3\n')
            for op in ops_on:
                f.write(op_tsv_row('on', op) + '\n')
            for op in ops_off:
                f.write(op_tsv_row('off', op) + '\n')
    else:
        emit_c_for_chip(ops_on, ops_off, args.chip or 'no-chip', sys.stdout)


if __name__ == '__main__':
    main()

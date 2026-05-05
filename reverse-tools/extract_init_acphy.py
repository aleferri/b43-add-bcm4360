#!/usr/bin/env python3
# extract_init_acphy.py
#
# Estrae da wlc_phy_init_acphy (blob MIPS BE wl.o) le due sequenze di write
# che servono per completare §1.3 in kernel-patch/existing_files/phy_ac.c.additions:
#
#   FASE 3 — mode-bit clears
#       Sequenza di phy_reg_write all'inizio della funzione, con dispatch
#       chip-specifico su acphychipid. Il binario espone tre forme:
#         - addiu/beq classico per BCM4360 (0x4360) e BCM4352 (0x4352)
#         - idiom xori-sltiu-beq per altre costanti (es. 0x43b3 — vedi
#           ). Prodotta prima del lock 0x19E / table-write loop.
#
#   FASE 9 — bphy_init
#       16 phy_reg_write consecutive dopo wlc_phy_radar_detect_init.
#       Valori costanti (niente chip-dispatch). Queste sono le write ai filtri
#       CCK del BPHY compatibili con il path 2.4 GHz 1 Mbit/s.
#
# Strategia: tracciamento lineare dei registri MIPS (s1=phy_reg_write,
# s3=phy_reg_read, a1=reg_arg, a2=val_arg) con analisi dei branch per
# il dispatch chip-specifico. Il confine fra fase-3 e fase-9 è l'indirizzo
# del lock 0x19E (phy_reg_mod con a1=414=0x19e, a2=2, a3=2).
#
# Prerequisiti:
#   mips-linux-gnu-objdump -dr --no-show-raw-insn -M no-aliases \
#       wlDSL-3580_EU.o_save > /tmp/wl_full.disasm
#
# Uso:
#   python3 extract_init_acphy.py /tmp/wl_full.disasm
#
# Output:
#   Stampa su stdout le due sezioni di codice C pronte per
#   b43_phy_ac_op_init() e b43_phy_ac_bphy_init().

import argparse, os, re, sys
from collections import defaultdict

# Chip ID constants (vedi README.md).
# 0x43b3 è il target reale del DSL-3580L; 4360 e 4352 restano per regression
# e per leggere i dispatch espliciti che il binario fa contro quelle costanti.
CHIP_43B3 = 0x43b3   # 17331 — DSL-3580L (target attuale)
CHIP_4352 = 0x4352   # 17234
CHIP_4360 = 0x4360   # 17248 — non più target, mantenuto per regression
CHIP_4352_FAMILY = (0x4352, 0x4348, 0x4333, 0x43A2, 0x43B0, 0x43B3)

# ---------------------------------------------------------------------------
# Parsing del disassembly
# ---------------------------------------------------------------------------

def parse_disasm_func(path, func_name):
    """Ritorna la lista di (addr, mnem, operands, reloc_sym_or_None)
    per la funzione func_name."""
    lines = open(path).readlines()
    start = end = None
    for i, l in enumerate(lines):
        if f'<{func_name}>:' in l:
            start = i
        if start and i > start + 5 and re.match(r'^[0-9a-f]+ <', l):
            end = i
            break
    if start is None:
        raise ValueError(f"Function {func_name} not found")
    if end is None:
        end = len(lines)

    result = []
    last = None
    for l in lines[start:end]:
        # relocation line: "\t\t\t532a0: R_MIPS_HI16\tphy_reg_read"
        m = re.match(r'\s+[0-9a-f]+:\s+(R_MIPS_\S+)\s+(\S+)', l)
        if m and last is not None:
            # Store (reloc_type, sym); keep only the first reloc per insn
            if last[3] is None:
                last[3] = (m.group(1), m.group(2))  # ('R_MIPS_LO16', 'phy_reg_write')
            continue
        # instruction line
        m = re.match(r'\s*([0-9a-f]+):\s+(\S+)(?:\s+(.*))?$', l)
        if m:
            insn = [int(m.group(1), 16),
                    m.group(2),
                    (m.group(3) or '').strip(),
                    None]  # [addr, mnem, ops_str, (reloc_type, sym)|None]
            result.append(insn)
            last = insn
    return result

# ---------------------------------------------------------------------------
# Tracciamento valore immediato
# ---------------------------------------------------------------------------

def imm(s):
    """Parsa stringa a intero (hex o dec, eventualmente negativo).
    Gestisce sia immediati decimali ("17248") che indirizzi hex objdump ("53880").
    Gestisce anche il formato 'ADDR <sym+off>' usato da objdump nei branch."""
    s = s.strip()
    # Strip symbol annotation: "53880 <wlc_phy_init_acphy+0x5e8>" → "53880"
    if '<' in s:
        s = s[:s.index('<')].strip()
    if not s:
        return None
    try:
        # Prova con prefisso 0x/-0x esplicito
        if s.startswith(('0x', '-0x', '+0x')):
            return int(s, 16)
        # Stringa con solo cifre hex (a-f) → è un indirizzo hex senza prefisso
        if re.fullmatch(r'[0-9a-fA-F]+', s):
            # Distingui indirizzo hex da immediato decimale:
            # Gli immediati MIPS in addiu/ori sono < 65536 (16 bit).
            # Se la stringa contiene a-f è sicuramente hex.
            # Se contiene solo 0-9, usa una soglia: >65535 → probabilmente hex.
            if re.search(r'[a-fA-F]', s):
                return int(s, 16)
            v_dec = int(s, 10)
            v_hex = int(s, 16)
            if v_dec > 65535:
                return v_hex   # è un indirizzo
            return v_dec       # è un immediato decimale
        return int(s, 10)
    except ValueError:
        return None

def branch_target(s):
    """Parsa un target di branch come indirizzo hex (sempre hex, mai decimale).
    objdump stampa i target senza prefisso 0x: '53880 <sym+off>' → 0x53880."""
    s = s.strip()
    if '<' in s:
        s = s[:s.index('<')].strip()
    try:
        return int(s, 16)
    except ValueError:
        return None

def split_ops(s):
    return [x.strip() for x in s.split(',')] if s else []

def track_reg(state, insns, idx):
    """
    Aggiorna `state` con l'effetto dell'istruzione insns[idx].
    state è un dict reg->int|None. Ritorna l'indice della prossima
    istruzione da processare (normalmente idx+1, salvo delay slots).
    """
    addr, mnem, ops_str, reloc = insns[idx]
    ops = split_ops(ops_str)

    if mnem == 'lui' and len(ops) == 2:
        rd, imm_s = ops
        v = imm(imm_s)
        state[rd] = ((v & 0xffff) << 16) if v is not None else None

    elif mnem in ('addiu', 'daddiu') and len(ops) == 3:
        rd, rs, imm_s = ops
        v = imm(imm_s)
        if reloc and isinstance(reloc, tuple) and 'LO16' in reloc[0]:
            # HI16+LO16 pair → simbolo; valore non numerico utile
            state[rd] = ('sym', reloc[1])
        elif rs == 'zero':
            state[rd] = (v & 0xffffffff) if v is not None else None
        else:
            sv = state.get(rs)
            if isinstance(sv, int) and v is not None:
                state[rd] = (sv + v) & 0xffffffff
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

    elif mnem == 'xori' and len(ops) == 3:
        # parte 1/3 dell'idiom "branch se rs == IMM" usato dal
        # compilatore Broadcom per costanti che non passano in addiu o per
        # nuovi dispatch (es. 0x43b3). track_reg memorizza la coppia per
        # permettere a sltiu+beq di chiudere il pattern.
        rd, rs, imm_s = ops
        v = imm(imm_s)
        sv = state.get(rs)
        if isinstance(sv, int) and v is not None:
            state[rd] = (sv ^ (v & 0xffff)) & 0xffffffff
        elif v is not None:
            state[rd] = ('xori_eq', rs, v & 0xffff)
        else:
            state[rd] = None

    elif mnem == 'sltiu' and len(ops) == 3:
        # parte 2/3. `sltiu rd, rs, 1` ⟺ rd = (rs == 0).
        rd, rs, imm_s = ops
        v = imm(imm_s)
        sv = state.get(rs)
        if v == 1 and isinstance(sv, tuple) and sv[0] == 'xori_eq':
            _, orig_rs, target_imm = sv
            state[rd] = ('eq_test', orig_rs, target_imm)
        elif v == 1 and isinstance(sv, int):
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

    elif mnem in ('sw', 'sh', 'sb', 'lw', 'lh', 'lb', 'lhu', 'lbu'):
        pass  # store: no dest invalidation; load: imprecise

    elif ops:
        rd = ops[0]
        if rd not in ('zero', 'sp', 'fp', 'ra', 'gp', 'at', 'k0', 'k1'):
            state[rd] = None

    return idx + 1


# ---------------------------------------------------------------------------
# Analisi della funzione
# ---------------------------------------------------------------------------

def analyse_init_acphy(insns):
    """
    Cammina linearmente le istruzioni con leggero supporto ai branch
    (segue solo il fall-through, non biforca). Raccoglie:

      mode_writes : lista di (addr, reg, val, chip_context)
          dove chip_context è 'generic' | 'BCM4352' | 'BCM4360' | 'shared'
      bphy_writes : lista di (addr, reg, val)

    Il confine fra le due sezioni è l'indirizzo del `phy_reg_mod` con
    a1=414 (=0x19E) a2=2 a3=2 che setta il table-write gate (§1.1).
    La sezione bphy è identificata come il blocco di jalr consecutivi
    a s1 (phy_reg_write) che segue la chiamata a wlc_phy_radar_detect_init.
    """
    # Identifica i registri function-pointer
    # s1 = phy_reg_write  (caricato a 0x5330c con HI16+LO16 reloc)
    # s3 = phy_reg_read   (caricato a 0x532a0 con HI16+LO16 reloc)
    # La prima write a s1 con R_MIPS_LO16 -> 'phy_reg_write' lo fissa
    PHY_WRITE_REG = None  # registro che contiene phy_reg_write
    PHY_READ_REG  = None
    PHY_MOD_REG   = None  # v0 dopo la seconda HI16+LO16 load di phy_reg_mod

    # Determina i registri dai reloc
    for addr, mnem, ops, reloc in insns:
        if reloc and reloc[0] == 'R_MIPS_LO16' and reloc[1] == 'phy_reg_write':
            ops_list = split_ops(ops)
            if ops_list:
                PHY_WRITE_REG = ops_list[0]
                break

    for addr, mnem, ops, reloc in insns:
        if reloc and reloc[0] == 'R_MIPS_LO16' and reloc[1] == 'phy_reg_read':
            ops_list = split_ops(ops)
            if ops_list:
                PHY_READ_REG = ops_list[0]
                break

    # Costruisce mappa addr->idx per salti
    addr_to_idx = {ins[0]: i for i, ins in enumerate(insns)}

    # Prima passata: trova l'indirizzo del table-write gate set
    # = phy_reg_mod(pi, 0x19e, 2, 2)
    # Nel blob è phy_reg_mod via v0 (secondo load HI16+LO16 di phy_reg_mod)
    gate_set_addr = None
    for i, (addr, mnem, ops, reloc) in enumerate(insns):
        if reloc and reloc[0] == 'R_MIPS_HI16' and reloc[1] == 'phy_reg_mod':
            # Cerca il jalr v0 successivo con a1=414 (0x19e) nel contesto
            for j in range(i, min(i + 20, len(insns))):
                a, m, o, r = insns[j]
                if m == 'jalr':
                    # Controlla che a1 sia 414 a breve distanza
                    for k in range(max(0, j-10), j+1):
                        a2, m2, o2, r2 = insns[k]
                        if m2 == 'addiu' and 'a1' in split_ops(o2):
                            ops2 = split_ops(o2)
                            if len(ops2) == 3 and imm(ops2[2]) == 414:
                                gate_set_addr = a
                                break
                    if gate_set_addr:
                        break
            if gate_set_addr:
                break

    # Trova wlc_phy_radar_detect_init call address
    radar_call_addr = None
    for addr, mnem, ops, reloc in insns:
        if reloc and reloc[0] == 'R_MIPS_LO16' and reloc[1] == 'wlc_phy_radar_detect_init':
            radar_call_addr = addr
            break

    # Trova il jalr subito dopo il load di radar_detect_init
    radar_jalr_addr = None
    if radar_call_addr:
        for i, (addr, mnem, ops, reloc) in enumerate(insns):
            if addr == radar_call_addr:
                for j in range(i, min(i + 5, len(insns))):
                    if insns[j][1] == 'jalr':
                        radar_jalr_addr = insns[j][0]
                        break
                break

    # --- Tracciamento registri con chip-dispatch awareness ---
    #
    # Pattern chip-dispatch:
    #   lw  v0, 0(s2)            # carica acphychipid
    #   addiu v1, zero, CHIP_4360
    #   beq  v0, v1, TARGET      # se BCM4360, salta
    #   addiu a1, zero, VAL_4360 # delay slot: a1 per BCM4360
    #   addiu v1, zero, CHIP_4352
    #   beq  v0, v1, TARGET2     # se BCM4352, salta
    #   addiu a1, zero, VAL_4352 # delay slot
    #   # fall-through: a1 = VAL_GENERIC (ultimo addiu a1 prima del jalr)
    #
    # Siccome tracciamo solo il fall-through, catturiamo il valore "generic".
    # Per recuperare anche 4360/4352, tracciamo i target dei branch.

    mode_writes = []   # (addr, reg, val, chip_ctx)
    bphy_writes  = []  # (addr, reg, val)

    # Stato registers per path principale (fall-through)
    state = {}
    # Chip-specific: simuliamo anche il path "beq taken" per raccogliere
    # i valori chip-specifici. Quando vediamo il pattern acphychipid,
    # teniamo traccia dei tre valori.

    # Mappa addr→(reg, val) collezionata da "taken" branch paths
    chip_specific_at = {}  # {jalr_addr: {'BCM4360': val, 'BCM4352': val, 'generic': val}}

    # Pre-pass: raccogli i dispatch chip-specifici
    # Pattern: (lw v0,0(s2) | lhu via acphychipid) → beq+delay × 2 → jalr s1
    chip_dispatch_addrs = set()
    i = 0
    while i < len(insns):
        addr, mnem, ops, reloc = insns[i]
        # Cerca il pattern: beq rX, rY, TARGET seguito da addiu a1,...
        # dove la stessa sequenza si ripete (due beq = due chip check)
        if mnem == 'beq' and i + 1 < len(insns):
            ops_list = split_ops(ops)
            if len(ops_list) == 3:
                target_s = ops_list[2]
                target = imm(target_s)
                # delay slot
                d_addr, d_mnem, d_ops, _ = insns[i+1]
                if d_mnem == 'addiu' and 'a1' in split_ops(d_ops):
                    d_ops_list = split_ops(d_ops)
                    val_taken = imm(d_ops_list[2]) if len(d_ops_list) == 3 else None
                    # Segna il target come "chip-specific path"
                    if target is not None:
                        chip_dispatch_addrs.add(target)
        i += 1

    # Tracciamento principale: fall-through con chip-ID dispatch
    #
    # Per ogni `beq` verso un target noto come chip-dispatch, annotiamo
    # il contesto chip per il prossimo jalr s1 che incontriamo.

    # --- Pass 2: pattern-matching per chip-dispatch blocks ---
    #
    # Pattern identificato nel disasm:
    #   addiu v1, zero, 17248          ; v1 = BCM4360
    #   beq   v0, v1, TARGET_4360      ; se BCM4360, salta
    #   addiu v1, zero, 17234          ; delay slot: v1 = BCM4352
    #   beq   v0, v1, TARGET_4352      ; se BCM4352, salta
    #   addiu a1, zero, VAL_4352       ; delay slot: val per BCM4352
    #   addiu a1, zero, VAL_GENERIC    ; sovrascrive: val per generic
    #   <1-2 insn setup a0>
    #   jalr  s1                       ; phy_reg_write(pi, a1, a2)
    #   <delay slot: a2>
    #
    # La funzione dispatch_pattern_scan() identifica ogni blocco e
    # restituisce (addr_jalr, reg_generic, reg_4352, reg_4360, val).
    # Nota: val=0 per quasi tutti i blocchi (delay slot = addu a2,zero,zero).

    def dispatch_pattern_scan(insns_list, jalr_reg):
        """
        Scansiona alla ricerca del pattern triplo BCM4360/BCM4352/generic.
        Ritorna lista di dict con chiavi: addr, reg_generic, reg_4352, reg_4360, val.
        """
        results = []
        n = len(insns_list)
        i = 0
        while i < n - 8:
            addr, mnem, ops, reloc = insns_list[i]
            # Cerca 'addiu v1, zero, 17248'
            ops_l = split_ops(ops)
            if not (mnem == 'addiu' and ops_l == ['v1', 'zero', '17248']):
                i += 1
                continue
            # i+1 dovrebbe essere beq v0,v1,TARGET_4360
            a1, m1, o1, _ = insns_list[i+1]
            if m1 != 'beq':
                i += 1
                continue
            o1_l = split_ops(o1)
            if len(o1_l) != 3 or 'v1' not in o1_l[:2]:
                i += 1
                continue
            # Delay slot di beq BCM4360: dovrebbe essere 'addiu v1,zero,17234'
            a2, m2, o2, _ = insns_list[i+2]
            o2_l = split_ops(o2)
            # i+2 = delay slot del beq BCM4360: addiu v1,zero,17234
            if not (m2 == 'addiu' and o2_l == ['v1', 'zero', '17234']):
                i += 1
                continue
            # i+3 = beq v0,v1,TARGET_4352
            a3, m3, o3, _ = insns_list[i+3]
            if m3 != 'beq':
                i += 1
                continue
            # i+4 = delay slot beq BCM4352: addiu a1,zero,VAL_4352
            a4, m4, o4, _ = insns_list[i+4]
            o4_l = split_ops(o4)
            if not (m4 == 'addiu' and len(o4_l) == 3 and o4_l[0] == 'a1'):
                i += 1
                continue
            val_4352 = imm(o4_l[2])
            # i+5 = addiu a1,zero,VAL_GENERIC (sovrascrittura per generic)
            a5, m5, o5, _ = insns_list[i+5]
            o5_l = split_ops(o5)
            if not (m5 == 'addiu' and len(o5_l) == 3 and o5_l[0] == 'a1'):
                # Non c'è sovrascrittura generica: val_generic = val_4352
                val_generic = val_4352
                jalr_start = i + 5
            else:
                val_generic = imm(o5_l[2])
                jalr_start = i + 6

            # Cerca il jalr s1 entro 4 insn
            jalr_addr = None
            a2_val = 0
            for j in range(jalr_start, min(jalr_start + 5, n)):
                aj, mj, oj, _ = insns_list[j]
                if mj == 'jalr' and jalr_reg and split_ops(oj)[0] == jalr_reg:
                    jalr_addr = aj
                    # delay slot = a2
                    if j + 1 < n:
                        _, md, od, _ = insns_list[j+1]
                        od_l = split_ops(od)
                        if md == 'addiu' and len(od_l) == 3 and od_l[0] == 'a2':
                            a2_val = imm(od_l[2]) or 0
                        elif md == 'addu' and len(od_l) == 3 and od_l[0] == 'a2' and od_l[1] == 'zero':
                            a2_val = 0
                    break

            if jalr_addr is None:
                i += 1
                continue

            # Recupera il val_4360 dal target del primo beq
            # TARGET_4360 contiene addiu a1,zero,VAL_4360 (l'ultimo addiu a1 prima del jalr)
            o1_l = split_ops(o1)
            target_4360 = branch_target(o1_l[2]) if len(o1_l) == 3 else None
            val_4360 = None
            if target_4360 is not None:
                tidx = next((k for k, ins in enumerate(insns_list)
                             if ins[0] == target_4360), None)
                if tidx is not None:
                    # Cerca addiu a1,zero,VAL nell'intorno
                    for k in range(tidx, min(tidx + 5, n)):
                        ak, mk, ok, _ = insns_list[k]
                        ok_l = split_ops(ok)
                        if mk == 'addiu' and len(ok_l) == 3 and ok_l[0] == 'a1':
                            val_4360 = imm(ok_l[2])
                            break

            results.append({
                'addr': jalr_addr,
                'reg_generic': val_generic,
                'reg_4352':   val_4352,
                'reg_4360':   val_4360,
                'val':         a2_val,
            })
            i = jalr_start + 2  # salta oltre il jalr+delay
        return results

    chip_dispatch_writes = dispatch_pattern_scan(insns, PHY_WRITE_REG)

    # Raccogliamo i valori (reg, val) di phy_reg_write per ogni percorso
    # Struttura: per ogni phy_reg_write incontriamo (addr, a1, a2)
    # dove chip_ctx dipende da quale branch path siamo
    #
    # Implementazione semplificata: simuliamo i tre path in parallelo
    # facendo tre passate lineari ciascuna con un "forced" chip choice.

    def trace_path(chip_choice):
        """
        Esegue una tracciamento lineare della funzione assumendo che
        chip_choice sia il risultato di acphychipid:
          None    → valore sconosciuto (segue fall-through dei beq)
          0x4360  → BCM4360: prende i beq con v1==BCM4360
          0x4352  → BCM4352: prende i beq con v1==BCM4352
          0x43b3  → DSL-3580L: dispatch tipicamente via xori-sltiu-beq
                    (vedi commenti inline)
        Ritorna lista di (addr, a1_val, a2_val) per ogni jalr s1.
        """
        local_state = {}
        writes = []
        visited = set()

        # per riconoscere il dispatch via xori-sltiu-beq dobbiamo
        # iniettare chip_choice nei registri caricati da `lw <reg>, 0(<acphychipid_ptr>)`.
        # Il pattern xori richiede un orig_rs di tipo int per chiudere la decisione.
        def is_chip_id_ptr(reg):
            v = local_state.get(reg)
            return isinstance(v, tuple) and v[0] == 'sym' and 'acphychipid' in v[1]

        # Stack di (idx, state_snapshot) per gestire salti
        # Usiamo approccio PC-simulation con forced chip choice
        pc = 0
        steps = 0

        while pc < len(insns) and steps < 10000:
            steps += 1
            if pc in visited:
                break
            visited.add(pc)

            addr, mnem, ops_str, reloc = insns[pc]
            ops = split_ops(ops_str)

            # Iniezione chip_choice su lw da acphychipid (prerequisito §0.2)
            if (mnem == 'lw' and chip_choice is not None and len(ops) == 2):
                m_base = re.match(r'0\((\w+)\)', ops[1])
                if m_base and is_chip_id_ptr(m_base.group(1)):
                    local_state[ops[0]] = chip_choice
                    pc += 1
                    continue

            # Gestione branch: beq/bne
            if mnem in ('beq', 'bne') and len(ops) == 3:
                rs, rt, tgt_s = ops
                tgt = branch_target(tgt_s)
                if tgt is None and tgt_s.startswith('-'):
                    tgt_s = tgt_s  # già negativo
                # Determina taken/not-taken
                rs_val = local_state.get(rs)
                rt_val = local_state.get(rt)
                taken = None

                if chip_choice is not None:
                    # Se uno dei due è la costante chip, decidiamo
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
                    # idiom xori-sltiu-beq
                    # Lo stato sul registro confrontato è ('eq_test', rs_orig, IMM):
                    # vale 1 sse rs_orig == IMM. Confronto contro zero:
                    #   beq v0, zero → branch se rs_orig != IMM
                    #   bne v0, zero → branch se rs_orig == IMM
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
                            orig_val = local_state.get(orig_rs)
                            if isinstance(orig_val, int):
                                orig_eq_imm = (orig_val == target_imm)
                                if mnem == 'beq':
                                    taken = not orig_eq_imm
                                else:
                                    taken = orig_eq_imm

                # Sempre esegui delay slot
                if pc + 1 < len(insns):
                    track_reg(local_state, insns, pc + 1)

                if taken is True and tgt is not None:
                    target_idx = addr_to_idx.get(tgt)
                    if target_idx is not None and target_idx not in visited:
                        pc = target_idx
                        continue
                elif taken is False:
                    pc += 2  # skip delay slot (già eseguito)
                    continue
                else:
                    # unknown: segui fall-through
                    pc += 2
                    continue

            # Gestione jump assoluto j/jr (return)
            elif mnem == 'j' and len(ops) == 1:
                tgt = branch_target(ops[0])
                if pc + 1 < len(insns):
                    track_reg(local_state, insns, pc + 1)  # delay
                if tgt is not None:
                    target_idx = addr_to_idx.get(tgt)
                    if target_idx is not None and target_idx not in visited:
                        pc = target_idx
                        continue
                break

            elif mnem == 'jr' and len(ops) == 1 and ops[0] == 'ra':
                break  # return

            # jalr = call
            elif mnem == 'jalr' and len(ops) >= 1:
                reg = ops[0]
                reg_val = local_state.get(reg)
                # delay slot
                if pc + 1 < len(insns):
                    track_reg(local_state, insns, pc + 1)
                # Cattura se è phy_reg_write
                if reg == PHY_WRITE_REG or (isinstance(reg_val, tuple) and
                                             reg_val[0] == 'sym' and
                                             'phy_reg_write' in str(reg_val)):
                    a1 = local_state.get('a1')
                    a2 = local_state.get('a2')
                    if isinstance(a1, int) and isinstance(a2, int):
                        writes.append((addr, a1, a2))
                # Invalida caller-saved
                for r in ('v0','v1','a0','a1','a2','a3',
                          't0','t1','t2','t3','t4','t5','t6','t7','t8','t9'):
                    local_state[r] = None
                pc += 2
                continue

            else:
                track_reg(local_state, insns, pc)

            pc += 1

        return writes

    writes_generic = trace_path(None)
    writes_4360    = trace_path(CHIP_4360)
    writes_4352    = trace_path(CHIP_4352)
    writes_43b3    = trace_path(CHIP_43B3)
    if {(a, r, v) for a, r, v in writes_43b3} != {(a, r, v) for a, r, v in writes_4352}:
        print('/* NOTE: init_acphy path 43b3 diverge da 4352 — vedi diff per-chip in reverse-output/by-chip/ */',
              file=sys.stderr)

    # --- Separa fase-3 da fase-9 ---
    #
    # Il confine è l'indirizzo del gate set (jalr che chiama phy_reg_mod
    # con a1=414). Tutto prima → fase-3. Tutto dopo radar_jalr → fase-9.

    def classify(writes_list, gate_addr, radar_addr, phase):
        """Filtra writes in base alla fase."""
        result = []
        for addr, reg, val in writes_list:
            if phase == 'mode' and gate_addr and addr < gate_addr:
                result.append((addr, reg, val))
            elif phase == 'bphy' and radar_addr and addr > radar_addr:
                result.append((addr, reg, val))
        return result

    mode_generic = classify(writes_generic, gate_set_addr, radar_jalr_addr, 'mode')
    mode_4360    = classify(writes_4360,    gate_set_addr, radar_jalr_addr, 'mode')
    mode_4352    = classify(writes_4352,    gate_set_addr, radar_jalr_addr, 'mode')
    mode_43b3    = classify(writes_43b3,    gate_set_addr, radar_jalr_addr, 'mode')

    bphy_writes  = classify(writes_generic, gate_set_addr, radar_jalr_addr, 'bphy')

    return {
        'gate_set_addr':        gate_set_addr,
        'radar_jalr_addr':      radar_jalr_addr,
        'mode_generic':         mode_generic,
        'mode_4360':            mode_4360,
        'mode_4352':            mode_4352,
        'mode_43b3':            mode_43b3,
        'chip_dispatch_writes': chip_dispatch_writes,
        'bphy_writes':          bphy_writes,
        'PHY_WRITE_REG':        PHY_WRITE_REG,
    }


# ---------------------------------------------------------------------------
# Output per-chip — emette UN solo path proiettato
# ---------------------------------------------------------------------------

def write_ops_tsv(mode_writes, bphy_writes, out_path):
    """Dump TSV machine-readable per il diff report (§0.4).

    Una riga per write con phase {'mode','bphy'}, addr, reg, val.
    L'ordine è quello di emissione (per addr); i confronti del diff
    avvengono come set di tuple, quindi l'ordine non altera il risultato.
    """
    with open(out_path, 'w') as f:
        f.write('phase\taddr\treg\tval\n')
        for addr, reg, val in mode_writes:
            f.write(f'mode\t0x{addr:08x}\t0x{reg:04x}\t0x{val:04x}\n')
        for addr, reg, val in bphy_writes:
            f.write(f'bphy\t0x{addr:08x}\t0x{reg:04x}\t0x{val:04x}\n')


def emit_c_for_chip(result, chip_label, out):
    """Emette le due funzioni (mode_init + bphy_init) per UN chip.

    Per chip ∈ {default,4352,4360,43b3} pesca writes_<chip> dal result
    e produce un C body senza side-by-side. La fase bphy è chip-agnostic
    (estratta dal path generic) e identica in tutti i file.
    """
    p = lambda *a: print(*a, file=out)
    mode_writes = result[f'mode_{chip_label}'] if chip_label != 'default' \
                  else result['mode_generic']

    p('/* ================================================================')
    p(' * extract_init_acphy.py --chip {} — output per-chip'.format(chip_label))
    p(' * Sorgente: wlDSL-3580_EU.o_save (MIPS BE, DSL-3580L, chip 0x43b3)')
    p(' * Funzione: wlc_phy_init_acphy')
    p(f" * mode writes per il path \"{chip_label}\": {len(mode_writes)}")
    p(f" * bphy writes (chip-agnostic):              {len(result['bphy_writes'])}")
    p(' *')
    p(' * (d) RMW chip_id|0x100 / chip_id|0x400 non sono estraibili staticamente')
    p(' *     e non compaiono in questo file. Vedi mode_init() del legacy emit.')
    p(' * ================================================================ */')
    p('')
    p(f'static void b43_phy_ac_mode_init_{chip_label}(struct b43_wldev *dev)')
    p('{')
    if not mode_writes:
        p('\t/* nessuna write tracciata per questo path */')
    for addr, reg, val in mode_writes:
        p(f'\tb43_phy_write(dev, 0x{reg:04x}, 0x{val:04x});'
          f'  /* @{addr:#010x} */')
    p('}')
    p('')
    p('/* bphy_init: chip-agnostic (path post-radar_detect_init) */')
    p(f'static void b43_phy_ac_bphy_init_{chip_label}(struct b43_wldev *dev)')
    p('{')
    if not result['bphy_writes']:
        p('\t/* nessuna write tracciata nel range post-radar */')
    for addr, reg, val in result['bphy_writes']:
        p(f'\tb43_phy_write(dev, 0x{reg:04x}, 0x{val:04x});'
          f'  /* @{addr:#010x} */')
    p('}')


# ---------------------------------------------------------------------------
# Output C (legacy, default — invariato)
# ---------------------------------------------------------------------------

def emit_c(result):
    print("/* ================================================================")
    print(" * extract_init_acphy.py — output automatico")
    print(" * Sorgente: wlDSL-3580_EU.o_save (MIPS BE, DSL-3580L, chip 0x43b3,")
    print(" *           BCM4352-family, 2x2 — vedi README.md §re-target)")
    print(" *")
    g = result['gate_set_addr']
    r = result['radar_jalr_addr']
    print(f" * Table-write gate @{g:#010x}" if g else " * Table-write gate: non trovato")
    print(f" * radar_detect_init jalr @{r:#010x}" if r else " * radar_detect_init: non trovato")
    print(f" * phy_reg_write register: {result['PHY_WRITE_REG']}")
    print(f" * Chip-dispatch blocks trovati: {len(result['chip_dispatch_writes'])}")
    print(" * ================================================================")
    print(" *")
    print(" * SEZIONE 1: Mode-bit clears (fase 3 di op_init)")
    print(" * Da inserire in b43_phy_ac_op_init() dopo b43_phy_ac_tables_init().")
    print(" * Sequenza estratta da wlc_phy_init_acphy, sezione pre-table-lock.")
    print(" *")
    print(" * Struttura:")
    print(" *   a) 1 write costante upfront (reg 0x410)")
    print(" *   b) N write chip-dispatch: reg dipende da chip, val=0 per tutti")
    print(" *   c) 3 write costanti finali (AFE, EXTG)")
    print(" *   d) 2 RMW chip-ID-in-value (non estraibili staticamente — skip MVP)")
    print(" */")
    print()

    print("static void b43_phy_ac_mode_init(struct b43_wldev *dev)")
    print("{")
    print("\t/* (a) Write costante upfront */")

    for addr, reg, val in result['mode_generic']:
        if reg == 0x410:
            print(f"\tb43_phy_write(dev, 0x{reg:04x}, 0x{val:04x});"
                  f"  /* @{addr:#010x} */")

    print()
    print("\t/* (b) Chip-dispatch: zeroing di registri AFE/RF per pagina corretta.")
    print("\t * BCM4352 (laptop) usa pagina 0x1xxx, generic/BCM4360 usa 0x0xxx.")
    print("\t * Tutti scrivono 0 — la differenza è solo nel register address.")
    print("\t * Per il driver b43 usiamo dev->phy.ac->num_cores per scegliere,")
    print("\t * oppure leggiamo i PCI device ID. Per il MVP usiamo BCM4352.")
    print("\t */")

    cw = result['chip_dispatch_writes']
    if cw:
        print(f"\t/* {len(cw)} blocchi chip-dispatch trovati. */")
        print()
        print("#if 0  /* BCM4352 (schede laptop — reg page 0x1xxx) */")
        for blk in cw:
            r4352 = blk['reg_4352']
            if r4352 is not None:
                print(f"\tb43_phy_write(dev, 0x{r4352:04x}, 0x{blk['val']:04x});"
                      f"  /* @{blk['addr']:#010x} — 4360={_fmt(blk['reg_4360'])} generic={_fmt(blk['reg_generic'])} */")
        print("#endif")
        print()
        print("#if 0  /* Generic (reg page 0x0xxx) */")
        for blk in cw:
            rgen = blk['reg_generic']
            if rgen is not None:
                print(f"\tb43_phy_write(dev, 0x{rgen:04x}, 0x{blk['val']:04x});"
                      f"  /* @{blk['addr']:#010x} — 4352={_fmt(blk['reg_4352'])} 4360={_fmt(blk['reg_4360'])} */")
        print("#endif")
    else:
        print("\t/* chip_dispatch_writes: nessuno trovato (errore di scan) */")

    print()
    print("\t/* (c) Write costanti finali */")
    for addr, reg, val in result['mode_generic']:
        if reg != 0x410:
            if reg == 0x721:
                print(f"\t/* SALAME: 0x{reg:04x} = 0x{val:04x} appare invariante nel blob DSL-3580")
                print(f"\t * ma non verificato su secondo blob. Cross-checkare con lo stesso")
                print(f"\t * script su un blob LE (es. ASUS RT-AC66U wl_apsta.o). */")
            print(f"\tb43_phy_write(dev, 0x{reg:04x}, 0x{val:04x});"
                  f"  /* @{addr:#010x}{' — VERIFICARE su secondo blob' if reg == 0x721 else ''} */")

    print()
    print("\t/* (d) RMW con chip_id|0x100 / chip_id|0x400 — non estraibili staticamente.")
    print("\t * Il blob scrive (chip_id OR 0x100) in reg 0x72a e (chip_id OR 0x400) in 0x725.")
    print("\t * Per il MVP, questi registri rimangono al default hardware. */")
    print("}")
    print()
    print()

    # --- FASE 9: bphy_init ---
    print("/* ================================================================")
    print(" * SEZIONE 2: bphy_init (fase 9 di op_init)")
    print(" * Inserire in b43_phy_ac_bphy_init(), chiamato da b43_phy_ac_op_init()")
    print(" * se b43_current_band(dev->wl) == NL80211_BAND_2GHZ.")
    print(" *")
    print(" * Estratte dalla sezione post-wlc_phy_radar_detect_init di")
    print(" * wlc_phy_init_acphy. Valori costanti (niente chip-dispatch).")
    print(" * Queste sono le write ai filtri CCK / BPHY compat registers.")
    print(" * ================================================================ */")
    print()
    print("static void b43_phy_ac_bphy_init(struct b43_wldev *dev)")
    print("{")
    if not result['bphy_writes']:
        print("\t/* ATTENZIONE: nessuna write trovata nella fase post-radar. */")
        print("\t/* Verificare manualmente il range radar_jalr_addr in avanti. */")
    else:
        print("\t/* Sequenza estratta da wlc_phy_init_acphy post-radar_detect_init.")
        print("\t * Registri 0x33a-0x349: BPHY CCK filter coefficients per 2.4 GHz.")
        print("\t * Pattern: coppie (high_val=0x395, high_val=0x395, low_val=0x315, low_val=0x315)")
        print("\t * ripetute 4 volte (una per core/path in configurazione 3x3).")
        print("\t */")
        for addr, reg, val in result['bphy_writes']:
            print(f"\tb43_phy_write(dev, 0x{reg:04x}, 0x{val:04x});"
                  f"  /* @{addr:#010x} */")
    print("}")


def _fmt(v):
    if v is None:
        return "---"
    return f"0x{v:04x}"


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(
        description='Estrae wlc_phy_init_acphy dal blob MIPS BE.')
    ap.add_argument('disr', help='disasm objdump (wl.disr)')
    ap.add_argument('--chip', choices=('default', '4352', '4360', '43b3'),
                    help='emetti solo il path del chip indicato. '
                         'Se omesso: comportamento legacy (emit_c side-by-side).')
    ap.add_argument('--out-dir', metavar='DIR',
                    help='scrivi <tool>_output.c e <tool>_ops.tsv in DIR. '
                         'Richiede --chip. Senza --out-dir: stdout.')
    args = ap.parse_args()

    if args.out_dir and not args.chip:
        ap.error('--out-dir richiede --chip')

    insns = parse_disasm_func(args.disr, 'wlc_phy_init_acphy')
    print(f"/* wlc_phy_init_acphy: {len(insns)} istruzioni */", file=sys.stderr)

    result = analyse_init_acphy(insns)
    g = result['gate_set_addr']
    r = result['radar_jalr_addr']
    g_s = f"{g:#010x}" if g else "None"
    r_s = f"{r:#010x}" if r else "None"
    print(f"/* gate_set_addr={g_s} */", file=sys.stderr)
    print(f"/* radar_jalr_addr={r_s} */", file=sys.stderr)
    print(f"/* mode_generic: {len(result['mode_generic'])} write */", file=sys.stderr)
    print(f"/* mode_4352:    {len(result['mode_4352'])} write */", file=sys.stderr)
    print(f"/* mode_4360:    {len(result['mode_4360'])} write */", file=sys.stderr)
    print(f"/* mode_43b3:    {len(result['mode_43b3'])} write */", file=sys.stderr)
    print(f"/* chip_dispatch: {len(result['chip_dispatch_writes'])} blocchi */", file=sys.stderr)
    print(f"/* bphy_writes:  {len(result['bphy_writes'])} write */", file=sys.stderr)
    print(file=sys.stderr)

    # Modalità per-chip: un solo path proiettato.
    if args.chip:
        mode_key = 'mode_generic' if args.chip == 'default' else f'mode_{args.chip}'
        if args.out_dir:
            os.makedirs(args.out_dir, exist_ok=True)
            base = 'init_acphy_extracted'
            with open(os.path.join(args.out_dir, base + '.c'), 'w') as f:
                emit_c_for_chip(result, args.chip, f)
            write_ops_tsv(result[mode_key], result['bphy_writes'],
                          os.path.join(args.out_dir, base + '_ops.tsv'))
        else:
            emit_c_for_chip(result, args.chip, sys.stdout)
        return

    # Modalità legacy (default): comportamento invariato.
    emit_c(result)


if __name__ == '__main__':
    main()

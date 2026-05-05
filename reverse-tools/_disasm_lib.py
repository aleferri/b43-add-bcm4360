# reverse-tools/_disasm_lib.py
#
# Primitive condivise dai tool di reverse del binario MIPS BE
# wlDSL-3580_EU.o_save. Estratte da extract_radio2069_init.py per
# riusarle in nuovi tool (vedi extract_switch_radio_acphy.py).
#
# Contenuto:
#   - costanti CHIP_*              
#   - parse_func()                  parsing objdump → list[Insn]
#   - track_reg()                   simulatore lineare di register state
#   - imm() / split_ops() / branch_target()  micro-helper di parsing
#
# La trace logica completa (con chip-injection, branch decisions,
# riconoscimento helper) resta nei tool, perché ogni funzione ha
# semantica di parametro/output diversa: switch_radio_acphy ha un
# parametro `on` da proiettare, radio2069_pwron_seq no, ecc.
#
# Idiom riconosciuti in track_reg (rilevanti per i dispatch chip-id):
#   - lui rd,IMM ; addiu rd,rd,IMM       → indirizzo simbolico via reloc
#   - lui rd,IMM ; ori   rd,rd,IMM       → costante > 0xffff
#   - xori rd,rs,IMM ; sltiu rd,rd,1     → rd = (rs == IMM)  
#
# Vedi reverse-tools/README.md.

import re

# Chip ID constants (vedi reverse-tools/README.md).
# 0x43b3 è il target reale del DSL-3580L; 4360 e 4352 restano per regression
# e per leggere i dispatch espliciti che il binario fa contro quelle costanti.
CHIP_43B3 = 0x43b3   # 17331 — DSL-3580L (target attuale)
CHIP_4352 = 0x4352   # 17234
CHIP_4360 = 0x4360   # 17248 — non più target, mantenuto per regression
CHIP_4352_FAMILY = (0x4352, 0x4348, 0x4333, 0x43A2, 0x43B0, 0x43B3)

# Mappatura CLI usata da tutti i tool per --chip:
#   default = nessun chip-dispatch preso (chip_choice = None)
#   4352/4360/43b3 = inietta la costante nei lw da `acphychipid`
CHIP_CHOICE = {
    'default': None,
    '4352':    CHIP_4352,
    '4360':    CHIP_4360,
    '43b3':    CHIP_43B3,
}

# Insn = [addr:int, mnemonic:str, ops_str:str, reloc:tuple|None]
#   reloc = (rtype, sym) se la riga successiva è una R_MIPS_*; altrimenti None.

# ---------------------------------------------------------------------------
# Parsing objdump
# ---------------------------------------------------------------------------

_FUNC_HEADER = re.compile(r'^[0-9a-f]+ <')
_RELOC_LINE  = re.compile(r'\s+[0-9a-f]+:\s+(R_MIPS_\S+)\s+(\S+)')
_INSN_LINE   = re.compile(r'\s*([0-9a-f]+):\s+(\S+)(?:\s+(.*))?$')

def parse_func(disr_path, func_name):
    """Parse objdump output, ritorna le istruzioni della funzione `func_name`.

    Una "Insn" è la lista mutabile [addr, mnemonic, ops_str, reloc] dove
    reloc è la coppia (R_MIPS_*, symbol) della riga reloc immediatamente
    successiva, oppure None. È mutabile perché alcune trace devono
    riallineare dopo il fatto (raro ma succede).
    """
    lines = open(disr_path).readlines()
    start = end = None
    needle = f'<{func_name}>:'
    for i, l in enumerate(lines):
        if needle in l:
            start = i
        elif start is not None and i > start + 5 and _FUNC_HEADER.match(l):
            end = i
            break
    if start is None:
        raise ValueError(f'{func_name}: not found in {disr_path}')
    if end is None:
        end = len(lines)

    out = []
    last = None
    for l in lines[start:end]:
        m = _RELOC_LINE.match(l)
        if m and last is not None:
            if last[3] is None:
                last[3] = (m.group(1), m.group(2))
            continue
        m = _INSN_LINE.match(l)
        if m:
            insn = [int(m.group(1), 16), m.group(2),
                    (m.group(3) or '').strip(), None]
            out.append(insn)
            last = insn
    return out


# ---------------------------------------------------------------------------
# Micro-helper
# ---------------------------------------------------------------------------

def split_ops(s):
    return [x.strip() for x in s.split(',')] if s else []


def branch_target(s):
    """Estrae l'indirizzo numerico da un operando di branch tipo "0x4582c <fn+0x..>"."""
    s = s.strip()
    if '<' in s:
        s = s[:s.index('<')].strip()
    try:
        return int(s, 16)
    except ValueError:
        return None


def imm(s):
    """Parsa un immediato numerico tollerando 0x-prefix, decimali, esadecimali nudi.

    objdump emette gli immediati come decimali quando piccoli e come hex
    "0x..." quando grandi. Per IMM senza prefisso applichiamo l'euristica
    "se cifre ASCII sono valido decimale ≤ 0xffff, è decimale; altrimenti hex".
    Tollerante a None/vuoto.
    """
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
# Simulatore di register-state lineare
# ---------------------------------------------------------------------------

# Lo stato di un registro è uno tra:
#   - int: valore numerico noto (32-bit unsigned, tipicamente)
#   - ('sym',     name): l'indirizzo del simbolo `name` (post-LO16)
#   - ('sym_hi',  name): metà alta dell'indirizzo (in attesa della LO16)
#   - ('xori_eq', orig_rs, imm): risultato di `xori rd, orig_rs, IMM`
#   - ('eq_test', orig_rs, imm): post-`sltiu rd, xori, 1`, vale 1 sse orig==imm
#   - None: sconosciuto / invalidato

CALLER_SAVED = ('v0','v1','a0','a1','a2','a3',
                't0','t1','t2','t3','t4','t5','t6','t7','t8','t9')


def track_reg(state, ins):
    """Aggiorna `state` (dict reg→stato) con l'effetto dell'istruzione `ins`.

    Non gestisce branch / jalr — quella logica è del chiamante (la trace
    di tool, che decide quali percorsi seguire). Qui solo aritmetica /
    move / lui-addiu / xori-sltiu (idiom chip-id eq).
    """
    addr, mnem, ops_str, reloc = ins
    ops = split_ops(ops_str)

    if mnem == 'lui' and len(ops) == 2:
        rd, imm_s = ops
        v = imm(imm_s)
        if reloc and 'LO16' not in reloc[0]:
            # Reloc verso una *sezione* (.text/.rodata/...) → trattiamo come
            # somma simbolica con base 0: le HI/LO immediate sono già
            # l'offset reale (PIC object). Cosi' lui+addiu su .text danno
            # l'indirizzo della funzione bersaglio, risolvibile via
            # un addr→func map del binario.
            if reloc[1].startswith('.'):
                state[rd] = ((v & 0xffff) << 16) if v is not None else None
            else:
                state[rd] = ('sym_hi', reloc[1])
        else:
            state[rd] = ((v & 0xffff) << 16) if v is not None else None

    elif mnem in ('addiu', 'daddiu') and len(ops) == 3:
        rd, rs, imm_s = ops
        v = imm(imm_s)
        if reloc and 'LO16' in reloc[0] and not reloc[1].startswith('.'):
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
        # compilatore Broadcom emette su costanti ≥ 0x10000.
        rd, rs, imm_s = ops
        v = imm(imm_s)
        sv = state.get(rs)
        if isinstance(sv, int) and v is not None:
            state[rd] = (sv ^ (v & 0xffff)) & 0xffffffff
        elif v is not None:
            # rs simbolico/None: ricordiamo l'idiom per la sltiu successiva.
            state[rd] = ('xori_eq', rs, v & 0xffff)
        else:
            state[rd] = None

    elif mnem == 'sltiu' and len(ops) == 3:
        # parte 2/3: `sltiu rd, rs, 1` ⟺ rd = (rs == 0).
        # Promuoviamo a 'eq_test' se rs era un xori_eq.
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

    elif mnem in ('sw', 'sh', 'sb', 'lh', 'lb', 'lhu', 'lbu', 'lw'):
        # I load lasciano dst = None salvo casi speciali (chip-id injection)
        # che vengono fatti dal chiamante PRIMA di chiamare track_reg.
        if mnem == 'lw' and ops:
            dst = ops[0]
            if dst not in ('zero', 'sp', 'fp', 'ra', 'gp', 'at', 'k0', 'k1'):
                state[dst] = None

    elif ops:
        rd = ops[0]
        if rd not in ('zero', 'sp', 'fp', 'ra', 'gp', 'at', 'k0', 'k1'):
            state[rd] = None


# ---------------------------------------------------------------------------
# Predicati riusabili sullo stato
# ---------------------------------------------------------------------------

def is_sym_ptr(state, reg, sym_name):
    """True se `reg` punta al simbolo `sym_name` (post LO16 risolto)."""
    v = state.get(reg)
    return isinstance(v, tuple) and v[0] in ('sym',) and v[1] == sym_name


def sym_of(state, reg):
    """Ritorna il nome del simbolo se `reg` ne punta uno; altrimenti None."""
    v = state.get(reg)
    if isinstance(v, tuple) and v[0] == 'sym':
        return v[1]
    return None


def invalidate_caller_saved(state):
    for r in CALLER_SAVED:
        state[r] = None


def build_func_addr_map(disr_path):
    """Costruisce {addr: func_name} scansionando le linee header objdump.

    Permette di risolvere i puntatori a funzione costruiti via .text reloc
    (lui+addiu su .text danno un int che è l'addr della callee).
    """
    out = {}
    with open(disr_path) as f:
        for l in f:
            m = _FUNC_HEADER.match(l)
            if m:
                # Riformatto: la regex matcha solo l'inizio. Estraggo nome
                # e indirizzo da una pattern dedicata.
                m2 = re.match(r'^([0-9a-f]+) <(.+)>:', l)
                if m2:
                    out[int(m2.group(1), 16)] = m2.group(2)
    return out

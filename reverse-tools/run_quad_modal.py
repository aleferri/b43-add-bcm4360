#!/usr/bin/env python3
# run_quad_modal.py
#
# Orchestratore reverse chip-aware:
#
#   1. Rilancia ogni extract_*.py chip-aware in 4 modi
#      (chip_choice ∈ {default, 4352, 4360, 43b3}) e scrive gli
#      output in reverse-output/by-chip/<chip>/.
#
#   2. Per ogni tool produce reverse-output/by-chip/<tool>_diff.md
#      con tre tabelle:
#        - sezioni identiche su tutti e 4 i path → chip-agnostic
#        - sezioni 43b3 == default ≠ {4360,4352} → 43b3 prende default
#        - sezioni 43b3 ≠ {4360, 4352, default} → anomalo, da investigare
#
# Uso:
#   python3 reverse-tools/run_quad_modal.py /tmp/wl.disr [reverse-output]
#
# Il secondo argomento è la dir base (default: ./reverse-output). Lo script
# scrive tutto sotto <base>/by-chip/.
#
# Tool inclusi (devono supportare --chip e --out-dir):
#   - extract_init_acphy.py     → init_acphy_extracted.{c,_ops.tsv}
#   - extract_radio2069_init.py → radio2069_init_extracted.{c,_ops.tsv}
#
# Aggiungere altri tool quando saranno chip-aware: vedi TOOLS in fondo.

import os, subprocess, sys
from pathlib import Path

CHIPS = ('default', '4352', '4360', '43b3')

# Ogni entry: (script_relative, basename_output, [args_extra])
# Il basename è quello che il tool scrive in --out-dir; lo riutilizziamo
# per leggerne il TSV nel diff.
TOOLS = [
    ('extract_init_acphy.py',         'init_acphy_extracted'),
    ('extract_radio2069_init.py',     'radio2069_init_extracted'),
    ('extract_switch_radio_acphy.py', 'switch_radio_acphy_extracted'),
]


def run_tool(script_dir, script, disr_path, chip, out_dir):
    """Lancia un tool con --chip CHIP --out-dir OUT_DIR. Errore -> raise."""
    cmd = [sys.executable, str(script_dir / script), str(disr_path),
           '--chip', chip, '--out-dir', str(out_dir)]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        sys.stderr.write(f'[run_quad_modal] FAIL: {" ".join(cmd)}\n')
        sys.stderr.write(res.stderr)
        raise SystemExit(res.returncode)
    return res.stderr  # stderr informativo (op count, ecc.) per il log


def load_tsv_tuples(tsv_path):
    """Carica un file _ops.tsv come set di tuple (header escluso)."""
    tuples = set()
    with open(tsv_path) as f:
        next(f, None)  # skip header
        for line in f:
            line = line.rstrip('\n')
            if not line:
                continue
            tuples.add(tuple(line.split('\t')))
    return tuples


def categorize(per_chip_sets):
    """Classifica le tuple secondo le 3 categorie del §0.4.

    per_chip_sets: dict chip -> set[tuple]
    Ritorna 4 liste ordinate di tuple:
      - agnostic    : in tutti e 4 i path
      - takes_default: 43b3 == default, ma 4352 e/o 4360 differiscono
      - anomalous   : 43b3 assente dagli altri tre o presente solo lì
      - other       : tutto il resto (es. presente in 4352 ma non in 43b3,
                      cioè branch chip-specifici NON 43b3 — utile per audit)
    """
    all_tuples = set().union(*per_chip_sets.values())

    agnostic, takes_default, anomalous, other = [], [], [], []

    for t in sorted(all_tuples):
        in_def = t in per_chip_sets['default']
        in_52  = t in per_chip_sets['4352']
        in_60  = t in per_chip_sets['4360']
        in_b3  = t in per_chip_sets['43b3']

        if in_def and in_52 and in_60 and in_b3:
            agnostic.append(t)
        elif in_b3 and in_def and not in_52 and not in_60:
            takes_default.append(t)
        elif in_b3 and not in_def and not in_52 and not in_60:
            # 43b3 unico ad averla → anomalia rilevata
            anomalous.append(t)
        elif (not in_b3) and (in_def or in_52 or in_60):
            # 43b3 NON ha una tupla che gli altri hanno → anomalia simmetrica
            anomalous.append(t)
        else:
            other.append(t)

    return agnostic, takes_default, anomalous, other


def fmt_tuple_md(t):
    """Riga markdown leggibile da una tupla TSV."""
    return ' | '.join(t)


def write_diff_report(tool_basename, per_chip_sets, out_path):
    """Scrive <tool>_diff.md secondo lo schema del §0.4."""
    agnostic, takes_default, anomalous, other = categorize(per_chip_sets)

    counts = {chip: len(per_chip_sets[chip]) for chip in CHIPS}
    total  = len(set().union(*per_chip_sets.values()))

    lines = []
    lines.append(f'# {tool_basename} — diff per-chip')
    lines.append('')
    lines.append('Confronto del set di operazioni estratte (tuple `_ops.tsv`)')
    lines.append('attraverso i 4 path chip-aware. Ogni "sezione" qui è una')
    lines.append('singola tupla (riga del TSV); il diff è a livello di insieme,')
    lines.append('non di sequenza — l\'ordine non altera il risultato.')
    lines.append('')
    lines.append('## Sintesi')
    lines.append('')
    lines.append('| metric | valore |')
    lines.append('|---|---:|')
    for chip in CHIPS:
        lines.append(f'| op count `{chip}` | {counts[chip]} |')
    lines.append(f'| tuple uniche totali | {total} |')
    lines.append(f'| ✅ chip-agnostic (in tutti e 4) | {len(agnostic)} |')
    lines.append(f'| 🟡 43b3 == default ≠ {{4352,4360}} | {len(takes_default)} |')
    lines.append(f'| 🔴 43b3 anomalo (vedi sotto) | {len(anomalous)} |')
    lines.append(f'| ⚪ altri pattern (audit secondario) | {len(other)} |')
    lines.append('')

    def section(title, tuples, header_cols):
        lines.append('## ' + title)
        lines.append('')
        if not tuples:
            lines.append('*(nessuna)*')
            lines.append('')
            return
        lines.append('| ' + ' | '.join(header_cols) + ' |')
        lines.append('|' + '|'.join(['---'] * len(header_cols)) + '|')
        for t in tuples:
            # Padding/trim a len(header_cols)
            cells = list(t) + [''] * (len(header_cols) - len(t))
            cells = cells[:len(header_cols)]
            lines.append('| ' + ' | '.join(cells) + ' |')
        lines.append('')

    # I due tool hanno header diversi:
    #   init_acphy:  (phase, addr, reg, val)
    #   radio2069:   (addr, type, field1, field2, field3)
    arity = max((len(next(iter(s), ())) for s in per_chip_sets.values() if s),
                default=4)
    if arity == 4:
        header_cols = ['phase', 'addr', 'reg', 'val']
    else:
        header_cols = ['addr', 'type', 'field1', 'field2', 'field3']

    section('✅ Verified chip-agnostic',
            agnostic, header_cols)
    section('🟡 43b3 prende il path default (ok per regression)',
            takes_default, header_cols)
    section('🔴 43b3 anomalo — da investigare',
            anomalous, header_cols)
    if other:
        section('⚪ Altri pattern (audit secondario, NON 43b3-specifici)',
                other, header_cols)

    lines.append('---')
    lines.append('')
    lines.append('Generato da `reverse-tools/run_quad_modal.py`. Per')
    lines.append('rigenerare:')
    lines.append('')
    lines.append('```sh')
    lines.append('mips-linux-gnu-objdump -dr --no-show-raw-insn -M no-aliases \\')
    lines.append('    wlDSL-3580_EU.o_save > /tmp/wl.disr')
    lines.append('python3 reverse-tools/run_quad_modal.py /tmp/wl.disr')
    lines.append('```')

    with open(out_path, 'w') as f:
        f.write('\n'.join(lines) + '\n')


def main():
    if len(sys.argv) < 2:
        print(f'uso: {sys.argv[0]} <wl.disr> [out_base=reverse-output]',
              file=sys.stderr)
        sys.exit(1)

    disr_path = Path(sys.argv[1]).resolve()
    if not disr_path.is_file():
        sys.exit(f'disr non trovato: {disr_path}')

    out_base = Path(sys.argv[2] if len(sys.argv) > 2 else 'reverse-output').resolve()
    by_chip  = out_base / 'by-chip'
    script_dir = Path(__file__).resolve().parent

    # Step 1: §0.3 — rilanciare ogni tool sui 4 chip.
    for chip in CHIPS:
        chip_dir = by_chip / chip
        chip_dir.mkdir(parents=True, exist_ok=True)
        for script, _ in TOOLS:
            stderr_log = run_tool(script_dir, script, disr_path, chip, chip_dir)
            print(f'[ok] {script} --chip {chip} → {chip_dir}', file=sys.stderr)

    # Step 2: §0.4 — diff report.
    for script, basename in TOOLS:
        per_chip_sets = {}
        for chip in CHIPS:
            tsv = by_chip / chip / (basename + '_ops.tsv')
            per_chip_sets[chip] = load_tsv_tuples(tsv)
        diff_path = by_chip / (basename + '_diff.md')
        write_diff_report(basename, per_chip_sets, diff_path)
        print(f'[ok] diff report → {diff_path}', file=sys.stderr)

    print(f'[done] output sotto {by_chip}', file=sys.stderr)


if __name__ == '__main__':
    main()

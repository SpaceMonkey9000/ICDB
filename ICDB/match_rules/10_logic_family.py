"""74/54-series and 4000-series CMOS: same function number = same pinout family.

74HC14, SN74LS14N, DM7414, 9N14, DL014 and 74ACT14 all belong to 74xx14;
CD4060B, HEF4060, MC14060 to 4060; 74LVC1G14 to 74xx1G14 (single-gate parts
are their own family). 54xx parts are kept separate from 74xx. 4000-series
numbers need a CMOS prefix (see _logic_names.RX_40): TP4056 (charger), UPC4558
(op-amp) and LM4040 (reference) are not grouped.
Proposes components that share a family with any device already on the diagram.
"""
from pathlib import Path
import sys
from _shipped_helpers import load_sibling, compact

names = load_sibling('_logic_names.py', '_icdb_logic_names')

RULE_ID = 'logic-family-v1'
LABEL = 'Logic family'
RANK = 2


def prepare(ctx):
    by_family = {}
    for c in ctx.components.values():
        k = names.group_key(c['part_number'] or '')
        if k:
            by_family.setdefault(k, []).append(c['id'])
    first, families, on_diagram = {}, {}, {}
    for s in ctx.sources:
        ident = (s.catalog_id, s.pinout_id)
        first.setdefault(ident, s.source_id)          # one proposer per diagram -> no duplicate rows
        on_diagram.setdefault(ident, set()).add(compact(s.name))
        k = names.group_key(s.device)
        if k:
            families.setdefault(ident, {}).setdefault(k, s.device)
    ctx.cache['logic-family'] = (by_family, first, families, on_diagram)


def candidates(source, ctx):
    by_family, first, families, on_diagram = ctx.cache['logic-family']
    ident = (source.catalog_id, source.pinout_id)
    if first.get(ident) != source.source_id:
        return []
    out = []
    for k, example in sorted(families.get(ident, {}).items()):
        for cid in by_family.get(k, []):
            if compact(ctx.components[cid]['part_number']) in on_diagram[ident]:
                continue                                  # exact rule already covers it
            out.append((cid, f'Same logic function {names.heading(k)} as {example} on this diagram.'))
    return out

"""74HC40xx / 74HC45xx <-> CD40xx / CD45xx cross-family proposals.

Most high-speed CMOS 74HC4xxx parts (74HC4066, 74HC4051, 74HC4511, 74HC40106)
use the pinout of the CD4xxx part with the same number, but not all do and the
supply range differs. The proposal is always flagged CAUTION, so it never lands
in "Ready to accept"; confirm against the datasheet.
"""
from pathlib import Path
import re
import sys
from _shipped_helpers import load_sibling, compact

names = load_sibling('_logic_names.py', '_icdb_logic_names')

RULE_ID = 'cmos-cross-family-v1'
LABEL = 'CMOS cross family'
RANK = 3
CAUTION = 'Most 74HC40xx parts are pin-compatible with CD40xx; confirm against the datasheet'

_NUMBER = re.compile(r'4[05]\d{2,3}')


def _other(k):
    """('74', '4066') -> ('40', '4066') and back; None for anything else."""
    if not k or not _NUMBER.fullmatch(k[1]):
        return None
    return {'74': ('40', k[1]), '40': ('74', k[1])}.get(k[0])


def prepare(ctx):
    by_family = {}
    for c in ctx.components.values():
        k = names.group_key(c['part_number'] or '')
        if _other(k):
            by_family.setdefault(k, []).append(c['id'])
    first, families, on_diagram = {}, {}, {}
    for s in ctx.sources:
        ident = (s.catalog_id, s.pinout_id)
        first.setdefault(ident, s.source_id)          # one proposer per diagram
        on_diagram.setdefault(ident, set()).add(compact(s.name))
        k = names.group_key(s.device)
        if _other(k):
            families.setdefault(ident, {}).setdefault(k, s.device)
    ctx.cache['cmos-cross-family'] = (by_family, first, families, on_diagram)


def candidates(source, ctx):
    by_family, first, families, on_diagram = ctx.cache['cmos-cross-family']
    ident = (source.catalog_id, source.pinout_id)
    if first.get(ident) != source.source_id:
        return []
    present = set(families.get(ident, {}))
    out = []
    for k, example in sorted(families.get(ident, {}).items()):
        other = _other(k)
        if other in present:
            continue                      # the diagram already has that family; logic-family covers it
        for cid in sorted(by_family.get(other, [])):
            if compact(ctx.components[cid]['part_number']) in on_diagram[ident]:
                continue
            out.append((cid, f'Cross-family {names.heading(other)} for {example} on this diagram.'))
    return out


def review(row, ctx):
    if row['rule'] == RULE_ID:
        return ('caution', CAUTION)
    return None

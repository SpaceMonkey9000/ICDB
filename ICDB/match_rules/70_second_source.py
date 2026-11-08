"""Curated second sources: parts that are pin-compatible in the same package.

    NE555 = SA555 = SE555 = LM555 = TLC555 = LMC555 = ICM7555 = TS555
    LM358 = LM258 = LM158 = LM2904        LM324 = LM224 = LM124 = LM2902
    LM393 = LM293 = LM193 = LM2903        LM339 = LM239 = LM139 = LM2901
    LM78xx = L78xx = MC78xx = UA78xx = KA78xx   (xx = 05 06 08 09 10 12 15 18 24)

A component's base is the longest group member its compacted part number starts
with, followed by a non-digit or the end (NE555P -> NE555, LM2904DR -> LM2904,
but LM3580 is not LM358). Components in the same group as a device on the
diagram - but with a different base - are proposed. Every proposal is CAUTION:
compatible in the same package only; check the package and datasheet.
"""
from pathlib import Path
import sys
from _shipped_helpers import compact

RULE_ID = 'second-source-v1'
LABEL = 'Second source'
RANK = 2
CAUTION = 'Known second source; confirm the package and datasheet pinout'

GROUPS = [
    ('NE555', 'SA555', 'SE555', 'LM555', 'TLC555', 'LMC555', 'ICM7555', 'TS555'),
    ('LM358', 'LM258', 'LM158', 'LM2904'),
    ('LM324', 'LM224', 'LM124', 'LM2902'),
    ('LM393', 'LM293', 'LM193', 'LM2903'),
    ('LM339', 'LM239', 'LM139', 'LM2901'),
] + [tuple(p + '78' + v for p in ('LM', 'L', 'MC', 'UA', 'KA'))
     for v in ('05', '06', '08', '09', '10', '12', '15', '18', '24')]

GROUP_OF = {member: i for i, g in enumerate(GROUPS) for member in g}
_BY_LENGTH = sorted(GROUP_OF, key=lambda m: (-len(m), m))


def base(part):
    c = compact(part)
    for member in _BY_LENGTH:
        if c.startswith(member) and not c[len(member):len(member) + 1].isdigit():
            return member
    return None


def prepare(ctx):
    by_group = {}
    for c in ctx.components.values():
        b = base(c['part_number'])
        if b:
            by_group.setdefault(GROUP_OF[b], []).append((b, c['id']))
    first, bases, on_diagram = {}, {}, {}
    for s in ctx.sources:
        ident = (s.catalog_id, s.pinout_id)
        first.setdefault(ident, s.source_id)
        on_diagram.setdefault(ident, set()).add(compact(s.name))
        b = base(s.name)
        if b:
            bases.setdefault(ident, {}).setdefault(b, s.device)
    ctx.cache['second-source'] = ({g: sorted(v) for g, v in by_group.items()}, first, bases, on_diagram)


def candidates(source, ctx):
    by_group, first, bases, on_diagram = ctx.cache['second-source']
    ident = (source.catalog_id, source.pinout_id)
    if first.get(ident) != source.source_id:
        return []
    present = bases.get(ident, {})
    out, seen = [], set()
    for b, example in sorted(present.items()):
        for other, cid in by_group.get(GROUP_OF[b], []):
            if other in present or cid in seen:
                continue                  # same base: exact / prefix-suffix rules cover it
            if compact(ctx.components[cid]['part_number']) in on_diagram[ident]:
                continue
            seen.add(cid)
            out.append((cid, f'Known second source: {example} ≈ {ctx.components[cid]["part_number"]} '
                             '(same package only)'))
    return out


def review(row, ctx):
    if row['rule'] == RULE_ID:
        return ('caution', CAUTION)
    return None

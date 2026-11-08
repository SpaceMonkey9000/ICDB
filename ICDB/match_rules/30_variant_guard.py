"""Block a suggestion when suffix variants of the target part have different
pinouts in the same package. "Different" means a supply, ground or NC pin is in
a different place (VIO/EN/NC on pin 5, V+/V- swapped); pure naming differences
(1OUT vs OUTA) do not block.

Example: component TJA1051 with diagrams TJA1051T (pin 5 NC), TJA1051T/3
(pin 5 VIO) and TJA1051T/E (pin 5 EN) in SOIC-8. Accepting any of them for the
bare TJA1051 would be a guess, so all three are blocked with the differing
pins listed. Link the exact variant (e.g. add TJA1051T/3 to the database).

When only ONE suffixed variant is in the library and its suffix has a '/'
segment (TJA1051T/3), the other variants are unknown: the suggestion gets a
CAUTION instead of a block.
Exact-name and manual matches are not affected.
"""
from pathlib import Path
import bisect
import sys
from _shipped_helpers import compact
import rule_api

RULE_ID = 'variant-guard-v1'
LABEL = 'Variant guard'
RANK = 3


def prepare(ctx):
    by_package = {}
    for s in ctx.sources:
        if s.project:
            by_package.setdefault(s.package, []).append((compact(s.name), s.name, s.project))
    ctx.cache['variant-guard'] = {p: sorted(v, key=lambda x: (x[0], x[1])) for p, v in by_package.items()}
    ctx.cache['variant-guard-keys'] = {p: [x[0] for x in v] for p, v in ctx.cache['variant-guard'].items()}


def review(row, ctx):
    if row['rule'] in ('exact-v1', 'manual-v1'):
        return None
    target = compact(row['target'])
    if not target or compact(row['source']) == target:
        return None
    items = ctx.cache['variant-guard'].get(row['package'], [])
    keys = ctx.cache['variant-guard-keys'].get(row['package'], [])
    i = bisect.bisect_left(keys, target)
    variants, names = {}, set()
    while i < len(keys) and keys[i].startswith(target):
        part, name, project = items[i]
        rest = part[len(target):]
        if rest and not (target[-1].isdigit() and rest[0].isdigit()):
            variants.setdefault(rule_api.class_signature(project), (name, project))
            names.add(name)
        i += 1
    if len(variants) < 2:
        if len(names) == 1:
            only = next(iter(names))
            if '/' in only:
                return ('caution', f'Only the suffixed variant {only} is in the library; suffixes may change pins')
        return None
    named = sorted(variants.values(), key=lambda v: v[0])
    diff = rule_api.differing_pins([p for _, p in named], by_class=True)
    shown = '; '.join(f"pin {n} = {' / '.join(v)}" for n, v in list(diff.items())[:4])
    return ('block', f"Variants of {row['target']} have different {row['package']} pinouts "
                     f"({', '.join(n for n, _ in named[:5])}): {shown}. Link the exact variant instead.")

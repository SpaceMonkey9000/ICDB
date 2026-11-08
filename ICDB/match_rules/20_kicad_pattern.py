"""KiCad symbol names use lower-case x as a wildcard: STM32F405RGTx, 93AAxxA,
MAX3490xPA. Propose components whose part number fits the pattern, including a
shorter base number (STM32F405 -> STM32F405RGTx). The variant guard blocks it
when the variants that fit have different pinouts.
"""
from pathlib import Path
import re
import sys
from _shipped_helpers import compact

RULE_ID = 'kicad-pattern-v1'
LABEL = 'KiCad pattern'
RANK = 2


def _pattern(device):
    if 'x' not in device:
        return None
    p = re.sub(r'[^0-9A-Zx]', '', re.sub(r'[a-wyz]', lambda m: m.group(0).upper(), device))
    return p if len(p) > 4 and 'x' not in p[:3] else None


def prepare(ctx):
    index = {}
    for c in ctx.components.values():
        k = compact(c['part_number'])
        if len(k) >= 4:
            index.setdefault(k[:3], []).append((k, c['id']))
    ctx.cache['kicad-pattern'] = index


def _fits(pattern, part):
    """part matches the start of pattern, x = any single character"""
    return len(part) <= len(pattern) and all(p == 'x' or p == c for p, c in zip(pattern, part))


def candidates(source, ctx):
    pattern = _pattern(source.device)
    if not pattern:
        return []
    out = []
    for part, cid in ctx.cache['kicad-pattern'].get(pattern[:3], []):
        if part == compact(source.name):
            continue
        if _fits(pattern, part):
            rest = pattern[len(part):]
            if rest and part[-1].isdigit() and rest[0].isdigit():
                continue                        # NE555 must not match NE5551x
            out.append((cid, f'{part} fits KiCad name pattern {source.device}.'))
    return out

"""Power-pin sanity for family suggestions on dual-row packages.

Standard 74xx / 4000-series DIP, SOIC and TSSOP parts have V+ on the last pin
(N) and V- on pin N/2. Some well-known members do not: 7473 / 7476 / 7490
(VCC pin 4/5, GND 11/13), CD4049 / CD4050 (VDD pin 1, VSS pin 8). A family or
prefix/suffix suggestion onto such a definition - or from such a definition onto
a standard part - is a likely mismatch, so the row gets a CAUTION naming the
actual supply pins.

Applies to logic-family, CMOS cross-family and 4000-number suggestions, and to
prefix/suffix / shared-number suggestions when the source or target is a 74xx /
4000-series logic name (op-amps, timers and regulators legitimately use other
supply pins).
"""
from pathlib import Path
import sys
from _shipped_helpers import load_sibling, row_project, package_family
import rule_api

names = load_sibling('_logic_names.py', '_icdb_logic_names')

RULE_ID = 'power-pin-sanity-v1'
LABEL = 'Power pins'
RANK = 3

FAMILY_RULES = {'logic-family-v1', 'cmos-cross-family-v1', '4000-prefix-v1'}
VARIANT_RULES = {'prefix-suffix-v1', 'prefix-shared-number-v1'}
PACKAGES = {'DIP', 'PDIP', 'SOIC', 'SO', 'TSSOP', 'SOP', 'SSOP'}


def review(row, ctx):
    rule = row['rule']
    if rule not in FAMILY_RULES and rule not in VARIANT_RULES:
        return None
    if rule in VARIANT_RULES and not (names.group_key_loose(row['source'] or '')
                                      or names.group_key_loose(row['target'] or '')):
        return None
    project = row_project(row, ctx)
    fam, count = package_family(project, row['package'])
    if fam not in PACKAGES or not count or count % 2:
        return None
    pins = rule_api.pins(project)
    plus = sorted((n for n, v in pins.items() if rule_api.pin_class(v) == 'V+'), key=rule_api.pin_sort_key)
    minus = sorted((n for n, v in pins.items() if rule_api.pin_class(v) == 'V-'), key=rule_api.pin_sort_key)
    if not plus or not minus:
        return None                    # 90_definition_quality reports missing supplies
    if count in plus and count // 2 in minus:
        return None
    show = lambda ns: ', '.join(f'{n} ({pins[n]})' for n in ns)
    return ('caution', f'Non-standard supply pins for a {fam}-{count} logic part: V+ on pin {show(plus)}, '
                       f'V- on pin {show(minus)} (usually {count} / {count // 2}). Check this is the same part.')

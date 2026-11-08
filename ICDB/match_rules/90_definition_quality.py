"""Definition quality: flag pin tables that look incomplete or placeholder.

CAUTION when the definition
  * has no supply (V+) or no ground (V-) pin, in IC packages (DIP, SOIC, TSSOP,
    SSOP, MSOP, QFP, QFN, DFN, PLCC ...) - transistors and regulators are not checked;
  * only has NC / P<n> / numeric placeholder names;
  * repeats the same signal name on several pins (NC, supplies and pads may repeat);
  * has a pin count that does not match the number of distinct pins in its table
    (an EP / TAB pad listed in the table counts as a pin).

Applies to pin-library definitions (Pinout manager -> Library); the ICPin batch
review keeps the pin data of the imported catalog as is.
"""
from collections import Counter
from pathlib import Path
import re
import sys
from _shipped_helpers import row_project, package_family
import rule_api
from pinout import exposed_pad

RULE_ID = 'definition-quality-v1'
LABEL = 'Definition quality'
RANK = 3

IC_PACKAGES = ('DIP', 'PDIP', 'SOIC', 'SO', 'SOP', 'TSSOP', 'SSOP', 'MSOP', 'VSSOP', 'QFP', 'LQFP', 'TQFP',
               'QFN', 'VQFN', 'WQFN', 'DFN', 'SON', 'PLCC')


def problems(project, package=''):
    pin_list = (project or {}).get('pins') or []
    fam, count = package_family(project, package)
    found = []
    names = [str(p.get('name') or '').strip() for p in pin_list]
    classes = [rule_api.pin_class(n) for n in names]
    pad = exposed_pad(project or {})
    if pad: classes.append(rule_api.pin_class(pad['name']))
    if names and all(c == 'NC' or re.fullmatch(r'(?i)P?\d+', n) or not n for n, c in zip(names, classes)):
        found.append('all pins are NC or placeholders (P1, P2 ...)')
    elif fam in IC_PACKAGES:
        missing = [k for k, label in (('V+', 'supply'), ('V-', 'ground')) if k not in classes]
        if missing:
            found.append('no ' + ' or '.join({'V+': 'supply (V+)', 'V-': 'ground (V-)'}[k] for k in missing) + ' pin')
    dup = Counter(rule_api.canonical_pin(n) for n, c in zip(names, classes) if c == 'SIG' and n)
    repeated = sorted(n for n, k in dup.items() if k > 1)
    if repeated:
        found.append('repeated signal names ' + ', '.join(repeated[:4]))
    numbers = {rule_api.pin_number(p.get('number')) for p in pin_list}
    if count is not None and count != len(numbers):
        found.append(f'pin count {count} but {len(numbers)} pins in the table')
    return found


def review(row, ctx):
    if 'definition_id' not in row:
        return None
    memo = ctx.cache.setdefault('definition-quality', {})
    k = (row['definition_id'], row['package'])
    if k not in memo:
        memo[k] = problems(row_project(row, ctx), row['package'])
    found = memo[k]
    if found:
        return ('caution', 'Definition quality: ' + '; '.join(found) + '. Check the pin table.')
    return None

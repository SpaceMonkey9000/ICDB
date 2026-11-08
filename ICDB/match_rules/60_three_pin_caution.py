"""Three-pin (and tab) packages: SOT-23-3, SOT-89, SOT-223, TO-92, TO-220, TO-252,
TO-247. Pin order is a vendor / family choice, not a standard: TL431 in SOT-23
exists with REF/K/A in different orders, LM317 is ADJ-OUT-IN while LM337 is
ADJ-IN-OUT, transistors swap E/B/C. Every non-exact suggestion is CAUTION, and so
is an exact name when either manufacturer is unknown or they differ.
"""
from pathlib import Path
import sys
from _shipped_helpers import row_project, package_family, row_manufacturers

RULE_ID = 'three-pin-caution-v1'
LABEL = 'Three-pin caution'
RANK = 3

TEXT = ('Three-pin pinouts vary by vendor/family (e.g. TL431 SOT-23, LM317 vs LM337); '
        'check the datasheet')
PREFIXES = ('SOT-89', 'SOT89', 'SOT-223', 'SOT223', 'TO-92', 'TO92', 'TO-220', 'TO220',
            'TO-252', 'TO252', 'TO-247', 'TO247')


def applies(project, package):
    fam, count = package_family(project, package)
    fam = fam.replace(' ', '')
    if fam.startswith(('SOT-23', 'SOT23')):
        rest = fam[len('SOT-23') if fam.startswith('SOT-23') else len('SOT23'):].lstrip('-')
        return (rest in ('', '3')) and (count is None or count <= 3)
    return fam.startswith(PREFIXES)


def review(row, ctx):
    if row['rule'] == 'manual-v1':
        return None
    if not applies(row_project(row, ctx), row['package']):
        return None
    if row['rule'] == 'exact-v1':
        a, b = row_manufacturers(row)
        if a and b and a == b:
            return None
    return ('caution', TEXT)

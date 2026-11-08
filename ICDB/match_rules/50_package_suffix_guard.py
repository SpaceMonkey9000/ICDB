"""Package code in the component's part number vs the definition's package.

The suffix after the base number of the definition's device name is decoded with
common vendor ordering-code schemes:

    TI / onsemi / ST:  N, P = DIP; D, DR = SOIC; PW = TSSOP; DGK = VSSOP (MSOP);
                       DBV = SOT-23; DCK = SC-70; NS = SOP; DB = SSOP; RGT, RTE = QFN
    NXP / Nexperia:    N = DIP; D = SO; PW = TSSOP; BQ = DHVQFN; GW = SC-88; GV = SC-74
    Microchip:         /P = DIP; /SN, /SM = SOIC; /ST = TSSOP; /MS = MSOP; /OT, /TT = SOT-23;
                       /MF, /MC = DFN; /ML, /MQ = QFN   (e.g. MCP6002-I/P, MCP1700T-3302E/TT)
    Maxim:             xPA = DIP-8; xSA = SOIC-8; xUA = uMAX-8 (MSOP)   (MAX485CPA+, MAX485ESA)

CAUTION when the decoded family differs from the definition's (LM358N vs a SOIC-8
diagram); BLOCK when it is a different pin-count class (SOT-23 part, SOIC-8
diagram). Anything not clearly one of these codes is ignored.
"""
from pathlib import Path
import re
import sys
from _shipped_helpers import compact, row_project, package_family

RULE_ID = 'package-suffix-guard-v1'
LABEL = 'Package suffix'
RANK = 3

TI = {'N': 'DIP', 'P': 'DIP', 'D': 'SOIC', 'DR': 'SOIC', 'DT': 'SOIC', 'PW': 'TSSOP', 'PWR': 'TSSOP',
      'PWT': 'TSSOP', 'DGK': 'MSOP', 'DGKR': 'MSOP', 'DGKT': 'MSOP', 'DBV': 'SOT-23', 'DBVR': 'SOT-23',
      'DBVT': 'SOT-23', 'DCK': 'SC-70', 'DCKR': 'SC-70', 'DCKT': 'SC-70', 'NS': 'SOP', 'NSR': 'SOP',
      'DB': 'SSOP', 'DBR': 'SSOP', 'RGT': 'QFN', 'RGTR': 'QFN', 'RGTT': 'QFN', 'RTE': 'QFN',
      'RTER': 'QFN', 'RTET': 'QFN', 'BQ': 'QFN', 'GW': 'SC-70', 'GV': 'SOT-23'}
MICROCHIP = {'P': 'DIP', 'SN': 'SOIC', 'SM': 'SOIC', 'ST': 'TSSOP', 'MS': 'MSOP', 'OT': 'SOT-23',
             'MF': 'DFN', 'MC': 'DFN', 'ML': 'QFN', 'MQ': 'QFN', 'TT': 'SOT-23'}
MAXIM = {'PA': 'DIP', 'SA': 'SOIC', 'UA': 'MSOP'}

# Definition package name -> family used for comparison
ALIASES = {'PDIP': 'DIP', 'DIL': 'DIP', 'SO': 'SOIC', 'SOP': 'SOP', 'VSSOP': 'MSOP', 'MSOP': 'MSOP',
           'UMAX': 'MSOP', 'SOT23': 'SOT-23', 'SC70': 'SC-70', 'SC88': 'SC-70', 'SOT363': 'SC-70',
           'SC74': 'SOT-23', 'SOT457': 'SOT-23', 'DHVQFN': 'QFN', 'VQFN': 'QFN', 'WQFN': 'QFN',
           'SON': 'DFN', 'WSON': 'DFN', 'VSON': 'DFN'}
SMALL = {'SOT-23', 'SC-70'}          # 3..6 pins
LARGE = {'DIP', 'SOIC', 'SOP', 'TSSOP', 'MSOP', 'SSOP', 'QFN', 'DFN', 'QFP'}


def _family(name):
    n = re.sub(r'[\s_]+', '', (name or '').upper())
    n = re.sub(r'-?\d+$', '', n) if not re.fullmatch(r'SOT-?23|SC-?70|SC-?88|SC-?74', n) else n
    plain = n.replace('-', '')
    if plain in ALIASES:
        return ALIASES[plain]
    for fam in ('SOT-23', 'SC-70'):
        if plain == fam.replace('-', ''):
            return fam
    return n if n in LARGE or n in SMALL else ''


def _suffix(source, target):
    """Original-text suffix of target after the base number of source, or None."""
    m = re.match(r'^(.*\d)', compact(source))
    if not m:
        return None
    core = m.group(1)
    t = re.sub(r'\s+', '', (target or '').upper())
    ct = compact(t)
    i = ct.find(core)
    if i < 0 or i > 3 or (i and not ct[:i].isalpha()):
        return None
    # map compact position back to the original string
    seen, pos = 0, 0
    while pos < len(t) and seen < i + len(core):
        if re.match(r'[0-9A-Z]', t[pos]):
            seen += 1
        pos += 1
    rest = t[pos:]
    if rest[:1].isdigit():
        return None                    # LM3580 is not LM358
    return rest


def decode(source, target):
    """Package family encoded in target's suffix, or None when not clearly coded."""
    rest = _suffix(source, target)
    if not rest:
        return None
    m = re.fullmatch(r'[-A-Z0-9]{0,8}/([A-Z]{1,2})(?:[0-9A-Z]{0,4})?', rest)
    if m and m.group(1) in MICROCHIP:                       # -I/P, T-E/OT, -I/SN
        return MICROCHIP[m.group(1)]
    if re.match(r'^(MAX|ICL|DS)', compact(target)):
        m = re.fullmatch(r'[CEAIM](PA|SA|UA)(?:\+|\+T|-T|T)?', rest)
        if m:
            return MAXIM[m.group(1)]
    clean = re.sub(r'(?:[,.]\d+|-Q100|G4|E4|Q1)$', '', rest)
    if clean in TI:
        return TI[clean]
    if clean[:1] in 'ABCI' and clean[1:] in TI and clean[1:]:     # grade letter: TL072CDR, LM358AD
        return TI[clean[1:]]
    return None


def review(row, ctx):
    source, target = row['source'], row['target']
    if compact(source) == compact(target):
        return None
    decoded = decode(source, target)
    if not decoded:
        return None
    fam, count = package_family(row_project(row, ctx), row['package'])
    have = _family(fam)
    if not have or have == decoded:
        return None
    if (decoded in SMALL) != (have in SMALL) and (decoded in SMALL or have in SMALL):
        return ('block', f'{target} is coded as {decoded}; this definition is {row["package"]}. '
                         'Different package class - link a matching definition.')
    return ('caution', f'{target} is coded as {decoded}; this definition is {row["package"]}. '
                       'Confirm the package before accepting.')

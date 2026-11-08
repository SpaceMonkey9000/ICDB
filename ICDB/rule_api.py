"""Pluggable matching rules for the pinout matcher.

A rule is a Python file in one of these folders (files starting with '_' are
ignored, rules load in file-name order):

    <ICDB application folder>/match_rules/     shipped rules
    <DATA folder>/match_rules/                  your own / site rules

A rule module defines:

    RULE_ID = 'logic-family-v1'   # stored with every decision; bump it when the rule changes
    LABEL   = 'Logic family'      # shown in the Match column and the rule filter
    RANK    = 2                   # 0 exact ... 4 none; lower sorts first

and any of these optional hooks:

    def prepare(ctx): ...                      # once per scan
    def candidates(source, ctx): -> iterable of (component_id, reason)
    def review(row, ctx): -> None | ('caution', text) | ('block', text)

`candidates` proposes extra targets for one ICPin source record. Proposals
always need review: a rule can never link anything by itself.
`review` sees every candidate row (from built-in and plugin rules); see
match_rules/README.md for the row fields. 'block'
makes the row Blocked with the given reason; 'caution' keeps it actionable but
it starts unchecked and appears in the Caution queue.

A rule that raises (on load or in any hook), or returns a result of the wrong
shape, is skipped for the scan and named in the scan's rule errors.

Site rules (DATA/match_rules) are Python code on a shared folder, so each file
runs only after a person on this computer has trusted that exact file content
(SHA-256). The list lives outside DATA, in
<LOCALAPPDATA>/IC_Tools/trusted_match_rules.json; editing a site rule needs
trusting it again. Shipped rules (next to the application) are always used.

Both hooks must depend only on the database and ctx (never on which rows are
currently visible), so a rescan before Accept gives identical results.
"""
import hashlib
import importlib.util
import json
import os
import re
import sys
from pathlib import Path

from icpin_bundle import key
from pinout import exposed_pad

APP_RULES = Path(__file__).resolve().parent / 'match_rules'


class Context:
    """Read-only view handed to rules. Built once per scan."""

    def __init__(self, db, components, exact, sources, mappings):
        self.db = db
        self.components = components          # id -> {id, part_number, manufacturer}
        self.exact = exact                    # KEY(part_number) -> [component, ...]
        self.sources = sources                # list of Source
        self.mappings = mappings              # (catalog_id, pinout_id) -> imported diagram row
        self.cache = {}                       # free scratch space for rules
        self._functions = None

    def function(self, component_id):
        """Function / description text of a component ('' if none)."""
        if self._functions is None:
            cols = {r[1] for r in self.db.execute('PRAGMA table_info(components)')}
            self._functions = ({r[0]: r[1] or '' for r in self.db.execute('SELECT id,function FROM components')}
                               if 'function' in cols else {})
        return self._functions.get(component_id, '')


class Source:
    __slots__ = ('catalog_id', 'source_id', 'pinout_id', 'device', 'name', 'manufacturer',
                 'package', 'project', 'record')

    def __init__(self, row, package_name):
        rec = json.loads(row['record_json'])
        self.catalog_id, self.source_id, self.pinout_id = row['catalog_id'], row['source_id'], row['pinout_id']
        self.record = rec
        self.device = rec['device']                 # as written (keeps lower-case x wildcards)
        self.name = key(rec['device'])
        self.manufacturer = rec['manufacturer']
        self.package = package_name(rec['package'])
        self.project = json.loads(row['project_json']) if row['project_json'] else {}
        if exposed_pad(self.project) and self.package == package_name(f"{self.project['package']}-{self.project['count']}"):
            self.package += '-EP'


# ---- pin comparison helpers shared by rules --------------------------------

_POWER = {'VCC': 'V+', 'VDD': 'V+', 'V+': 'V+', '+VCC': 'V+', 'VS': 'V+', '+VS': 'V+',
          'GND': 'V-', 'VSS': 'V-', 'V-': 'V-', '0V': 'V-', 'VEE': 'V-'}


_ACTIVE_LOW = (
    re.compile(r'^~\{([^{}]+)\}$'),         # KiCad overbar ~{CS}
    re.compile(r'^[/~!]([^/~!].*)$'),        # /CS ~CS !CS
    re.compile(r'^(.+?)(?:#|_N|\*)$'),         # CS# CS_N CS*
)


def _active_low(name):
    """'/CS', '~{CS}', '~CS', 'CS#', 'CS_N', 'nCS' -> '/CS' (case-sensitive test for nCS
    so EN, IN, GEN are not affected; a bare trailing N is never stripped)."""
    s = re.sub(r'\s+', '', name or '')
    if re.fullmatch(r'n[A-Z][A-Z0-9_]*', s):
        return '/' + s[1:]
    for rx in _ACTIVE_LOW:
        m = rx.match(s)
        if m:
            return '/' + m.group(1).lstrip('/~!')
    return s


def canonical_pin(name):
    """1A == A1, VDD == VCC, VSS == GND, /CS == ~{CS} == CS# == nCS == CS_N,
    case and spaces ignored."""
    s = _active_low(name).upper().replace('~', '/')
    if s in _POWER:
        return _POWER[s]
    m = re.fullmatch(r'(/?)(\d+)([A-Z]+)', s) or re.fullmatch(r'(/?)([A-Z]+)(\d+)', s)
    if m:
        a, b, c = m.groups()
        letters, digits = (c, b) if b.isdecimal() else (b, c)
        return f'{a}{letters}{digits}'
    return s


def pin_number(value):
    """Numeric pin numbers as int (sortable), others ('EP', 'A1', 'TAB') as str."""
    if isinstance(value, int):
        return value
    text = str(value).strip()
    return int(text) if text.isdecimal() else text


def pin_sort_key(number):
    """Sort key for mixed int / str pin numbers: numbers first, then names."""
    return (isinstance(number, str), number)


def _sorted_pins(items):
    return tuple(sorted(items, key=lambda t: (pin_sort_key(t[0]), t[1])))


def pins(project):
    result = {pin_number(p['number']): p['name'] for p in (project or {}).get('pins', [])}
    pad = exposed_pad(project or {})
    if pad: result[pin_number(pad['number'])] = pad['name']
    return result


def canonical_signature(project):
    return _sorted_pins((n, canonical_pin(v)) for n, v in pins(project).items())


_SUPPLY_EXTRA = re.compile(r'^(VIO|VCCIO|VDDIO|VBAT|VBB|VS|VIN|VCC\d|VDD\d|AVCC|AVDD|DVCC|DVDD|VREG|VLOGIC|VL|'
                           r'VDDA|VDDD|VCCA|VCCB|VDDQ|VCCQ|VPOS|\+V|\+VDD|\+\d+V\d*)$')
_GROUND_EXTRA = re.compile(r'^(AGND|DGND|PGND|SGND|GND\d|VSSA|VSSD|AVSS|DVSS|VSSIO|-VS|-VCC|-VDD|-V|VNEG|-VEE)$')
_PAD = {'EP', 'PAD', 'EPAD', 'TAB', 'THERMALPAD', 'EXPOSEDPAD'}
_NC = {'NC', 'N.C.', 'N/C', 'DNC', 'NU'}


def pin_class(name):
    """Coarse electrical class: V+, V-, NC, PAD (exposed pad / tab) or SIG (any
    signal). Used to tell a real pinout difference (a supply or NC pin moved) from
    a naming difference."""
    s = re.sub(r'\s+', '', (name or '').upper())
    if s in _PAD:
        return 'PAD'
    c = canonical_pin(name)
    if c in ('V+', 'V-'):
        return c
    if s in _NC:
        return 'NC'
    if _SUPPLY_EXTRA.match(s):
        return 'V+'
    if _GROUND_EXTRA.match(s):
        return 'V-'
    return 'SIG'


def class_signature(project):
    return _sorted_pins((n, pin_class(v)) for n, v in pins(project).items())


def differing_pins(projects, by_class=False):
    """Pins whose (canonical) name differs between projects -> {pin: [names...]}"""
    maps = [pins(p) for p in projects]
    numbers = sorted(set().union(*maps), key=pin_sort_key) if maps else []
    out = {}
    for n in numbers:
        names = [m.get(n, '') for m in maps]
        f = pin_class if by_class else canonical_pin
        if len({f(x) for x in names}) > 1:
            out[n] = names
    return out


# ---- guarded hook calls ------------------------------------------------------

class RuleFailure(Exception):
    """A rule raised, or returned a result of the wrong shape. The scan drops the rule and recomputes."""
    def __init__(self, rule, hook, exc):
        self.rule = rule
        self.message = f'{rule.path.name} {hook}: {type(exc).__name__}: {exc}'
        super().__init__(self.message)


def _check_candidates(value):
    if value is None: return []
    if isinstance(value, (str, bytes, dict)): raise TypeError('candidates must return an iterable of (component_id, reason) pairs')
    out = []
    for item in value:
        if not isinstance(item, (tuple, list)) or len(item) != 2:
            raise TypeError(f'candidate {item!r} is not a (component_id, reason) pair')
        cid, why = item
        if isinstance(cid, bool) or not isinstance(cid, int):
            raise TypeError(f'component_id {cid!r} is not an integer')
        out.append((cid, str(why)))
    return out


def _check_review(value):
    if not value: return None
    if not isinstance(value, (tuple, list)) or len(value) != 2 or value[0] not in ('block', 'caution') or not isinstance(value[1], str):
        raise TypeError(f"review must return None, ('caution', text) or ('block', text), not {value!r}")
    return tuple(value)


_CHECKS = {'candidates': _check_candidates, 'review': _check_review}


def call(rule, hook, *args):
    """Run one rule hook; any exception or malformed result becomes RuleFailure."""
    try:
        value = getattr(rule, hook)(*args)
        check = _CHECKS.get(hook)
        return check(value) if check else value
    except Exception as exc:
        raise RuleFailure(rule, hook, exc) from exc


# ---- loader ----------------------------------------------------------------

class Rule:
    def __init__(self, module, path):
        self.module, self.path = module, path
        self.RULE_ID = getattr(module, 'RULE_ID')
        self.LABEL = getattr(module, 'LABEL', self.RULE_ID)
        self.RANK = int(getattr(module, 'RANK', 3))
        self.prepare = getattr(module, 'prepare', None)
        self.candidates = getattr(module, 'candidates', None)
        self.review = getattr(module, 'review', None)


_cache = {}


# ---- site-rule trust (per computer, outside the shared DATA folder) -----------

def trust_file():
    from shared_data import location_file
    return location_file().parent / 'trusted_match_rules.json'


def _trust_state():
    try:
        value = json.loads(trust_file().read_text('utf-8-sig'))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def _file_sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def site_rule_files(data_root):
    folder = Path(data_root) / 'match_rules' if data_root else None
    if not folder or not folder.is_dir(): return []
    return [p for p in sorted(folder.glob('*.py')) if not p.name.startswith('_')]


def undecided_site_rules(data_root):
    """[(path, sha256)] of site rules this computer has neither trusted nor declined."""
    state = _trust_state(); known = set(state.get('trusted', {})) | set(state.get('declined', {}))
    out = []
    for path in site_rule_files(data_root):
        try: sha = _file_sha(path)
        except OSError: continue
        if sha not in known: out.append((path, sha))
    return out


def record_trust(items, trusted):
    """Remember a decision for these exact files ([(path, sha256)])."""
    state = _trust_state()
    for k in ('trusted', 'declined'): state.setdefault(k, {})
    for path, sha in items:
        state['trusted' if trusted else 'declined'][sha] = Path(path).name
        state['declined' if trusted else 'trusted'].pop(sha, None)
    target = trust_file(); target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_name(f'{target.name}.{os.getpid()}.tmp')
    temp.write_text(json.dumps(state, indent=2), 'utf-8'); temp.replace(target)


def confirm_site_rules(data_root, parent=None):
    """Ask once per new/changed site rule file. Returns False if the user cancels the run."""
    items = undecided_site_rules(data_root)
    if not items: return True
    from tkinter import messagebox
    names = '\n'.join(f'  {p.name}  (SHA-256 {sha[:12]}…)' for p, sha in items[:15])
    answer = messagebox.askyesnocancel('Site match rules',
        f'{len(items)} match rule file(s) in the shared DATA folder are new or changed:\n\n{names}\n\n'
        'Match rules are Python programs and run with your Windows permissions. Only trust them if you know who wrote them.\n\n'
        'Yes: trust these exact files on this computer.\nNo: run without them.\nCancel: do not run.', parent=parent)
    if answer is None: return False
    record_trust(items, bool(answer))
    return True


def _register_shipped_helpers():
    """Shipped rules import _shipped_helpers by name; provide it without putting any folder on sys.path."""
    if '_shipped_helpers' in sys.modules: return
    spec = importlib.util.spec_from_file_location('_shipped_helpers', APP_RULES / '_shipped_helpers.py')
    module = importlib.util.module_from_spec(spec)
    sys.modules['_shipped_helpers'] = module
    try: spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop('_shipped_helpers', None); raise


def load_rules(data_root=None):
    """Return (rules, errors). Modules are cached per file modification time.
    Site rules load only when this computer trusts their exact content."""
    _register_shipped_helpers()
    folders = [(APP_RULES, False)] + ([(Path(data_root) / 'match_rules', True)] if data_root else [])
    rules, errors, seen = [], [], set()
    state = _trust_state() if data_root else {}
    trusted, declined = state.get('trusted', {}), state.get('declined', {})
    for folder, site in folders:
        if not folder.is_dir():
            continue
        for path in sorted(folder.glob('*.py')):
            if path.name.startswith('_'):
                continue
            try:
                if site:
                    sha = _file_sha(path)
                    if sha in declined: continue
                    if sha not in trusted:
                        errors.append(f'{path.name}: site rule not trusted on this computer; skipped (run matching again to review it)')
                        continue
                stamp = (str(path), path.stat().st_mtime_ns) + ((sha,) if site else ())
                if stamp not in _cache:
                    name = f'icdb_rule_{abs(hash(str(path)))}'
                    spec = importlib.util.spec_from_file_location(name, path)
                    module = importlib.util.module_from_spec(spec)
                    sys.modules[name] = module
                    spec.loader.exec_module(module)
                    _cache[stamp] = Rule(module, path)
                rule = _cache[stamp]
                if rule.RULE_ID in seen or rule.RULE_ID in BUILTIN_RULE_IDS:
                    raise ValueError(f'duplicate rule id {rule.RULE_ID}')
                seen.add(rule.RULE_ID)
                rules.append(rule)
            except Exception as exc:          # a broken site rule must not stop matching
                errors.append(f'{path.name}: {exc}')
    return rules, errors


BUILTIN_RULE_IDS = {'exact-v1', '4000-prefix-v1', 'manual-v1', 'none-v1', 'prefix-suffix-v1',
                    'prefix-shared-number-v1'}

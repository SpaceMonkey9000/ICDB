"""Reviewed, additive matching. Family rules propose candidates, never equivalence."""
import hashlib
import json
import re
import uuid
from icpin_bundle import Bundle, UNKNOWN, encoded, key
from pinouts import package_name
import rule_api

RULE_VERSION = '4000-prefix-v1'
VARIANT_RULE = 'prefix-suffix-v1'
# Second-source prefixes: a shared number with two of these prefixes (LM358 / KA358,
# NE555 / SA555) is a plausible alternate source; any other shared number (BC547 / LM547)
# is only a coincidence until someone confirms it. Shared by both matchers.
SECOND_SOURCE_PREFIXES = {'LM','TL','NE','SA','SE','KA','UA','MC','L','AZ','LMV','TS','NJM','RC','KIA'}
EXACT_MFR_CAUTION = 'Different manufacturer; exact part name — confirm the datasheet pinout'


def shared_number_caution(source, target):
    """Caution text for a 'Shared number only' pair: never pre-checked, always confirmed by a person."""
    a, b = part_tokens(source)[1], part_tokens(target)[1]
    if a in SECOND_SOURCE_PREFIXES and b in SECOND_SOURCE_PREFIXES:
        return f'Second-source prefixes {a}/{b}; confirm the datasheet pinout'
    return 'Shared number only; accept only if the datasheet pinout is the same'
SCHEMA = '''
CREATE TABLE IF NOT EXISTS pinout_review_session(id INTEGER PRIMARY KEY CHECK(id=1), state TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS pinout_verified_mappings(
 id INTEGER PRIMARY KEY, source_name TEXT NOT NULL, source_manufacturer TEXT NOT NULL,
 package TEXT NOT NULL, signature TEXT NOT NULL, target_name TEXT NOT NULL,
 target_manufacturer TEXT NOT NULL, source_url TEXT NOT NULL, source_page TEXT NOT NULL,
 operation_id TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1,
 UNIQUE(source_name,source_manufacturer,package,signature,target_name,target_manufacturer));
CREATE TABLE IF NOT EXISTS icpin_sources(
 catalog_id TEXT NOT NULL, source_id TEXT NOT NULL, pinout_id TEXT NOT NULL,
 record_json TEXT NOT NULL, project_json TEXT NOT NULL,
 PRIMARY KEY(catalog_id,source_id));
CREATE TABLE IF NOT EXISTS icpin_source_catalogs(catalog_id TEXT PRIMARY KEY, sha256 TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS pinout_match_decisions(
 decision_key TEXT PRIMARY KEY, catalog_id TEXT NOT NULL, source_id TEXT NOT NULL,
 component_id INTEGER NOT NULL, package TEXT NOT NULL, rule_version TEXT NOT NULL,
 evidence TEXT NOT NULL, decision TEXT NOT NULL, reason TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS pinout_match_operations(
 id TEXT PRIMARY KEY, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
 action TEXT NOT NULL, count INTEGER NOT NULL DEFAULT 0, undone INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS pinout_match_created(
 link_id INTEGER PRIMARY KEY, operation_id TEXT NOT NULL, decision_key TEXT NOT NULL);
CREATE TRIGGER IF NOT EXISTS pinout_match_manual_update AFTER UPDATE OF component_id,asset_id,package,pin_count,label ON pinout_links
 WHEN OLD.component_id IS NOT NEW.component_id OR OLD.asset_id IS NOT NEW.asset_id OR OLD.package IS NOT NEW.package
  OR OLD.pin_count IS NOT NEW.pin_count OR OLD.label IS NOT NEW.label
 BEGIN DELETE FROM pinout_match_created WHERE link_id=OLD.id; END;
CREATE TRIGGER IF NOT EXISTS pinout_match_manual_delete AFTER DELETE ON pinout_links
 BEGIN DELETE FROM pinout_match_created WHERE link_id=OLD.id; END;
'''


def migrate_triggers(db):
    """0.4.8: ownership is released only by a real association edit, not default changes."""
    row = db.execute("SELECT sql FROM sqlite_master WHERE type='trigger' AND name='pinout_match_manual_update'").fetchone()
    if row and 'WHEN OLD.component_id' not in row[0]:
        db.executescript('DROP TRIGGER IF EXISTS pinout_match_manual_update;')


def digest(value):
    return hashlib.sha256(encoded(value).encode('utf-8')).hexdigest()


def remember_sources(store, bundle):
    """Called inside bundle import transaction, including unresolved device rows."""
    db = store.db
    db.execute('DELETE FROM icpin_sources WHERE catalog_id=?', (bundle.catalog_id,))
    for record in bundle.devices:
        sid = digest([key(record['device']), key(record['manufacturer']),
                      package_name(record['package']), record['pinout_id']])
        project = bundle.pinouts.get(record['pinout_id'], {}).get('project', {})
        db.execute('INSERT OR REPLACE INTO icpin_sources VALUES(?,?,?,?,?)',
                   (bundle.catalog_id, sid, record['pinout_id'], encoded(record), encoded(project)))
    db.execute('INSERT OR REPLACE INTO icpin_source_catalogs VALUES(?,?)', (bundle.catalog_id, bundle.sha))


def recover_sources(store):
    """Upgrade old imports from checksum-verified retained bundles only."""
    issues = []
    for row in store.db.execute('SELECT * FROM icpin_bundles').fetchall():
        saved = store.db.execute('SELECT sha256 FROM icpin_source_catalogs WHERE catalog_id=?', (row['catalog_id'],)).fetchone()
        if saved and saved[0] == row['sha256']:
            continue
        try:
            bundle = Bundle(store.path({'path': row['bundle_path']}))
            if bundle.sha != row['sha256'] or bundle.catalog_id != row['catalog_id']:
                raise ValueError('Retained source bundle identity/checksum differs')
            with store.db:
                remember_sources(store, bundle)
        except (OSError, ValueError) as exc:
            issues.append(f"{row['catalog_id']}: {exc}. Reimport the original ICPin bundle.")
    return issues


def pin_signature(project):
    from pinout import exposed_pad
    identity = [project.get('count'), sorted((p['number'], p['name'].strip().casefold(), str(p.get('role') or '').casefold()) for p in project.get('pins', []))]
    pad = exposed_pad(project)
    if pad: identity.append(['exposed_pad', pad])
    return digest(identity)


def family_number(name):
    m = re.fullmatch(r'(?:CD|HEF|HCF|MC1|HD1)(4\d{3})[A-Z]*', key(name))
    return m.group(1) if m else None


def part_tokens(name):
    """Preserve every digit run, leading zero and intervening character."""
    name = key(name)
    if not re.fullmatch(r'[A-Z0-9_./+\-]+', name): return None
    runs = list(re.finditer(r'[0-9]+', name))
    if not runs: return None
    return (tuple(m.group() for m in runs), name[:runs[0].start()],
            tuple(name[a.end():b.start()] for a,b in zip(runs,runs[1:])),
            name[runs[-1].end():])


def nearby_prefix(a, b):
    if not a or not b: return False
    if a.endswith(b) or b.endswith(a): return True
    if abs(len(a)-len(b)) > 1: return False
    if len(a) == len(b): return sum(x != y for x,y in zip(a,b)) <= 1
    short, long = sorted((a,b), key=len)
    return any(long[:i]+long[i+1:] == short for i in range(len(long)))


def variant_match(source, target):
    a, b = part_tokens(source), part_tokens(target)
    if not a or not b or a[0] != b[0] or key(source) == key(target): return None
    digits, prefix, middle, suffix = a
    changes = []
    for label, old, new in [('prefix',prefix,b[1]),('internal letters/separators',' / '.join(middle),' / '.join(b[2])),('suffix',suffix,b[3])]:
        if old != new: changes.append(f"{label} {old or '∅'} → {new or '∅'}")
    if prefix == b[1] and middle == b[2]:
        rank, label = 1, 'Suffix variant'
    elif sum(map(len,digits)) >= 3 and middle == b[2] and nearby_prefix(prefix, b[1]):
        rank, label = 2, 'Prefix variant'
    else:
        # Short numeric codes are too broad unless their textual base is similar.
        if sum(map(len,digits)) < 3: return None
        rank, label = 3, 'Shared number only'
    reason = f"{label}; numeric identifier {' / '.join(digits)}; " + '; '.join(changes) + '; review required'
    return rank, label, reason


def candidate_order(row):
    return (row['rank'], key(row['source']), key(row['target']),
            key(row['target_manufacturer']), row['package'], row['catalog_id'],
            row['source_id'], row['component_id'] or -1)


def scan(store, manual=None, source_scope=None, integrity_cache=None, force_integrity=False):
    """Pure read after recovery. Indexed identities; no per-candidate filesystem IO."""
    db = store.db
    exact, families, by_id, numeric = {}, {}, {}, {}
    for row in db.execute("SELECT id,coalesce(part_number,'') AS part_number,manufacturer FROM components"):
        c = dict(row); by_id[c['id']] = c
        if key(c['part_number']): exact.setdefault(key(c['part_number']), []).append(c)
        n = family_number(c['part_number'])
        if n: families.setdefault(n, []).append(c)
        tokens = part_tokens(c['part_number'])
        if tokens: numeric.setdefault(tokens[0], []).append(c)
    mappings = {(r['catalog_id'], r['pinout_id']): dict(r) for r in db.execute('''
        SELECT p.*,a.path,a.sha256 FROM icpin_pinouts p JOIN pinout_assets a ON a.id=p.asset_id''')}
    # Session-only cache. Commits force byte verification of all affected diagrams.
    source_rows = list(db.execute('SELECT * FROM icpin_sources ORDER BY catalog_id,source_id'))
    wanted = {(r['catalog_id'], r['pinout_id']) for r in source_rows
              if source_scope is None or (r['catalog_id'], r['source_id']) in source_scope}
    cache = integrity_cache if integrity_cache is not None else {}
    for ident, p in mappings.items():
        if ident not in wanted: continue
        try:
            path = store.path(p); stat = path.stat()
            token = (str(path), stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns, p['imported_sha256'], p['sha256'])
            if force_integrity or token not in cache:
                cache[token] = hashlib.sha256(path.read_bytes()).hexdigest() == p['imported_sha256'] == p['sha256']
            p['file_ok'] = cache[token]
        except OSError:
            p['file_ok'] = False
    links = {(r['component_id'], r['asset_id'], r['package']): dict(r) for r in db.execute('SELECT * FROM pinout_links')}
    referenced_components = {cid for cid, _, _ in links}
    signatures = {p['asset_id']: pin_signature(json.loads(p['project_json'])) for p in mappings.values()}
    linked_signatures = {}
    for (cid, aid, pkg), link in links.items():
        if aid in signatures: linked_signatures.setdefault((cid, pkg), set()).add(signatures[aid])
    sources = source_rows
    source_signatures = {}
    for src in sources:
        rec = json.loads(src['record_json'])
        if src['project_json'] != '{}':
            group = (src['catalog_id'], key(rec['device']), key(rec['manufacturer']), package_name(rec['package']))
            source_signatures.setdefault(group, set()).add(pin_signature(json.loads(src['project_json'])))
    decisions = {r['decision_key']: dict(r) for r in db.execute('SELECT * FROM pinout_match_decisions')}
    manual_targets = {}
    for d in decisions.values():
        if d['rule_version'] == 'manual-v1':
            manual_targets.setdefault((d['catalog_id'], d['source_id']), set()).add(d['component_id'])
    verified = {}
    for v in db.execute('SELECT * FROM pinout_verified_mappings WHERE active=1'):
        identity = (v['source_name'], v['source_manufacturer'], v['package'], v['signature'])
        verified.setdefault(identity, set()).add((v['target_name'], v['target_manufacturer']))
    manual_list = [] if manual is None else ([manual] if isinstance(manual, tuple) else manual)
    # Pluggable rules (match_rules folders). They see every source, not just the scope.
    data_root = getattr(store, 'root', None)
    rules, load_errors = rule_api.load_rules(data_root)
    failures = []

    def run(rules, errors):
        ctx = rule_api.Context(db, by_id, exact, [rule_api.Source(r, package_name) for r in source_rows], mappings)
        ctx.errors = errors
        for rule in rules:
            if rule.prepare: rule_api.call(rule, 'prepare', ctx)
        plugin = {r.RULE_ID: r for r in rules}
        plugin_reason = {}
        source_by_id = {(s.catalog_id, s.source_id): s for s in ctx.sources}
        # Pre-pass over ALL sources (scope-independent): plugin proposals, and the
        # (diagram, component) pairs they claim so broad built-in variant
        # suggestions don't repeat them from other sources of the same diagram.
        proposals, claimed = {}, set()
        for s in ctx.sources:
            for c in exact.get(s.name, []):            # already an exact name on this diagram
                claimed.add((s.catalog_id, s.pinout_id, c['id']))
            for rule in rules:
                if not rule.candidates: continue
                for cid, why in rule_api.call(rule, 'candidates', s, ctx):
                    if cid in by_id:
                        proposals.setdefault((s.catalog_id, s.source_id), []).append((rule, cid, str(why)))
                        claimed.add((s.catalog_id, s.pinout_id, cid))
        result = []
        for src in sources:
            if source_scope is not None and (src['catalog_id'], src['source_id']) not in source_scope: continue
            record = json.loads(src['record_json']); name = key(record['device'])
            p = mappings.get((src['catalog_id'], src['pinout_id']))
            candidates = [(c, 'exact-v1') for c in exact.get(name, [])]
            if re.fullmatch(r'4\d{3}', name):
                candidates += [(c, RULE_VERSION) for c in families.get(name, [])]
            targets = set(manual_targets.get((src['catalog_id'], src['source_id']), ()))
            for entry in manual_list:
                if (src['catalog_id'], src['source_id']) == tuple(entry[:2]): targets.add(entry[2])
            identity = (name, key(record['manufacturer']), package_name(record['package']),
                        pin_signature(json.loads(src['project_json'])))
            approved = verified.get(identity, set())
            for target_name, target_mfr in approved:
                targets.update(c['id'] for c in exact.get(target_name, [])
                               if key(c['manufacturer']) == target_mfr and not variant_match(name, c['part_number']))
            for cid in sorted(targets):
                c = by_id.get(cid)
                if c and not any(x['id'] == c['id'] for x, _ in candidates): candidates.append((c, 'manual-v1'))
            # Preserve manual/legacy rule identities and decisions before broad suggestions.
            seen = {c['id'] for c,_ in candidates}
            for rule, cid, why in proposals.get((src['catalog_id'], src['source_id']), []):
                if cid not in seen:
                    candidates.append((by_id[cid], rule.RULE_ID)); seen.add(cid)
                    plugin_reason[(src['catalog_id'], src['source_id'], cid)] = why
            tokens = part_tokens(name)
            if tokens:
                for c in numeric.get(tokens[0], []):
                    if (src['catalog_id'], src['pinout_id'], c['id']) in claimed: continue
                    if c['id'] not in seen and variant_match(name, c['part_number']):
                        candidates.append((c, VARIANT_RULE)); seen.add(c['id'])
            if not candidates: candidates = [(None, 'none-v1')]
            for c, rule in candidates:
                pkg = package_name(record['package']); blocked = ''
                if not p: blocked = 'No imported diagram; unresolved ICPin record.'
                elif pkg != p['package']: blocked = 'Source package differs from diagram.'
                elif src['project_json'] != p['project_json']: blocked = 'Source pin data differs from imported diagram.'
                elif not p['file_ok']: blocked = 'Managed diagram missing or modified; restore/reimport before matching.'
                group = (src['catalog_id'], name, key(record['manufacturer']), pkg)
                if len(source_signatures.get(group, ())) > 1:
                    blocked = 'Conflicting source pin assignments for the same device/package.'
                if c and p and linked_signatures.get((c['id'], pkg), set()) - {signatures[p['asset_id']]}:
                    blocked = 'Pin assignments differ from an existing generated reference for this device/package.'
                pre_caution = ''
                if c and record['manufacturer'].strip().casefold() not in UNKNOWN and c['manufacturer'].strip() and record['manufacturer'].strip().casefold() != c['manufacturer'].strip().casefold():
                    # Second sources share exact names (LM358 TI / ST): caution, as in the library matcher.
                    if rule == 'exact-v1': pre_caution = EXACT_MFR_CAUTION
                    else: blocked = 'Manufacturer conflict.'
                if c and p:
                    existing = links.get((c['id'], p['asset_id'], pkg))
                    if existing and existing['pin_count'] not in (None, p['pin_count']): blocked = 'Existing association pin count conflicts with diagram.'
                unique_exact = False
                if rule == 'exact-v1':
                    pool = exact[name]
                    mfr = record['manufacturer'].strip().casefold()
                    compatible = [v for v in pool if mfr in UNKNOWN or not v['manufacturer'].strip() or v['manufacturer'].strip().casefold() == mfr]
                    unique_exact = len(compatible) == 1
                if rule in plugin:
                    rank, match_kind = plugin[rule].RANK, plugin[rule].LABEL
                else:
                    rank, match_kind = {'exact-v1':(0,'Exact'), RULE_VERSION:(2,'4000 family'), 'manual-v1':(2,'Manual'), 'none-v1':(4,'No candidate'), VARIANT_RULE:(3,'Variant')}[rule]
                reason = plugin_reason.get((src['catalog_id'], src['source_id'], c['id'] if c else None), '') + ' Review required.' if rule in plugin else {'exact-v1': 'Exact part identity' if unique_exact else 'Exact name; ambiguous database identity', RULE_VERSION: 'Generic 4xxx + CD/HEF/HCF/MC1/HD1 prefix; alphabetic suffix retained; review required', 'manual-v1': 'Explicit manual target; review required', 'none-v1': 'No candidate under current rules', VARIANT_RULE:''}[rule]
                if rule == VARIANT_RULE: rank, match_kind, reason = variant_match(name, c['part_number'])
                if rule == VARIANT_RULE and match_kind == 'Shared number only' and not pre_caution:
                    pre_caution = shared_number_caution(name, c['part_number'])
                if pre_caution and not blocked: reason = f'CAUTION: {pre_caution} | {reason}'
                dk = digest([src['catalog_id'], src['source_id'], c['id'] if c else None, pkg, rule])
                reusable = bool(c and (key(c['part_number']), key(c['manufacturer'])) in approved)
                evidence = digest([record, src['project_json'], c, p, unique_exact] + (['verified-pair-v1'] if reusable else []))
                decision = decisions.get(dk)
                decision = decision['decision'] if decision and decision['evidence'] == evidence else ''
                linked = bool(c and p and (c['id'], p['asset_id'], pkg) in links)
                status = 'Blocked' if blocked else 'Linked' if linked else 'Rejected' if decision == 'reject' else 'Unmatched' if not c else 'Exact' if rule == 'exact-v1' and unique_exact else 'Review'
                result.append(dict(catalog_id=src['catalog_id'], source_id=src['source_id'], pinout_id=src['pinout_id'],
                    source=record['device'], source_manufacturer=record['manufacturer'], target=c['part_number'] if c else '',
                    target_manufacturer=c['manufacturer'] if c else '', component_id=c['id'] if c else None,
                    asset_id=p['asset_id'] if p else None, path=p['path'] if p else '', package=pkg,
                    pin_count=p['pin_count'] if p else '', rank=rank, match_kind=match_kind, rule=rule, decision_key=dk, evidence=evidence,
                    reason=blocked or reason, status=status, verified=reusable, caution='' if blocked else pre_caution,
                    has_reference=bool(c and c['id'] in referenced_components),
                    notes=record['notes'], source_url=record['source_url'], source_page=record['source_page']))
        # Review hooks: block or flag rows (CAN transceivers, variant conflicts...).
        review_rules = [r for r in rules if r.review]
        for row in result:
            if row['status'] not in {'Exact', 'Review', 'Rejected'}: row['caution'] = ''
            row['plugin'] = row['rule'] in plugin
            if row['status'] not in {'Exact', 'Review', 'Rejected'} or not row['component_id']:
                continue
            for rule in review_rules:
                verdict = rule_api.call(rule, 'review', row, ctx)
                if not verdict: continue
                kind, text = verdict
                if kind == 'block':
                    row['status'], row['reason'] = 'Blocked', text
                    break
                if kind == 'caution' and not row['caution']:
                    row['caution'] = text
                    row['reason'] = f"CAUTION: {text} | {row['reason']}"
        return result

    while True:
        # A rule that raises or returns a malformed result is dropped and the whole scan is
        # recomputed without it, so no partial output of a broken rule remains (as in library_matcher).
        rule_errors = list(load_errors) + failures
        try:
            result = run(rules, rule_errors)
            break
        except rule_api.RuleFailure as failure:
            failures.append(failure.message)
            rules = [r for r in rules if r is not failure.rule]
    scan.rule_errors = rule_errors
    return sorted(result, key=candidate_order)


def apply(store, reviewed, action='accept', remember=False):
    if action not in {'accept', 'reject'}: raise ValueError('Invalid decision')
    if not reviewed: return None, 0
    db = store.db
    if db.in_transaction: raise ValueError('Finish current database operation first')
    try:
        db.execute('BEGIN IMMEDIATE')
        scope = {(r['catalog_id'], r['source_id']) for r in reviewed}
        manual = [(r['catalog_id'], r['source_id'], r['component_id']) for r in reviewed if r['rule']=='manual-v1']
        current = {r['decision_key']: r for r in scan(store, manual, source_scope=scope, force_integrity=True)}
        for old in reviewed:
            latest = current.get(old['decision_key'])
            # Reference presence is display metadata; another package may be linked independently.
            if latest is None or {k:v for k,v in latest.items() if k!='has_reference'} != {k:v for k,v in old.items() if k!='has_reference'}:
                raise ValueError('Source, target or link changed after review. Rescan before applying.')
            if old['status'] not in {'Exact', 'Review', 'Rejected'}:
                raise ValueError('Select only actionable candidate rows.')
        if action == 'accept':
            batch_signatures = {}
            for row in reviewed:
                project = db.execute('SELECT project_json FROM icpin_pinouts WHERE asset_id=?', (row['asset_id'],)).fetchone()[0]
                scope = (row['component_id'], row['package'])
                batch_signatures.setdefault(scope, set()).add(pin_signature(json.loads(project)))
            if any(len(v) > 1 for v in batch_signatures.values()):
                raise ValueError('Selected batch contains conflicting pin assignments for one device/package.')
        op = str(uuid.uuid4()); count = 0
        db.execute('INSERT INTO pinout_match_operations(id,action) VALUES(?,?)', (op, action))
        for row in {r['decision_key']: r for r in reviewed}.values():
            db.execute('INSERT OR REPLACE INTO pinout_match_decisions VALUES(?,?,?,?,?,?,?,?,?)',
                (row['decision_key'], row['catalog_id'], row['source_id'], row['component_id'], row['package'], row['rule'], row['evidence'], action, row['reason']))
            if action == 'accept':
                cid, aid, pkg = row['component_id'], row['asset_id'], row['package']
                if db.execute('SELECT 1 FROM pinout_links WHERE component_id=? AND asset_id=? AND package=?', (cid, aid, pkg)).fetchone(): continue
                first = not db.execute('SELECT 1 FROM pinout_links WHERE component_id=?', (cid,)).fetchone()
                lid = db.execute('INSERT INTO pinout_links(component_id,asset_id,package,pin_count,is_default) VALUES(?,?,?,?,?)', (cid, aid, pkg, row['pin_count'], int(first))).lastrowid
                db.execute('INSERT INTO pinout_match_created VALUES(?,?,?)', (lid, op, row['decision_key']))
            count += 1
        if action == 'accept' and remember:
            for row in reviewed:
                src = db.execute('SELECT project_json FROM icpin_sources WHERE catalog_id=? AND source_id=?',
                                 (row['catalog_id'], row['source_id'])).fetchone()
                db.execute('''INSERT INTO pinout_verified_mappings
                    (source_name,source_manufacturer,package,signature,target_name,target_manufacturer,source_url,source_page,operation_id)
                    VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(source_name,source_manufacturer,package,signature,target_name,target_manufacturer)
                    DO UPDATE SET active=1,source_url=excluded.source_url,source_page=excluded.source_page,operation_id=excluded.operation_id WHERE pinout_verified_mappings.active=0''',
                    (key(row['source']),key(row['source_manufacturer']),row['package'],pin_signature(json.loads(src[0])),
                     key(row['target']),key(row['target_manufacturer']),row['source_url'],row['source_page'],op))
        db.execute('UPDATE pinout_match_operations SET count=? WHERE id=?', (count, op))
        db.commit(); return op, count
    except Exception:
        db.rollback(); raise


def undo(store, operation_id):
    """Ownership is invalidated when a link is edited or deleted through any writer."""
    db = store.db
    if db.in_transaction: raise ValueError('Finish current database operation first')
    try:
        db.execute('BEGIN IMMEDIATE')
        op = db.execute("SELECT * FROM pinout_match_operations WHERE id=? AND action='accept' AND undone=0", (operation_id,)).fetchone()
        if not op: raise ValueError('Operation unavailable or already undone')
        rows = db.execute('''SELECT l.*,m.decision_key FROM pinout_match_created m JOIN pinout_links l ON l.id=m.link_id WHERE m.operation_id=?''', (operation_id,)).fetchall()
        for r in rows:
            db.execute('DELETE FROM pinout_links WHERE id=?', (r['id'],))
            db.execute("DELETE FROM pinout_match_decisions WHERE decision_key=? AND decision='accept'", (r['decision_key'],))
        # Only devices whose newly-created default was removed need a replacement default.
        for cid in {r['component_id'] for r in rows if r['is_default']}:
            if not db.execute('SELECT 1 FROM pinout_links WHERE component_id=? AND is_default=1', (cid,)).fetchone():
                db.execute('UPDATE pinout_links SET is_default=1 WHERE id=(SELECT min(id) FROM pinout_links WHERE component_id=?)', (cid,))
        db.execute('UPDATE pinout_verified_mappings SET active=0 WHERE operation_id=?', (operation_id,))
        db.execute('UPDATE pinout_match_operations SET undone=1 WHERE id=?', (operation_id,))
        db.commit(); return len(rows)
    except Exception:
        db.rollback(); raise

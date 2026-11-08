"""ICDB 0.7: editable pin data, persistent decisions and selective publication."""
from collections import defaultdict, Counter
from contextlib import closing, nullcontext
from dataclasses import asdict
from pathlib import Path
import copy
import getpass
import hashlib
import json
import socket
import sqlite3
import uuid

import pinout as _pinout
from pinout import Project, Pin, diagram, check_text, ROLES, exposed_pad, project_label
from pinouts import package_name
from icpin_bundle import UNKNOWN


class BatchDecisionError(ValueError):
    """All failed selections, collected before any decision is written."""
    def __init__(self, issues, selected_count):
        self.issues = issues
        self.selected_count = selected_count
        details = [f"{i['part']} ({i['package']}), proposed {i['proposed']}: {i['reason']}" for i in issues]
        super().__init__(f"Cannot accept {len(issues)} of {selected_count} selected links. No changes made.\n\n" + '\n\n'.join(details))

class _UndoConflict(Exception):
    def __init__(self, op_id, label, issues):
        super().__init__(label)
        self.op_id, self.label, self.issues = op_id, label, issues

SCHEMA = '''
CREATE TABLE IF NOT EXISTS pl_definitions(
 id INTEGER PRIMARY KEY AUTOINCREMENT, signature TEXT NOT NULL UNIQUE,
 project_json TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 1,
 edited INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS pl_sources(
 namespace TEXT NOT NULL, external_id TEXT NOT NULL,
 definition_id INTEGER NOT NULL REFERENCES pl_definitions(id),
 imported_json TEXT NOT NULL, devices_json TEXT NOT NULL,
 PRIMARY KEY(namespace,external_id));
CREATE INDEX IF NOT EXISTS pl_source_definition ON pl_sources(definition_id);
CREATE TABLE IF NOT EXISTS pl_conflicts(
 namespace TEXT NOT NULL, external_id TEXT NOT NULL, incoming_json TEXT NOT NULL,
 PRIMARY KEY(namespace,external_id));
CREATE TABLE IF NOT EXISTS pl_matches(
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 component_id INTEGER NOT NULL REFERENCES components(id) ON DELETE CASCADE,
 definition_id INTEGER NOT NULL REFERENCES pl_definitions(id),
 status TEXT NOT NULL DEFAULT 'Suggested', rule TEXT NOT NULL, reason TEXT NOT NULL,
 blocked TEXT NOT NULL DEFAULT '', evidence TEXT NOT NULL DEFAULT '',
 UNIQUE(component_id,definition_id));
CREATE INDEX IF NOT EXISTS pl_match_definition ON pl_matches(definition_id,status);
CREATE TABLE IF NOT EXISTS pl_publications(
 match_id INTEGER PRIMARY KEY REFERENCES pl_matches(id) ON DELETE CASCADE,
 link_id INTEGER REFERENCES pinout_links(id) ON DELETE SET NULL,
 content_hash TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS pl_approvals(
 match_id INTEGER PRIMARY KEY REFERENCES pl_matches(id) ON DELETE CASCADE,
 component_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS pl_ignored_imports(
 namespace TEXT NOT NULL, external_id TEXT NOT NULL, incoming_hash TEXT NOT NULL,
 PRIMARY KEY(namespace,external_id));
CREATE TABLE IF NOT EXISTS pl_operations(
 id INTEGER PRIMARY KEY AUTOINCREMENT, before_json TEXT NOT NULL, after_json TEXT NOT NULL,
 undone INTEGER NOT NULL DEFAULT 0, session TEXT NOT NULL DEFAULT '', label TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS pl_settings(key TEXT PRIMARY KEY,value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS pl_imports(
 id INTEGER PRIMARY KEY, name TEXT NOT NULL, report TEXT NOT NULL,
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
'''


MATCH_FIELDS = ('component_id','definition_id','status','rule','reason','blocked','evidence')
VERBS = {'Accepted':'Accept','Rejected':'Reject','Suggested':'Reset to Suggested'}


def _renderer_version():
    """Published output depends on pinout.py; any change to it invalidates cached SVGs."""
    # Only the declared version: shared DATA folders may be used from installs whose pinout.py
    # bytes differ (line endings, frozen builds). Bump pinout.VERSION whenever drawings change.
    return 'renderer-'+str(getattr(_pinout,'VERSION','') or 'unknown')

RENDERER = _renderer_version()


def session_id():
    who = []
    for fn in (getpass.getuser, socket.gethostname):
        try: who.append(fn())
        except Exception: pass
    # Stable per user and computer, so a restart can still undo the same person's decisions.
    return '@'.join(who) if who else 'unknown@'+uuid.uuid4().hex


def search_match(term, parts, project_json, devices):
    """Case-folded substring search; the term is literal (no LIKE wildcards)."""
    if not term: return 1
    fields = [parts or '']
    try:
        data = json.loads(project_json or '{}')
        fields += [str(data.get(k,'')) for k in ('device','package','source')]
        fields.append(package_label(data))
    except (ValueError, TypeError, KeyError, AttributeError): pass
    for line in (devices or '').split('\n'):
        try: fields += [str(r.get('device','')) for r in json.loads(line) if isinstance(r,dict)]
        except (ValueError, TypeError): pass
    return int(any(term in f.casefold() for f in fields))


def encoded(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False)


def digest(value):
    return hashlib.sha256(encoded(value).encode()).hexdigest()


def validate_data(data):
    """Storage supports packages the renderer cannot draw yet."""
    if not isinstance(data.get('device'), str) or not data['device'].strip():
        raise ValueError('A pinout title is required.')
    if not isinstance(data.get('package'), str) or not data['package'].strip():
        raise ValueError('A package or unresolved package description is required.')
    count = data.get('count')
    if type(count) is not int or count < 1 or count > 4096:
        raise ValueError('Pin count must be between 1 and 4096.')
    pins = data.get('pins', [])
    if len(pins) != count or len({str(p.get('number')) for p in pins}) != count:
        raise ValueError('Pin count and unique pin numbers do not agree.')
    exposed_pad(data)  # validate the separate optional terminal
    check_text('Title', data['device'])
    for p in pins:
        if not isinstance(p.get('number'), (str, int)) or isinstance(p['number'], bool) or not str(p['number']).strip():
            raise ValueError('Each pin needs a number or pad identifier.')
        if not isinstance(p.get('name'), str) or not p['name'].strip():
            raise ValueError('Every pin needs a name.')
        if p.get('role', 'Signal') not in ROLES:
            raise ValueError('Unknown pin role: '+str(p.get('role')))
        check_text('Pin name', p['name'])
    return data


def signature(data):
    # Strict comparison: never conflate GND, VSS, VEE or NC/DNC.
    identity = [data['package'], data['count'], sorted(
        [(str(p['number']), p['name'], p.get('role','Signal'), p.get('description',''))
         for p in data['pins']])]
    pad = exposed_pad(data)
    if pad: identity.append(['exposed_pad', pad])
    return digest(identity)


def project(data, title=None):
    values = {k: v for k, v in data.items() if k in Project.__dataclass_fields__}
    values['pins'] = [Pin(**p) for p in values['pins']]
    if title is not None: values['device'] = title
    p = Project(**values)
    p.validate()
    return p


def comparison_pins(data):
    """Normal leads plus an explicitly marked optional underside terminal."""
    result = {str(p['number']): p for p in data.get('pins', [])}
    pad = exposed_pad(data)
    if pad: result[pad['number']] = dict(pad, name=pad['name']+' (EP)')
    return result


def render_issue(data):
    try: project(data)
    except (ValueError, TypeError) as exc: return str(exc)
    return ''


def package_label(data):
    return package_name(project_label(data))


class Library:
    def __init__(self, store, session=None):
        """session identifies this user's undo history; pass it on to worker instances."""
        self.store, self.db, self.root = store, store.db, store.root
        self.session = session or session_id()
        if not self.db.execute("SELECT 1 FROM sqlite_master WHERE name='pl_definitions'").fetchone():
            folder = self.root/'backups'; folder.mkdir(parents=True, exist_ok=True)
            path = folder/('components_before_0_7_0_'+uuid.uuid4().hex[:8]+'.sqlite')
            with closing(sqlite3.connect(path)) as target: self.db.backup(target)
        self.db.executescript(SCHEMA)
        columns = {r[1] for r in self.db.execute('PRAGMA table_info(pl_operations)')}
        for column in ('session','label'):
            if column in columns: continue
            try: self.db.execute(f"ALTER TABLE pl_operations ADD COLUMN {column} TEXT NOT NULL DEFAULT ''")
            except sqlite3.OperationalError as exc:
                if 'duplicate column' not in str(exc): raise
        self.db.create_function('icdb_search', 4, search_match, deterministic=True)
        self.migrate_legacy()

    def _transaction(self):
        """Take the write lock before validating, so checks and writes are atomic."""
        if not self.db.in_transaction: self.db.execute('BEGIN IMMEDIATE')
        return self.db

    def definitions(self, term='', limit=-1, offset=0):
        term = (term or '').casefold()
        return self.db.execute('''SELECT d.*, (SELECT count(*) FROM pl_matches m
          WHERE m.definition_id=d.id AND m.status='Accepted') AS uses
          FROM pl_definitions d WHERE ?='' OR icdb_search(?,
           (SELECT group_concat(c.part_number,char(10)) FROM pl_matches m JOIN components c ON c.id=m.component_id
            WHERE m.definition_id=d.id AND m.status='Accepted'), d.project_json,
           (SELECT group_concat(s.devices_json,char(10)) FROM pl_sources s WHERE s.definition_id=d.id))
          ORDER BY id LIMIT ? OFFSET ?''', (term,term,limit,offset)).fetchall()

    def get(self, ident):
        row = self.db.execute('SELECT * FROM pl_definitions WHERE id=?', (ident,)).fetchone()
        if row is None: raise ValueError('Pinout no longer exists.')
        return dict(row), json.loads(row['project_json'])

    def _definition(self, data):
        validate_data(data)
        sig = signature(data)
        row = self.db.execute('SELECT id FROM pl_definitions WHERE signature=?', (sig,)).fetchone()
        if row: return row[0], False
        ident = self.db.execute('INSERT INTO pl_definitions(signature,project_json) VALUES(?,?)',
                                (sig, encoded(data))).lastrowid
        return ident, True

    def preview_import(self, batch):
        counts = Counter()
        for item in batch['items']:
            validate_data(item['project'])
            args = (batch['namespace'],item['id'])
            ignored = self.db.execute('SELECT incoming_hash FROM pl_ignored_imports WHERE namespace=? AND external_id=?',args).fetchone()
            if ignored and ignored[0]==digest(item):
                counts['previously resolved conflicts'] += 1
                continue
            old = self.db.execute('SELECT * FROM pl_sources WHERE namespace=? AND external_id=?',args).fetchone()
            if old:
                counts['unchanged' if old['imported_json']==encoded(item['project']) and
                       old['devices_json']==encoded(item['devices']) else 'conflicts'] += 1
            else:
                counts['new source records'] += 1
        return dict(counts)

    def import_batch(self, batch):
        counts = Counter()
        with self._transaction():
            for item in batch['items']:
                data = validate_data(item['project'])
                args = (batch['namespace'],item['id'])
                ignored = self.db.execute('SELECT incoming_hash FROM pl_ignored_imports WHERE namespace=? AND external_id=?',args).fetchone()
                if ignored and ignored[0]==digest(item):
                    counts['previously resolved conflicts'] += 1
                    continue
                old = self.db.execute('SELECT * FROM pl_sources WHERE namespace=? AND external_id=?', args).fetchone()
                if old:
                    if old['imported_json']==encoded(data) and old['devices_json']==encoded(item['devices']):
                        counts['unchanged'] += 1
                        self.db.execute('DELETE FROM pl_conflicts WHERE namespace=? AND external_id=?',args)
                    else:
                        self.db.execute('INSERT OR REPLACE INTO pl_conflicts VALUES(?,?,?)', (*args,encoded(item)))
                        counts['conflicts retained for review'] += 1
                    continue
                ident, new = self._definition(data)
                self.db.execute('INSERT INTO pl_sources VALUES(?,?,?,?,?)',
                                (*args,ident,encoded(data),encoded(item['devices'])))
                counts['new definitions' if new else 'reused definitions'] += 1
            report = '\n'.join(batch.get('report', []))
            self.db.execute('INSERT INTO pl_imports(name,report) VALUES(?,?)',
                            (batch['name'],encoded(dict(counts))+'\n'+report))
        return dict(counts)

    def resolve_conflict(self, namespace, external_id, use_incoming=False):
        with self._transaction():
            row = self.db.execute('SELECT incoming_json FROM pl_conflicts WHERE namespace=? AND external_id=?',
                                  (namespace,external_id)).fetchone()
            if not row: raise ValueError('Conflict is already resolved.')
            item = json.loads(row[0])
            if use_incoming:
                ident, _ = self._definition(item['project'])
                alternative = namespace+':alternative:'+digest(item)[:16]
                self.db.execute('INSERT OR IGNORE INTO pl_sources VALUES(?,?,?,?,?)',
                    (alternative,external_id,ident,encoded(item['project']),encoded(item['devices'])))
            self.db.execute('INSERT OR REPLACE INTO pl_ignored_imports VALUES(?,?,?)',
                            (namespace,external_id,digest(item)))
            self.db.execute('DELETE FROM pl_conflicts WHERE namespace=? AND external_id=?',(namespace,external_id))

    def save(self, data, ident=None):
        validate_data(data)
        with self._transaction():
            if ident is None:
                return self._definition(data)[0]
            old, before = self.get(ident)
            if data == before: return ident
            existing = self.db.execute('SELECT id FROM pl_definitions WHERE signature=? AND id!=?',
                                      (signature(data),ident)).fetchone()
            if existing: raise ValueError(f'Identical pin data already exists as pinout #{existing[0]}. Link that pinout instead.')
            if package_label(data) != package_label(before):
                used = self.db.execute('SELECT 1 FROM pl_matches WHERE definition_id=?', (ident,)).fetchone()
                if used: raise ValueError('Package/count is linked. Use Save as new for a package variant.')
            uses = self.db.execute("SELECT count(*) FROM pl_matches WHERE definition_id=? AND status='Accepted'",(ident,)).fetchone()[0]
            problem = render_issue(data) if uses else ''
            if problem: raise ValueError(f"Cannot save pinout #{ident} ({data['device']}): it is accepted for {uses} part(s) "
                                         f"and could not be published: {problem}. Use Save as new, or correct the pin data.")
            data = copy.deepcopy(data); data['verified'] = False
            self.db.execute('UPDATE pl_definitions SET signature=?,project_json=?,revision=revision+1,edited=1 WHERE id=?',
                            (signature(data),encoded(data),ident))
        return ident

    def migrate_legacy(self):
        """One-time, per-row tolerant import of pre-0.7 links; problems are logged, not fatal."""
        done = "SELECT 1 FROM pl_settings WHERE key='legacy_migrated'"
        if self.db.execute(done).fetchone(): return
        with self._transaction():
            if self.db.execute(done).fetchone(): return
            notes = []
            for row in self.db.execute('SELECT * FROM icpin_pinouts').fetchall():
                where = f"Legacy pinout {row['catalog_id']}/{row['pinout_id']}"
                self.db.execute('SAVEPOINT legacy_row')
                try:
                    notes += self._migrate_row(row, where)
                    self.db.execute('RELEASE legacy_row')
                except (ValueError, TypeError, KeyError, AttributeError, sqlite3.IntegrityError) as exc:
                    self.db.execute('ROLLBACK TO legacy_row'); self.db.execute('RELEASE legacy_row')
                    notes.append(f'{where}: skipped ({exc})')
            if notes: self.db.execute('INSERT INTO pl_imports(name,report) VALUES(?,?)',('legacy migration','\n'.join(notes)))
            self.db.execute("INSERT INTO pl_settings VALUES('legacy_migrated','1')")

    def _migrate_row(self, row, where):
        notes = []
        data = json.loads(row['project_json'])
        for p in data.get('pins', []):
            if isinstance(p, dict) and p.get('role','Signal') not in ROLES:
                notes.append(f"{where}: pin {p.get('number')} role {p.get('role')!r} migrated as 'Signal'"); p['role'] = 'Signal'
        ident, _ = self._definition(data)
        records = [json.loads(s[0]) for s in self.db.execute(
            'SELECT record_json FROM icpin_sources WHERE catalog_id=? AND pinout_id=?',
            (row['catalog_id'],row['pinout_id']))]
        if not records:
            records = [dict(device=data['device'], manufacturer='',package=package_label(data))]
        self.db.execute('INSERT OR IGNORE INTO pl_sources VALUES(?,?,?,?,?)',
            ('catalog:'+row['catalog_id'], row['pinout_id'], ident, encoded(data), encoded(records)))
        for link in self.db.execute('SELECT * FROM pinout_links WHERE asset_id=?', (row['asset_id'],)).fetchall():
            c = self.db.execute('SELECT part_number,manufacturer FROM components WHERE id=?',(link['component_id'],)).fetchone()
            if c is None:
                notes.append(f"{where}: link #{link['id']} skipped; component #{link['component_id']} no longer exists"); continue
            self.db.execute('INSERT OR IGNORE INTO pl_matches(component_id,definition_id,status,rule,reason) VALUES(?,?,?,?,?)',
                            (link['component_id'],ident,'Accepted','legacy','Existing ICDB link'))
            mid = self.db.execute('SELECT id FROM pl_matches WHERE component_id=? AND definition_id=?',
                                 (link['component_id'],ident)).fetchone()[0]
            pub = self.db.execute('SELECT link_id FROM pl_publications WHERE match_id=?',(mid,)).fetchone()
            if pub and pub[0] is not None and pub[0]!=link['id']:
                notes.append(f"{where}: link #{link['id']} ({c['part_number']} / {link['package']}) left unmanaged; "
                             f"link #{pub[0]} already publishes this pinout for the part"); continue
            self.db.execute('INSERT OR IGNORE INTO pl_publications(match_id,link_id) VALUES(?,?)',(mid,link['id']))
            self.db.execute('INSERT OR IGNORE INTO pl_approvals VALUES(?,?)',(mid,encoded(list(c))))
        for decision in self.db.execute('''SELECT DISTINCT d.component_id FROM pinout_match_decisions d
            JOIN icpin_sources s ON s.catalog_id=d.catalog_id AND s.source_id=d.source_id
            JOIN components c ON c.id=d.component_id
            WHERE d.catalog_id=? AND s.pinout_id=? AND d.decision='reject' ''',(row['catalog_id'],row['pinout_id'])).fetchall():
            self.db.execute('''INSERT OR IGNORE INTO pl_matches(component_id,definition_id,status,rule,reason)
                VALUES(?,?,'Rejected','legacy-reject','Rejected in ICDB before 0.7')''',(decision[0],ident))
        return notes

    def matches(self, term='', state='All', limit=-1, offset=0):
        term = (term or '').casefold()
        return self.db.execute('''SELECT m.*,c.part_number,c.manufacturer,d.project_json,d.revision
            FROM pl_matches m JOIN components c ON c.id=m.component_id
            JOIN pl_definitions d ON d.id=m.definition_id
            WHERE (?='All' OR m.status=?) AND (?='' OR icdb_search(?,c.part_number,d.project_json,NULL))
            ORDER BY CASE m.status WHEN 'Suggested' THEN 0 WHEN 'Blocked' THEN 1 ELSE 2 END,
            d.id,c.part_number LIMIT ? OFFSET ?''',(state,state,term,term,limit,offset)).fetchall()

    def _snapshot(self, mid):
        row = self.db.execute('SELECT * FROM pl_matches WHERE id=?',(mid,)).fetchone()
        return {f:row[f] for f in MATCH_FIELDS} if row else None

    def _log(self, before, after, label):
        if before: self.db.execute('INSERT INTO pl_operations(before_json,after_json,session,label) VALUES(?,?,?,?)',
                                   (encoded(before),encoded(after),self.session,label))

    def manual_link(self, ident, components):
        before, after = {}, {}
        with self._transaction():
            self.get(ident)
            for cid in dict.fromkeys(map(int,components)):
                old = self.db.execute('SELECT id FROM pl_matches WHERE component_id=? AND definition_id=?',(cid,ident)).fetchone()
                snapshot = self._snapshot(old[0]) if old else None
                self.db.execute('''INSERT INTO pl_matches(component_id,definition_id,rule,reason)
                    VALUES(?,?,'manual-v1','Manually selected; confirm package and pin assignments')
                    ON CONFLICT(component_id,definition_id) DO UPDATE SET
                    status=CASE WHEN pl_matches.status='Accepted' THEN 'Accepted' ELSE 'Suggested' END,
                    rule='manual-v1',reason=excluded.reason,blocked='',evidence='' ''',(cid,ident))
                mid = self.db.execute('SELECT id FROM pl_matches WHERE component_id=? AND definition_id=?',(cid,ident)).fetchone()[0]
                before[str(mid)] = snapshot; after[str(mid)] = self._snapshot(mid)
            self._log(before, after, f'Link {len(after)} part(s) to pinout #{ident}')

    def acceptance_issues(self, ids):
        """Validate the whole batch, including incompatible proposals in it."""
        ids = list(dict.fromkeys(map(int, ids)))
        records, selected = {}, defaultdict(list)
        issues = []
        for mid in ids:
            row = self.db.execute('SELECT m.*,c.part_number FROM pl_matches m JOIN components c ON c.id=m.component_id WHERE m.id=?', (mid,)).fetchone()
            if row is None:
                issues.append(dict(match_id=mid, part=f'Link #{mid}', package='', proposed='', reason='Suggestion no longer exists. Refresh the list.'))
                continue
            _, data = self.get(row['definition_id'])
            records[mid] = (row, data)
            selected[(row['component_id'], package_label(data))].append((mid, data))
        for mid, (row, data) in records.items():
            reasons = []
            if row['blocked']: reasons.append(row['blocked'])
            problem = render_issue(data)
            if problem: reasons.append('Rendering unavailable: '+problem)
            current = self.db.execute("""SELECT m.id,d.id AS definition_id,d.project_json FROM pl_matches m
                JOIN pl_definitions d ON d.id=m.definition_id
                WHERE m.component_id=? AND m.status='Accepted' AND m.id!=?""", (row['component_id'], mid))
            for other in current:
                existing = json.loads(other['project_json'])
                if package_label(existing)==package_label(data) and signature(existing)!=signature(data):
                    reasons.append(f"Already accepted: {existing['device']} [pinout #{other['definition_id']}, link #{other['id']}]. Pin data differs; compare the diagrams, then reject the incorrect link before accepting a replacement.")
            for other_mid, other_data in selected[(row['component_id'], package_label(data))]:
                if other_mid!=mid and signature(other_data)!=signature(data):
                    reasons.append(f"Also selected: {other_data['device']} [link #{other_mid}], with different pin data. Choose only one pinout for this part/package.")
            if reasons:
                issues.append(dict(match_id=mid, part=row['part_number'], package=package_label(data),
                    proposed=f"{data['device']} [pinout #{row['definition_id']}, link #{mid}]", reason=' '.join(reasons)))
        return issues

    def decide(self, ids, status, transaction=True):
        """transaction=False: the caller owns the (already locked) transaction."""
        if status not in ('Accepted','Rejected','Suggested'): raise ValueError('Invalid decision.')
        ids = list(dict.fromkeys(map(int,ids)))
        with self._transaction() if transaction else nullcontext():
            before = {str(mid):self._snapshot(mid) for mid in ids}
            self._set_status(ids, status)
            self._log(before, {m:self._snapshot(int(m)) for m in before}, f'{VERBS[status]} {len(ids)} link(s)')

    def _set_status(self, ids, status):
        if status == 'Accepted':
            issues = self.acceptance_issues(ids)
            if issues: raise BatchDecisionError(issues, len(ids))
        for mid in ids:
            row = self.db.execute('SELECT * FROM pl_matches WHERE id=?',(mid,)).fetchone()
            if row is None: raise ValueError('Suggestion no longer exists. Refresh the list.')
            if status == 'Accepted':
                c = self.db.execute('SELECT part_number,manufacturer FROM components WHERE id=?',(row['component_id'],)).fetchone()
                self.db.execute('INSERT OR REPLACE INTO pl_approvals VALUES(?,?)',(mid,encoded(list(c))))
            self.db.execute('UPDATE pl_matches SET status=? WHERE id=?',(status,mid))

    def add_group_members(self, ident, component_ids):
        """Explicit group assignment; all selected additions succeed or none do."""
        components = list(dict.fromkeys(map(int,component_ids)))
        before = {}
        with self._transaction():
            self.get(ident)
            for cid in components:
                if not self.db.execute('SELECT 1 FROM components WHERE id=?',(cid,)).fetchone():
                    raise ValueError('A selected component no longer exists.')
                old = self.db.execute('SELECT * FROM pl_matches WHERE component_id=? AND definition_id=?',(cid,ident)).fetchone()
                if old and old['status']=='Accepted':continue
                self.db.execute("""INSERT INTO pl_matches(component_id,definition_id,rule,reason)
                    VALUES(?,?,'manual-v1','Explicitly added to this pinout group')
                    ON CONFLICT(component_id,definition_id) DO UPDATE SET
                    rule='manual-v1',reason=excluded.reason,blocked='',evidence='' """,(cid,ident))
                mid = self.db.execute('SELECT id FROM pl_matches WHERE component_id=? AND definition_id=?',(cid,ident)).fetchone()[0]
                before[str(mid)] = {f:old[f] for f in MATCH_FIELDS} if old else None  # None: inserted, delete on undo
            self._set_status(list(map(int,before)),'Accepted')
            self._log(before, {m:self._snapshot(int(m)) for m in before}, f'Add {len(before)} part(s) to pinout #{ident}')
        return len(before)

    def remove_group_members(self, ident, match_ids):
        ids = list(dict.fromkeys(map(int,match_ids)))
        with self._transaction():
            for mid in ids:
                row = self.db.execute('SELECT definition_id,status FROM pl_matches WHERE id=?',(mid,)).fetchone()
                if not row or row[0]!=ident or row[1]!='Accepted':
                    raise ValueError('Group membership changed. Refresh before removing parts.')
            self.decide(ids,'Rejected',transaction=False)
        return len(ids)

    def _operation(self):
        return self.db.execute('SELECT * FROM pl_operations WHERE undone=0 AND session=? ORDER BY id DESC LIMIT 1',(self.session,)).fetchone()

    @staticmethod
    def _describe(op):
        if op['label']: return op['label']
        states = Counter(v if isinstance(v,str) else v['status'] for v in json.loads(op['after_json']).values())
        return ', '.join(f'{VERBS.get(s,s)} {n} link(s)' for s, n in states.items())

    def undo_description(self):
        """What undo() would reverse for this session, or None."""
        op = self._operation()
        return self._describe(op) if op else None

    def _stale(self, after):
        for mid, expected in after.items():
            row = self._snapshot(int(mid))
            if isinstance(expected, str): expected = dict(status=expected)
            if row is None or any(row[k]!=expected[k] for k in ('status','component_id','definition_id') if k in expected): return True
        return False

    def _accepted_conflicts(self, ids):
        """Accepted links in ids that now clash with another Accepted link (same part/package, different pin data)."""
        issues = []
        for mid in ids:
            row = self.db.execute("SELECT m.component_id,d.id AS definition_id,d.project_json,c.part_number FROM pl_matches m "
                                  "JOIN pl_definitions d ON d.id=m.definition_id JOIN components c ON c.id=m.component_id "
                                  "WHERE m.id=? AND m.status='Accepted'",(mid,)).fetchone()
            if row is None: continue
            data = json.loads(row['project_json'])
            for other in self.db.execute("""SELECT m.id,d.id AS definition_id,d.project_json FROM pl_matches m
                    JOIN pl_definitions d ON d.id=m.definition_id
                    WHERE m.component_id=? AND m.status='Accepted' AND m.id!=?""",(row['component_id'],mid)):
                existing = json.loads(other['project_json'])
                if package_label(existing)==package_label(data) and signature(existing)!=signature(data):
                    issues.append(f"{row['part_number']} ({package_label(data)}): pinout #{row['definition_id']} would conflict "
                                  f"with accepted pinout #{other['definition_id']} [link #{other['id']}]")
                    break
        return issues

    def undo(self):
        """Reverse this session's newest operation. A stale one is dropped from history (undone=2) and reported."""
        stale = None
        try:
            stale = self._undo_once()
        except _UndoConflict as exc:
            # The restore was rolled back; drop the operation from history so older decisions stay reachable.
            with self._transaction():
                self.db.execute('UPDATE pl_operations SET undone=2 WHERE id=? AND undone=0',(exc.op_id,))
            raise ValueError(f'"{exc.label}" cannot be undone: it would re-accept a pinout that conflicts with a link '
                             'accepted since then. No changes made; it was removed from the undo history.\n\n'
                             + '\n'.join(exc.issues)) from None
        if stale: raise ValueError(f'Records changed since "{stale}"; it cannot be undone and was removed from the undo history. '
                                   'Undo again to reach older decisions.')
        return stale is not False

    def _undo_once(self):
        """Returns False (nothing to undo), None (undone) or the description of a stale operation."""
        stale = None
        with self._transaction():
            op = self._operation()
            if not op: return False
            before, after = json.loads(op['before_json']), json.loads(op['after_json'])
            if self._stale(after):
                self.db.execute('UPDATE pl_operations SET undone=2 WHERE id=?',(op['id'],)); stale = self._describe(op)
            else:
                def status_of(state): return state if isinstance(state, str) else (state or {}).get('status')
                reaccepted = [int(mid) for mid, state in before.items()
                              if status_of(state)=='Accepted' and status_of(after.get(mid))!='Accepted']
                for mid, state in before.items():
                    if isinstance(state, str): self.db.execute('UPDATE pl_matches SET status=? WHERE id=?',(state,mid))
                    elif state is None:
                        # Created by the operation. A published link is removed by the next publish instead.
                        if self.db.execute('SELECT 1 FROM pl_publications WHERE match_id=? AND link_id IS NOT NULL',(mid,)).fetchone():
                            self.db.execute("UPDATE pl_matches SET status='Suggested' WHERE id=?",(mid,))
                        else: self.db.execute('DELETE FROM pl_matches WHERE id=?',(mid,))
                    else:
                        self.db.execute('UPDATE pl_matches SET status=?,rule=?,reason=?,blocked=?,evidence=? WHERE id=?',
                                        (state['status'],state['rule'],state['reason'],state['blocked'],state['evidence'],mid))
                issues = self._accepted_conflicts(reaccepted)
                if issues: raise _UndoConflict(op['id'], self._describe(op), issues)  # rolls back the restore
                self.db.execute('UPDATE pl_operations SET undone=1 WHERE id=?',(op['id'],))
        return stale

    def publish(self, force=False):
        """Immutable SVG revisions first, one DB commit last. Old images survive failures."""
        created = []; changed = 0; unchanged = 0; removed = 0; rendered = 0; skipped = []
        db = self.db
        try:
            db.execute('BEGIN IMMEDIATE')
            for row in self.matches(state='Accepted'):
                data = json.loads(row['project_json'])
                pkg = package_label(data); label = row['part_number']+' / '+pkg
                # Problem links keep their previous output; the rest still publish.
                where = f"{label} (pinout #{row['definition_id']})"
                approval = db.execute('SELECT component_json FROM pl_approvals WHERE match_id=?',(row['id'],)).fetchone()
                if not approval or approval[0]!=encoded([row['part_number'],row['manufacturer']]):
                    skipped.append(where+': component identity changed; re-accept the link before publishing'); continue
                if row['blocked']: skipped.append(where+': blocked: '+row['blocked']); continue
                token = digest([RENDERER,data,row['part_number'],row['component_id'],row['definition_id']])
                pub = db.execute('SELECT * FROM pl_publications WHERE match_id=?',(row['id'],)).fetchone()
                old = db.execute('SELECT * FROM pinout_links WHERE id=?',(pub['link_id'],)).fetchone() if pub and pub['link_id'] else None
                if not force and pub and old and pub['content_hash']==token and old['package']==pkg and old['label']==label:
                    asset = db.execute('SELECT * FROM pinout_assets WHERE id=?',(old['asset_id'],)).fetchone()
                    existing_path = self.store.path(asset)
                    if existing_path.is_file() and hashlib.sha256(existing_path.read_bytes()).hexdigest()==asset['sha256']:
                        unchanged += 1
                        continue
                problem = render_issue(data)
                if problem: skipped.append(where+': rendering unavailable: '+problem); continue
                try: svg = diagram(project(data,row['part_number'])).svg()
                except Exception as exc: skipped.append(f'{where}: rendering failed: {exc}'); continue
                rendered += 1
                # Keep per-part/definition assets distinct even when titles happen to be equal.
                svg += f"\n<!-- ICDB component {row['component_id']} pinout {row['definition_id']} -->"
                content = svg.encode('utf-8'); sha = hashlib.sha256(content).hexdigest()
                relative = 'pinouts/generated/'+sha+'.svg'; path = self.root/relative
                if not path.exists() or path.read_bytes()!=content:
                    path.parent.mkdir(parents=True,exist_ok=True)
                    tmp = path.with_suffix('.tmp')
                    try: tmp.write_bytes(content); tmp.replace(path)
                    finally: tmp.unlink(missing_ok=True)
                    created.append(path)
                asset = db.execute('SELECT id FROM pinout_assets WHERE sha256=?',(sha,)).fetchone()
                aid = asset[0] if asset else db.execute('''INSERT INTO pinout_assets(sha256,path,original_name,caption,source)
                    VALUES(?,?,?,?,?)''',(sha,relative,row['part_number']+'.svg',row['part_number'],data.get('source',''))).lastrowid
                pub = db.execute('SELECT * FROM pl_publications WHERE match_id=?',(row['id'],)).fetchone()
                old = db.execute('SELECT * FROM pinout_links WHERE id=?',(pub['link_id'],)).fetchone() if pub and pub['link_id'] else None
                pkg = package_label(data)
                label = row['part_number']+' / '+pkg
                if old and old['asset_id']==aid and old['package']==pkg and old['label']==label:
                    unchanged += 1
                elif old:
                    db.execute('UPDATE pinout_links SET asset_id=?,package=?,pin_count=?,label=? WHERE id=?',
                               (aid,pkg,data['count'],label,old['id'])); changed += 1
                else:
                    first = not db.execute('SELECT 1 FROM pinout_links WHERE component_id=?',(row['component_id'],)).fetchone()
                    lid = db.execute('INSERT INTO pinout_links(component_id,asset_id,package,pin_count,label,is_default) VALUES(?,?,?,?,?,?)',
                                     (row['component_id'],aid,pkg,data['count'],label,int(first))).lastrowid
                    old = {'id':lid}; changed += 1
                db.execute('INSERT OR REPLACE INTO pl_publications VALUES(?,?,?)',(row['id'],old['id'],token))
            for pub in db.execute('''SELECT p.* FROM pl_publications p JOIN pl_matches m ON m.id=p.match_id
                                  WHERE m.status!='Accepted' ''').fetchall():
                link = db.execute('SELECT * FROM pinout_links WHERE id=?',(pub['link_id'],)).fetchone()
                if link:
                    db.execute('DELETE FROM pinout_links WHERE id=?',(link['id'],))
                    if link['is_default']:
                        db.execute('UPDATE pinout_links SET is_default=1 WHERE id=(SELECT min(id) FROM pinout_links WHERE component_id=?)', (link['component_id'],))
                    removed += 1
                db.execute('DELETE FROM pl_publications WHERE match_id=?',(pub['match_id'],))
            db.commit()
        except Exception:
            db.rollback()
            for path in created:
                if not db.execute('SELECT 1 FROM pinout_assets WHERE path=?',(path.relative_to(self.root).as_posix(),)).fetchone():
                    path.unlink(missing_ok=True)
            raise
        result = dict(updated=changed,unchanged=unchanged,removed=removed,skipped=skipped)
        if force: result['rendered'] = rendered
        return result

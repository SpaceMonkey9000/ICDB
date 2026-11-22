"""ICDB 0.7: editable pin data, persistent decisions and selective publication."""
from collections import Counter
from contextlib import closing, nullcontext
from dataclasses import asdict
from pathlib import Path
import copy
import hashlib
import json
import sqlite3
import uuid

import pinout as _pinout
from pinout import Project, Pin, diagram, check_text, ROLES, exposed_pad, project_label
from pinouts import package_name
from icpin_bundle import UNKNOWN


SCHEMA = '''
CREATE TABLE IF NOT EXISTS pl_definitions(
 id INTEGER PRIMARY KEY AUTOINCREMENT, signature TEXT NOT NULL UNIQUE,
 project_json TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 1,
 edited INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS pl_json_ids(
 external_id TEXT PRIMARY KEY, definition_id INTEGER NOT NULL REFERENCES pl_definitions(id));
CREATE INDEX IF NOT EXISTS pl_json_definition ON pl_json_ids(definition_id);
CREATE TRIGGER IF NOT EXISTS pl_json_delete AFTER DELETE ON pl_definitions
BEGIN DELETE FROM pl_json_ids WHERE definition_id=OLD.id; END;
CREATE TABLE IF NOT EXISTS pl_sources(
 namespace TEXT NOT NULL, external_id TEXT NOT NULL,
 definition_id INTEGER NOT NULL REFERENCES pl_definitions(id),
 imported_json TEXT NOT NULL, devices_json TEXT NOT NULL,
 PRIMARY KEY(namespace,external_id));
CREATE INDEX IF NOT EXISTS pl_source_definition ON pl_sources(definition_id);
CREATE TABLE IF NOT EXISTS pl_conflicts(
 namespace TEXT NOT NULL, external_id TEXT NOT NULL, incoming_json TEXT NOT NULL,
 PRIMARY KEY(namespace,external_id));
CREATE TABLE IF NOT EXISTS pl_assignments(
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 component_id INTEGER NOT NULL REFERENCES components(id) ON DELETE CASCADE,
 definition_id INTEGER NOT NULL REFERENCES pl_definitions(id),
 is_default INTEGER CHECK(is_default IN (0,1)),
 UNIQUE(component_id,definition_id));
CREATE INDEX IF NOT EXISTS pl_assignment_definition ON pl_assignments(definition_id);
CREATE TABLE IF NOT EXISTS pl_ignored_imports(
 namespace TEXT NOT NULL, external_id TEXT NOT NULL, incoming_hash TEXT NOT NULL,
 PRIMARY KEY(namespace,external_id));
CREATE TABLE IF NOT EXISTS pl_settings(key TEXT PRIMARY KEY,value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS pl_imports(
 id INTEGER PRIMARY KEY, name TEXT NOT NULL, report TEXT NOT NULL,
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS pl_file_hashes(
 path TEXT PRIMARY KEY, size INTEGER NOT NULL, mtime_ns INTEGER NOT NULL, sha256 TEXT NOT NULL);
'''


def _renderer_version():
    """Published output depends on pinout.py; any change to it invalidates cached SVGs."""
    # Only the declared version: shared DATA folders may be used from installs whose pinout.py
    # bytes differ (line endings, frozen builds). Bump pinout.VERSION whenever drawings change.
    return 'renderer-'+str(getattr(_pinout,'VERSION','') or 'unknown')

RENDERER = _renderer_version()


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
    def __init__(self, store):
        self.store, self.db, self.root = store, store.db, store.root
        legacy = self.db.execute("SELECT 1 FROM sqlite_master WHERE name='pl_matches'").fetchone()
        if legacy or not self.db.execute("SELECT 1 FROM sqlite_master WHERE name='pl_definitions'").fetchone():
            folder = self.root / 'backups'
            folder.mkdir(parents=True, exist_ok=True)
            path = folder / ('components_before_assignments_' + uuid.uuid4().hex + '.sqlite')
            with closing(sqlite3.connect(path)) as target:
                self.db.backup(target)
        self.db.executescript(SCHEMA)
        self.db.create_function('icdb_search', 4, search_match, deterministic=True)
        from database_version import install
        with self._transaction():
            self._install_assignments()
            install(self.db)
        self.migrate_legacy()

    def _install_assignments(self):
        db = self.db
        legacy = db.execute("SELECT 1 FROM sqlite_master WHERE name='pl_matches'").fetchone()
        if legacy:
            db.execute('ALTER TABLE pl_publications RENAME TO pl_old_publications')
        db.execute("""CREATE TABLE IF NOT EXISTS pl_publications(
            assignment_id INTEGER PRIMARY KEY REFERENCES pl_assignments(id) ON DELETE CASCADE,
            link_id INTEGER REFERENCES pinout_links(id) ON DELETE SET NULL,
            content_hash TEXT NOT NULL DEFAULT '')""")
        if legacy:
            db.execute("""INSERT INTO pl_assignments(id, component_id, definition_id, is_default)
                SELECT m.id, m.component_id, m.definition_id, l.is_default
                FROM pl_matches m LEFT JOIN pl_old_publications p ON p.match_id=m.id
                LEFT JOIN pinout_links l ON l.id=p.link_id WHERE m.status='Accepted'""")
            db.execute("""INSERT INTO pl_publications
                SELECT p.match_id,p.link_id,p.content_hash FROM pl_old_publications p
                JOIN pl_assignments a ON a.id=p.match_id""")
            db.execute("""DELETE FROM pinout_links WHERE id IN (
                SELECT link_id FROM pl_old_publications WHERE match_id NOT IN (SELECT id FROM pl_assignments))
                AND id NOT IN (SELECT link_id FROM pl_publications WHERE link_id IS NOT NULL)""")
            for table in ('pl_old_publications', 'pl_approvals', 'pl_operations', 'pl_matches'):
                db.execute(f'DROP TABLE IF EXISTS {table}')
        db.execute('CREATE INDEX IF NOT EXISTS pl_published_link ON pl_publications(link_id)')
        db.execute("""CREATE TRIGGER IF NOT EXISTS pl_sync_published_default
            AFTER UPDATE OF is_default ON pinout_links WHEN OLD.is_default<>NEW.is_default BEGIN
                UPDATE pl_assignments SET is_default=NEW.is_default
                WHERE id IN (SELECT assignment_id FROM pl_publications WHERE link_id=NEW.id);
            END""")
        db.execute("""CREATE TRIGGER IF NOT EXISTS pl_unpublish_assignment
            BEFORE DELETE ON pl_assignments BEGIN
                DELETE FROM pinout_links WHERE id=(
                    SELECT link_id FROM pl_publications WHERE assignment_id=OLD.id)
                AND NOT EXISTS (SELECT 1 FROM pl_publications other
                    JOIN pl_publications own ON other.link_id=own.link_id
                    WHERE own.assignment_id=OLD.id AND other.assignment_id<>OLD.id);
            END""")

    def _transaction(self):
        """Take the write lock before validating, so checks and writes are atomic."""
        if not self.db.in_transaction: self.db.execute('BEGIN IMMEDIATE')
        return self.db

    def definitions(self, term='', limit=-1, offset=0):
        term = (term or '').casefold()
        return self.db.execute('''SELECT d.*, (SELECT count(*) FROM pl_assignments m
          WHERE m.definition_id=d.id) AS uses
          FROM pl_definitions d WHERE ?='' OR icdb_search(?,
           (SELECT group_concat(c.part_number,char(10)) FROM pl_assignments m JOIN components c ON c.id=m.component_id
            WHERE m.definition_id=d.id), d.project_json,
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

    def _save_locked(self, data, ident=None):
        """Validate and modify a pinout inside the caller-owned write transaction."""
        validate_data(data)
        if ident is None:
            # Imports deliberately reuse identical pin data (_definition); a user's new
            # pinout must not silently collapse into another one and lose its title.
            existing = self.db.execute('SELECT id,project_json FROM pl_definitions WHERE signature=?',
                                       (signature(data),)).fetchone()
            if existing:
                try: title = json.loads(existing[1]).get('device', '')
                except (ValueError, AttributeError): title = ''
                raise ValueError(f'Identical pin data already exists as pinout #{existing[0]}'
                                 + (f' ("{title}")' if title else '') +
                                 '. Change the pin data, or link that pinout instead.')
            return self._definition(data)[0]
        old, before = self.get(ident)
        if data == before: return ident
        existing = self.db.execute('SELECT id FROM pl_definitions WHERE signature=? AND id!=?',
                                  (signature(data),ident)).fetchone()
        if existing: raise ValueError(f'Identical pin data already exists as pinout #{existing[0]}. Link that pinout instead.')
        if package_label(data) != package_label(before):
            used = self.db.execute('SELECT 1 FROM pl_assignments WHERE definition_id=?', (ident,)).fetchone()
            if used: raise ValueError('Package/count is linked. Use Duplicate pinout for a package variant, or remove its devices first.')
        uses = self.db.execute("SELECT count(*) FROM pl_assignments WHERE definition_id=?",(ident,)).fetchone()[0]
        problem = render_issue(data) if uses else ''
        if problem: raise ValueError(f"Cannot save pinout #{ident} ({data['device']}): it is assigned to {uses} part(s) "
                                     f"and could not be published: {problem}. Use Duplicate pinout, or correct the pin data.")
        data = copy.deepcopy(data); data['verified'] = False
        self.db.execute('UPDATE pl_definitions SET signature=?,project_json=?,revision=revision+1,edited=1 WHERE id=?',
                        (signature(data),encoded(data),ident))
        return ident

    def save(self, data, ident=None, *, locked=False):
        with (nullcontext() if locked else self._transaction()):
            return self._save_locked(data, ident)

    def save_with_members(self, data, ident, expected_revision, expected_members, desired_members, *, locked=False):
        """Atomically save pin data and group membership changes.

        Caller stages changes in memory. The lock is taken before checking the
        expected revision and membership snapshot. A failed validation rolls
        back the entire operation, including any pin-definition modification.
        """
        if ident is None:
            raise ValueError('Save a new pinout before assigning group members.')
        expected = set(map(int, expected_members))
        desired = set(map(int, desired_members))
        with (nullcontext() if locked else self._transaction()):
            record, _ = self.get(ident)
            if record['revision'] != expected_revision:
                raise ValueError('This pinout changed externally. Reload it before saving.')
            current = {r[0] for r in self.db.execute(
                "SELECT component_id FROM pl_assignments WHERE definition_id=?", (ident,))}
            if current != expected:
                raise ValueError('Group membership changed externally. Reload before saving.')
            to_remove = sorted(current - desired)
            to_add = sorted(desired - current)
            self.db.executemany('DELETE FROM pl_assignments WHERE component_id=? AND definition_id=?',
                                ((cid, ident) for cid in to_remove))
            self._save_locked(data, ident)
            self._add_assignments(ident, to_add, data)
        return ident

    def _add_assignments(self, ident, component_ids, data):
        if not component_ids:
            return
        problem = render_issue(data)
        if problem:
            raise ValueError(f'Cannot assign {data["device"]}: {problem}')
        package = package_label(data)
        for cid in component_ids:
            part = self.db.execute('SELECT part_number FROM components WHERE id=?', (cid,)).fetchone()
            if part is None:
                raise ValueError('A selected component no longer exists.')
            for row in self.db.execute("""SELECT d.project_json FROM pl_assignments a JOIN pl_definitions d
                ON d.id=a.definition_id WHERE a.component_id=? AND a.definition_id<>?""", (cid, ident)):
                if package_label(json.loads(row[0])) == package:
                    raise ValueError(f'{part[0]} already has a different {package} pinout. Remove that assignment first.')
        self.db.executemany('INSERT OR IGNORE INTO pl_assignments(component_id,definition_id) VALUES(?,?)',
                            ((cid, ident) for cid in component_ids))

    def add_group_members(self, ident, component_ids, *, locked=False):
        with (nullcontext() if locked else self._transaction()):
            _, data = self.get(ident)
            self._add_assignments(ident, set(map(int, component_ids)), data)

    def delete_definition(self, ident, *, locked=False, expected_revision=None, expected_members=None):
        """Delete an unused pinout definition."""
        with (nullcontext() if locked else self._transaction()):
            row = self.db.execute('SELECT id,revision FROM pl_definitions WHERE id=?', (ident,)).fetchone()
            if row is None:
                raise ValueError('Pinout no longer exists.')
            if expected_revision is not None and row['revision'] != expected_revision:
                raise ValueError('Pinout changed externally since deletion was staged.')
            if expected_members is not None:
                current_members = {r[0] for r in self.db.execute(
                    "SELECT component_id FROM pl_assignments WHERE definition_id=?", (ident,))}
                if current_members != set(map(int, expected_members)):
                    raise ValueError('Pinout group membership changed externally since deletion was staged.')
            accepted = self.db.execute(
                "SELECT count(*) FROM pl_assignments WHERE definition_id=?", (ident,)
            ).fetchone()[0]
            sources = self.db.execute(
                'SELECT count(*) FROM pl_sources WHERE definition_id=?', (ident,)
            ).fetchone()[0]
            if accepted or sources:
                raise ValueError(
                    f'Cannot delete this pinout: {accepted} device assignment(s) '
                    f'and {sources} imported source reference(s) still use it. '
                    'Unassign devices and Save first. Imported definitions '
                    'must be detached from their source before deletion.'
                )
            self.db.execute('DELETE FROM pl_definitions WHERE id=?', (ident,))
        return True

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
            self.db.execute('INSERT OR IGNORE INTO pl_assignments(component_id,definition_id,is_default) VALUES(?,?,?)',
                            (link['component_id'], ident, link['is_default']))
            mid = self.db.execute('SELECT id FROM pl_assignments WHERE component_id=? AND definition_id=?',
                                 (link['component_id'],ident)).fetchone()[0]
            pub = self.db.execute('SELECT link_id FROM pl_publications WHERE assignment_id=?',(mid,)).fetchone()
            if pub and pub[0] is not None and pub[0]!=link['id']:
                notes.append(f"{where}: link #{link['id']} ({c['part_number']} / {link['package']}) left unmanaged; "
                             f"link #{pub[0]} already publishes this pinout for the part"); continue
            self.db.execute('INSERT OR IGNORE INTO pl_publications(assignment_id,link_id) VALUES(?,?)',(mid,link['id']))
        return notes

    def _file_has_hash(self, path, sha):
        """Verify a published file, re-hashing only when its size or mtime changed."""
        try: stat = path.stat()
        except OSError: return False
        try: key = path.relative_to(self.root).as_posix()  # stable across machines sharing DATA
        except ValueError: key = str(path)
        row = self.db.execute('SELECT size,mtime_ns,sha256 FROM pl_file_hashes WHERE path=?',(key,)).fetchone()
        if row and (row[0],row[1]) == (stat.st_size,stat.st_mtime_ns):
            return row[2] == sha
        try: actual = hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError: return False
        self.db.execute('INSERT OR REPLACE INTO pl_file_hashes VALUES(?,?,?,?)',(key,stat.st_size,stat.st_mtime_ns,actual))
        return actual == sha

    def publish(self, force=False, definition_ids=None, progress=None):
        """Immutable SVG revisions first, one DB commit last. Old images survive failures.

        definition_ids limits the run to the assignments of those pinouts (used after
        Save, which must not walk the whole catalogue); None publishes everything.
        progress(done, total) is called now and then from this (worker) thread."""
        created = []; changed = 0; unchanged = 0; removed = 0; rendered = 0; skipped = []
        db = self.db
        try:
            db.execute('BEGIN IMMEDIATE')
            query = """SELECT a.*, c.part_number, d.project_json
                FROM pl_assignments a JOIN components c ON c.id=a.component_id
                JOIN pl_definitions d ON d.id=a.definition_id"""
            if definition_ids is None:
                rows = db.execute(query + ' ORDER BY a.id').fetchall()
            else:
                ids = sorted({int(i) for i in definition_ids})
                rows = db.execute(query + ' WHERE a.definition_id IN (SELECT value FROM json_each(?))'
                                  ' ORDER BY a.id', (json.dumps(ids),)).fetchall()
            components = {row['component_id'] for row in rows}
            total = len(rows)
            if progress:
                progress(0, total)
            for index, row in enumerate(rows, 1):
                if progress and (index % 200 == 0 or index == total):
                    progress(index, total)
                data = json.loads(row['project_json'])
                pkg = package_label(data)
                label = row['part_number'] + ' / ' + pkg
                where = f"{label} (pinout #{row['definition_id']})"
                token = digest([RENDERER,data,row['part_number'],row['component_id'],row['definition_id']])
                pub = db.execute('SELECT * FROM pl_publications WHERE assignment_id=?',(row['id'],)).fetchone()
                old = db.execute('SELECT * FROM pinout_links WHERE id=?',(pub['link_id'],)).fetchone() if pub and pub['link_id'] else None
                if not force and pub and old and pub['content_hash']==token and old['package']==pkg and old['label']==label:
                    asset = db.execute('SELECT * FROM pinout_assets WHERE id=?',(old['asset_id'],)).fetchone()
                    if self._file_has_hash(self.store.path(asset), asset['sha256']):
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
                pub = db.execute('SELECT * FROM pl_publications WHERE assignment_id=?',(row['id'],)).fetchone()
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
                                     (row['component_id'],aid,pkg,data['count'],label,int(first and row['is_default'] is None))).lastrowid
                    old = {'id':lid}; changed += 1
                db.execute('INSERT OR REPLACE INTO pl_publications VALUES(?,?,?)',(row['id'],old['id'],token))
            # Apply explicit preferences after rendering so unique defaults can switch
            # between two existing links in either publication order.
            preferences = db.execute("""SELECT a.component_id, a.is_default, p.link_id
                FROM pl_assignments a JOIN pl_publications p ON p.assignment_id=a.id
                WHERE a.is_default IS NOT NULL AND p.link_id IS NOT NULL
                ORDER BY a.is_default, a.id""").fetchall()
            if definition_ids is not None:
                preferences = [row for row in preferences if row['component_id'] in components]
            for row in preferences:
                if row['is_default']:
                    db.execute('UPDATE pinout_links SET is_default=0 WHERE component_id=? AND id<>? AND is_default=1',
                               (row['component_id'], row['link_id']))
                db.execute('UPDATE pinout_links SET is_default=? WHERE id=? AND is_default<>?',
                           (row['is_default'], row['link_id'], row['is_default']))
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

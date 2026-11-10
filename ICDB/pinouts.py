"""Persistent, portable image references. ICOCR folder indexes remain disposable caches."""
from contextlib import closing
import hashlib
import json
import os
import re
import shutil
import sqlite3
from pathlib import Path
from PIL import Image
from reference_images import reference_suffix

SCHEMA = '''
CREATE TABLE IF NOT EXISTS pinout_assets(
 id INTEGER PRIMARY KEY, sha256 TEXT NOT NULL UNIQUE, path TEXT NOT NULL UNIQUE,
 original_name TEXT NOT NULL, caption TEXT NOT NULL DEFAULT '', source TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS pinout_links(
 id INTEGER PRIMARY KEY, component_id INTEGER NOT NULL REFERENCES components(id),
 asset_id INTEGER NOT NULL REFERENCES pinout_assets(id), package TEXT NOT NULL DEFAULT '',
 pin_count INTEGER CHECK(pin_count IS NULL OR pin_count>0), label TEXT NOT NULL DEFAULT '',
 is_default INTEGER NOT NULL DEFAULT 0 CHECK(is_default IN (0,1)),
 UNIQUE(component_id,asset_id,package));
CREATE UNIQUE INDEX IF NOT EXISTS pinout_one_default ON pinout_links(component_id) WHERE is_default=1;
CREATE INDEX IF NOT EXISTS pinout_asset_links ON pinout_links(asset_id);
CREATE TABLE IF NOT EXISTS pinout_settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS pinout_discovered(
 path TEXT PRIMARY KEY, mtime INTEGER, size INTEGER, asset_id INTEGER REFERENCES pinout_assets(id));
CREATE TABLE IF NOT EXISTS pinout_scan_failures(
 path TEXT PRIMARY KEY, mtime INTEGER NOT NULL, size INTEGER NOT NULL, error TEXT NOT NULL);
'''
EXTENSIONS = {'.jpg', '.jpeg', '.png', '.bmp', '.webp', '.svg'}


def migrate(db, root):
    if not db.execute("SELECT 1 FROM sqlite_master WHERE name='pinout_assets'").fetchone():
        backup = Path(root)/'backups'/'components_before_0_4.sqlite'
        backup.parent.mkdir(parents=True, exist_ok=True)
        if not backup.exists():
            with closing(sqlite3.connect(backup)) as dest:
                db.backup(dest)
    db.executescript(SCHEMA)
    from icpin_bundle import SCHEMA as BUNDLE_SCHEMA
    db.executescript(BUNDLE_SCHEMA)
    from pinout_matcher import SCHEMA as MATCH_SCHEMA, migrate_triggers
    migrate_triggers(db)
    db.executescript(MATCH_SCHEMA)
    with db:
        migrate_package_labels(db)
        from database_version import install
        install(db)


def package_name(value):
    if re.search(r'[-_ ]EP$', value.strip(), re.I):
        return package_name(re.sub(r'[-_ ]EP$', '', value.strip(), flags=re.I))+'-EP'
    key = re.sub(r'[\s_-]+', '', value.strip().upper())
    # Type I / II are physical layouts, not interchangeable TSOP aliases.
    match = re.fullmatch(r'TSOP(II|I|2|1)(?:([0-9]+))?', key)
    if match:
        family = 'TSOP-II' if match[1] in ('II','2') else 'TSOP-I'
        return family + ('-' + match[2] if match[2] else '')
    if key in ('POWERSO20','POWERSO2020'):
        return 'PowerSO20'
    # Preserve numeric package-family names before separating a pin count
    # (0.8.1: SOT-23-5 stays SOT-23-5, not SOT-235).
    match = re.fullmatch(r'(TO220|TO252|TO247|TO263AB|TO263|SOT223|SOT89|SOT323|SOT353|SOT363|SOT563|SOT23|SC70|SC88|SC74|TO92)([0-9]*)', key)
    if match:
        return NUMERIC_FAMILIES[match[1]] + ('-' + match[2] if match[2] else '')
    # Any other FAMILYnn-count written with separators (e.g. 'SOD-123-2'): split on the last separator.
    match = re.fullmatch(r'([A-Z]+)[\s_-]*([0-9]+)[\s_-]+([0-9]+)', value.strip().upper())
    if match:
        return f'{match[1]}-{match[2]}-{match[3]}'
    return re.sub(r'^([A-Z]+)([0-9]+)$', r'\1-\2', key)


NUMERIC_FAMILIES = {'TO220': 'TO-220', 'TO252': 'TO-252', 'SOT89': 'SOT-89', 'TO247': 'TO-247', 'TO263': 'TO-263',
                    'TO263AB': 'TO-263AB', 'SOT223': 'SOT-223', 'SOT323': 'SOT-323', 'SOT353': 'SOT-353',
                    'SOT363': 'SOT-363', 'SOT563': 'SOT-563', 'SOT23': 'SOT-23', 'SC70': 'SC-70', 'SC88': 'SC-88',
                    'SC74': 'SC-74', 'TO92': 'TO-92'}


def migrate_package_labels(db):
    """0.8.1: re-normalize stored labels that older releases merged (SOT-235 -> SOT-23-5). Idempotent."""
    changed = 0
    for table in ('icpin_pinouts', 'pinout_links', 'pinout_match_decisions'):
        if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone(): continue
        for (old,) in db.execute(f'SELECT DISTINCT package FROM {table}').fetchall():
            if not isinstance(old, str) or not re.fullmatch(r'(SOT|SC|TO)-[0-9]+', old): continue
            new = package_name(old)
            if new != old:
                changed += db.execute(f'UPDATE OR IGNORE {table} SET package=? WHERE package=?', (new, old)).rowcount
    return changed


class Pinouts:
    def __init__(self, db, root):
        self.db, self.root = db, Path(root).resolve()
        migrate(db, root)

    def path(self, asset):
        path = (self.root/asset['path']).resolve()
        if not path.is_relative_to(self.root/'pinouts'):
            raise ValueError('Image path is outside the managed pinouts folder')
        return path

    def import_image(self, filename):
        filename = Path(filename)
        data = filename.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        row = self.db.execute('SELECT * FROM pinout_assets WHERE sha256=?', (digest,)).fetchone()
        suffix = reference_suffix(filename)
        inside = filename.resolve().is_relative_to(self.root/'pinouts')
        relative = filename.resolve().relative_to(self.root).as_posix() if inside else 'pinouts/'+digest+suffix
        existing = self.db.execute('SELECT id FROM pinout_assets WHERE path=?',(relative,)).fetchone()
        if row and existing and row['id'] != existing['id']:
            raise ValueError('Replacement duplicates another registered image; link that image in the manager instead.')
        target = self.path(row) if row else self.root/relative
        def write():
            target.parent.mkdir(parents=True, exist_ok=True)
            if not target.exists() or hashlib.sha256(target.read_bytes()).hexdigest() != digest:
                temp = target.with_suffix('.tmp')
                try:
                    temp.write_bytes(data)
                    temp.replace(target)
                finally:
                    temp.unlink(missing_ok=True)
        if row:
            write()
            return row['id']
        # Register first and write inside the transaction: a failed insert leaves no orphan file.
        with self.db:
            if existing:
                self.db.execute('UPDATE pinout_assets SET sha256=? WHERE id=?',(digest,existing['id']))
                aid = existing['id']
            else:
                aid = self.db.execute('INSERT INTO pinout_assets(sha256,path,original_name,caption) VALUES(?,?,?,?)',
                    (digest, relative, filename.name, filename.stem)).lastrowid
            write()
        return aid

    def assets(self, term=''):
        return self.db.execute('''SELECT a.*,count(l.id) AS links FROM pinout_assets a
            LEFT JOIN pinout_links l ON a.id=l.asset_id
            WHERE a.caption LIKE ? OR a.original_name LIKE ? OR a.source LIKE ?
            GROUP BY a.id ORDER BY a.original_name,a.id''', ('%'+term+'%',)*3).fetchall()

    def link(self, asset_id, component_ids, package='', pin_count=None, label='', default=False):
        package = package_name(package)
        pin_count = int(pin_count) if str(pin_count or '').strip() else None
        if pin_count is not None and pin_count <= 0:
            raise ValueError('Pin count must be a positive integer')
        with self.db:
            for cid in set(map(int, component_ids)):
                existing = self.db.execute('SELECT id,is_default FROM pinout_links WHERE component_id=? AND asset_id=? AND package=?',
                    (cid,asset_id,package)).fetchone()
                first = not self.db.execute('SELECT 1 FROM pinout_links WHERE component_id=?',(cid,)).fetchone()
                chosen = default or first or bool(existing and existing['is_default'])
                if chosen:
                    self.db.execute('UPDATE pinout_links SET is_default=0 WHERE component_id=? AND is_default=1',(cid,))
                self.db.execute('''INSERT INTO pinout_links(component_id,asset_id,package,pin_count,label,is_default)
                    VALUES(?,?,?,?,?,?) ON CONFLICT(component_id,asset_id,package) DO UPDATE SET
                    pin_count=excluded.pin_count,label=excluded.label,is_default=excluded.is_default''',
                    (cid,asset_id,package,pin_count,label,int(chosen)))

    def links(self, component_id=None, asset_id=None):
        return self.db.execute('''SELECT l.*,c.part_number,c.manufacturer,a.original_name,a.path,a.caption,a.source
            FROM pinout_links l JOIN components c ON c.id=l.component_id JOIN pinout_assets a ON a.id=l.asset_id
            WHERE (? IS NULL OR l.component_id=?) AND (? IS NULL OR l.asset_id=?)
            ORDER BY c.part_number,l.is_default DESC,l.package,l.id''',
            (component_id,component_id,asset_id,asset_id)).fetchall()

    def unlink(self, ids):
        with self.db:
            for ident in ids:
                old = self.db.execute('SELECT component_id,is_default FROM pinout_links WHERE id=?',(ident,)).fetchone()
                self.db.execute('DELETE FROM pinout_links WHERE id=?',(ident,))
                if old and old['is_default']:
                    self.db.execute('UPDATE pinout_links SET is_default=1 WHERE id=(SELECT min(id) FROM pinout_links WHERE component_id=?)',(old['component_id'],))

    def edit_links(self, ids, **changes):
        if not changes:return
        if set(changes)-{'package','pin_count','label'}:raise ValueError('Invalid association field')
        if 'package' in changes:changes['package']=package_name(changes['package'])
        if 'pin_count' in changes:
            value=str(changes['pin_count'] or '').strip()
            changes['pin_count']=int(value) if value else None
            if changes['pin_count'] is not None and changes['pin_count']<=0:
                raise ValueError('Pin count must be positive')
        with self.db:
            for ident in ids:
                self.db.execute('UPDATE pinout_links SET '+','.join(k+'=?' for k in changes)+' WHERE id=?',
                                (*changes.values(),int(ident)))

    def set_default(self, ident):
        self.set_defaults([ident])

    def set_defaults(self, ids):
        rows=[]
        for ident in dict.fromkeys(map(int,ids)):
            row=self.db.execute('SELECT id,component_id FROM pinout_links WHERE id=?',(ident,)).fetchone()
            if not row:raise ValueError('Reference no longer exists')
            rows.append(row)
        if len({r['component_id'] for r in rows})!=len(rows):
            raise ValueError('Select only one association per device. Each device can have only one default.')
        with self.db:
            for row in rows:
                self.db.execute('UPDATE pinout_links SET is_default=0 WHERE component_id=? AND is_default=1',(row['component_id'],))
                self.db.execute('UPDATE pinout_links SET is_default=1 WHERE id=?',(row['id'],))

    def metadata(self, aid, caption, source):
        with self.db:
            self.db.execute('UPDATE pinout_assets SET caption=?,source=? WHERE id=?',(caption.strip(),source.strip(),aid))

    def setting(self, key, value=None):
        if value is not None:
            with self.db:
                self.db.execute('INSERT OR REPLACE INTO pinout_settings VALUES(?,?)',(key,value))
        row = self.db.execute('SELECT value FROM pinout_settings WHERE key=?',(key,)).fetchone()
        return row[0] if row else ''

    def scan(self, folder, retry_failed=True):
        """Discover new/changed files; never infer electrical equivalence or erase links.

        Failed files are recorded with mtime/size. Unless retry_failed, they are skipped
        silently until they change (automatic scans); manual scans retry and report them."""
        folder = Path(folder).resolve()
        if not folder.is_dir():
            raise ValueError('Pinout folder is unavailable')
        generated = self.root/'pinouts'/'icpin'
        native_generated = self.root/'pinouts'/'generated'
        added, errors = 0, []
        for base, dirs, files in os.walk(folder):
            base = Path(base)
            # Generated revisions are managed only by the bundle importer; do not descend.
            dirs[:] = sorted(d for d in dirs if not (base/d).resolve().is_relative_to(generated) and not (base/d).resolve().is_relative_to(native_generated))
            for name in sorted(files):
                path = base/name
                if path.is_symlink() or not path.is_file() or path.suffix.lower() not in EXTENSIONS:
                    continue
                try:
                    stat = path.stat()
                    old = self.db.execute('SELECT * FROM pinout_discovered WHERE path=?',(str(path),)).fetchone()
                    if old and (old['mtime'],old['size']) == (stat.st_mtime_ns,stat.st_size):
                        continue
                    failed = self.db.execute('SELECT * FROM pinout_scan_failures WHERE path=?',(str(path),)).fetchone()
                    if not retry_failed and failed and (failed['mtime'],failed['size']) == (stat.st_mtime_ns,stat.st_size):
                        continue
                    try:
                        aid = self.import_image(path)
                    except (OSError, ValueError, Image.DecompressionBombError) as exc:
                        with self.db:
                            self.db.execute('INSERT OR REPLACE INTO pinout_scan_failures VALUES(?,?,?,?)',
                                (str(path),stat.st_mtime_ns,stat.st_size,str(exc)))
                        raise
                    with self.db:
                        self.db.execute('INSERT OR REPLACE INTO pinout_discovered VALUES(?,?,?,?)',
                            (str(path),stat.st_mtime_ns,stat.st_size,aid))
                        self.db.execute('DELETE FROM pinout_scan_failures WHERE path=?',(str(path),))
                    added += 1
                except (OSError, ValueError, Image.DecompressionBombError) as exc:
                    errors.append(f'{path.name}: {exc}')
        return added, errors

    def suggestions(self):
        result = []
        devices = {}
        for row in self.db.execute('SELECT id,part_number,manufacturer FROM components WHERE part_number IS NOT NULL'):
            devices.setdefault(row['part_number'].strip().upper(), []).append(row)
        linked = {(r['asset_id'],r['component_id'],r['package']) for r in self.db.execute('SELECT asset_id,component_id,package FROM pinout_links')}
        generated = {r[0] for r in self.db.execute('SELECT asset_id FROM icpin_pinouts')}
        names = [(r['id'],r['original_name']) for r in self.assets() if r['id'] not in generated and not r['path'].startswith('pinouts/generated/')]
        names += [(r['asset_id'],Path(r['path']).name) for r in self.db.execute('SELECT * FROM pinout_discovered')]
        seen = set()
        for aid, name in names:
            fields = Path(name).stem.upper().split('__')
            if len(fields)>2:
                continue
            package = package_name(fields[1]) if len(fields)==2 else ''
            rows = devices.get(fields[0], [])
            # Ambiguous manufacturer variants need manual assignment.
            if len(rows)!=1:
                continue
            row = rows[0]; key = (aid,row['id'],package)
            if key in seen or key in linked:
                continue
            seen.add(key)
            result.append((aid,row['id'],row['part_number'],package,name))
        return result

    def import_legacy(self, config_path):
        """Explicit ICOCR mappings only; unresolved records are reported, never guessed."""
        config_path = Path(config_path).resolve()
        data = json.loads(config_path.read_text('utf-8'))
        folder = Path(data.get('folder','diagrams'))
        folder = folder if folder.is_absolute() else config_path.parent.parent/folder
        imported, skipped = 0, []
        for part, entry in data.get('devices',{}).items():
            try:
                rows = self.db.execute('SELECT id FROM components WHERE upper(trim(part_number))=?',(part.strip().upper(),)).fetchall()
                if len(rows)!=1:
                    raise ValueError('No unique exact database entry')
                path = (folder/entry['image']).resolve()
                if not path.is_relative_to(folder.resolve()):
                    raise ValueError('Image is outside the configured folder')
                aid = self.import_image(path)
                package = entry.get('package','')
                if not package and '__' in path.stem:
                    package = path.stem.split('__',1)[1]
                # Re-import does not overwrite manually edited metadata or defaults.
                if not self.db.execute('SELECT 1 FROM pinout_links WHERE component_id=? AND asset_id=? AND package=?',
                        (rows[0][0],aid,package_name(package))).fetchone():
                    self.link(aid,[rows[0][0]],package)
                    imported += 1
            except (OSError, ValueError, KeyError, TypeError) as exc:
                skipped.append(f'{part}: {exc}')
        return imported, skipped

    def export_bundle(self, folder):
        """Versioned interchange format for the planned ICOCR 0.8.4.5 reader."""
        folder = Path(folder).resolve(); folder.mkdir(parents=True,exist_ok=True)
        assets = [dict(r) for r in self.db.execute('SELECT * FROM pinout_assets ORDER BY id')]
        links = [dict(r) for r in self.db.execute('''SELECT l.*,c.part_number,c.manufacturer FROM pinout_links l
            JOIN components c ON c.id=l.component_id ORDER BY l.component_id,l.id''')]
        for asset in assets:
            source = self.path(asset)
            if not source.is_file() or hashlib.sha256(source.read_bytes()).hexdigest()!=asset['sha256']:
                raise ValueError('Missing or changed managed image: '+asset['original_name'])
        for asset in assets:
            source, target = self.path(asset), folder/asset['path']
            target.parent.mkdir(parents=True,exist_ok=True)
            if source!=target:
                shutil.copy2(source,target)
        payload = {'schema_version':1,'producer':'ICDB 0.5.2','assets':assets,'links':links}
        temp = folder/'pinout_references.json.tmp'
        temp.write_text(json.dumps(payload,ensure_ascii=False,indent=2),'utf-8')
        temp.replace(folder/'pinout_references.json')
        return len(assets),len(links)

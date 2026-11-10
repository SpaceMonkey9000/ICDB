"""Offline component catalogue builder. Python standard library only."""
import argparse, csv, functools, hashlib, io, json, re, sqlite3
from pathlib import Path
from datetime import datetime, timezone
from shared_data import data_directory, database_file

SCHEMA='''
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS sources(id INTEGER PRIMARY KEY, name TEXT, format TEXT, sha256 TEXT UNIQUE, metadata TEXT, imported_at TEXT);
CREATE TABLE IF NOT EXISTS source_lines(source_id INTEGER REFERENCES sources, line INTEGER, raw TEXT, PRIMARY KEY(source_id,line));
CREATE TABLE IF NOT EXISTS components(id INTEGER PRIMARY KEY, part_number TEXT, manufacturer TEXT NOT NULL DEFAULT '', family_hint TEXT NOT NULL DEFAULT '', UNIQUE(part_number,manufacturer));
CREATE TABLE IF NOT EXISTS entries(id INTEGER PRIMARY KEY, source_id INTEGER REFERENCES sources, line INTEGER, ordinal INTEGER, source_group TEXT, raw TEXT, part_number TEXT, package_or_interface TEXT, qualifiers TEXT, status TEXT, reason TEXT, component_id INTEGER REFERENCES components, UNIQUE(source_id,line,ordinal));
CREATE TABLE IF NOT EXISTS checks(source_id INTEGER REFERENCES sources, section TEXT, declared INTEGER, parsed INTEGER);
CREATE INDEX IF NOT EXISTS part_search ON components(part_number);
CREATE INDEX IF NOT EXISTS entry_part ON entries(component_id);
CREATE VIEW IF NOT EXISTS review_queue AS SELECT e.*,s.name AS source_name FROM entries e JOIN sources s ON s.id=e.source_id WHERE e.status!='source_listed';
'''

# Background/worker connections wait this long for another user's write lock. The interactive
# connection (Tk thread) uses UI_BUSY_TIMEOUT_SECONDS so the window never freezes for long.
BUSY_TIMEOUT_SECONDS = 30
UI_BUSY_TIMEOUT_SECONDS = 8


@functools.lru_cache(maxsize=256)
def _like_matcher(pattern, escape):
    """Compile a LIKE pattern to a predicate on case-folded text."""
    tokens = []  # literal strings and the wildcards '%' / '_' (as None-tagged tuples)
    chars = iter(pattern)
    for c in chars:
        if escape is not None and c == escape:
            tokens.append(next(chars, '').casefold())
        elif c in '%_':
            tokens.append((c,))
        else:
            tokens.append(c.casefold())
    literal = ''.join(t for t in tokens[1:-1] if isinstance(t, str))
    if (len(tokens) >= 2 and tokens[0] == ('%',) and tokens[-1] == ('%',)
            and all(isinstance(t, str) for t in tokens[1:-1])):
        return lambda value: literal in value  # the common '%text%' search
    rx = re.compile(''.join('.*' if t == ('%',) else '.' if t == ('_',) else re.escape(t) for t in tokens), re.S)
    return lambda value: rx.fullmatch(value) is not None


def unicode_like(pattern, value, escape):
    """SQL LIKE with Unicode case folding (SQLite's own LIKE folds ASCII only, so 'ö'
    never matched 'Ö' and 'µ' never matched the 'Μ' that str.upper() stores)."""
    if pattern is None or value is None:
        return None
    if escape is not None and len(escape) != 1:
        raise ValueError('ESCAPE expression must be a single character')
    if isinstance(value, bytes):
        value = value.decode('utf-8', 'replace')
    value = str(value)
    return int(_like_matcher(str(pattern), escape)(value.lower() if value.isascii() else value.casefold()))


def connect(path, timeout=BUSY_TIMEOUT_SECONDS):
    db=sqlite3.connect(path,timeout=timeout);db.row_factory=sqlite3.Row
    db.execute(f'PRAGMA busy_timeout={int(timeout*1000)}')
    # Only the ESCAPE form (used with search_pattern) is replaced; plain LIKE stays native.
    db.create_function('like', 3, unicode_like, deterministic=True)
    db.executescript(SCHEMA)
    for table in ('components', 'entries'):
        if 'function' not in {r['name'] for r in db.execute('PRAGMA table_info('+table+')')}:
            db.execute('ALTER TABLE '+table+" ADD COLUMN function TEXT NOT NULL DEFAULT ''")
    from database_version import install
    install(db)
    db.commit()
    return db

def hint(part):
    for pattern,label in [(r'^MC(?:68HC|68HCP|9S12)','Motorola/Freescale MCU naming pattern'),
        (r'^R7F70','Renesas MCU naming pattern'),(r'^(SAK|SAH)-XC','Infineon XC MCU naming pattern'),
        (r'^PIC\d','PIC MCU naming pattern'),(r'^(ATMEGA|ATTINY|AT90)','AVR naming pattern'),
        (r'^(SN)?74(?:[A-Z]{1,5})?\d','74-series logic naming pattern'),
        (r'^HCF\d','HCF naming pattern'),(r'^LM(?:V|C)?\d','LM naming pattern'),
        (r'^AD(?:A|G|C|S)?\d','AD naming pattern')]:
        if re.match(pattern,part):return label+' (inferred; unverified)'
    return ''

def part_key(value):
    """Conservative identity: retain package suffixes, punctuation and internal spaces."""
    return (value or '').strip().upper()


def function_key(value):
    return ' '.join((value or '').split()).casefold()


def check_duplicates(db):
    """Read-only report; source evidence and manufacturer variants are retained."""
    groups = {}
    for row in db.execute('SELECT id,part_number,manufacturer,function FROM components ORDER BY id'):
        key = part_key(row['part_number'])
        if key:
            groups.setdefault(key, []).append(dict(row))
    components = []
    for part, rows in sorted(groups.items()):
        if len(rows) > 1:
            manufacturers = [part_key(r['manufacturer']) for r in rows]
            components.append({'part_number': part, 'records': rows,
                'classification': 'duplicate part/manufacturer' if len(set(manufacturers)) < len(rows)
                    else 'same part, different manufacturers (review only)'})
    evidence = {}
    for row in db.execute("SELECT e.id,e.part_number,e.component_id,e.function,e.line,s.name AS source FROM entries e LEFT JOIN sources s ON s.id=e.source_id ORDER BY e.id"):
        key = (row['component_id'], part_key(row['part_number']), function_key(row['function']))
        if key[1]:
            evidence.setdefault(key, []).append(dict(row))
    return {'component_groups': components,
        'repeated_source_groups': [rows for rows in evidence.values() if len(rows) > 1]}


def import_file(db, path, fmt='csv', replace_duplicates=False):
    """Import a complete, validated two-column CSV in one transaction."""
    if fmt != 'csv':
        raise ValueError('Only two-column CSV imports are supported.')
    path = Path(path)
    data = path.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    if not replace_duplicates and db.execute('SELECT 1 FROM sources WHERE sha256=?', (digest,)).fetchone():
        return {'source': path.name, 'already_imported': True}
    text = data.decode('utf-8-sig')
    # Match csv.reader's line breaks (\r\n, \r, \n only); str.splitlines() also splits on
    # U+2028, \x0b, \x0c etc., which shifted every later raw source line.
    lines = text.replace('\r\n', '\n').replace('\r', '\n').split('\n')
    if lines and lines[-1] == '':
        lines.pop()
    # Accept comma CSV and semicolon CSV as commonly saved by Swedish Excel.
    first_line = next((line for line in lines if line.strip()), '')
    delimiter = ','
    quoted = False
    for char in first_line:
        if char == '"':
            quoted = not quoted
        elif not quoted and char in ',;':
            delimiter = char
            break
    reader = csv.reader(io.StringIO(text, newline=''), delimiter=delimiter, strict=True)
    records = []
    first = True
    try:
        while True:
            start = reader.line_num + 1
            try:
                row = next(reader)
            except StopIteration:
                break
            if not row or (len(row) == 1 and not row[0].strip()):
                continue
            if len(row) != 2:
                raise ValueError(f'Line {start}: expected 2 columns, found {len(row)}. Quote functions containing commas.')
            part, function = (cell.strip() for cell in row)
            header = (re.sub(r'[ _-]', '', part.lower()), function.lower())
            if first and header in {('partnumber', 'function'), ('part', 'function')}:
                first = False
                continue
            first = False
            if not part or not function:
                raise ValueError(f'Line {start}: part number and function must both be non-empty.')
            if any(c in part for c in '\r\n\x00') or '\x00' in function:
                raise ValueError(f'Line {start}: invalid control character.')
            records.append((start, '\n'.join(lines[start-1:reader.line_num]), part.upper(), function))
    except csv.Error as exc:
        raise ValueError(f'Invalid CSV near line {reader.line_num}: {exc}') from exc
    if not records:
        raise ValueError('CSV contains no component rows.')
    report = {'source': path.name, 'rows': len(records), 'entries': 0,
              'skipped_duplicates': 0, 'replaced_duplicates': 0, 'function_conflicts': 0, 'duplicates': []}
    with db:
        # Lock the write transaction before checking identities.
        db.execute('BEGIN IMMEDIATE')
        existing = {}
        for row in db.execute('SELECT id,part_number,function FROM components ORDER BY id'):
            existing.setdefault(part_key(row['part_number']), []).append(dict(row))
        if replace_duplicates:
            # Keep source archives immutable; an explicit reimport may reapply a prior file.
            source = db.execute('SELECT id FROM sources WHERE sha256=?', (digest,)).fetchone()
            sid = source[0] if source else db.execute(
                'INSERT INTO sources(name,format,sha256,metadata,imported_at) VALUES(?,?,?,?,?)',
                (path.name, 'csv', digest, json.dumps({'parser_version':'0.4', 'source_claim_only':True,
                 'duplicate_policy':'replace'}), datetime.now(timezone.utc).isoformat())).lastrowid
            if not source:
                db.executemany('INSERT INTO source_lines VALUES(?,?,?)', ((sid,i,l) for i,l in enumerate(lines,1)))
            seen = {}
            replaced = set()
            for line, raw, part, function in records:
                key = part_key(part)
                candidates = existing.get(key, [])
                previous = seen.get(key)
                if candidates:
                    functions = [previous[1]] if previous else [r['function'] for r in candidates]
                    conflict = not any(function_key(function) == function_key(v) for v in functions)
                    report['duplicates'].append({'line':line, 'part_number':part,
                        'location':'CSV' if previous else 'database',
                        'first_csv_line':previous[0] if previous else None,
                        'component_ids':[r['id'] for r in candidates],
                        'incoming_function':function, 'existing_functions':functions,
                        'function_conflict':conflict})
                    report['function_conflicts'] += int(conflict)
                    replaced.update(r['id'] for r in candidates)
                    db.executemany('UPDATE components SET function=? WHERE id=?',
                                   ((function,r['id']) for r in candidates))
                else:
                    cid = db.execute('INSERT INTO components(part_number,manufacturer,family_hint,function) VALUES(?,?,?,?)',
                                     (part,'',hint(part),function)).lastrowid
                    candidates = existing[key] = [{'id':cid,'function':function}]
                    report['entries'] += 1
                for candidate in candidates:
                    db.execute('''INSERT OR IGNORE INTO entries(source_id,line,ordinal,source_group,raw,part_number,
                        package_or_interface,qualifiers,status,reason,component_id,function)
                        VALUES(?,?,?,?,?,?,?,?,?,?,?,?)''',
                        (sid,line,candidate['id'],'',raw,part,'','','source_listed',
                         'CSV function supplied by user; unverified',candidate['id'],function))
                seen[key] = (line,function)
            report['replaced_duplicates'] = len(replaced)
            return report
        seen = {}
        accepted = []
        for line, raw, part, function in records:
            key = part_key(part)
            if key in seen or key in existing:
                previous = seen.get(key)
                candidates = existing.get(key, [])
                functions = [previous[1]] if previous else [r['function'] for r in candidates]
                conflict = not any(function_key(function) == function_key(f) for f in functions)
                report['duplicates'].append({'line': line, 'part_number': part,
                    'location': 'CSV' if previous else 'database',
                    'first_csv_line': previous[0] if previous else None,
                    'component_ids': [r['id'] for r in candidates],
                    'incoming_function': function, 'existing_functions': functions,
                    'function_conflict': conflict})
                report['skipped_duplicates'] += 1
                report['function_conflicts'] += int(conflict)
            else:
                accepted.append((line, raw, part, function))
            seen.setdefault(key, (line, function))
        sid = db.execute('INSERT INTO sources(name,format,sha256,metadata,imported_at) VALUES(?,?,?,?,?)',
            (path.name, 'csv', digest, json.dumps({'parser_version':'0.3', 'source_claim_only':True,
                'duplicate_report': report['duplicates']}), datetime.now(timezone.utc).isoformat())).lastrowid
        db.executemany('INSERT INTO source_lines VALUES(?,?,?)', ((sid,i,l) for i,l in enumerate(lines,1)))
        for line, raw, part, function in accepted:
            cid = db.execute('INSERT INTO components(part_number,manufacturer,family_hint,function) VALUES(?,?,?,?)',
                (part, '', hint(part), function)).lastrowid
            db.execute('INSERT INTO entries(source_id,line,ordinal,source_group,raw,part_number,package_or_interface,qualifiers,status,reason,component_id,function) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
                (sid,line,1,'',raw,part,'','','source_listed','CSV function supplied by user; unverified',cid,function))
        report['entries'] = len(accepted)
    return report

def summary(db):
    return {'components':db.execute('SELECT count(*) FROM components').fetchone()[0],
        'entries_by_status':dict(db.execute('SELECT status,count(*) FROM entries GROUP BY status')),
        'sources':[dict(r) for r in db.execute('SELECT s.name,count(e.id) entries,count(DISTINCT e.component_id) components FROM sources s LEFT JOIN entries e ON e.source_id=s.id GROUP BY s.id')],
        'count_mismatches':[dict(r) for r in db.execute('SELECT s.name,c.section,c.declared,c.parsed FROM checks c JOIN sources s ON s.id=c.source_id WHERE declared!=parsed')]}

def export(db,folder):
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    queries={'components':'SELECT * FROM components ORDER BY part_number,manufacturer',
        'review_queue':'SELECT * FROM review_queue ORDER BY source_id,line,ordinal',
        'source_entries':'SELECT e.*,s.name AS source_name FROM entries e JOIN sources s ON s.id=e.source_id ORDER BY e.id'}
    if db.execute("SELECT 1 FROM sqlite_master WHERE name='pinout_assets'").fetchone():
        queries['pinout_assets']='SELECT * FROM pinout_assets ORDER BY id'
        queries['pinout_links']='SELECT l.*,c.part_number,c.manufacturer FROM pinout_links l JOIN components c ON c.id=l.component_id ORDER BY l.id'
    for name,query in queries.items():
        cur=db.execute(query)
        with (folder/(name+'.tsv')).open('w',encoding='utf-8',newline='') as f:
            writer=csv.writer(f,delimiter='\t');writer.writerow([d[0] for d in cur.description]);writer.writerows(cur)
    (folder/'summary.json').write_text(json.dumps(summary(db),indent=2),'utf-8')


def search_pattern(text):
    """Substring search without wildcards; * and ? match any/matching-one characters.

    Use with LIKE ... ESCAPE '\\'. The text is not upper-cased (that turned µ into Μ and
    ß into SS); connect() makes LIKE case-insensitive for all scripts."""
    text = (text or '').strip()
    pattern = ''.join('%' if c == '*' else '_' if c == '?' else
                      '\\' + c if c in '%_\\' else c for c in text)
    return pattern if '*' in text or '?' in text else '%' + pattern + '%'


def add_device(db, part, function='', manufacturer=''):
    part, manufacturer = part.strip().upper(), manufacturer.strip()
    if not part:
        raise ValueError('Part number is required')
    with db:
        if db.execute('SELECT 1 FROM components WHERE upper(trim(part_number))=? AND upper(trim(manufacturer))=?',
                      (part, manufacturer.upper())).fetchone():
            raise ValueError('This part number and manufacturer already exist')
        return db.execute('INSERT INTO components(part_number,manufacturer,family_hint,function) VALUES(?,?,?,?)',
                          (part, manufacturer, hint(part), function.strip())).lastrowid


def update_device(db, cid, part, function='', manufacturer=''):
    """Edit catalogue metadata in place, retaining evidence and reference links."""
    part, manufacturer = part.strip().upper(), manufacturer.strip()
    if not part:
        raise ValueError('Part number is required')
    with db:
        old = db.execute('SELECT * FROM components WHERE id=?', (cid,)).fetchone()
        if old is None:
            raise ValueError('This device no longer exists')
        if db.execute('SELECT 1 FROM components WHERE upper(trim(part_number))=? AND upper(trim(manufacturer))=? AND id!=?',
                      (part, manufacturer.upper(), cid)).fetchone():
            raise ValueError('This part number and manufacturer already exist')
        family = old['family_hint'] if part == old['part_number'] else hint(part)
        db.execute('UPDATE components SET part_number=?,function=?,manufacturer=?,family_hint=? WHERE id=?',
                   (part, function.strip(), manufacturer, family, cid))
    return cid


def delete_devices(db, ids):
    """Remove devices, their evidence entries and links, retaining source archives/images."""
    with db:
        for cid in set(map(int, ids)):
            if db.execute("SELECT 1 FROM sqlite_master WHERE name='pinout_links'").fetchone():
                db.execute('DELETE FROM pinout_links WHERE component_id=?', (cid,))
            # Component ids can be reused; an old match decision must not apply to a new part.
            if db.execute("SELECT 1 FROM sqlite_master WHERE name='pinout_match_decisions'").fetchone():
                db.execute('DELETE FROM pinout_match_decisions WHERE component_id=?', (cid,))
            db.execute('DELETE FROM entries WHERE component_id=?', (cid,))
            db.execute('DELETE FROM components WHERE id=?', (cid,))


def main():
    p=argparse.ArgumentParser();p.add_argument('--db',default=str(database_file(data_directory(Path(__file__).resolve().parent))));sub=p.add_subparsers(dest='command',required=True)
    imp=sub.add_parser('import');imp.add_argument('--format',choices=['csv'],default='csv');imp.add_argument('--replace-duplicates',action='store_true');imp.add_argument('file')
    sub.add_parser('duplicates');sub.add_parser('summary');ex=sub.add_parser('export');ex.add_argument('folder');find=sub.add_parser('find');find.add_argument('part')
    args=p.parse_args();db=connect(args.db)
    if args.command=='import':print(json.dumps(import_file(db,args.file,args.format,replace_duplicates=args.replace_duplicates),indent=2))
    elif args.command=='duplicates':print(json.dumps(check_duplicates(db),indent=2))
    elif args.command=='summary':print(json.dumps(summary(db),indent=2))
    elif args.command=='export':export(db,args.folder)
    else:
        for r in db.execute("SELECT * FROM components WHERE part_number LIKE ? ESCAPE '\\' LIMIT 100",(search_pattern(args.part),)):print(dict(r))
    db.close()
if __name__=='__main__':main()

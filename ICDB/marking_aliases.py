"""Experimental exact top-mark catalogue."""
import json
import re

SCHEMA = """CREATE TABLE IF NOT EXISTS component_marking_aliases(
    marking TEXT NOT NULL,
    component_id INTEGER NOT NULL REFERENCES components(id) ON DELETE CASCADE,
    packages_json TEXT NOT NULL,
    source TEXT NOT NULL,
    PRIMARY KEY(marking, component_id))"""


def alias_record(marking, packages, source):
    marking = marking.strip().upper()
    if not re.fullmatch(r'[A-Z0-9][A-Z0-9 ./+_-]{0,63}', marking):
        raise ValueError('Enter a marking of up to 64 letters, digits or marking punctuation.')
    packages = sorted({part.strip().upper() for part in packages.split(',') if part.strip()})
    if any(not re.fullmatch(r'[A-Z][A-Z0-9-]{0,31}', p) for p in packages):
        raise ValueError('Enter comma-separated package labels, such as TSSOP-16, SSOP-16.')
    return dict(marking=marking, packages=packages, source=source.strip())


def save_aliases(db, drafts):
    for draft in drafts:
        row = db.execute('SELECT part_number,manufacturer FROM components WHERE id=?',
                         (draft['component_id'],)).fetchone()
        if row is None or list(row) != draft['identity']:
            raise ValueError(f"Target for {draft['marking']} changed. Select the target again.")
        key = (draft['marking'], draft['component_id'])
        if 'before' in draft:
            row = db.execute('SELECT packages_json,source FROM component_marking_aliases '
                             'WHERE marking=? AND component_id=?', key).fetchone()
            current = dict(packages=json.loads(row[0]), source=row[1]) if row else None
            if current != draft['before']:
                raise ValueError(f"Alias {draft['marking']} changed since it was staged.")
        if draft.get('remove'):
            db.execute('DELETE FROM component_marking_aliases WHERE marking=? AND component_id=?', key)
            continue
        db.execute("""INSERT INTO component_marking_aliases VALUES(?,?,?,?)
                   ON CONFLICT(marking,component_id) DO UPDATE
                   SET packages_json=excluded.packages_json,source=excluded.source""",
                   (draft['marking'], draft['component_id'], json.dumps(draft['packages']),
                    draft['source']))

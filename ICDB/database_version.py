"""Persistent content revision; SQLite triggers also cover worker/external writes.

The version displays the last edit date and the cumulative count of changed
records. Both are updated in the same transaction as the content change.
"""
import json
from pathlib import Path

CONTENT_TABLES = (
    'components', 'component_marking_aliases', 'entries', 'sources', 'source_lines', 'checks',
    'pinout_assets', 'pinout_links', 'icpin_pinouts', 'icpin_bundles',
    'icpin_sources', 'pinout_verified_mappings', 'pinout_match_decisions',
    'pl_definitions', 'pl_sources', 'pl_conflicts', 'pl_assignments',
    'pl_publications', 'pl_ignored_imports',
)


def initial_base(db):
    """Legacy installers record the active DB release separately from pack updates."""
    filename = db.execute('PRAGMA database_list').fetchone()[2]
    if filename:
        folder = Path(filename).parent
        if folder.name.lower() == 'db': folder = folder.parent
        try:
            state = json.loads((folder/'data-pack-installed.json').read_text('utf-8-sig'))
            value = state.get('database_version')
            if isinstance(value,str) and value and value[0].isdigit(): return value
        except (OSError, ValueError, AttributeError): pass
    return 'Unversioned'


def install(db):
    """Call after schema creation, inside the caller's initialization transaction."""
    db.execute('CREATE TABLE IF NOT EXISTS icdb_database_version '
               '(id INTEGER PRIMARY KEY CHECK(id=1), base TEXT NOT NULL, '
               'revision INTEGER NOT NULL DEFAULT 0 CHECK(revision>=0), last_edited TEXT)')
    db.execute('INSERT OR IGNORE INTO icdb_database_version (id,base,revision) VALUES(1,?,0)',
               (initial_base(db),))
    migrating = 'last_edited' not in {
        row[1] for row in db.execute('PRAGMA table_info(icdb_database_version)')
    }
    if migrating:
        db.execute('ALTER TABLE icdb_database_version ADD COLUMN last_edited TEXT')
    tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    for table in CONTENT_TABLES:
        if table not in tables:
            continue
        columns = [r[1] for r in db.execute(f'PRAGMA table_info("{table}")')]
        changed = ' OR '.join(f'OLD."{c}" IS NOT NEW."{c}"' for c in columns)
        for action in ('INSERT', 'UPDATE', 'DELETE'):
            condition = ' WHEN '+changed if action == 'UPDATE' else ''
            name = f'icdb_rev_{table}_{action.lower()}'
            if migrating:
                db.execute(f'DROP TRIGGER IF EXISTS "{name}"')
            db.execute(f'CREATE TRIGGER IF NOT EXISTS "{name}" '
                       f'AFTER {action} ON "{table}"{condition} BEGIN '
                       'UPDATE icdb_database_version '
                       "SET revision=revision+1, last_edited=date('now','localtime') WHERE id=1; END")


def database_version(db):
    last_edited, revision = db.execute(
        'SELECT last_edited,revision FROM icdb_database_version WHERE id=1').fetchone()
    return f'{last_edited or "Date unknown"}-r{revision}'

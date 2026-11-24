"""Preview and replay an ordered selection of CSV and ICDB JSON files."""
from pathlib import Path

from builder import import_file
from component_json import check_preview, identity, plan_batch, read_batch
from qt_component_csv import preview_component_csv


ACTIONS = frozenset(('New', 'New part', 'New pinout', 'Reused pinout',
                     'New assignment', 'New marking alias', 'Set default preference'))
PUBLISH_ACTIONS = frozenset(('New assignment', 'Set default preference'))


def preview_files(library, paths, progress, components=None):
    """components: a staged ComponentDraft payload. Save writes staged component changes
    before the import, so the preview applies them first in the same way; without
    this a staged import could never be saved next to an overlapping staged component."""
    files = []
    db = library.db
    # Plan against the effects of earlier files using the same writes as Save.
    # The planning transaction is always rolled back and never publishes SVGs.
    db.execute('BEGIN IMMEDIATE')
    try:
        if components:
            from qt_component_draft import ComponentDraft
            staged = ComponentDraft()
            staged.restore(db, dict(components, pending_import=None))
            created = staged.apply_locked(db)
            staged.apply_aliases_locked(db, created)
        for index, source in enumerate(paths, 1):
            entry = source if isinstance(source, dict) else {'path': source, 'kind': Path(source).suffix.lower()}
            files.append(plan_file(library, entry))
            progress(index, len(paths))
        return files
    finally:
        db.rollback()


def plan_file(library, entry, *, replay=False):
    path = entry['path']
    db = library.db
    try:
        if entry['kind'] == '.csv':
            excluded = set(entry.get('excluded_lines', ()))
            result = preview_component_csv(db, path, excluded_lines=excluded)
            digest = result['sha256']
            rows = [row[1:] for row in result['rows']]
            if result['already_imported']:
                rows = [(part, description, 'Previously imported', 'Exact CSV content already imported')
                        for part, description, _, _ in rows]
            if digest != entry.get('digest', digest):
                raise ValueError('CSV content changed since preview. Choose the files again.')
            if replay:
                check_preview(rows, entry['rows'])
            if any(row[2] == 'New' for row in rows):
                import_file(db, path, expected_sha256=digest, locked=True, excluded_lines=excluded)
            return dict(entry, digest=digest, rows=rows, row_keys=[row[0] for row in result['rows']])
        if entry['kind'] == '.json':
            batch = entry['batch'] if 'batch' in entry else read_batch(path)
            keys = []
            rows = plan_batch(library, batch, apply=True, row_keys=keys)
            if replay:
                check_preview(rows, entry['rows'])
            return dict(entry, batch=batch, rows=rows, row_keys=keys)
        raise ValueError('Expected a CSV or ICDB JSON file.')
    except Exception as exc:
        raise ValueError(f'{path}: {exc}') from exc


def exclude_rows(entry, keys):
    """Remove selected input records before replanning the whole selection."""
    if entry['kind'] == '.csv':
        return dict(entry, excluded_lines=sorted(set(entry.get('excluded_lines', ())) | keys))

    parts, pinouts = entry['batch']
    removed = {identity(part) for i, part in enumerate(parts) if ('part', i) in keys}
    kept_parts = []
    for i, part in enumerate(parts):
        if ('part', i) not in keys:
            aliases = [alias for j, alias in enumerate(part.get('marking_aliases', ()))
                       if ('alias', i, j) not in keys]
            kept_parts.append(dict(part, marking_aliases=aliases))

    kept_pinouts = []
    removed_numbers = {number for number, _ in removed}
    removed_numbers -= {identity(part)[0] for part in kept_parts}
    for i, pinout in enumerate(pinouts):
        if ('pinout', i) in keys:
            continue
        devices = []
        remaining_targets = False
        for j, device in enumerate(pinout.get('devices', ())):
            key = identity(device)
            removed_part = (key in removed if 'manufacturer' in device
                            else key[0] in removed_numbers)
            remaining_targets |= not removed_part
            if ('device', i, j) not in keys and not removed_part:
                devices.append(device)
        if remaining_targets or not pinout.get('devices'):
            kept_pinouts.append(dict(pinout, devices=devices))
    return dict(entry, batch=(kept_parts, kept_pinouts))

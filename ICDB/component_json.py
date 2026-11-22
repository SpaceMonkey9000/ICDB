"""Portable ICDB parts and editable pinout batches."""
from collections import defaultdict
import json
from pathlib import Path
import tempfile
import uuid

from builder import hint
from marking_aliases import alias_record, save_aliases
from pin_library import package_label, render_issue, signature, validate_data

FORMAT = 'icdb-data'
VERSION = 3


def field(record, name, default=None, required=False):
    value = record.get(name, default)
    if not isinstance(value, str) or '\x00' in value or (required and not value.strip()):
        raise ValueError(f'Invalid {name}: expected text' + (' with a value' if required else ''))
    return value


def objects(record, name):
    values = record.get(name, [])
    if not isinstance(values, list) or any(not isinstance(value, dict) for value in values):
        raise ValueError(f'{name} must be a list of objects.')
    return values


def identity(record):
    return (field(record, 'part_number', required=True).strip().casefold(),
            field(record, 'manufacturer', '').strip().casefold())


def read_batch(path):
    batch = json.loads(Path(path).read_text(encoding='utf-8-sig'))
    if (not isinstance(batch, dict) or batch.get('format') != FORMAT
            or type(batch.get('version')) is not int or batch['version'] not in (1, 2, VERSION)):
        raise ValueError('Expected an ICDB data JSON file, version 1, 2 or 3.')
    parts, pinouts = objects(batch, 'parts'), objects(batch, 'pinouts')
    part_keys, pinout_ids = set(), set()
    for part in parts:
        key = identity(part)
        if key in part_keys:
            raise ValueError(f'Duplicate part in file: {part["part_number"]}')
        part_keys.add(key)
        field(part, 'description', '')
        aliases = []
        for alias in objects(part, 'marking_aliases'):
            packages = alias.get('packages', [])
            if not isinstance(packages, list) or any(not isinstance(p, str) or ',' in p for p in packages):
                raise ValueError('Alias packages must be a list of package labels.')
            aliases.append(alias_record(field(alias, 'marking', required=True), ','.join(packages),
                                        field(alias, 'source', '')))
        if len({a['marking'] for a in aliases}) != len(aliases):
            raise ValueError(f'Duplicate marking alias on {part["part_number"]}.')
        if aliases:
            part['marking_aliases'] = aliases
    for item in pinouts:
        ident = field(item, 'id', required=True)
        if ident in pinout_ids:
            raise ValueError(f'Duplicate pinout ID: {ident}')
        pinout_ids.add(ident)
        devices = []
        for device in objects(item, 'devices'):
            identity(device)
            if batch['version'] < VERSION and device.get('status') != 'Accepted':
                continue
            if 'is_default' in device and type(device['is_default']) is not bool:
                raise ValueError(f'{ident}: is_default must be true or false.')
            devices.append({k: device[k] for k in ('part_number', 'manufacturer', 'is_default') if k in device})
        item['devices'] = devices
        project = item.get('project')
        if not isinstance(project, dict):
            raise ValueError(f'{ident}: project must be an object.')
        field(project, 'source', '')
        if 'verified' in project and type(project['verified']) is not bool:
            raise ValueError(f'{ident}: verified must be true or false.')
        for pin in objects(project, 'pins'):
            field(pin, 'description', '')
            field(pin, 'role', 'Signal')
        try:
            validate_data(project)
        except ValueError as exc:
            raise ValueError(f'{ident}: {exc}') from exc
    return parts, pinouts


def records(db):
    return db.execute("""SELECT id, part_number, manufacturer, function AS description
                         FROM components WHERE trim(part_number) <> '' ORDER BY id""")


def process_batch(library, batch, apply=False, expected=None):
    """Preview and commit use the same planner. Commit rechecks the reviewed plan."""
    db = library.db
    db.execute('BEGIN IMMEDIATE' if apply else 'BEGIN')
    try:
        rows = plan_batch(library, batch, apply)
        if apply:
            check_preview(rows, expected)
            db.commit()
        else:
            db.rollback()
        return rows
    except BaseException:
        db.rollback()
        raise


def check_preview(rows, expected):
    # Journal JSON restores rows as lists.
    if len(rows) != len(expected) or any(tuple(a) != tuple(b) for a, b in zip(rows, expected)):
        raise ValueError('Import results changed since preview. Revert the staged batch and preview it again.')


def plan_batch(library, batch, apply, *, row_keys=None):
    db = library.db
    parts, pinouts = batch
    components = defaultdict(list)
    by_number = defaultdict(list)
    for row in records(db):
        part = dict(row)
        key = identity(part)
        components[key].append(part)
        by_number[key[0]].append(part)

    saved_aliases = {(r['component_id'], r['marking']): (json.loads(r['packages_json']), r['source'])
                     for r in db.execute('SELECT * FROM component_marking_aliases')}
    rows = []
    for index, part in enumerate(parts, 1):
        name = part['part_number'].strip()
        manufacturer = part.get('manufacturer', '').strip()
        description = part.get('description', '')
        key = identity(part)
        found = components[key]
        if len(found) > 1 or (found and found[0]['description'] != description):
            status = 'Conflict'
            details = 'Multiple matching parts' if len(found) > 1 else 'Existing description differs'
        elif found:
            status, details = 'Unchanged', manufacturer
        else:
            status, details = 'New part', manufacturer
            cid = -index
            if apply:
                cid = db.execute("""INSERT INTO components(part_number, manufacturer, family_hint, function)
                                    VALUES(?, ?, ?, ?)""", (name, manufacturer, hint(name), description)).lastrowid
            record = dict(part, id=cid, part_number=name, manufacturer=manufacturer)
            found.append(record)
            by_number[key[0]].append(record)
        rows.append((name, description, status, details))
        if row_keys is not None:
            row_keys.append(('part', index-1))
        for alias_index, alias in enumerate(part.get('marking_aliases', [])):
            if row_keys is not None:
                row_keys.append(('alias', index-1, alias_index))
            marking = alias['marking']
            if len(found) != 1:
                rows.append((marking, name, 'Conflict', 'Multiple matching alias targets'))
                continue
            target = found[0]
            current = saved_aliases.get((target['id'], marking))
            desired = (alias['packages'], alias['source'])
            if current is not None:
                action = 'Unchanged' if current == desired else 'Conflict'
                rows.append((marking, name, action, 'Existing marking alias'))
                continue
            rows.append((marking, name, 'New marking alias', ', '.join(alias['packages'])))
            if apply:
                save_aliases(db, [dict(alias, component_id=target['id'],
                                       identity=[target['part_number'], target['manufacturer']])])

    definitions = {r['signature']: r['id'] for r in db.execute('SELECT signature, id FROM pl_definitions')}
    links, assigned = {}, defaultdict(set)
    packages = {}
    incoming_defaults = {}
    for row in db.execute("""SELECT a.*, d.project_json, l.is_default AS published_default
        FROM pl_assignments a JOIN pl_definitions d ON d.id=a.definition_id
        LEFT JOIN pl_publications p ON p.assignment_id=a.id
        LEFT JOIN pinout_links l ON l.id=p.link_id"""):
        cid, ident = row['component_id'], row['definition_id']
        default = row['is_default']
        links[cid, ident] = default if default is not None else row['published_default']
        if ident not in packages:
            packages[ident] = package_label(json.loads(row['project_json']))
        assigned[cid, packages[ident]].add(ident)
    for index, item in enumerate(pinouts, 1):
        if row_keys is not None:
            row_keys.append(('pinout', index-1))
        external_id, data = item['id'], item['project']
        existing = db.execute("""SELECT d.id, d.project_json FROM pl_json_ids j JOIN pl_definitions d
                                 ON d.id = j.definition_id WHERE j.external_id = ?""", (external_id,)).fetchone()
        package = package_label(data)
        sig = signature(data)
        definition_id = definitions.get(sig, -index)
        if existing and signature(json.loads(existing['project_json'])) != sig:
            rows.append((data['device'], package, 'Conflict', f'Pinout ID already has different data: {external_id}'))
            continue
        status = 'Unchanged' if existing else 'Reused pinout' if sig in definitions else 'New pinout'
        problem = render_issue(data)
        rows.append((data['device'], package, status, problem or ''))
        if apply:
            definition_id, _ = library._definition(data)
            db.execute('INSERT OR IGNORE INTO pl_json_ids VALUES(?, ?)', (external_id, definition_id))
        definitions[sig] = definition_id

        for device_index, device in enumerate(item.get('devices', [])):
            if row_keys is not None:
                row_keys.append(('device', index-1, device_index))
            key = identity(device)
            found = components[key] if 'manufacturer' in device else by_number[key[0]]
            name = device['part_number']
            if len(found) != 1:
                reason = 'Multiple matching parts' if found else 'Part not found'
                rows.append((name, package, 'Unresolved link', reason))
                continue
            cid = found[0]['id']
            key = (cid, definition_id)
            default = device.get('is_default')
            existing_link = key in links
            if default:
                other = incoming_defaults.setdefault(cid, definition_id)
                if other != definition_id:
                    raise ValueError(f'{name} has more than one default pinout in the import.')
            if existing_link and (default is None or links[key] == default):
                rows.append((name, package, 'Unchanged', 'Existing assignment'))
                continue
            reason = problem
            if assigned[cid, package] - {definition_id}:
                reason = 'A different pinout is already assigned for this part and package'
            if reason:
                rows.append((name, package, 'Conflict', reason))
                continue
            assigned[cid, package].add(definition_id)
            action = 'Set default preference' if existing_link else 'New assignment'
            detail = 'Default pinout' if default else 'Non-default pinout' if default is False else ''
            rows.append((name, package, action, detail))
            links[key] = default
            if apply:
                if default:
                    db.execute('UPDATE pl_assignments SET is_default=0 WHERE component_id=? AND definition_id<>? AND is_default=1',
                               key)
                db.execute("""INSERT INTO pl_assignments(component_id,definition_id,is_default)
                    VALUES(?,?,?) ON CONFLICT(component_id,definition_id) DO UPDATE SET is_default=excluded.is_default""",
                    (*key, default))
    return rows


def export_batch(library, path, selected=None):
    db = library.db
    with library._transaction():
        selected = None if selected is None else set(selected)
        parts = {row['id']: {'part_number': row['part_number'], 'manufacturer': row['manufacturer'],
                             'description': row['description']} for row in records(db)
                 if selected is None or row['id'] in selected}
        if selected is not None and selected != parts.keys():
            raise ValueError('The component selection changed. Refresh and select the parts again.')
        for alias in db.execute('SELECT * FROM component_marking_aliases ORDER BY marking'):
            if alias['component_id'] in parts:
                parts[alias['component_id']].setdefault('marking_aliases', []).append(dict(
                    marking=alias['marking'], packages=json.loads(alias['packages_json']), source=alias['source']))
        devices = defaultdict(list)
        for row in db.execute("""SELECT a.definition_id,a.component_id,coalesce(a.is_default,l.is_default) AS is_default
            FROM pl_assignments a LEFT JOIN pl_publications p ON p.assignment_id=a.id
            LEFT JOIN pinout_links l ON l.id=p.link_id ORDER BY a.component_id"""):
            if row['component_id'] in parts:
                part = parts[row['component_id']]
                device = {key: part[key] for key in ('part_number', 'manufacturer')}
                if row['is_default'] is not None:
                    device['is_default'] = bool(row['is_default'])
                devices[row['definition_id']].append(device)
        identities = {}
        for row in db.execute('SELECT external_id, definition_id FROM pl_json_ids ORDER BY rowid'):
            identities.setdefault(row['definition_id'], row['external_id'])
        pinouts = []
        for row in db.execute('SELECT id, project_json FROM pl_definitions ORDER BY id'):
            ident = row['id']
            if selected is not None and ident not in devices:
                continue
            external_id = identities.get(ident)
            if external_id is None:
                external_id = str(uuid.uuid4())
                db.execute('INSERT INTO pl_json_ids VALUES(?, ?)', (external_id, ident))
            pinouts.append({'id': external_id, 'devices': devices[ident],
                            'project': json.loads(row['project_json'])})
        payload = {'format': FORMAT, 'version': VERSION, 'parts': list(parts.values()), 'pinouts': pinouts}

    destination = Path(path)
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=destination.parent,
                                         delete=False) as temp:
            temp_path = Path(temp.name)
            json.dump(payload, temp, ensure_ascii=False, indent=2)
            temp.write('\n')
        temp_path.replace(destination)
    finally:
        if temp_path:
            temp_path.unlink(missing_ok=True)
    return len(parts), len(pinouts)

"""Pure-python staged component editor. All mutations are applied by caller transaction.

Snapshots provide optimistic concurrency checks and prevent silently overwriting edits
from other ICDB/ICOCR processes. Staging has no SQL write side effects.
"""
from copy import deepcopy
import json

from marking_aliases import save_aliases

FIELDS = ('part_number', 'function', 'manufacturer')


class ComponentDraft:
    def __init__(self):
        self.edits = {}  # existing component id -> {'before': ..., 'after': ...}
        self.deleted = {}  # existing component id -> original database snapshot
        self.added = {}  # negative temporary id -> fields
        self.next_temp = -1
        self.pending_import = None
        self.aliases = []

    @property
    def changed(self):
        return bool(self.edits or self.deleted or self.added or self.pending_import or self.aliases)

    @staticmethod
    def snapshot(db, cid):
        row = db.execute('SELECT part_number,function,manufacturer FROM components WHERE id=?', (cid,)).fetchone()
        if row is None:
            raise ValueError(f'Component {cid} no longer exists')
        return {field: row[field] or '' for field in FIELDS}

    def add(self, part, function='', manufacturer=''):
        item = dict(zip(FIELDS, (part, function, manufacturer)))
        self._normalize(item)
        cid = self.next_temp
        self.next_temp -= 1
        self.added[cid] = item
        return cid

    def update(self, db, cid, **changes):
        if any(key not in FIELDS for key in changes):
            raise ValueError('Unsupported component field')
        if cid in self.deleted:
            raise ValueError('Component is staged for deletion')
        if cid < 0:
            item = self.added[cid].copy()
            item.update(changes)
            self._normalize(item)
            self.added[cid] = item
            return
        if cid not in self.edits:
            baseline = self.snapshot(db, cid)
            self.edits[cid] = {'before': baseline, 'after': baseline.copy()}
        state = self.edits[cid]
        updated = state['after'].copy()
        updated.update(changes)
        self._normalize(updated)
        state['after'] = updated
        if state['after'] == state['before']:
            del self.edits[cid]

    def delete(self, db, cid):
        self.delete_many(db, (cid,))

    def delete_many(self, db, ids):
        ids = set(ids)
        # Resolve every baseline before changing the draft.
        snapshots = {
            cid: self.edits[cid]['before'] if cid in self.edits else self.snapshot(db, cid)
            for cid in ids if cid >= 0 and cid not in self.deleted
        }
        self.aliases[:] = [row for row in self.aliases if row['component_id'] not in ids]
        for cid in ids:
            self.added.pop(cid, None)
            self.edits.pop(cid, None)
        self.deleted.update(snapshots)

    @staticmethod
    def _saved_aliases(db, cid):
        return {marking: dict(packages=json.loads(packages), source=source)
                for marking, packages, source in db.execute(
                    'SELECT marking,packages_json,source FROM component_marking_aliases WHERE component_id=?',
                    (cid,))}

    def alias_view(self, db, cid):
        saved = self._saved_aliases(db, cid)
        visible = {marking: dict(data, staged=False) for marking, data in saved.items()}
        for row in self.aliases:
            if row['component_id'] != cid:
                continue
            marking = row['marking']
            data = saved.get(marking) if row.get('remove') else row
            if data is not None:
                visible[marking] = dict(packages=data['packages'], source=data['source'],
                                        staged=True, remove=row.get('remove', False))
        return visible

    def change_alias(self, db, cid, *, original=None, replacement=None):
        if cid in self.deleted:
            raise ValueError('Component is staged for deletion.')
        if cid in self.added:
            row = tuple(self.added[cid][field] for field in ('part_number', 'manufacturer'))
        else:
            row = db.execute('SELECT part_number,manufacturer FROM components WHERE id=?', (cid,)).fetchone()
            if row is None:
                raise ValueError('The target component no longer exists.')
        saved = self._saved_aliases(db, cid)
        existing = {item['marking']: item for item in self.aliases if item['component_id'] == cid}
        marking = replacement['marking'] if replacement else None
        if marking and marking != original:
            if (marking in existing or marking in saved) and not existing.get(marking, {}).get('remove'):
                raise ValueError(f'Alias {marking} already exists for this component.')
        changes = {original: None} if original and original != marking else {}
        if replacement is not None:
            changes[marking] = dict(packages=replacement['packages'], source=replacement['source'])
        for key, after in changes.items():
            prior = existing.get(key, {})
            before = prior.get('before', saved.get(key))
            if prior:
                self.aliases.remove(prior)
            if before != after:
                self.aliases.append(dict(marking=key, component_id=cid, identity=list(row),
                                         before=before, remove=after is None, **(after or {})))

    def apply_aliases_locked(self, db, created_ids=None):
        # Component edits have already validated their original identities and been applied.
        if not db.in_transaction:
            raise RuntimeError('Alias writes require caller-owned SQLite transaction')
        for draft in self.aliases:
            cid = draft['component_id']
            if cid < 0:
                component = self.added[cid]
                draft = dict(draft, component_id=(created_ids or {})[cid],
                             identity=[component[key] for key in ('part_number', 'manufacturer')])
            edit = self.edits.get(draft['component_id'])
            if edit and draft['identity'] == [edit['before'][key] for key in ('part_number', 'manufacturer')]:
                draft = dict(draft, identity=[edit['after'][key] for key in ('part_number', 'manufacturer')])
            save_aliases(db, [draft])

    def find_duplicate(self, db, part, manufacturer, ignore=None):
        """Return the part number of another component, saved or staged, with the same
        part number and manufacturer (case-insensitive), as Save would refuse it; else None.
        `ignore` is the component being edited."""
        key = (str(part).strip().upper(), str(manufacturer).strip().upper())
        if not key[0]:
            return None
        staged = {cid: state['after'] for cid, state in self.edits.items()}
        staged.update(self.added)
        for cid, values in staged.items():
            if cid != ignore and (values['part_number'].upper(), values['manufacturer'].upper()) == key:
                return values['part_number']
        for row in db.execute('SELECT id,part_number FROM components WHERE upper(part_number)=? '
                              'AND upper(coalesce(manufacturer,\'\'))=?', key):
            cid = row[0]
            if cid != ignore and cid not in self.deleted and cid not in self.edits:
                return row[1]
        return None

    def view(self, cid, row):
        if cid in self.deleted:
            return None
        if cid in self.edits:
            return self.edits[cid]['after']
        return row

    def clear(self):
        self.edits.clear()
        self.deleted.clear()
        self.added.clear()
        self.next_temp = -1
        self.pending_import = None
        self.aliases = []

    @staticmethod
    def _normalize(item):
        item['part_number'] = str(item['part_number']).strip().upper()
        item['function'] = str(item['function']).strip()
        item['manufacturer'] = str(item['manufacturer']).strip()
        if not item['part_number']:
            raise ValueError('Part number is required')

    def payload(self):
        return {'edits': deepcopy(self.edits), 'deleted': deepcopy(self.deleted),
                'added': deepcopy(self.added), 'next_temp': self.next_temp,
                'pending_import': deepcopy(self.pending_import), 'aliases': deepcopy(self.aliases)}

    def restore(self, db, payload):
        edits = {int(k): v for k, v in payload['edits'].items()}
        deleted = {int(k): v for k, v in payload['deleted'].items()}
        added = {int(k): v for k, v in payload['added'].items()}
        for cid, state in edits.items():
            if self.snapshot(db, cid) != state['before']:
                raise ValueError(f'Component {cid} changed since draft was saved')
            self._normalize(state['after'])
        for cid, before in deleted.items():
            if self.snapshot(db, cid) != before:
                raise ValueError(f'Component {cid} changed since draft was saved')
        for item in added.values():
            self._normalize(item)
        self.edits, self.deleted, self.added = edits, deleted, added
        self.pending_import = payload.get('pending_import')
        self.aliases = payload.get('aliases', [])
        self.next_temp = min(int(payload.get('next_temp', -1)), *(added.keys() or [-1])) - 1

    def apply_locked(self, db):
        """Caller MUST own BEGIN IMMEDIATE; raises to roll back the entire transaction."""
        if not db.in_transaction:
            raise RuntimeError('Component writes require caller-owned SQLite transaction')
        from builder import hint
        for cid, state in self.edits.items():
            if self.snapshot(db, cid) != state['before']:
                raise ValueError(f'Component {cid} was modified externally; reload before saving')
        for cid, before in self.deleted.items():
            if self.snapshot(db, cid) != before:
                raise ValueError(f'Component {cid} was modified externally; reload before saving')
        # Validate all new names against existing rows and each other, excluding staged deletions.
        owners = {}
        for row in db.execute('SELECT id,part_number,manufacturer FROM components'):
            if row['id'] not in self.deleted:
                owners[(str(row['part_number'] or '').strip().upper(),
                        str(row['manufacturer'] or '').strip().upper())] = row['id']
        for cid, state in self.edits.items():
            old = state['before']
            owners.pop((old['part_number'].strip().upper(), old['manufacturer'].strip().upper()), None)
        for cid, values in [*[(cid, v['after']) for cid, v in self.edits.items()], *self.added.items()]:
            key = (values['part_number'].upper(), values['manufacturer'].upper())
            if key in owners:
                raise ValueError(f'Duplicate component: {values["part_number"]} ({values["manufacturer"]})')
            owners[key] = cid
        if self.deleted:
            # Delete the same linked records as the legacy builder helper.
            ids = [(cid,) for cid in sorted(self.deleted)]
            tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            for table in ('pinout_links', 'pinout_match_decisions'):
                if table in tables:
                    db.executemany(f'DELETE FROM {table} WHERE component_id=?', ids)
            db.executemany('DELETE FROM entries WHERE component_id=?', ids)
            db.executemany('DELETE FROM components WHERE id=?', ids)
        for cid, state in self.edits.items():
            new, old = state['after'], state['before']
            family = (db.execute('SELECT family_hint FROM components WHERE id=?', (cid,)).fetchone()[0]
                      if new['part_number'] == old['part_number'] else hint(new['part_number']))
            db.execute('UPDATE components SET part_number=?,function=?,manufacturer=?,family_hint=? WHERE id=?',
                       (new['part_number'], new['function'], new['manufacturer'], family, cid))
        created = {}
        for temp_id, item in self.added.items():
            cursor = db.execute('INSERT INTO components(part_number,manufacturer,family_hint,function) VALUES(?,?,?,?)',
                       (item['part_number'], item['manufacturer'], hint(item['part_number']), item['function']))
            created[temp_id] = cursor.lastrowid
        return created

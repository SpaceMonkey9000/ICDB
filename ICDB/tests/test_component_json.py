import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from builder import connect
from component_json import export_batch, process_batch, read_batch
from pin_library import Library
from pinouts import Pinouts


class ComponentJsonTests(TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root / 'parts.json'
        self.source = self.library('source')
        self.target = self.library('target')
        self.devices = [{'part_number': name, 'manufacturer': 'Example'} for name in ('A', 'B')]
        self.pinout = {
            'id': 'example-qfn4',
            'devices': self.devices,
            'project': {
                'device': 'A/B', 'package': 'QFN', 'count': 4, 'source': 'Datasheet p. 2',
                'pins': [{'number': n, 'name': name}
                         for n, name in enumerate(('IN', 'GND', 'OUT', 'NC'), 1)],
                'exposed_pad': {'number': 'EP', 'name': 'GND'},
            },
        }

    def library(self, name):
        path = self.root / name
        path.mkdir()
        db = connect(path / 'components.sqlite')
        self.addCleanup(db.close)
        return Library(Pinouts(db, path))

    def batch(self, version=3):
        self.path.write_text(json.dumps({
            'format': 'icdb-data', 'version': version,
            'parts': [dict(part, description='Test part') for part in self.devices],
            'pinouts': [self.pinout],
        }), encoding='utf-8')
        return read_batch(self.path)

    def apply(self, library, batch):
        preview = process_batch(library, batch)
        return process_batch(library, batch, apply=True, expected=preview)

    def test_batch_round_trip(self):
        rows = self.apply(self.source, self.batch())
        self.assertEqual([r[2] for r in rows],
                         ['New part', 'New part', 'New pinout', 'New assignment', 'New assignment'])
        self.assertEqual(export_batch(self.source, self.path), (2, 1))
        batch = read_batch(self.path)
        self.assertEqual(batch[1], [self.pinout])
        self.assertTrue(all(r[2] == 'Unchanged' for r in process_batch(self.source, batch)))
        self.apply(self.target, batch)
        self.assertEqual(export_batch(self.target, self.path), (2, 1))
        self.assertEqual(read_batch(self.path), batch)
        cid = self.target.db.execute("SELECT id FROM components WHERE part_number='B'").fetchone()[0]
        self.assertEqual(export_batch(self.target, self.path, [cid]), (1, 1))
        selected = read_batch(self.path)
        self.assertEqual(selected[1][0]['devices'], [self.devices[1]])
        self.assertEqual(selected[1][0]['id'], self.pinout['id'])

    def test_publish_imported_pinouts(self):
        self.apply(self.target, self.batch())
        self.assertEqual(self.target.db.execute('SELECT count(*) FROM pinout_links').fetchone()[0], 0)
        result = self.target.publish()
        self.assertEqual(result['updated'], 2)
        self.assertEqual(self.target.db.execute('SELECT count(*) FROM pinout_links').fetchone()[0], 2)
        self.assertTrue(list((self.root / 'target').rglob('*.svg')))

    def test_default_and_explicit_no_default_survive_rebuild(self):
        self.devices[0]['is_default'] = True
        self.devices[1]['is_default'] = False
        self.apply(self.source, self.batch())
        self.source.publish()
        export_batch(self.source, self.path)
        exported = read_batch(self.path)
        self.apply(self.target, exported)
        for force in (False, True):
            self.target.publish(force=force)
            defaults = self.target.db.execute("""SELECT c.part_number, l.is_default
                 FROM pinout_links l JOIN components c ON c.id=l.component_id ORDER BY c.part_number""")
            self.assertEqual(list(map(tuple, defaults)), [('A', 1), ('B', 0)])
        self.assertTrue(all(row[2] == 'Unchanged' for row in process_batch(self.target, exported)))

    def test_legacy_export_imports_only_explicit_accepted_links(self):
        self.devices[0]['status'] = 'Accepted'
        self.devices[1]['status'] = 'Suggested'
        self.apply(self.source, self.batch(version=2))
        self.assertEqual(self.source.publish()['updated'], 1)
        result = self.source.db.execute("""SELECT c.part_number FROM pl_assignments a
            JOIN components c ON c.id=a.component_id""").fetchall()
        self.assertEqual([row[0] for row in result], ['A'])

    def test_pinout_conflict_and_stale_preview(self):
        batch = self.batch()
        preview = process_batch(self.source, batch)
        self.apply(self.source, batch)
        with self.assertRaisesRegex(ValueError, 'changed since preview'):
            process_batch(self.source, batch, apply=True, expected=preview)
        self.pinout['project']['pins'][0]['name'] = 'VIN'
        self.assertIn('Conflict', [r[2] for r in self.apply(self.source, self.batch())])
        export_batch(self.source, self.path)
        self.assertEqual(read_batch(self.path)[1][0]['project']['pins'][0]['name'], 'IN')

    def test_reused_definition_and_unresolved_link(self):
        batch = self.batch()
        parts, pinouts = batch
        alias = dict(pinouts[0], id='another-id', devices=[self.devices[0], {'part_number': 'MISSING'}])
        rows = self.apply(self.source, (parts, [*pinouts, alias]))
        self.assertEqual([r[2] for r in rows[-3:]], ['Reused pinout', 'Unchanged', 'Unresolved link'])
        self.assertEqual(export_batch(self.source, self.path), (2, 1))

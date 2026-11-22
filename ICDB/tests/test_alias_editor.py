import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from builder import connect
from marking_aliases import alias_record
from qt_component_draft import ComponentDraft


class AliasEditorTests(TestCase):
    def setUp(self):
        folder = TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.db = connect(Path(folder.name) / 'components.sqlite')
        self.addCleanup(self.db.close)
        self.cid = self.db.execute("INSERT INTO components(part_number, manufacturer) VALUES('MAX3232', 'TI')").lastrowid
        self.db.execute('INSERT INTO component_marking_aliases VALUES (?, ?, ?, ?)',
                        ('MB3232I', self.cid, '["TSSOP-16"]', 'Datasheet'))
        self.db.commit()
        self.stage = ComponentDraft()

    def test_rename_and_remove_are_staged_and_recoverable(self):
        alias = alias_record('mb3232c', 'SSOP-16', 'Marking table')
        self.stage.change_alias(self.db, self.cid, original='MB3232I', replacement=alias)
        view = self.stage.alias_view(self.db, self.cid)
        self.assertTrue(view['MB3232I']['remove'])
        self.assertTrue(view['MB3232C']['staged'])
        restored = ComponentDraft()
        restored.restore(self.db, json.loads(json.dumps(self.stage.payload())))
        self.stage.clear()
        self.assertEqual(list(self.stage.alias_view(self.db, self.cid)), ['MB3232I'])

        self.db.execute('BEGIN IMMEDIATE')
        restored.apply_locked(self.db)
        restored.apply_aliases_locked(self.db)
        self.db.commit()
        self.assertEqual(self.stage.alias_view(self.db, self.cid),
                         {'MB3232C': dict(packages=['SSOP-16'], source='Marking table', staged=False)})

    def test_remove_unsaved_alias_cancels_addition(self):
        self.stage.change_alias(self.db, self.cid, replacement=alias_record('MAX3232I', '', ''))
        self.stage.change_alias(self.db, self.cid, original='MAX3232I')
        self.assertFalse(self.stage.changed)

    def test_add_alias_for_new_component_and_rename_before_save(self):
        cid = self.stage.add('NEW-IC', manufacturer='Example')
        self.stage.change_alias(self.db, cid, replacement=alias_record('NEWIC', 'SOIC-8', ' Datasheet '))
        self.stage.update(self.db, cid, part_number='NEW-IC-A')
        restored = ComponentDraft()
        restored.restore(self.db, json.loads(json.dumps(self.stage.payload())))
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            created = restored.apply_locked(self.db)
            restored.apply_aliases_locked(self.db, created)
        self.assertIn('NEWIC', self.stage.alias_view(self.db, created[cid]))
        self.assertEqual(self.db.execute('SELECT part_number FROM components WHERE id=?',
                                         (created[cid],)).fetchone()[0], 'NEW-IC-A')

    def test_add_duplicate_does_not_stage_edit(self):
        with self.assertRaisesRegex(ValueError, 'already exists'):
            self.stage.change_alias(self.db, self.cid, replacement=alias_record('MB3232I', '', 'New source'))
        self.assertFalse(self.stage.changed)

    def test_concurrent_edit_blocks_removal_and_rolls_back_other_changes(self):
        self.stage.update(self.db, self.cid, part_number='MAX3232E')
        self.stage.change_alias(self.db, self.cid, original='MB3232I')
        self.db.execute("UPDATE component_marking_aliases SET source='External edit'")
        self.db.commit()
        with self.assertRaisesRegex(ValueError, 'Alias MB3232I changed'):
            with self.db:
                self.db.execute('BEGIN IMMEDIATE')
                self.stage.apply_locked(self.db)
                self.stage.apply_aliases_locked(self.db)
        self.assertEqual(self.db.execute('SELECT part_number FROM components').fetchone()[0], 'MAX3232')
        self.assertEqual(self.db.execute('SELECT source FROM component_marking_aliases').fetchone()[0], 'External edit')

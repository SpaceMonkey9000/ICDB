"""Regression: group picker must accept component drafts before their first Save."""
from pathlib import Path
from tempfile import TemporaryDirectory
from builder import connect
from pinouts import Pinouts
from pin_library import Library
from qt_component_draft import ComponentDraft


def definition():
    return {'device': 'Existing SOIC', 'package': 'SOIC', 'count': 4,
            'pins': [{'number': i, 'name': str(i), 'role': 'Signal'} for i in range(1, 5)]}


def members(db, definition_id):
    return {r[0] for r in db.execute(
        "SELECT component_id FROM pl_assignments WHERE definition_id=?", (definition_id,))}


def test_staged_new_component_group_assignment():
    with TemporaryDirectory() as td:
        db = connect(Path(td) / 'components.sqlite')
        library = Library(Pinouts(db, Path(td)))
        pinout_id = library.save(definition())
        original_revision = library.get(pinout_id)[0]['revision']
        stage = ComponentDraft()
        temp_id = stage.add('TPS65150', 'Display power controller')
        assert temp_id < 0
        assert db.execute('SELECT COUNT(*) FROM components').fetchone()[0] == 0
        # The UI can now add this temporary ID to the staged membership.
        desired = {temp_id}
        db.execute('BEGIN IMMEDIATE')
        created = stage.apply_locked(db)
        real_members = {created.get(cid, cid) for cid in desired}
        library.save_with_members(definition(), pinout_id,
                                  original_revision, set(), real_members)
        assert real_members == members(db, pinout_id)
        assert db.execute('SELECT part_number FROM components WHERE id=?', (created[temp_id],)).fetchone()[0] == 'TPS65150'
        db.close()


def test_staged_group_failure_rolls_back_component_additions():
    with TemporaryDirectory() as td:
        db = connect(Path(td) / 'components.sqlite')
        library = Library(Pinouts(db, Path(td)))
        pinout_id = library.save(definition())
        rev = library.get(pinout_id)[0]['revision']
        stage = ComponentDraft()
        temp_id = stage.add('TEMP123')
        db.execute('BEGIN IMMEDIATE')
        try:
            created = stage.apply_locked(db)
            library.save_with_members(definition(), pinout_id,
                                      rev, set(), {created[temp_id], 99999999})
        except ValueError:
            db.rollback()
        else:
            raise AssertionError('Bad group member accepted')
        assert not db.execute("SELECT 1 FROM components WHERE part_number='TEMP123'").fetchone()
        assert not members(db, pinout_id)
        db.close()


if __name__ == '__main__':
    test_staged_new_component_group_assignment()
    test_staged_group_failure_rolls_back_component_additions()
    print('Staged group-device regression tests passed')

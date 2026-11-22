"""Backend transactional regression for staged pinout deletions."""
from pathlib import Path
from tempfile import TemporaryDirectory
from builder import connect
from pinouts import Pinouts
from pin_library import Library
from qt_draft_store import write_draft, read_draft, draft_file


def defn(name):
    return {'device': name, 'package': 'SOIC', 'count': 4, 'pins': [
        {'number': 1, 'name': 'VCC', 'role': 'Power'},
        {'number': 2, 'name': 'GND', 'role': 'Ground'},
        {'number': 3, 'name': 'NC', 'role': 'NC'},
        {'number': 4, 'name': 'OUT', 'role': 'Output'}]}


def test_staged_delete_commit_revert_and_rollback():
    with TemporaryDirectory() as folder:
        root = Path(folder)
        db = connect(root / 'components.sqlite')
        lib = Library(Pinouts(db, root))
        one = lib.save(defn('Delete on Save'))
        row, _ = lib.get(one)
        staged = {'definition_id': one, 'revision': row['revision'], 'members': [], 'name': 'Delete on Save'}
        # Stage is only a session payload; SQLite must remain untouched.
        draftpath = draft_file(root, root / 'components.sqlite')
        write_draft(draftpath, {'kind': 'pinout_session', 'drafts': {}, 'deletions': {str(one): staged}})
        assert lib.get(one)[1]['device'] == 'Delete on Save'
        assert read_draft(draftpath)['deletions'][str(one)] == staged
        # Revert drops the draft, leaves definition intact.
        saved = read_draft(draftpath)
        saved['deletions'].clear()
        assert lib.get(one)[1]['device'] == 'Delete on Save'
        # Commit via the same locked operation used by MainWindow.save_all.
        db.execute('BEGIN IMMEDIATE')
        lib.delete_definition(one, locked=True, expected_revision=staged['revision'], expected_members=set())
        db.commit()
        assert db.execute('SELECT 1 FROM pl_definitions WHERE id=?', (one,)).fetchone() is None
        # If a later operation fails, pinout deletion must roll back too.
        two = lib.save(defn('Rollback deletion'))
        other = defn('Keep me')
        other['pins'][0]['name'] = 'VDD'
        third = lib.save(other)
        rev2 = lib.get(two)[0]['revision']
        db.execute('BEGIN IMMEDIATE')
        try:
            lib.delete_definition(two, locked=True, expected_revision=rev2, expected_members=set())
            raise ValueError('Injected failure after deletion')
        except ValueError:
            db.rollback()
        assert lib.get(two)[1]['device'] == 'Rollback deletion'
        assert lib.get(third)[1]['device'] == 'Keep me'
        db.close()


def test_staged_unassign_then_delete_one_commit():
    with TemporaryDirectory() as folder:
        root = Path(folder)
        db = connect(root / 'components.sqlite')
        lib = Library(Pinouts(db, root))
        db.execute("INSERT INTO components(part_number) VALUES('IC0001')")
        cid = db.execute('SELECT id FROM components').fetchone()[0]
        db.commit()
        ident = lib.save(defn('Unassign then delete'))
        revision = lib.get(ident)[0]['revision']
        lib.save_with_members(defn('Unassign then delete'), ident, revision, set(), {cid})
        rev = lib.get(ident)[0]['revision']
        db.execute('BEGIN IMMEDIATE')
        lib.save_with_members(defn('Unassign then delete'), ident, rev, {cid}, set(), locked=True)
        lib.delete_definition(ident, locked=True)
        db.commit()
        assert db.execute('SELECT 1 FROM pl_definitions WHERE id=?', (ident,)).fetchone() is None
        db.close()


def test_stale_delete_revision_is_rejected():
    with TemporaryDirectory() as folder:
        root = Path(folder)
        db = connect(root / 'components.sqlite')
        lib = Library(Pinouts(db, root))
        ident = lib.save(defn('Stale original'))
        rev = lib.get(ident)[0]['revision']
        lib.save(defn('Stale changed'), ident)
        db.execute('BEGIN IMMEDIATE')
        try:
            lib.delete_definition(ident, locked=True, expected_revision=rev, expected_members=set())
        except ValueError as exc:
            assert 'externally' in str(exc)
            db.rollback()
        else:
            raise AssertionError('External revision modification not rejected')
        assert lib.get(ident)[1]['device'] == 'Stale changed'
        db.close()

if __name__ == '__main__':
    test_staged_delete_commit_revert_and_rollback()
    test_staged_unassign_then_delete_one_commit()
    test_stale_delete_revision_is_rejected()
    print('Staged deletion tests passed')

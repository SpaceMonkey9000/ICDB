"""Regression tests for all-or-nothing multiple-pinout commits and draft recovery."""
from pathlib import Path
from tempfile import TemporaryDirectory
from builder import connect
from pinouts import Pinouts
from pin_library import Library
from qt_draft_store import draft_file, write_draft, read_draft
from test_transactional_edit import definition, members


def test_multiple_pinout_commit():
    with TemporaryDirectory() as folder:
        root=Path(folder); db=connect(root/'components.sqlite'); lib=Library(Pinouts(db,root))
        db.execute("INSERT INTO components(part_number) VALUES('ABC123')"); db.commit()
        cid=db.execute('SELECT id FROM components').fetchone()[0]
        first=lib.save(definition('Original A'))
        second=lib.save(definition('Original B', 'VDD'))
        ra=lib.get(first)[0]['revision']; rb=lib.get(second)[0]['revision']
        db.execute('BEGIN IMMEDIATE')
        lib.save_with_members(definition('Modified A'),first,ra,set(),{cid},locked=True)
        lib.save_with_members(definition('Modified B','VDD'),second,rb,set(),set(),locked=True)
        db.commit()
        assert lib.get(first)[1]['device']=='Modified A'
        assert lib.get(second)[1]['device']=='Modified B'
        assert members(db,first)=={cid}
        # The second failed write must undo the first successful write as well.
        ra=lib.get(first)[0]['revision']; rb=lib.get(second)[0]['revision']
        db.execute('BEGIN IMMEDIATE')
        try:
            lib.save_with_members(definition('Should roll back A'),first,ra,{cid},{cid},locked=True)
            lib.save_with_members(definition('Should roll back B','VDD'),second,rb,set(),{987654321},locked=True)
        except ValueError:
            db.rollback()
        else: raise AssertionError('Invalid membership was accepted')
        assert lib.get(first)[1]['device']=='Modified A'
        assert lib.get(second)[1]['device']=='Modified B'
        assert lib.get(first)[0]['revision']==ra
        assert lib.get(second)[0]['revision']==rb
        db.close()


def test_multiple_draft_journal():
    with TemporaryDirectory() as folder:
        path=draft_file(Path(folder),Path(folder)/'components.sqlite')
        drafts={'1':{'new':False,'definition_id':1,'raw':{'title':'A'},'base_members':[], 'draft_members':[]},
                '2':{'new':False,'definition_id':2,'raw':{'title':'B'},'base_members':[], 'draft_members':[]}}
        write_draft(path,{'kind':'pinout_session','drafts':drafts})
        assert read_draft(path)['drafts']==drafts

if __name__ == '__main__':
    test_multiple_pinout_commit()
    test_multiple_draft_journal()
    print('Multiple-pinout session tests passed')

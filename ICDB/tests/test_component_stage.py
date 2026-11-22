"""Headless tests for component draft, combined transactions, conflicts and recovery."""
from pathlib import Path
from tempfile import TemporaryDirectory
from builder import connect
from pinouts import Pinouts
from pin_library import Library
from qt_component_draft import ComponentDraft


def test_component_staging():
    with TemporaryDirectory() as td:
        root=Path(td)
        db=connect(root/'components.sqlite')
        Library(Pinouts(db,root))
        db.execute("INSERT INTO components(part_number,function,manufacturer) VALUES('U1','old','TI')")
        db.execute("INSERT INTO components(part_number,function,manufacturer) VALUES('U2','old','TI')")
        db.commit()
        a,b=[row[0] for row in db.execute('SELECT id FROM components ORDER BY id')]
        stage=ComponentDraft()
        stage.update(db,a,function='modified')
        tmp=stage.add('u3','new','TI')
        stage.delete(db,b)
        # All edits are merely staged; the DB is unchanged.
        assert db.execute('SELECT function FROM components WHERE id=?',(a,)).fetchone()[0]=='old'
        assert db.execute('SELECT count(*) FROM components').fetchone()[0]==2
        restored=ComponentDraft()
        restored.restore(db,stage.payload())
        assert restored.added[tmp]['part_number']=='U3'
        # Cancel discards all without writing.
        stage.clear()
        assert not stage.changed
        db.execute('BEGIN IMMEDIATE')
        restored.apply_locked(db)
        db.commit()
        assert db.execute('SELECT function FROM components WHERE id=?',(a,)).fetchone()[0]=='modified'
        assert db.execute('SELECT count(*) FROM components').fetchone()[0]==2
        assert not db.execute("SELECT 1 FROM components WHERE part_number='U2'").fetchone()
        # Stale edits cannot overwrite an externally modified component.
        stale=ComponentDraft()
        stale.update(db,a,function='pending')
        db.execute('UPDATE components SET function=? WHERE id=?',('external',a))
        db.commit()
        db.execute('BEGIN IMMEDIATE')
        try:
            stale.apply_locked(db)
        except ValueError:
            db.rollback()
        else:
            raise AssertionError('stale edit was accepted')
        assert db.execute('SELECT function FROM components WHERE id=?',(a,)).fetchone()[0]=='external'
        try:
            ComponentDraft().restore(db,stale.payload())
        except ValueError:
            pass
        else:
            raise AssertionError('stale recovery was accepted')
        db.close()


def test_combined_rollback():
    with TemporaryDirectory() as td:
        root=Path(td)
        db=connect(root/'components.sqlite')
        lib=Library(Pinouts(db,root))
        db.execute("INSERT INTO components(part_number) VALUES('U1')")
        db.commit()
        cid=db.execute('SELECT id FROM components').fetchone()[0]
        sample=lambda name: {'device':name,'package':'SOIC','count':4,
            'pins':[{'number':1,'name':'VCC','role':'Power'}, {'number':2,'name':'GND','role':'Ground'}, {'number':3,'name':'IN','role':'Signal'}, {'number':4,'name':'OUT','role':'Signal'}]}
        pin=lib.save(sample('Original'))
        rev=lib.get(pin)[0]['revision']
        staged=ComponentDraft()
        staged.update(db,cid,function='new function')
        db.execute('BEGIN IMMEDIATE')
        try:
            staged.apply_locked(db)
            # invalid group id fails after component mutation, must roll back both
            lib.save_with_members(sample('Modified'),pin,rev,set(),{999999999})
        except ValueError:
            db.rollback()
        else:
            raise AssertionError('invalid group should abort')
        assert db.execute('SELECT function FROM components WHERE id=?',(cid,)).fetchone()[0] in ('',None)
        assert lib.get(pin)[1]['device']=='Original'
        # Combined successful save.
        db.execute('BEGIN IMMEDIATE')
        staged.apply_locked(db)
        lib.save_with_members(sample('Modified'),pin,rev,set(),{cid})
        assert db.execute('SELECT function FROM components WHERE id=?',(cid,)).fetchone()[0]=='new function'
        assert lib.get(pin)[1]['device']=='Modified'
        db.close()


if __name__=='__main__':
    test_component_staging()
    test_combined_rollback()
    print('Component stage and combined transaction tests passed')

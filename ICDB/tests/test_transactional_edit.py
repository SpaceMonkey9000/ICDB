"""Headless transaction/rollback tests for staged pinout and membership editing."""
import copy
import tempfile
from pathlib import Path
from builder import connect
from pinouts import Pinouts
from pin_library import Library


def definition(name, a='VCC', b='GND'):
    return {'device': name, 'package': 'SOIC', 'count': 4, 'pins': [
        {'number': 1, 'name': a, 'role': 'Power'},
        {'number': 2, 'name': b, 'role': 'Ground'},
        {'number': 3, 'name': 'IN', 'role': 'Signal'},
        {'number': 4, 'name': 'OUT', 'role': 'Signal'},
    ]}


def members(db, did):
    return {r[0] for r in db.execute("SELECT component_id FROM pl_assignments WHERE definition_id=?", (did,))}


def test_transaction():
    with tempfile.TemporaryDirectory() as tmp:
        root=Path(tmp)
        db=connect(root/'components.sqlite')
        lib=Library(Pinouts(db,root))
        for part in ('ABC1','ABC2','ABC3'):
            db.execute('INSERT INTO components(part_number) VALUES(?)',(part,))
        db.commit()
        cids=[r[0] for r in db.execute('SELECT id FROM components ORDER BY id')]
        did=lib.save(definition('Original'))
        rev=lib.get(did)[0]['revision']
        edited=definition('Changed')
        # Both edits are committed together.
        lib.save_with_members(edited,did,rev,set(),{cids[0],cids[1]})
        assert lib.get(did)[1]['device']=='Changed'
        assert members(db,did)==set(cids[:2])
        rev=lib.get(did)[0]['revision']
        # Remove a member, add another, and modify the pinout atomically.
        lib.save_with_members(definition('Changed Again'),did,rev,set(cids[:2]),{cids[1],cids[2]})
        assert members(db,did)==set(cids[1:])
        assert lib.get(did)[1]['device']=='Changed Again'
        rev=lib.get(did)[0]['revision']
        # A bad device ID must roll back the changed name and removals.
        try:
            lib.save_with_members(definition('Should rollback'),did,rev,set(cids[1:]),{cids[2],987654321})
        except ValueError: pass
        else: raise AssertionError('Invalid component ID was accepted')
        assert lib.get(did)[1]['device']=='Changed Again'
        assert members(db,did)==set(cids[1:])
        assert lib.get(did)[0]['revision']==rev
        # Bad pin data must not alter group membership.
        bad=definition('Invalid')
        bad['pins'][1]['number']=1
        try:
            lib.save_with_members(bad,did,rev,set(cids[1:]),set())
        except ValueError: pass
        else: raise AssertionError('Invalid pin layout was accepted')
        assert members(db,did)==set(cids[1:])
        # Stale definition revision is rejected.
        lib.save(definition('External update'),did)
        try:
            lib.save_with_members(definition('Stale'),did,rev,set(cids[1:]),set())
        except ValueError as exc: assert 'changed externally' in str(exc)
        else: raise AssertionError('Stale edit overwritten new data')
        assert lib.get(did)[1]['device']=='External update'
        # Stale group member snapshot is rejected, even if revision did not change.
        rev=lib.get(did)[0]['revision']
        lib.add_group_members(did,[cids[0]])
        try:
            lib.save_with_members(definition('Stale members'),did,rev,set(cids[1:]),set())
        except ValueError as exc: assert 'membership changed externally' in str(exc)
        else: raise AssertionError('Stale membership snapshot accepted')
        assert lib.get(did)[1]['device']=='External update'
        db.close()


def test_conflicting_pinout_rollback():
    with tempfile.TemporaryDirectory() as tmp:
        root=Path(tmp)
        db=connect(root/'components.sqlite')
        lib=Library(Pinouts(db, root))
        db.execute("INSERT INTO components(part_number) VALUES('TESTIC')")
        db.commit()
        cid=db.execute('SELECT id FROM components').fetchone()[0]
        a=lib.save(definition('Group A'))
        b=lib.save(definition('Group B', 'VDD'))
        lib.add_group_members(a,[cid])
        rev=lib.get(b)[0]['revision']
        try:
            lib.save_with_members(definition('Attempted Change','VDD'),b,rev,set(),{cid})
        except ValueError: pass
        else: raise AssertionError('Conflicting accepted pinout was accepted')
        assert lib.get(b)[1]['device']=='Group B'
        assert members(db,b)==set()
        assert members(db,a)=={cid}
        db.close()

if __name__=='__main__':
    test_transaction(); test_conflicting_pinout_rollback(); print('Transactional tests passed')

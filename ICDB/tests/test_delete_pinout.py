import tempfile
from pathlib import Path
from builder import connect
from pinouts import Pinouts
from pin_library import Library

def test_delete():
    with tempfile.TemporaryDirectory() as temp:
        root=Path(temp)
        db=connect(root/'components.sqlite')
        lib=Library(Pinouts(db,root))
        def definition(name):
            return {'device':name,'package':'SOIC','count':2,'pins':[{'number':1,'name':'VCC-'+name,'role':'Power'}, {'number':2,'name':'GND','role':'Ground'}]}
        a=lib.save(definition('Test A'))
        assert lib.delete_definition(a) is True
        b=lib.save(definition('Test B'))
        db.execute("INSERT INTO components(part_number) VALUES('ABC123')")
        cid=db.execute('SELECT id FROM components').fetchone()[0]
        db.commit()
        db.execute("INSERT INTO pl_assignments(component_id,definition_id) VALUES(?,?)", (cid,b))
        try: lib.delete_definition(b)
        except ValueError as ex: assert 'device assignment' in str(ex)
        else: raise AssertionError('Accepted pinout deleted')
        db.execute("DELETE FROM pl_assignments WHERE definition_id=?", (b,))
        assert lib.delete_definition(b) is True
        assert not db.execute('SELECT 1 FROM pl_assignments WHERE definition_id=?', (b,)).fetchone()
        c=lib.save(definition('Test C'))
        db.execute("INSERT INTO pl_sources(namespace,external_id,definition_id,imported_json,devices_json) VALUES(?,?,?,?,?)",('test','source',c,'{}','[]'))
        try: lib.delete_definition(c)
        except ValueError as ex: assert 'source' in str(ex)
        else: raise AssertionError('Imported pinout deleted')
        assert db.execute('SELECT 1 FROM pl_definitions WHERE id=?',(c,)).fetchone()
        d=lib.save(definition('Test D'))
        db.execute("INSERT INTO pl_assignments(component_id,definition_id) VALUES(?,?)", (cid,d))
        mid=db.execute('SELECT id FROM pl_assignments WHERE definition_id=?', (d,)).fetchone()[0]
        db.execute("INSERT INTO pinout_assets(sha256,path,original_name) VALUES('a'*64,'pinouts/a.svg','a.svg')")
        aid=db.execute('SELECT id FROM pinout_assets ORDER BY id DESC LIMIT 1').fetchone()[0]
        db.execute('INSERT INTO pinout_links(component_id,asset_id,package,is_default) VALUES(?,?,?,1)',(cid,aid,'SOIC'))
        lid=db.execute('SELECT id FROM pinout_links ORDER BY id DESC LIMIT 1').fetchone()[0]
        db.execute('INSERT INTO pl_publications(assignment_id,link_id) VALUES(?,?)',(mid,lid))
        db.execute('DELETE FROM pl_assignments WHERE id=?',(mid,))
        assert lib.delete_definition(d) is True
        assert not db.execute('SELECT 1 FROM pinout_links WHERE id=?',(lid,)).fetchone()
        assert not db.execute('SELECT 1 FROM pl_publications WHERE assignment_id=?',(mid,)).fetchone()
        db.close()

if __name__=='__main__':
    test_delete(); print('Deletion tests passed')

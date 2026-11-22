"""Regression tests for one-save new-pinout creation plus device assignment."""
import pytest
from builder import connect
from pinouts import Pinouts
from pin_library import Library
from test_revision19_fixes import definition, window


def test_create_and_assign_in_one_sqlite_transaction(tmp_path):
    db = connect(tmp_path / 'components.sqlite')
    library = Library(Pinouts(db, tmp_path))
    with db:
        cid = db.execute("INSERT INTO components(part_number,manufacturer,family_hint,function) VALUES('ABC123','','','IC')").lastrowid
    data = definition('ABC123', prefix='A')
    db.execute('BEGIN IMMEDIATE')
    ident = library.save(data, None, locked=True)
    row, _ = library.get(ident)
    library.save_with_members(data, ident, row['revision'], set(), {cid}, locked=True)
    db.commit()
    assert db.execute("SELECT 1 FROM pl_assignments WHERE component_id=? AND definition_id=?",(cid,ident)).fetchone()
    db.close()


def test_invalid_association_rolls_back_new_definition(tmp_path):
    db = connect(tmp_path / 'components.sqlite')
    library = Library(Pinouts(db, tmp_path))
    data = definition('ABC123', prefix='A')
    db.execute('BEGIN IMMEDIATE')
    ident = library.save(data, None, locked=True)
    row, _ = library.get(ident)
    with pytest.raises(ValueError):
        library.save_with_members(data, ident, row['revision'], set(), {999999}, locked=True)
    db.rollback()
    assert db.execute('SELECT COUNT(*) FROM pl_definitions').fetchone()[0] == 0
    db.close()


def test_add_pinout_stages_new_definition_and_member(window):
    page = window.components
    page.refresh(window.test_ids[2])
    page.add_selected_pinout()
    editor = window.library_page
    assert editor._new
    assert editor.title.text() == 'NE5532'
    assert window.test_ids[2] in editor._draft_members
    assert editor.use_existing_button.isVisible() or not window.isVisible()
    assert window.save_all(confirmed=True)
    assert window.db.execute("SELECT 1 FROM pl_assignments m JOIN pl_definitions d ON d.id=m.definition_id WHERE m.component_id=? AND json_extract(d.project_json,'$.device')='NE5532'",(window.test_ids[2],)).fetchone()


def test_add_pinout_new_staged_component(window):
    cid = window.component_stage.add('BRANDNEW123', 'New part', '')
    window.component_changed()
    window.components.refresh(cid)
    window.components.add_selected_pinout()
    assert cid in window.library_page._draft_members
    assert window.save_all(confirmed=True)
    row = window.db.execute('SELECT id FROM components WHERE part_number=?',('BRANDNEW123',)).fetchone()
    assert row
    assert window.db.execute("SELECT 1 FROM pl_assignments WHERE component_id=?",(row[0],)).fetchone()


@pytest.mark.parametrize('reuse', [True, False])
def test_save_identical_new_pinout_offers_existing_group(window, monkeypatch, reuse):
    from PySide6.QtWidgets import QMessageBox

    part = window.component_stage.add('EXTRA123')
    window.components.refresh(part)
    window.components.add_selected_pinout()
    editor = window.library_page
    editor.loading = True
    editor._populate_editor(definition(title='Extra device'))
    editor.loading = False
    original_members = {row[0] for row in window.db.execute(
        'SELECT component_id FROM pl_assignments WHERE definition_id=?', (window.test_pinout,))}
    prompts = []

    def answer(_, title, text, *_buttons):
        prompts.append((title, text))
        return QMessageBox.StandardButton.Yes if reuse else QMessageBox.StandardButton.Cancel

    monkeypatch.setattr(QMessageBox, 'question', answer)
    monkeypatch.setattr(window, '_publish_after_new_pinout', lambda: None)
    assert window.save_all(confirmed=True) is reuse
    assert len(prompts) == 1 and 'Existing SOIC' in prompts[0][1]
    assert window.db.execute('SELECT count(*) FROM pl_definitions').fetchone()[0] == 1
    part_row = window.db.execute("SELECT id FROM components WHERE part_number='EXTRA123'").fetchone()
    updated_members = {row[0] for row in window.db.execute(
        'SELECT component_id FROM pl_assignments WHERE definition_id=?', (window.test_pinout,))}
    if reuse:
        assert part_row is not None and updated_members == original_members | {part_row[0]}
        assert editor.definition_id == window.test_pinout
        assert editor.title.text() == 'Existing SOIC'
    else:
        assert part_row is None and updated_members == original_members
        assert editor._new and editor.title.text() == 'Extra device'

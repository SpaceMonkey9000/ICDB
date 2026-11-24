"""Regression tests for the Revision 19 bug fixes and optimizations."""
import json
import os
import time
import subprocess
import sys
from pathlib import Path

import pytest

from builder import connect
from pinouts import Pinouts
from pin_library import Library

HERE = Path(__file__).resolve().parent.parent  # application folder


def definition(title='Existing SOIC', prefix='P', package='SOIC', count=8):
    return {'device': title, 'package': package, 'count': count,
            'pins': [{'number': i, 'name': f'{prefix}{i}', 'role': 'Signal', 'description': ''}
                     for i in range(1, count + 1)]}


def seed(data, parts=('LM358', 'TL072', 'NE5532')):
    db = connect(data / 'components.sqlite')
    library = Library(Pinouts(db, data))
    with db:
        ids = [db.execute('INSERT INTO components(part_number,manufacturer,family_hint,function) VALUES(?,?,?,?)',
                          (p, '', '', 'Op-amp')).lastrowid for p in parts]
    pinout = library.save(definition())
    library.add_group_members(pinout, ids[:2])
    db.close()
    return pinout, ids


# ---------------------------------------------------------------- backend

def test_new_pinout_with_identical_pins_is_rejected(tmp_path):
    db = connect(tmp_path / 'components.sqlite')
    library = Library(Pinouts(db, tmp_path))
    first = library.save(definition('Original'))
    with pytest.raises(ValueError, match=f'pinout #{first}'):
        library.save(definition('Renamed copy'))
    assert db.execute('SELECT count(*) FROM pl_definitions').fetchone()[0] == 1
    # Different pin data is still a new definition, and imports still reuse identical data.
    assert library.save(definition('Other', prefix='Q')) != first
    counts = library.import_batch({'namespace': 'test', 'name': 'batch', 'items': [
        {'id': 'x', 'project': definition('Imported'), 'devices': []}]})
    assert counts == {'reused definitions': 1}
    db.close()


def test_database_module_does_not_need_tkinter(tmp_path):
    code = ("import sys; sys.modules['tkinter'] = None\n"
            f"sys.path.insert(0, {str(HERE)!r})\n"
            "from builder import connect\n"
            f"db = connect({str(tmp_path / 'c.sqlite')!r})\n"
            "from database_version import database_version\n"
            "print(database_version(db))\n")
    result = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_publish_reuses_cached_hashes_and_repairs_changed_files(tmp_path):
    pinout, _ = seed(tmp_path)
    db = connect(tmp_path / 'components.sqlite')
    library = Library(Pinouts(db, tmp_path))
    assert library.publish()['updated'] == 2
    assert library.publish()['unchanged'] == 2
    assert db.execute('SELECT count(*) FROM pl_file_hashes').fetchone()[0] == 2
    path, sha = db.execute('SELECT path,sha256 FROM pinout_assets LIMIT 1').fetchone()
    target = tmp_path / path
    good = target.read_bytes()
    target.write_bytes(b'<svg/>')  # damaged shared file: size and mtime change
    library.publish()
    assert target.read_bytes() == good
    db.close()


def test_delete_devices_removes_links(tmp_path):
    from builder import delete_devices
    _, ids = seed(tmp_path)
    db = connect(tmp_path / 'components.sqlite')
    delete_devices(db, ids[:2])
    assert db.execute('SELECT count(*) FROM components').fetchone()[0] == 1
    assert db.execute("SELECT count(*) FROM pl_assignments").fetchone()[0] == 0
    db.close()


# ---------------------------------------------------------------- Qt interface

@pytest.fixture
def window(tmp_path, monkeypatch):
    pytest.importorskip('PySide6')
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    from PySide6.QtCore import QSettings, QStandardPaths
    from PySide6.QtWidgets import QApplication, QMessageBox
    import icdb_qt
    QStandardPaths.setTestModeEnabled(True)
    app = QApplication.instance() or QApplication([])
    ini = str(tmp_path / 'settings.ini')
    monkeypatch.setattr(icdb_qt, 'QSettings', lambda *a: QSettings(ini, QSettings.Format.IniFormat))
    answers = {'question': QMessageBox.StandardButton.Yes}
    for name in ('information', 'warning', 'critical'):
        monkeypatch.setattr(QMessageBox, name, staticmethod(lambda *a, **k: QMessageBox.StandardButton.Ok))
    monkeypatch.setattr(QMessageBox, 'question', staticmethod(lambda *a, **k: answers['question']))
    data = tmp_path / 'DATA'
    data.mkdir()
    pinout, ids = seed(data)
    w = icdb_qt.MainWindow(data)
    w.test_pinout, w.test_ids, w.answers = pinout, ids, answers
    yield w
    w.component_stage.clear()
    w.library_page.pending_pinouts.clear()
    w.library_page.changed = False
    w.close()
    app.processEvents()


def test_group_members_are_listed_once(window):
    page = window.library_page
    page._show_definition(window.test_pinout)
    assert page.members.rowCount() == 2


def test_inline_edit_updates_one_row_without_full_refresh(window):
    comp = window.components
    calls = []
    original = comp.refresh
    comp.refresh = lambda *a, **k: (calls.append(1), original(*a, **k))
    row = next(r for r in range(comp.table.rowCount()) if comp.table.item(r, 0).text() == 'LM358')
    comp.table.item(row, 1).setText('  dual op-amp  ')
    assert calls == []
    cid = window.test_ids[0]
    row = next(r for r in range(comp.table.rowCount()) if comp.table.item(r, 0).data(256) == cid)
    assert comp.table.item(row, 1).text() == 'dual op-amp'
    assert window.component_stage.edits[cid]['after']['function'] == 'dual op-amp'


def test_pinouts_column_uses_label_cache(window):
    comp = window.components
    labels = comp._pinout_labels()
    assert labels[window.test_ids[0]] == {'SOIC-8'}
    assert window.test_ids[2] not in labels
    window.library.add_group_members(window.test_pinout, [window.test_ids[2]])
    assert comp._pinout_labels()[window.test_ids[2]] == {'SOIC-8'}


def test_orphaned_unsaved_members_are_shown_and_pruned(window):
    page = window.library_page
    page._show_definition(window.test_pinout)
    page._stage_group(page._draft_members | {-7})  # an unsaved component that was never restored
    assert page.members.rowCount() == 3
    assert page.prune_missing_members() == 1
    assert -7 not in page._draft_members and page.members.rowCount() == 2


def test_delete_button_stages_all_selected_devices(window):
    from PySide6.QtCore import QItemSelectionModel, Qt

    page = window.components
    page.refresh()
    selected = set(window.test_ids[:2])
    flags = QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows
    page.table.clearSelection()
    for row in range(page.table.rowCount()):
        index = page.table.model().index(row, 0)
        if index.data(Qt.ItemDataRole.UserRole) in selected:
            page.table.selectionModel().select(index, flags)
    assert page.delete_button.isEnabled()
    assert not page.edit_button.isEnabled()
    page.delete_button.click()
    assert set(window.component_stage.deleted) == selected
    assert window.db.execute('SELECT COUNT(*) FROM components').fetchone()[0] == 3
    assert window.save_all(confirmed=True)
    assert [row[0] for row in window.db.execute('SELECT id FROM components')] == [window.test_ids[2]]


def test_deleting_a_group_member_does_not_block_save(window):
    page = window.library_page
    page._show_definition(window.test_pinout)
    page.title.setText('Edited title')
    page.mark_changed()
    window.component_stage.delete(window.db, window.test_ids[0])
    assert window.save_all(confirmed=True)
    members = {r[0] for r in window.db.execute(
        "SELECT component_id FROM pl_assignments WHERE definition_id=?", (window.test_pinout,))}
    assert members == {window.test_ids[1]}


def test_new_pinout_stays_open_on_filter_change_and_is_selected_after_save(window):
    page = window.library_page
    page.new_definition()
    page.title.setText('Brand new')
    page.pins.item(0, 1).setText('VCC')
    page.mark_changed()
    page.search.setText('Existing')
    page.refresh()
    assert page._new and page.title.text() == 'Brand new'
    page.search.clear()
    assert window.save_all(confirmed=True)
    assert not page._new and page.definition_id is not None
    assert page.data['device'] == 'Brand new'


def test_import_picker_previews_and_saves_mixed_files(window, tmp_path, monkeypatch):
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication, QFileDialog

    csv_path = tmp_path / 'first.CSV'
    json_path = tmp_path / 'second.json'
    duplicates = tmp_path / 'third.csv'
    csv_path.write_text('A,First part\n', encoding='utf-8')
    json_path.write_text(json.dumps({
        'format': 'icdb-data', 'version': 3,
        'parts': [{'part_number': 'A', 'description': 'First part'},
                  {'part_number': 'B', 'description': 'Second part'}],
    }), encoding='utf-8')
    duplicates.write_text('A,Different description\nB,Second part\nC,Third part\n',
                          encoding='utf-8')
    paths = [str(path) for path in (csv_path, json_path, duplicates)]
    monkeypatch.setattr(QFileDialog, 'getOpenFileNames', lambda *args: (paths, ''))
    page = window.import_page
    page.choose_button.click()
    deadline = time.monotonic() + 5
    while window.job is not None and time.monotonic() < deadline:
        QApplication.processEvents()
        time.sleep(0.01)
    assert window.job is None
    assert page.preview.rowCount() == 6
    assert [page.preview.item(i, 2).text() for i in range(6)] == [
        'New', 'Unchanged', 'New part', 'Already in ICDB', 'Already in ICDB', 'New']
    assert [page.preview.item(i, 4).text() for i in (0, 1, 3)] == [
        csv_path.name, json_path.name, duplicates.name]
    assert not window.db.execute("SELECT 1 FROM components WHERE part_number IN ('A', 'B', 'C')").fetchone()
    page.preview.sortItems(0, Qt.SortOrder.DescendingOrder)
    assert page.preview.item(0, 0).text() == 'C'
    assert page.preview.item(0, 1).text() == 'Third part'
    assert page.preview.item(0, 4).text() == duplicates.name
    page.import_button.click()
    assert window.component_stage.pending_import['kind'] == 'files'
    assert not page.import_button.isEnabled() and not page.choose_button.isEnabled()
    with pytest.raises(ValueError):
        window.stage_import('csv', ('other.csv', 'def'), [])
    assert window.save_all(confirmed=True)
    assert list(map(tuple, window.db.execute(
        "SELECT part_number, function FROM components WHERE part_number IN ('A', 'B', 'C') ORDER BY part_number"
    ))) == [('A', 'First part'), ('B', 'Second part'), ('C', 'Third part')]


def test_delete_import_review_rows_before_and_after_save(window, tmp_path):
    from PySide6.QtCore import QItemSelectionModel, Qt
    from PySide6.QtWidgets import QApplication
    from import_batch import preview_files

    path = tmp_path / 'conflicts.json'
    path.write_text(json.dumps({
        'format': 'icdb-data', 'version': 3,
        'parts': [{'part_number': part, 'description': 'Incoming description'}
                  for part in ('LM358', 'TL072', 'NE5532', 'New A', 'New B', 'New C')],
    }), encoding='utf-8')
    page = window.import_page
    assert not page.delete_button.isHidden()
    assert not page.delete_button.isEnabled()
    page.preview_ready(preview_files(window.library, [str(path)], lambda *_: None))
    page.preview.selectRow(3)
    assert page.preview.item(3, 2).text() == 'New part'
    page.delete_button.click()
    deadline = time.monotonic() + 5
    while window.job is not None and time.monotonic() < deadline:
        QApplication.processEvents()
        time.sleep(0.01)
    assert window.job is None
    assert page.preview.rowCount() == 5
    page.import_button.click()
    assert window.save_all(confirmed=True)
    assert page.preview.rowCount() == 3
    page.preview.sortItems(0, Qt.SortOrder.DescendingOrder)
    selection = page.preview.selectionModel()
    flags = QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows
    for row in (0, 2):
        selection.select(page.preview.model().index(row, 0), flags)
    page.delete_button.click()
    assert page.preview.rowCount() == 1
    assert page.preview.item(0, 0).text() == 'NE5532'
    page.preview.selectRow(0)
    page.delete_button.click()
    assert page.preview.rowCount() == 0
    assert not page.delete_button.isHidden()
    assert not page.delete_button.isEnabled()
    assert [row[0] for row in window.db.execute(
        "SELECT part_number FROM components WHERE part_number LIKE 'New %' ORDER BY part_number"
    )] == ['New B', 'New C']


def test_settings_data_shows_database_information(window):
    from PySide6.QtWidgets import QFormLayout, QGroupBox
    from database_version import database_version
    from ui.settings_dialog import SettingsDialog

    dialog = SettingsDialog(window)
    group = dialog.findChild(QGroupBox)
    assert group.title() == 'Database information'
    form = group.layout()
    values = [form.itemAt(row, QFormLayout.ItemRole.FieldRole).widget().text()
              for row in range(form.rowCount())]
    assert values == [database_version(window.db), '3', '1']


def test_large_pin_count_is_displayed(window):
    page = window.library_page
    big = window.library.save(definition('BGA part', package='BGA', count=300))
    page._show_definition(big)
    assert page.count.value() == 300 and page.pins.rowCount() == 300


def test_reducing_pin_count_asks_before_removing_data(window):
    page = window.library_page
    page._show_definition(window.test_pinout)
    from PySide6.QtWidgets import QMessageBox
    window.answers['question'] = QMessageBox.StandardButton.No
    page.count.setValue(6)
    assert page.pins.rowCount() == 8 and page.count.value() == 8
    window.answers['question'] = QMessageBox.StandardButton.Yes
    page.count.setValue(6)
    assert page.pins.rowCount() == 6


def test_save_as_new_with_unchanged_pins_is_refused_up_front(window):
    page = window.library_page
    page._show_definition(window.test_pinout)
    page.title.setText('Just a new title')
    page.save(as_new=True)
    assert not page._new and page.definition_id == window.test_pinout
    page.pins.item(0, 1).setText('CHANGED')
    page.save(as_new=True)
    assert page._new and page.definition_id is None


def test_group_device_double_click_opens_component(window, monkeypatch):
    from PySide6.QtCore import Qt

    page = window.library_page
    page._show_definition(window.test_pinout)
    window.tabs.setCurrentWidget(page)
    window.components.search.setText('unrelated filter')
    monkeypatch.setattr(window.components, 'ROW_LIMIT', 0)
    item = page.members.item(0, 1)
    component_id = item.data(Qt.ItemDataRole.UserRole)
    page.members.itemDoubleClicked.emit(item)
    assert window.tabs.currentWidget() is window.components
    assert window.components.selected_id() == component_id

    staged_id = window.component_stage.add('STAGED123', 'Draft device')
    page._stage_group(page._draft_members | {staged_id})
    window.tabs.setCurrentWidget(page)
    item = next(page.members.item(i, 0) for i in range(page.members.rowCount())
                if page.members.item(i, 0).data(Qt.ItemDataRole.UserRole) == staged_id)
    page.members.itemDoubleClicked.emit(item)
    assert window.tabs.currentWidget() is window.components
    assert window.components.selected_id() == staged_id
    assert staged_id in page._draft_members


def test_database_version_migrates_and_tracks_committed_changes(tmp_path):
    import sqlite3
    from database_version import database_version

    path = tmp_path / 'components.sqlite'
    from builder import SCHEMA

    legacy = sqlite3.connect(path)
    with legacy:
        legacy.executescript(SCHEMA)
        legacy.executescript('''
            CREATE TABLE icdb_database_version (
                id INTEGER PRIMARY KEY, base TEXT NOT NULL, revision INTEGER NOT NULL);
            INSERT INTO icdb_database_version VALUES(1,'Unversioned',0);
            CREATE TRIGGER icdb_rev_components_insert AFTER INSERT ON components BEGIN
                UPDATE icdb_database_version SET revision=revision+1 WHERE id=1;
            END;
            CREATE TRIGGER icdb_rev_components_update AFTER UPDATE ON components
            WHEN OLD.function IS NOT NEW.function BEGIN
                UPDATE icdb_database_version SET revision=revision+1 WHERE id=1;
            END;
            INSERT INTO components(part_number) VALUES ('LM358');
        ''')
    legacy.close()

    db = connect(path)
    assert database_version(db) == 'Date unknown-r1'
    with sqlite3.connect(path) as writer:
        writer.execute('UPDATE components SET function=function')
        assert database_version(writer) == 'Date unknown-r1'
        writer.execute("UPDATE components SET function='Op-amp'")
        writer.rollback()
        assert database_version(writer) == 'Date unknown-r1'
        writer.execute("UPDATE components SET function='Op-amp'")
    day = db.execute("SELECT date('now','localtime')").fetchone()[0]
    assert database_version(db) == f'{day}-r2'
    db.close()

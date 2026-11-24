"""Regressions for the review fixes: start-up DATA folder, imports next to staged
components, undoing a staged pinout deletion, publishing after Save, SVG clean-up."""
import json
import time
from pathlib import Path

import pytest

from test_revision19_fixes import window, seed  # noqa: F401  (fixture)


def wait_for_job(window):
    from PySide6.QtWidgets import QApplication
    deadline = time.monotonic() + 10
    while window.job is not None and time.monotonic() < deadline:
        QApplication.processEvents()
        time.sleep(0.01)
    assert window.job is None


def choose(window, monkeypatch, *paths):
    from PySide6.QtWidgets import QFileDialog
    monkeypatch.setattr(QFileDialog, 'getOpenFileNames', lambda *a: ([str(p) for p in paths], ''))
    window.import_page.choose_button.click()
    wait_for_job(window)


def statuses(window):
    page = window.import_page
    return {page.preview.item(i, 0).text(): page.preview.item(i, 2).text()
            for i in range(page.preview.rowCount())}


# ------------------------------------------------------------------ start-up

def test_main_window_is_not_the_prototype(window):
    import icdb_qt
    assert not hasattr(icdb_qt, 'TEST_DATA')
    assert 'Prototype' not in window.windowTitle()


def test_main_uses_shared_data_resolution(tmp_path, monkeypatch):
    import icdb_qt
    seen = []
    monkeypatch.setattr(icdb_qt, 'data_directory', lambda root: seen.append(root) or tmp_path)
    from PySide6.QtWidgets import QApplication
    monkeypatch.setattr(icdb_qt, 'QApplication', lambda *a: QApplication.instance())
    monkeypatch.setattr(icdb_qt.sys, 'argv', ['icdb_qt.py'])
    monkeypatch.setattr(icdb_qt, 'MainWindow', lambda data, **k: (_ for _ in ()).throw(SystemExit(data)))
    from PySide6.QtWidgets import QMessageBox
    monkeypatch.setattr(QMessageBox, 'question', staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes))
    with pytest.raises(SystemExit) as exc:
        icdb_qt.main()
    assert seen and exc.value.code == tmp_path
    other = tmp_path / 'other'
    monkeypatch.setattr(icdb_qt.sys, 'argv', ['icdb_qt.py', '--data', str(other)])
    with pytest.raises(SystemExit) as exc:
        icdb_qt.main()
    assert exc.value.code == other.resolve()


# ------------------------------------------------------- imports and staged components

def test_csv_import_saves_next_to_staged_component(window, tmp_path, monkeypatch):
    window.component_stage.add('ZZZ1', 'staged')
    window.component_changed()
    csv = tmp_path / 'parts.csv'
    csv.write_text('ZZZ1,From csv\nZZZ2,Other\n', encoding='utf-8')
    choose(window, monkeypatch, csv)
    # The preview sees the staged component, as Save will.
    assert statuses(window) == {'ZZZ1': 'Already in ICDB', 'ZZZ2': 'New'}
    window.import_page.import_button.click()
    assert window.save_all(confirmed=True)
    rows = dict(window.db.execute("SELECT part_number,function FROM components WHERE part_number LIKE 'ZZZ%'"))
    assert rows == {'ZZZ1': 'staged', 'ZZZ2': 'Other'}


def test_component_change_after_staging_import_previews_again(window, tmp_path, monkeypatch):
    csv = tmp_path / 'parts.csv'
    csv.write_text('YYY1,From csv\n', encoding='utf-8')
    choose(window, monkeypatch, csv)
    window.import_page.import_button.click()
    assert window.component_stage.pending_import
    # A component with the same part number is staged after the import.
    window.component_stage.add('YYY1', 'staged later')
    window.component_changed()
    assert window.staged_import_is_stale()
    assert not window.save_all(confirmed=True)          # re-preview instead of a failed Save
    wait_for_job(window)
    assert not window.staged_import_is_stale()
    assert window.component_stage.pending_import['rows'][0][2] == 'Already in ICDB'
    assert window.save_all(confirmed=True)
    assert window.db.execute("SELECT function FROM components WHERE part_number='YYY1'").fetchone()[0] == 'staged later'


# ------------------------------------------------------- staged pinout deletion

def test_undo_deletion_restores_devices(window):
    page = window.library_page
    page._show_definition(window.test_pinout)
    before = set(page._base_members)
    assert before
    page.delete_definition()
    assert str(window.test_pinout) in page.pending_deletions and not page._draft_members
    page.delete_definition()                            # Undo deletion
    assert str(window.test_pinout) not in page.pending_deletions
    assert page._draft_members == before
    assert not page.session_payload()['drafts']
    assert not page.has_pending()


def test_deletion_saves_despite_unfinished_pin_edits(window):
    page = window.library_page
    page._show_definition(window.test_pinout)
    page.pins.item(0, 1).setText('')                    # invalid: blank pin name
    page.mark_changed()
    page.delete_definition()
    assert window.save_all(confirmed=True)
    assert window.db.execute('SELECT 1 FROM pl_definitions WHERE id=?', (window.test_pinout,)).fetchone() is None


def test_delete_button_label_follows_restored_draft(window):
    page = window.library_page
    page._show_definition(window.test_pinout)
    page.title.setText('Edited')
    page.mark_changed()
    page.new_definition()
    assert page.delete_button.text() == 'Discard new pinout'
    page._show_definition(window.test_pinout)          # opens the stashed edit
    assert page.delete_button.text() == 'Delete pinout'


# ------------------------------------------------------- publishing after Save

def test_save_stores_publish_targets_until_published(window, monkeypatch):
    page = window.library_page
    page._show_definition(window.test_pinout)
    page.title.setText('Renamed')
    page.mark_changed()
    monkeypatch.setattr(window, '_publish_after_new_pinout', lambda: None)
    assert window.save_all(confirmed=True)
    assert window._stored_publish_targets() == {window.test_pinout}
    # A later session resumes it.
    started = []
    monkeypatch.setattr(window, '_publish_after_new_pinout', lambda: started.append(set(window._publish_targets)))
    window._publish_targets = set()
    window._resume_pending_publish()
    assert started == [{window.test_pinout}] and not window.publish_notice.isHidden()
    window._clear_publish_targets({window.test_pinout})
    assert window._stored_publish_targets() == set()


def test_publish_queued_by_save_on_close_does_not_start(window, monkeypatch):
    started = []
    monkeypatch.setattr(window, 'run_job', lambda *a, **k: started.append(a[0]) or True)
    window._queue_publish({window.test_pinout})
    window._closed = True
    window._publish_after_new_pinout()
    assert not started
    window._closed = False


def test_publish_removes_superseded_generated_svgs(window):
    from pinouts import Pinouts
    from pin_library import Library
    from builder import connect
    from shared_data import database_file
    db = connect(database_file(window.data))
    library = Library(Pinouts(db, window.data))
    try:
        library.publish()
        first = {r[0] for r in db.execute("SELECT path FROM pinout_assets WHERE path LIKE 'pinouts/generated/%'")}
        assert first
        row, data = library.get(window.test_pinout)
        data['pins'][0]['name'] = data['pins'][0]['name'] + 'X'  # changes the drawing
        library.save(data, window.test_pinout)
        result = library.publish()
        second = {r[0] for r in db.execute("SELECT path FROM pinout_assets WHERE path LIKE 'pinouts/generated/%'")}
        assert result['removed'] == len(first - second) > 0
        for relative in first - second:
            assert not (Path(window.data) / relative).exists()
        for relative in second:
            assert (Path(window.data) / relative).is_file()
    finally:
        db.close()

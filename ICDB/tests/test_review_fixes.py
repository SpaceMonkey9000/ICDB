"""Regression tests for the review fixes: hidden new pinouts, checks at staging time,
recovery drafts that are kept, and the pin role delegate."""
import json
import time

import pytest

from qt_draft_store import read_draft, write_draft
from test_revision19_fixes import definition, window  # noqa: F401  (fixture)


def _titles(page):
    return [page.table.item(r, 0).text() for r in range(page.table.rowCount())]


def _select_row(page, ident):
    for r in range(page.table.rowCount()):
        if page.table.item(r, 0).data(0x0100) == ident:  # Qt.UserRole
            page.table.selectRow(r)
            page.load_selected()
            return
    raise AssertionError(f'{ident!r} not listed: {_titles(page)}')


def _definition_titles(window):
    return sorted(r[0] for r in window.db.execute(
        "SELECT json_extract(project_json,'$.device') FROM pl_definitions"))


# ------------------------------------------------------------ new pinouts

def test_untouched_new_pinout_is_not_staged_or_saved(window):
    page = window.library_page
    page.new_definition()
    assert not page.has_pending() and not window.global_save.isEnabled()
    page.new_definition()                    # a second click
    _select_row(page, window.test_pinout)    # then open another pinout
    assert not any(k.startswith('new:') for k in page.pending_pinouts)
    page.title.setText('Edited')
    page.mark_changed()
    assert window.save_all(confirmed=True)
    assert _definition_titles(window) == ['Edited']   # no hidden "New device"


def test_edited_new_pinout_stays_listed_and_reopens(window):
    page = window.library_page
    page.new_definition()
    page.title.setText('Brand new')
    page.pins.item(0, 1).setText('VCC')      # marks the draft changed
    key = page._active_draft_key
    _select_row(page, window.test_pinout)
    page.refresh()
    assert 'Brand new (new, unsaved)' in _titles(page)
    _select_row(page, key)
    assert page._new and page._active_draft_key == key and page.title.text() == 'Brand new'
    assert window.save_all(confirmed=True)
    assert 'Brand new' in _definition_titles(window)


def test_new_pinout_can_be_discarded_with_delete_button(window):
    page = window.library_page
    page.new_definition()
    page.pins.item(0, 1).setText('VCC')
    assert page.delete_button.text() == 'Discard new pinout'
    page.delete_definition()
    assert not page._new and not page.has_pending()
    assert not any(k.startswith('new:') for k in page.pending_pinouts)


# ------------------------------------------------------ checks at staging time

def test_same_package_assignment_is_refused_when_staged(window, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    warnings = []
    monkeypatch.setattr(QMessageBox, 'warning', staticmethod(lambda *a, **k: warnings.append(a[2])))
    other = window.library.save(definition('Other SOIC', prefix='Q'))
    page = window.library_page
    page._show_definition(other)
    page._stage_group(page._draft_members | {window.test_ids[0], window.test_ids[2]})
    assert window.test_ids[0] not in page._draft_members      # LM358 already has a SOIC-8
    assert window.test_ids[2] in page._draft_members          # NE5532 has none
    assert warnings and 'LM358' in warnings[0]
    assert window.save_all(confirmed=True)


def test_staged_removal_frees_the_package_for_another_pinout(window):
    page = window.library_page
    page._show_definition(window.test_pinout)
    page._stage_group(page._draft_members - {window.test_ids[0]})  # unassign LM358 (staged)
    other = window.library.save(definition('Other SOIC', prefix='Q'))
    page.refresh()
    _select_row(page, other)
    page._stage_group(page._draft_members | {window.test_ids[0]})
    assert window.test_ids[0] in page._draft_members
    assert window.save_all(confirmed=True)


def test_package_change_on_assigned_pinout_warns_in_status_bar(window):
    page = window.library_page
    page._show_definition(window.test_pinout)
    window.tabs.setCurrentWidget(page)
    assert window.status_warning.isHidden()
    page.package.setCurrentText('DIP')
    page.render()
    text = window.status_warning.text()
    assert not window.status_warning.isHidden() and 'SOIC-8 → DIP-8' in text and '2 device(s)' in text
    assert 'Duplicate pinout' in window.status_warning.toolTip()
    # Same colour as other status text in both themes: no fixed colour of its own.
    assert 'color' not in window.status_warning.styleSheet()
    from PySide6.QtWidgets import QApplication
    for dark in (False, True):
        window.set_theme(dark)
        QApplication.processEvents()           # palette changes reach widgets via events
        label = window.status_warning
        text = QApplication.palette().color(QApplication.palette().ColorRole.WindowText)
        assert label.palette().color(label.foregroundRole()) == text
    window.set_theme(False)
    window.tabs.setCurrentWidget(window.components)   # only shown on the Pinout library tab
    assert window.status_warning.isHidden()
    window.tabs.setCurrentWidget(page)
    page._stage_group(set())
    page.render()
    assert window.status_warning.isHidden()


def test_deleting_assigned_pinout_removes_devices_and_saves(window):
    page = window.library_page
    page._show_definition(window.test_pinout)
    page.delete_definition()                   # question() answers Yes in the fixture
    assert str(window.test_pinout) in page.pending_deletions
    assert window.save_all(confirmed=True)
    assert _definition_titles(window) == []
    assert window.db.execute('SELECT count(*) FROM components').fetchone()[0] == 3


def test_save_error_names_the_pinout(window, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    errors = []
    monkeypatch.setattr(QMessageBox, 'critical', staticmethod(lambda *a, **k: errors.append(a[2])))
    page = window.library_page
    page._show_definition(window.test_pinout)
    page.package.setCurrentText('DIP')        # refused at Save: devices still assigned
    page.mark_changed()
    assert not window.save_all(confirmed=True)
    assert 'Existing SOIC' in errors[0] and 'Duplicate pinout' in errors[0]


# ------------------------------------------------------------- recovery drafts

def test_kept_component_draft_is_not_overwritten(window):
    path = window.component_draft_path
    write_draft(path, {'new': True, 'definition_id': None, 'base_members': [], 'draft_members': [],
                       'kind': 'components', 'raw': {'marker': 'kept'}})
    window._component_recovery_pending = False
    window._protect_component_draft = True       # the user chose Keep for later
    window.component_stage.add('NEWPART')
    window.component_changed()
    assert window.save_component_draft()
    kept = list(path.parent.glob(path.stem + '.preserved-*.json'))
    assert len(kept) == 1 and read_draft(kept[0])['raw'] == {'marker': 'kept'}
    assert read_draft(path)['raw']['added']
    # Save and Revert remove only this session's journal, never a kept one.
    window._protect_component_draft = True
    path.unlink()
    write_draft(path, {'new': True, 'definition_id': None, 'base_members': [], 'draft_members': [],
                       'kind': 'components', 'raw': {'marker': 'kept again'}})
    assert window.save_all(confirmed=True)
    assert read_draft(path)['raw'] == {'marker': 'kept again'}


def test_kept_pinout_draft_survives_an_unrelated_save(window):
    path = window.draft_path
    write_draft(path, {'kind': 'pinout_session', 'drafts': {}, 'deletions': {}})
    window._startup_recovery_pending = False
    window._protect_existing_draft = True
    window.component_stage.add('OTHER')
    window.component_changed()
    assert window.save_all(confirmed=True)
    assert path.exists()


def test_preserved_draft_is_offered_at_next_start(window):
    path = window.draft_path
    path.parent.mkdir(parents=True, exist_ok=True)
    older = path.with_name(path.stem + '.preserved-1000.json')
    newer = path.with_name(path.stem + '.preserved-2000.json')
    for item in (older, newer):
        write_draft(item, {'kind': 'pinout_session', 'drafts': {}, 'deletions': {}})
    assert window._recovery_file(path) == newer
    write_draft(path, {'kind': 'pinout_session', 'drafts': {}, 'deletions': {}})
    assert window._recovery_file(path) == path


def _stage_session_with_new_member(window):
    """A new component plus a new pinout whose group contains it, journaled to disk."""
    cid = window.component_stage.add('FRESH1', 'fresh', '')
    window.component_changed()
    window.components.refresh(cid)
    window.components.add_selected_pinout()
    page = window.library_page
    page.pins.item(0, 1).setText('VCC')
    assert window.save_component_draft() and window.save_draft()
    payloads = read_draft(window.draft_path), read_draft(window.component_draft_path)
    # Forget the in-memory session, as after a crash.
    page.pending_pinouts.clear(); page.changed = False; page._new = False
    page.definition_id = None; page.clear()
    window.component_stage.clear()
    return payloads


def test_recovery_restores_components_and_pinouts_together(window, monkeypatch):
    _stage_session_with_new_member(window)
    asked = []
    monkeypatch.setattr(window, '_ask_recovery', lambda found, details: asked.append(found) or 'restore')
    window.offer_session_recovery()
    assert len(asked) == 1 and len(asked[0]) == 2   # one prompt for both journals
    assert window.component_stage.added
    assert window.save_all(confirmed=True)
    cid = window.db.execute("SELECT id FROM components WHERE part_number='FRESH1'").fetchone()[0]
    assert window.db.execute('SELECT 1 FROM pl_assignments WHERE component_id=?', (cid,)).fetchone()


def test_recovery_prunes_members_when_components_cannot_be_restored(window, monkeypatch):
    pinout_payload, component_payload = _stage_session_with_new_member(window)
    component_payload['raw']['deleted'] = {str(window.test_ids[0]): {'part_number': 'CHANGED',
                                                                     'function': '', 'manufacturer': ''}}
    write_draft(window.component_draft_path, component_payload)   # now conflicts with the database
    monkeypatch.setattr(window, '_ask_recovery', lambda found, details: 'restore')
    window.offer_session_recovery()
    assert not window.component_stage.changed
    assert window.component_draft_path.exists()        # kept, not overwritten
    assert all(int(c) > 0 for d in window.library_page.session_payload()['drafts'].values()
               for c in d['draft_members'])
    assert window.save_all(confirmed=True)


def test_keep_for_later_protects_both_journals(window, monkeypatch):
    _stage_session_with_new_member(window)
    monkeypatch.setattr(window, '_ask_recovery', lambda found, details: 'keep')
    window.offer_session_recovery()
    assert window._protect_existing_draft and window._protect_component_draft


# ------------------------------------------------------------- pin role delegate

def test_roles_are_items_not_widgets(window):
    page = window.library_page
    page._show_definition(window.test_pinout)
    assert page.pins.cellWidget(0, 2) is None
    assert page._pin_role(0) == 'Signal'
    page.pins.item(0, 2).setText('Power')       # what the delegate writes
    assert page.changed and page.read_data()['pins'][0]['role'] == 'Power'


def test_large_pinout_opens_quickly(window):
    big = window.library.save(definition('Big', prefix='B', package='QFP', count=1024))
    page = window.library_page
    start = time.perf_counter()
    page._show_definition(big)
    assert time.perf_counter() - start < 0.6    # was ~1.3 s with one combo box per pin
    assert page.pins.rowCount() == 1024


# ------------------------------------------------------------- devices

def test_device_dialog_stays_open_on_errors(window):
    from ui.dialogs import DeviceDialog
    dialog = DeviceDialog(window.components, validate=window.components.device_error)
    dialog.accept()                                  # empty part number
    assert dialog.result() == 0
    dialog.part.setText('lm358')                     # duplicate of a saved part
    dialog.accept()
    assert dialog.result() == 0 and dialog.part.text() == 'lm358'
    dialog.part.setText('LM358')
    dialog.manufacturer.setText('TI')                # another manufacturer is fine
    dialog.accept()
    assert dialog.result() == 1


def test_duplicates_consider_staged_changes(window):
    comp, stage, db = window.components, window.component_stage, window.db
    lm358, tl072 = window.test_ids[:2]
    assert comp.device_error('LM358') and comp.device_error('LM358', ignore=lm358) is None
    stage.add('NEWPART', '', 'ACME')
    assert comp.device_error('newpart', '', 'acme')
    stage.delete(db, tl072)                          # a staged deletion frees its name
    assert comp.device_error('TL072') is None
    stage.update(db, lm358, part_number='LM358B')    # so does a staged rename
    assert comp.device_error('LM358') is None and comp.device_error('LM358B')


def test_inline_rename_to_existing_part_is_refused(window):
    comp = window.components
    comp.refresh(window.test_ids[0])
    row = next(r for r in range(comp.table.rowCount())
               if comp.table.item(r, 0).data(0x0100) == window.test_ids[0])
    comp.table.item(row, 0).setText('TL072')
    assert not window.component_stage.edits
    assert any(comp.table.item(r, 0).text() == 'LM358' for r in range(comp.table.rowCount()))


def test_edit_device_changes_manufacturer(window, monkeypatch):
    from PySide6.QtWidgets import QDialog
    from ui import components_page
    comp = window.components
    comp.refresh(window.test_ids[0])
    assert comp.edit_button.isEnabled()
    comp._change_alias(window.test_ids[0], None, dict(marking='L358', packages=[], source=''))

    class FakeDialog:
        def __init__(self, parent, record, validate=None):
            self.validate = validate
        def exec(self):
            return QDialog.DialogCode.Accepted
        def values(self):
            return 'LM358', 'Op-amp', 'Texas Instruments'
    monkeypatch.setattr(components_page, 'DeviceDialog', FakeDialog)
    comp.edit()
    assert window.component_stage.edits[window.test_ids[0]]['after']['manufacturer'] == 'Texas Instruments'
    assert window.save_all(confirmed=True)        # the alias follows the edited identity
    assert window.db.execute('SELECT manufacturer FROM components WHERE id=?',
                             (window.test_ids[0],)).fetchone()[0] == 'Texas Instruments'


def test_alias_change_shows_current_part_number(window):
    cid = window.component_stage.add('FIRSTNAME')
    window.component_stage.change_alias(window.db, cid, replacement=dict(marking='FN1', packages=[], source=''))
    window.component_stage.update(window.db, cid, part_number='SECONDNAME')
    assert 'Add alias FN1 → SECONDNAME (new)' in window.changes_text()


# ------------------------------------------------------------- pinout editor

def test_editor_is_disabled_without_an_open_pinout(window):
    page = window.library_page
    page._show_definition(window.test_pinout)
    assert all(p.isEnabled() for p in page._editor_pages)
    page.definition_id = None
    page.clear()
    assert not any(p.isEnabled() for p in page._editor_pages)
    assert page.package.currentText() == '' and page.title.text() == ''
    page.new_definition()
    assert all(p.isEnabled() for p in page._editor_pages)


# ------------------------------------------------------------- publishing

def test_publish_waits_for_running_job_and_shows_notice(window, monkeypatch):
    started = []
    monkeypatch.setattr(window, 'run_job', lambda *a, **k: started.append(a[0]) or True)
    window.job = object()                             # another operation is running
    window._queue_publish({window.test_pinout})
    window._publish_after_new_pinout()
    assert window._publish_retry and not window.publish_notice.isHidden() and not started
    window.job = None
    window.component_stage.add('STAGED')              # new edits staged meanwhile
    window._publish_after_new_pinout()
    assert not started and not window.publish_notice.isHidden()
    window.component_stage.clear()
    window._publish_after_new_pinout()
    assert started == ['publish']
    window.publish_complete({'updated': 1}, 'Publish result')
    assert window.publish_notice.isHidden()


# ------------------------------------------------------------- targeted publishing

def test_save_publishes_only_the_edited_pinout(window, monkeypatch):
    from PySide6.QtCore import QTimer
    other = window.library.save(definition('Other', prefix='Q', package='DIP'))
    window.library.add_group_members(other, [window.test_ids[2]])
    jobs = []
    monkeypatch.setattr(window, 'run_job', lambda op, payload, *a, **k: jobs.append((op, payload)) or True)
    monkeypatch.setattr(QTimer, 'singleShot', staticmethod(lambda ms, fn: fn()))
    page = window.library_page
    page._show_definition(window.test_pinout)
    page.pins.item(0, 2).setText('Power')
    assert window.save_all(confirmed=True)
    assert jobs == [('publish', {'definition_ids': [window.test_pinout]})]


def test_renaming_a_device_republishes_its_pinouts(window, monkeypatch):
    from PySide6.QtCore import QTimer
    jobs = []
    monkeypatch.setattr(window, 'run_job', lambda op, payload, *a, **k: jobs.append((op, payload)) or True)
    monkeypatch.setattr(QTimer, 'singleShot', staticmethod(lambda ms, fn: fn()))
    window.component_stage.update(window.db, window.test_ids[0], part_number='LM358N')
    assert window.save_all(confirmed=True)
    assert jobs == [('publish', {'definition_ids': [window.test_pinout]})]   # labels carry the part


def test_targeted_publish_touches_only_listed_pinouts(tmp_path):
    from builder import connect
    from pinouts import Pinouts
    from pin_library import Library
    db = connect(tmp_path / 'components.sqlite')
    lib = Library(Pinouts(db, tmp_path))
    with db:
        ids = [db.execute("INSERT INTO components(part_number,manufacturer,family_hint,function) "
                          "VALUES(?,'','','')", (f'P{i}',)).lastrowid for i in range(4)]
    a = lib.save(definition('A', prefix='A'))
    b = lib.save(definition('B', prefix='B', package='DIP'))
    lib.add_group_members(a, ids[:2])
    lib.add_group_members(b, ids[2:])
    seen = []
    result = lib.publish(definition_ids=[a], progress=lambda done, total: seen.append((done, total)))
    assert result['updated'] == 2 and seen[0] == (0, 2) and seen[-1] == (2, 2)
    linked = {r[0] for r in db.execute('SELECT component_id FROM pinout_links')}
    assert linked == set(ids[:2])
    assert lib.publish()['updated'] == 2        # the full publish picks up the rest
    db.close()


def test_image_paths_are_checked_without_resolving(tmp_path):
    from builder import connect
    from pinouts import Pinouts
    store = Pinouts(connect(tmp_path / 'components.sqlite'), tmp_path)
    assert store.path({'path': 'pinouts/generated/x.svg'}) == store.root / 'pinouts' / 'generated' / 'x.svg'
    assert store.path({'path': 'Pinouts\\old.png'}) == store.root / 'Pinouts' / 'old.png'
    for bad in ('pinouts/../components.sqlite', '/etc/passwd', 'C:/x/pinouts/a.svg', 'other/a.svg', ''):
        with pytest.raises(ValueError):
            store.path({'path': bad})

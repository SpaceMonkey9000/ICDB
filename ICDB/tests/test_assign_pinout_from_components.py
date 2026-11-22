"""GUI integration checks for assigning library pinouts from Components / ICOCR handoff."""
import pytest
from test_revision19_fixes import window  # existing offscreen Qt fixture and temporary database


def _choose_definition(monkeypatch, library_id):
    from PySide6.QtWidgets import QDialog
    from ui.dialogs import PinoutAssignmentDialog
    def select(dialog):
        dialog.definition_id = library_id
        return QDialog.DialogCode.Accepted
    monkeypatch.setattr(PinoutAssignmentDialog, 'exec', select)


def test_assign_existing_component_is_staged_until_save(window, monkeypatch):
    _choose_definition(monkeypatch, window.test_pinout)
    page = window.components
    page.refresh(window.test_ids[2])  # NE5532 initially has no pinout
    assert page.assign_pinout_button.isEnabled()
    page.assign_selected_pinout()
    assert window.test_ids[2] in window.library_page._draft_members
    assert not window.db.execute('''SELECT 1 FROM pl_assignments WHERE component_id=?
        AND definition_id=? ''',
        (window.test_ids[2], window.test_pinout)).fetchone()
    assert window.save_all(confirmed=True)
    assert window.db.execute('''SELECT 1 FROM pl_assignments WHERE component_id=?
        AND definition_id=? ''',
        (window.test_ids[2], window.test_pinout)).fetchone()


def test_assign_unsaved_icocr_component_in_same_commit(window, monkeypatch):
    _choose_definition(monkeypatch, window.test_pinout)
    cid = window.component_stage.add('NEWIC123', 'Example IC', '')
    window.component_changed()
    page = window.components
    page.refresh(cid)
    assert page.assign_pinout_button.isEnabled()
    page.assign_selected_pinout()
    assert cid in window.library_page._draft_members
    assert window.save_all(confirmed=True)
    actual = window.db.execute('SELECT id FROM components WHERE part_number=?',
                               ('NEWIC123',)).fetchone()
    assert actual
    assert window.db.execute('''SELECT 1 FROM pl_assignments WHERE component_id=?
        AND definition_id=? ''',
        (actual[0], window.test_pinout)).fetchone()


def test_cancel_picker_does_not_stage_membership(window, monkeypatch):
    from PySide6.QtWidgets import QDialog
    from ui.dialogs import PinoutAssignmentDialog
    monkeypatch.setattr(PinoutAssignmentDialog, 'exec',
                        lambda _: QDialog.DialogCode.Rejected)
    page = window.components
    page.refresh(window.test_ids[2])
    page.assign_selected_pinout()
    assert not window.library_page.has_pending()

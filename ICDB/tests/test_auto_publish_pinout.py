"""Publishing new accepted pinouts after an atomic Save."""
import pytest
from builder import connect
from pinouts import Pinouts
from pin_library import Library
from test_revision19_fixes import definition, window


def test_new_accepted_definition_can_publish_without_forced_rebuild(tmp_path):
    db = connect(tmp_path / 'components.sqlite')
    library = Library(Pinouts(db, tmp_path))
    with db:
        component_id = db.execute(
            "INSERT INTO components(part_number,manufacturer,family_hint,function) "
            "VALUES('NEWIC88','','','Test IC')"
        ).lastrowid
    db.execute('BEGIN IMMEDIATE')
    definition_id = library.save(definition('NEWIC88'), None, locked=True)
    row, _ = library.get(definition_id)
    library.save_with_members(definition('NEWIC88'), definition_id, row['revision'],
                              set(), {component_id}, locked=True)
    db.commit()

    # Database commit alone does not create the shared generated SVG.
    assert db.execute('SELECT COUNT(*) FROM pinout_links').fetchone()[0] == 0
    result = library.publish(force=False)
    assert result['updated'] == 1
    assert not result['skipped']
    link = db.execute('''SELECT a.path FROM pinout_links l JOIN pinout_assets a
                         ON l.asset_id=a.id WHERE l.component_id=?''', (component_id,)).fetchone()
    assert link is not None
    svg = tmp_path / link[0]
    assert svg.is_file()
    assert b'<svg' in svg.read_bytes()
    assert library.publish(force=False)['unchanged'] == 1
    db.close()


def test_new_assigned_pinout_schedules_publish_after_save(window, monkeypatch):
    from PySide6.QtCore import QTimer
    callbacks = []
    monkeypatch.setattr(QTimer, 'singleShot', staticmethod(lambda ms, fn: callbacks.append((ms, fn))))
    window.components.refresh(window.test_ids[2])
    window.components.add_selected_pinout()
    assert window.save_all(confirmed=True)
    assert any(getattr(fn, '__name__', '') == '_publish_after_new_pinout'
               for ms, fn in callbacks)
    # The queued callback is not triggered before Save commits.
    assert window.db.execute('SELECT COUNT(*) FROM pinout_links WHERE component_id=?',
                             (window.test_ids[2],)).fetchone()[0] == 0


def test_new_unassigned_definition_does_not_schedule_svg_publish(window, monkeypatch):
    from PySide6.QtCore import QTimer
    callbacks = []
    monkeypatch.setattr(QTimer, 'singleShot', staticmethod(lambda ms, fn: callbacks.append(fn)))
    window.library_page.new_definition()
    # No associated device, so the new definition is not an ICOCR publication.
    assert window.save_all(confirmed=True)
    assert not any(getattr(fn, '__name__', '') == '_publish_after_new_pinout'
                   for fn in callbacks)

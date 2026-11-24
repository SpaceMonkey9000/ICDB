"""Pinout library actions: new, use existing, delete, save and publish."""
import uuid
from PySide6.QtWidgets import (
    QMessageBox, QDialog,
)
from pin_library import signature
from library_queries import group_members
from ui.dialogs import PinoutAssignmentDialog


class PinoutActionsMixin:
    """Create, link, delete, save and publish definitions. Mixed into PinoutLibraryPage."""

    def new_definition(self):
        self.stash_current()
        self.draft_timer.stop()
        self.preview_timer.stop()
        self.table.blockSignals(True)
        self.table.clearSelection()
        self.table.blockSignals(False)
        self.definition_id = None
        self._active_draft_key = 'new:' + uuid.uuid4().hex
        self._new = True
        self._link_component_id = None
        self.loading = True
        self.data = dict(device='New device', package='SOIC', count=8, source='', verified=False,
            pins=[dict(number=i, name='NC', role='NC', description='') for i in range(1,9)])
        self._populate_editor(self.data)
        self._reset_group_draft()
        self.refresh_members()
        self.loading = False
        # Not a staged change until the user edits it or assigns devices: an untouched
        # template is dropped when another pinout is opened, instead of being written
        # at Save as a hidden "New device" (two of them made Save fail outright).
        self.changed = False
        self._update_use_existing_button()
        self._update_delete_button()
        self.render()
        self.refresh()
        self.app.update_draft_ui()
        self.app.message('New pinout opened. Edit it or add devices to stage it; Save commits it.')

    def _update_use_existing_button(self):
        self.use_existing_button.setVisible(bool(self._new and self._link_component_id is not None))

    def use_existing_definition(self):
        """Replace the new pinout draft with an existing definition linked to the same device."""
        cid = self._link_component_id
        if cid is None or not self._new:
            return
        if cid < 0:
            record = self.app.component_stage.added.get(cid)
        else:
            saved = self.app.db.execute('SELECT * FROM components WHERE id=?', (cid,)).fetchone()
            record = self.app.component_stage.view(cid, dict(saved)) if saved else None
        if not record:
            QMessageBox.warning(self, 'Use existing definition', 'Component no longer available.')
            return
        picker = PinoutAssignmentDialog(self, self.app.db, record['part_number'])
        if picker.exec() != QDialog.DialogCode.Accepted:
            return
        # Switching to an existing pinout intentionally replaces this new draft.
        # Avoid silently dropping pin edits the user has already entered.
        if any(self._row_has_content(i) for i in range(self.pins.rowCount())) or self.source.text().strip():
            if QMessageBox.question(self, 'Use existing definition',
                    'Discard the new pinout draft and link the existing definition instead?',
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
                return
        key = self._draft_key()
        # The new definition was only a provisional choice. Replace that draft rather
        # than committing an unwanted empty pinout alongside the existing association.
        self.pending_pinouts.pop(key, None)
        self.changed = False
        self._link_component_id = None
        self.app.open_pinout_definition(picker.definition_id)
        if self.definition_id != picker.definition_id:
            return
        self._stage_group(self._draft_members | {cid})
        self._update_use_existing_button()
        self.app.save_draft()
        if cid in self._draft_members:
            self.app.message(f"Existing pinout linked to {record['part_number']} (unsaved).")

    def discard_new_definition(self):
        """Drop the new pinout open in the editor (staged or untouched)."""
        if self.changed and QMessageBox.question(self, 'Discard new pinout',
                'Discard this new pinout and its staged device assignments?',
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return
        self.draft_timer.stop()
        self.preview_timer.stop()
        self.pending_pinouts.pop(self._active_draft_key, None)
        self.changed = False
        self._new = False
        self.definition_id = None
        self._active_draft_key = None
        self.clear()
        self.refresh()
        self.app.save_draft() if self.has_pending() else self.app.clear_draft()
        self.app.update_draft_ui()
        self.app.components.show_details()
        self.app.message('New pinout discarded.')

    def delete_definition(self):
        if self._new:
            if self.data is not None:
                self.discard_new_definition()
            return
        ident = self.definition_id
        if ident is None:
            QMessageBox.information(self, 'Delete pinout', 'Select a saved pinout to delete.')
            return
        key = str(ident)
        if key in self.pending_deletions:
            deletion = self.pending_deletions.pop(key)
            # The editor holds this pinout's state; staging the deletion also stashed a
            # copy with its devices removed, which Save would otherwise still apply.
            self.pending_pinouts.pop(key, None)
            self.changed = self._pin_fields_changed or self._draft_members != self._base_members
            # Staging the deletion removed the pinout's devices; put them back.
            restore = set(map(int, deletion.get('restore_members', deletion.get('members', []))))
            if restore != self._draft_members:
                self._stage_group(restore)
            self.app.update_draft_ui()
            self.app.save_draft() if self.has_pending() else self.app.clear_draft()
            self.refresh()
            self.app.message('Staged pinout deletion cancelled.')
            return
        try:
            row, data = self.app.library.get(ident)
            accepted = {r['component_id'] for r in group_members(self.app.db, ident)}
            sources = self.app.db.execute(
                'SELECT count(*) FROM pl_sources WHERE definition_id=?', (ident,)).fetchone()[0]
        except Exception as exc:
            QMessageBox.critical(self, 'Delete pinout', str(exc))
            return
        if sources:
            QMessageBox.warning(self, 'Delete pinout',
                'Imported source references still use this definition. Detach them before deletion.')
            return
        # Save refuses to delete a pinout that still has devices, and a refused Save
        # discards every other staged change too. Settle the devices here instead.
        members = set(self._draft_members) if self.definition_id == ident else set(accepted)
        name = f'"{data.get("device", "Untitled")}" ({data.get("package", "")})'
        if members:
            text = (f'Pinout {name} is assigned to {len(members)} device(s).\n\n'
                    'Remove those assignments and stage the deletion? Nothing changes in the database '
                    'until Save; Revert cancels both.')
        else:
            text = (f'Stage deletion of pinout {name}?\n\n'
                    'No database changes occur until global Save. Revert cancels the deletion.')
        response = QMessageBox.question(self, 'Delete pinout', text,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if response != QMessageBox.StandardButton.Yes:
            return
        if members:
            self._stage_group(set())
        self.stash_current()
        self.pending_deletions[key] = {'definition_id': int(ident), 'revision': row['revision'],
                                        'members': sorted(accepted),
                                        'restore_members': sorted(members),
                                        'name': str(data.get('device', 'Untitled')),
                                        'package': str(data.get('package', ''))}
        self.app.update_draft_ui()
        self.app.save_draft()
        self.refresh()
        self.app.message('Pinout deletion staged. View changes or Save to commit; Revert to cancel.')

    def save(self, as_new=False):
        if not as_new:
            self.app.save_all()
            return
        if self.data is None:
            return
        if self._draft_members != self._base_members:
            QMessageBox.warning(self, 'Duplicate pinout',
                'Revert group membership edits before copying this pinout as a new definition.')
            return
        original = self.definition_id
        try:
            data = self.read_data()
        except Exception as exc:
            QMessageBox.warning(self, 'Duplicate pinout', str(exc))
            return
        existing = self.app.db.execute('SELECT id FROM pl_definitions WHERE signature=?',
                                       (signature(data),)).fetchone()
        if existing:
            # Saving would be refused: a copy needs different pin data (the title is not part of it).
            QMessageBox.information(self, 'Duplicate pinout',
                f'Pinout #{existing[0]} already has exactly this pin data; a title alone does not make a '
                'new pinout. Edit the package, pins or exposed pad here first, then choose Duplicate pinout. '
                'The original stays unchanged.')
            return
        # Save as new becomes another staged draft. It never writes before global Save.
        if original is not None:
            self.pending_pinouts.pop(str(original), None)
        self._active_draft_key = 'new:' + uuid.uuid4().hex
        self.definition_id = None
        self._new = True
        self._link_component_id = None
        self.data = data
        self._base_revision = None
        self._base_members = set()
        self._draft_members = set()
        self._group_undo.clear()
        self._pin_fields_changed = True
        self.changed = True
        self.table.blockSignals(True)
        self.table.clearSelection()
        self.table.blockSignals(False)
        self.refresh_members()
        self._update_use_existing_button()
        self._update_delete_button()
        self.refresh()
        self.app.update_draft_ui()
        self.draft_timer.start()
        self.app.message('Pinout copy staged as new; Save commits it with the rest of the session.')

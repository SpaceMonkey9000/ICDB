"""Staged pinout edits per definition, and the session/recovery payloads."""
import copy
import uuid
import time
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QTableWidgetItem,
)


class PinoutDraftsMixin:
    """Per-definition staged edits and recovery payloads. Mixed into PinoutLibraryPage."""

    def _draft_key(self):
        if self._new:
            if not self._active_draft_key or not self._active_draft_key.startswith('new:'):
                self._active_draft_key = 'new:' + uuid.uuid4().hex
            return self._active_draft_key
        return str(self.definition_id) if self.definition_id is not None else None

    def has_pending(self):
        return self.changed or bool(self.pending_pinouts) or bool(self.pending_deletions)

    def stash_current(self):
        if self.changed and self.data is not None:
            key = self._draft_key()
            if key:
                self.pending_pinouts[key] = self.draft_payload()
        self.changed = False

    def session_payload(self):
        drafts = dict(self.pending_pinouts)
        if self.changed and self.data is not None:
            key = self._draft_key()
            if key:
                drafts[key] = self.draft_payload()
        return {'kind': 'pinout_session', 'drafts': drafts,
                'deletions': copy.deepcopy(self.pending_deletions), 'saved_at': time.time()}

    def load_session(self, drafts, deletions=None):
        # Validate all supplied keys before mutating the active editor.
        if not isinstance(drafts, dict):
            raise ValueError('Pinout draft session is not an object')
        for key, payload in drafts.items():
            if not isinstance(payload, dict) or 'raw' not in payload:
                raise ValueError(f'Invalid pinout draft {key}')
        self.pending_pinouts = dict(drafts)
        self.pending_deletions = dict(deletions or {})
        self.changed = False
        self.app.update_draft_ui()

    def draft_payload(self):
        """Store exactly what is on screen; invalid intermediate edits are allowed."""
        if self.data is None:
            return None
        raw = {'title': self.title.text(), 'package': self.package.currentText(),
               'source': self.source.text(), 'count': self.count.value(),
               'pad_enabled': self.pad_enabled.isChecked(),
               'pad_number': self.pad_number.text(), 'pad_name': self.pad_name.text(),
               'pad_role': self.pad_role.currentText(),
               'pins': [[(self._pin_role(i) if j == 2 else
                         (self.pins.item(i,j).text() if self.pins.item(i,j) else ''))
                         for j in range(4)] for i in range(self.pins.rowCount())]}
        return {'definition_id': self.definition_id, 'new': self._new,
                'base_revision': self._base_revision,
                'base_members': sorted(self._base_members),
                'group_undo': [sorted(members) for members in self._group_undo],
                'pin_fields_changed': self._pin_fields_changed,
                'draft_members': sorted(self._draft_members), 'link_component': self._link_component_id, 'raw': raw,
                'saved_at': time.time()}

    def restore_draft(self, draft, key=None):
        """Open a staged or recovered draft in the editor. A new draft keeps its list key."""
        self.preview_timer.stop()
        self.loading = True
        self.table.blockSignals(True)
        try:
            if draft['new']:
                self._active_draft_key = key if key and str(key).startswith('new:') else 'new:' + uuid.uuid4().hex
            else:
                self._active_draft_key = str(draft['definition_id'])
            self.definition_id = draft['definition_id']
            self._new = bool(draft['new'])
            if self._new:
                self.data = dict(device='New device', package='SOIC', count=1,
                                 pins=[dict(number=1,name='NC',role='NC',description='')])
            else:
                _, self.data = self.app.library.get(self.definition_id)
            target = self._active_draft_key if self._new else self.definition_id
            self.table.clearSelection()
            for row in range(self.table.rowCount()):
                item = self.table.item(row, 0)
                if item and item.data(Qt.ItemDataRole.UserRole) == target:
                    self.table.selectRow(row)
                    break
            self._base_revision = draft['base_revision']
            self._base_members = set(map(int, draft['base_members']))
            self._draft_members = set(map(int, draft['draft_members']))
            self._group_undo = [set(members) for members in draft.get('group_undo', [])]
            self._pin_fields_changed = draft.get('pin_fields_changed', True)
            self._link_component_id = draft.get('link_component')
            raw = draft['raw']
            self.title.setText(raw['title'])
            self.package.setCurrentText(raw['package'])
            self.source.setText(raw['source'])
            self.count.setValue(int(raw['count']))
            self.pad_enabled.setChecked(bool(raw['pad_enabled']))
            self.pad_number.setText(raw['pad_number'])
            self.pad_name.setText(raw['pad_name'])
            self.pad_role.setCurrentText(raw['pad_role'])
            self.pins.setRowCount(len(raw['pins']))
            for i, line in enumerate(raw['pins']):
                for j in (0,1,3):
                    self.pins.setItem(i,j,QTableWidgetItem(str(line[j])))
                self._role_combobox(i, str(line[2]))
            self.changed = True
        finally:
            self.loading = False
            self.table.blockSignals(False)
        self.refresh_members()
        self._update_use_existing_button()
        self.render()
        self.app.update_draft_ui()

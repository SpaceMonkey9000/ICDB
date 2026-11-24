"""Groups panel: staged additions and removals of the components that share a pinout."""
import json
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem, QAbstractItemView,
    QLineEdit, QPushButton, QDialog, QMessageBox,
)
from builder import search_pattern, unicode_like
from library_queries import group_members
from pin_library import package_label


class PinoutGroupsMixin:
    """Staged group membership. Mixed into PinoutLibraryPage."""

    def _reset_group_draft(self):
        if self.definition_id is None:
            self._base_revision = None
            self._base_members = set()
        else:
            row, _ = self.app.library.get(self.definition_id)
            self._base_revision = row['revision']
            self._base_members = {r['component_id'] for r in group_members(self.app.db, self.definition_id)}
        self._draft_members = set(self._base_members)
        self._group_undo.clear()
        self._pin_fields_changed = False

    def _editor_package_label(self):
        try:
            return package_label(self.read_data())
        except Exception:
            return package_label(self.data) if self.data is not None else None

    def _package_conflicts(self, component_ids):
        """component id -> title of another pinout with the same package that the component
        keeps after this session (saved assignments not staged for removal, plus other staged
        drafts). Save refuses these, and a refused Save discards every staged change."""
        label = self._editor_package_label()
        if label is None or not component_ids:
            return {}
        current_key = self._active_draft_key if self._new else str(self.definition_id)
        drafts = {key: draft for key, draft in self.session_payload()['drafts'].items() if key != current_key}

        def draft_label(draft, fallback_json=None):
            try:
                return package_label(self.app._pinout_data_from_draft(draft)), draft['raw']['title']
            except Exception:
                if fallback_json is None:
                    return None, None
                data = json.loads(fallback_json)
                return package_label(data), data.get('device')

        conflicts = {}
        for cid in component_ids:
            if cid > 0:
                for ident, project_json in self.app.db.execute(
                        'SELECT d.id,d.project_json FROM pl_assignments a JOIN pl_definitions d '
                        'ON d.id=a.definition_id WHERE a.component_id=?', (cid,)):
                    key = str(ident)
                    if key == current_key or key in self.pending_deletions:
                        continue
                    if key in drafts:
                        if cid not in set(map(int, drafts[key]['draft_members'])):
                            continue  # staged removal
                        other, title = draft_label(drafts[key], project_json)
                    else:
                        data = json.loads(project_json)
                        other, title = package_label(data), data.get('device')
                    if other == label:
                        conflicts[cid] = title or 'Untitled'
            for key, draft in drafts.items():
                if cid in conflicts or cid not in set(map(int, draft['draft_members'])):
                    continue
                other, title = draft_label(draft)
                if other == label:
                    conflicts[cid] = (title or 'Untitled') + ' (staged)'
        return conflicts

    def _stage_group(self, new_members):
        new_members = set(map(int, new_members))
        conflicts = self._package_conflicts(new_members - self._draft_members)
        if conflicts:
            names = []
            for cid, title in sorted(conflicts.items()):
                part = self._member_part_number(cid)
                names.append(f'{part}: already uses “{title}”')
            QMessageBox.warning(self, 'Devices not added',
                f'These devices already have a {self._editor_package_label()} pinout and were not added. '
                'Remove that assignment first.\n\n' + '\n'.join(names[:20])
                + (f'\n… and {len(names) - 20} more' if len(names) > 20 else ''))
            new_members -= set(conflicts)
        if new_members == self._draft_members:
            return
        self._group_undo.append(set(self._draft_members))
        self._draft_members = new_members
        self._group_changed()
        self.app.message('Group changes staged — Save commits, Revert discards.')

    def _member_part_number(self, cid):
        stage = self.app.component_stage
        if cid < 0:
            return stage.added.get(cid, {}).get('part_number', f'#{cid}')
        if cid in stage.edits:
            return stage.edits[cid]['after']['part_number']
        row = self.app.db.execute('SELECT part_number FROM components WHERE id=?', (cid,)).fetchone()
        return row[0] if row else f'#{cid}'

    def _group_changed(self):
        # A new pinout counts as staged once it has devices or edited fields.
        self.changed = self._pin_fields_changed or self._draft_members != self._base_members
        self.app.update_draft_ui()
        self.refresh_members()
        self.queue_preview()  # refreshes the package-change warning
        self.app.components.show_details()
        if self.has_pending():
            self.draft_timer.start()
        else:
            self.draft_timer.stop()
            self.app.clear_draft()

    def update_group_actions(self):
        editable = self.data is not None
        self.add_members_button.setEnabled(editable)
        self.remove_members_button.setEnabled(editable and bool(self.members.selectionModel().selectedRows()))
        self.undo_group_button.setEnabled(editable and bool(self._group_undo))

    def refresh_members(self):
        # Display both persisted and staged additions, with the staged field values.
        stage = self.app.component_stage
        ids = sorted(self._draft_members)
        rows = []
        persisted = [cid for cid in ids if cid > 0 and cid not in stage.deleted]
        for offset in range(0, len(persisted), 500):
            chunk = persisted[offset:offset+500]
            for row in self.app.db.execute(
                'SELECT id,part_number,function FROM components WHERE id IN ('+
                ','.join('?' for _ in chunk)+')', chunk):
                record = dict(row)
                if record['id'] in stage.edits:
                    record.update(stage.edits[record['id']]['after'])
                rows.append(record)
        for cid in ids:
            if cid < 0:
                if cid in stage.added:
                    rows.append({'id': cid, **stage.added[cid]})
                else:
                    # A recovered draft can reference an unsaved component whose own draft
                    # was not restored. Show it so it can be removed; Save rejects it.
                    rows.append({'id': cid, 'part_number': '(missing unsaved component)',
                                 'function': 'Not restored. Remove it from the group.'})
        rows.sort(key=lambda row: (row['part_number'] or '').casefold())
        sorting = self.members.isSortingEnabled()
        self.members.setSortingEnabled(False)
        self.members.setRowCount(len(rows))
        for row_index, record in enumerate(rows):
            for col, key in enumerate(('part_number','function')):
                item = QTableWidgetItem(record[key] or '')
                item.setData(Qt.ItemDataRole.UserRole, record['id'])
                self.members.setItem(row_index, col, item)
        self.members.setSortingEnabled(sorting)
        self.update_group_actions()

    def open_group_member(self, item):
        self.app.components.open_device(item.data(Qt.ItemDataRole.UserRole))

    def add_members(self):
        if self.data is None:
            return
        dialog = QDialog(self)
        dialog.setWindowTitle('Stage devices for pinout group')
        dialog.resize(820, 580)
        layout = QVBoxLayout(dialog)
        query = QLineEdit()
        query.setPlaceholderText('Search part number…')
        layout.addWidget(query)
        table = QTableWidget(0,3)
        table.setHorizontalHeaderLabels(['Part number','Function','Current pinout'])
        table.verticalHeader().hide()
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.horizontalHeader().setStretchLastSection(True)
        table.setSortingEnabled(True)
        layout.addWidget(table,1)

        def search():
            # The Components tab also has staged additions, edits and deletions.
            # Expose its live draft here instead of searching SQLite alone.
            text = query.text()
            pattern = search_pattern(text) if text.strip() else None
            if pattern is None:
                existing = [dict(r) for r in self.app.db.execute('''
                    SELECT id,part_number,function FROM components
                    ORDER BY part_number COLLATE NOCASE LIMIT 5000''')]
            else:
                existing = [dict(r) for r in self.app.db.execute('''
                    SELECT id,part_number,function FROM components
                    WHERE part_number LIKE ? ESCAPE '\\' OR function LIKE ? ESCAPE '\\'
                    ORDER BY part_number COLLATE NOCASE LIMIT 5000''', (pattern, pattern))]
            stage = self.app.component_stage
            rows = []
            def matches(value):
                # Same Unicode-aware LIKE as the SQL search, evaluated in Python (no round trip).
                return pattern is None or bool(unicode_like(pattern, value or '', '\\'))
            for record in existing:
                cid = record['id']
                if cid in stage.deleted or cid in self._draft_members:
                    continue
                if cid in stage.edits:
                    # Only staged edits can differ from what SQLite already matched.
                    record = {**record, **stage.edits[cid]['after']}
                    if not (matches(record['part_number']) or matches(record['function'])):
                        continue
                rows.append(record)
            # Edits that newly match the search must also be included.
            present = {r['id'] for r in rows}
            for cid, edit in stage.edits.items():
                if cid in present or cid in stage.deleted or cid in self._draft_members:
                    continue
                record = {'id': cid, **edit['after']}
                if matches(record['part_number']) or matches(record['function']):
                    rows.append(record)
            for cid, record in stage.added.items():
                if cid in self._draft_members:
                    continue
                if matches(record['part_number']) or matches(record['function']):
                    rows.append({'id': cid, **record})
            rows.sort(key=lambda r: (r['part_number'] or '').casefold())
            rows = rows[:5000]
            ids = [int(r['id']) for r in rows if int(r['id']) > 0]
            assigned = {}
            for offset in range(0, len(ids), 500):
                chunk = ids[offset:offset+500]
                sql = """SELECT m.component_id,
                    json_extract(d.project_json,'$.device') AS title,
                    json_extract(d.project_json,'$.package') AS family,
                    json_extract(d.project_json,'$.count') AS pin_count
                    FROM pl_assignments m JOIN pl_definitions d ON d.id=m.definition_id
                    WHERE m.component_id IN ("""+','.join('?' for _ in chunk)+')'
                for r in self.app.db.execute(sql,chunk):
                    assigned.setdefault(r['component_id'],[]).append(
                        f"{r['title'] or 'Untitled'} ({r['family'] or '?'}-{r['pin_count'] or '?'})")
            table.setSortingEnabled(False)
            table.setRowCount(len(rows))
            for i,record in enumerate(rows):
                values = (record['part_number'] or '', record['function'] or '',
                          'New — unsaved' if record['id'] < 0 else
                          ', '.join(assigned.get(record['id'],[])) or '—')
                for j,value in enumerate(values):
                    item = QTableWidgetItem(value)
                    item.setData(Qt.ItemDataRole.UserRole, record['id'])
                    table.setItem(i,j,item)
            table.setSortingEnabled(True)
        query.returnPressed.connect(search)
        actions = QHBoxLayout()
        find_button = QPushButton('Search')
        find_button.clicked.connect(search)
        actions.addWidget(find_button)
        add_button = QPushButton('Stage selected devices')
        def add_selected():
            ids = {table.item(item.row(),0).data(Qt.ItemDataRole.UserRole) for item in table.selectedItems()}
            if ids:
                self._stage_group(self._draft_members | ids)
                search()
        add_button.clicked.connect(add_selected)
        actions.addWidget(add_button)
        layout.addLayout(actions)
        search()
        dialog.exec()

    def prune_missing_members(self):
        """Drop unsaved (negative) component ids that no longer exist in the component draft,
        from the open editor and every stashed pinout draft. Returns the number removed."""
        added = self.app.component_stage.added
        removed = 0
        missing = {cid for cid in self._draft_members if cid < 0 and cid not in added}
        if missing:
            removed += len(missing)
            self._draft_members -= missing
            self._group_undo = [members - missing for members in self._group_undo]
        for draft in self.pending_pinouts.values():
            members = [int(cid) for cid in draft.get('draft_members', [])]
            kept = [cid for cid in members if cid > 0 or cid in added]
            if len(kept) != len(members):
                removed += len(members) - len(kept)
                draft['draft_members'] = kept
        if removed:
            self.refresh_members()
            self.app.update_draft_ui()
            self.app.save_draft()
        return removed

    def remove_members(self):
        if self.data is None:
            return
        ids = {self.members.item(item.row(),0).data(Qt.ItemDataRole.UserRole)
               for item in self.members.selectedItems()}
        if ids:
            self._stage_group(self._draft_members - ids)

    def undo_group(self):
        if self._group_undo:
            self._draft_members = self._group_undo.pop()
            self._group_changed()

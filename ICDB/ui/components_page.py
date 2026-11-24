"""Components tab: catalogue list, staged edits and the selected component's details."""
import json
import webbrowser
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QSplitter, QTableWidget, QTableWidgetItem, QAbstractItemView,
    QHeaderView, QLabel, QLineEdit, QPushButton, QMessageBox, QDialog,
)
from builder import search_pattern, unicode_like
from pin_library import project, package_label
from pinout import diagram
from reference_images import load_reference_image
from ui.alias_dialog import AliasDialog
from ui.common import NoWheelComboBox, part_search_url, qt_image_from_pil
from ui.dialogs import DeviceDialog, PinoutAssignmentDialog
from ui.pinout_view import PinoutView


class ComponentsPage(QWidget):
    ROW_LIMIT = 30000

    def __init__(self, app):
        super().__init__()
        self.app = app
        self.links = []
        self.alias_rows = {}
        self._label_cache = {}  # definition id -> ((revision, signature), package label)
        v = QVBoxLayout(self)
        main = QSplitter(Qt.Orientation.Horizontal)
        # Keep device actions and search local to the Components browser.
        # The selected-component pane starts at the top of the workspace.
        browser = QWidget()
        browser_layout = QVBoxLayout(browser)
        browser_layout.setContentsMargins(0, 0, 0, 0)
        browser_layout.setSpacing(6)
        device_actions = QHBoxLayout()
        add_button = QPushButton('Add device')
        add_button.clicked.connect(self.add)
        device_actions.addWidget(add_button)
        self.edit_button = QPushButton('Edit device')
        self.edit_button.setToolTip('Edit part number, function and manufacturer (staged until Save)')
        self.edit_button.clicked.connect(self.edit)
        self.edit_button.setEnabled(False)
        device_actions.addWidget(self.edit_button)
        self.delete_button = QPushButton('Delete device')
        self.delete_button.clicked.connect(self.delete)
        device_actions.addWidget(self.delete_button)
        export_button = QPushButton('Export selected')
        export_button.clicked.connect(self.export_selected_json)
        device_actions.addWidget(export_button)
        device_actions.addStretch(1)
        browser_layout.addLayout(device_actions)
        search_row = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText('Search part number, marking, function, manufacturer…')
        self.search.returnPressed.connect(self.refresh)
        search_row.addWidget(self.search, 1)
        search_button = QPushButton('Search')
        search_button.clicked.connect(self.refresh)
        search_row.addWidget(search_button)
        browser_layout.addLayout(search_row)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(['Part number', 'Function', 'Pinouts'])
        self.table.verticalHeader().hide()
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.DoubleClicked | QAbstractItemView.EditTrigger.EditKeyPressed)
        self.table.setSortingEnabled(True)
        header = self.table.horizontalHeader()
        for column in range(3):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.Interactive)
        header.setStretchLastSection(True)
        for index, size in enumerate((210, 360, 220)):
            self.table.setColumnWidth(index, size)
        self.table.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self._populating = False
        self.table.itemChanged.connect(self.inline_change)
        self.table.itemSelectionChanged.connect(self.show_details)
        browser_layout.addWidget(self.table, 1)
        main.addWidget(browser)
        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(4, 0, 0, 0)
        rv.addWidget(QLabel('Selected component'))
        self.selection_title = QLabel('No component selected')
        self.selection_title.setWordWrap(True)
        rv.addWidget(self.selection_title)
        choice_row = QHBoxLayout()
        choice_row.addWidget(QLabel('Pinout'))
        self.choice = NoWheelComboBox()
        self.choice.currentIndexChanged.connect(self.show_pinout)
        choice_row.addWidget(self.choice, 1)
        rv.addLayout(choice_row)
        self.pinout = PinoutView()
        self.pinout.setMinimumHeight(100)
        vertical = QSplitter(Qt.Orientation.Vertical)
        vertical.addWidget(self.pinout)
        alias_panel = QWidget()
        alias_layout = QVBoxLayout(alias_panel)
        alias_layout.setContentsMargins(0, 0, 0, 0)
        alias_layout.addWidget(QLabel('Aliases'))
        self.alias_table = QTableWidget(0, 4)
        self.alias_table.setHorizontalHeaderLabels(['Marking', 'Packages', 'Source', 'Change'])
        self.alias_table.verticalHeader().hide()
        self.alias_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.alias_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.alias_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.alias_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        alias_layout.addWidget(self.alias_table)
        alias_actions = QHBoxLayout()
        self.add_alias_button = QPushButton('Add alias')
        self.add_alias_button.clicked.connect(self.add_marking_alias)
        self.add_alias_button.setEnabled(False)
        self.edit_alias_button = QPushButton('Edit alias')
        self.edit_alias_button.clicked.connect(self.edit_alias)
        self.delete_alias_button = QPushButton('Delete alias')
        self.delete_alias_button.clicked.connect(self.delete_alias)
        self.alias_table.itemSelectionChanged.connect(self._update_alias_actions)
        alias_actions.addWidget(self.add_alias_button)
        alias_actions.addWidget(self.edit_alias_button)
        alias_actions.addWidget(self.delete_alias_button)
        alias_actions.addStretch(1)
        alias_layout.addLayout(alias_actions)
        component_actions = QHBoxLayout()
        self.search_datasheet_button = QPushButton('Search datasheet')
        self.search_datasheet_button.clicked.connect(self.datasheet)
        self.search_datasheet_button.setEnabled(False)
        component_actions.addWidget(self.search_datasheet_button)
        self.edit_pinout_button = QPushButton('Edit pinout')
        self.edit_pinout_button.setToolTip('Open the selected library definition in Pinout Library')
        self.edit_pinout_button.clicked.connect(self.edit_selected_pinout)
        self.edit_pinout_button.setEnabled(False)
        component_actions.addWidget(self.edit_pinout_button)
        self.assign_pinout_button = QPushButton('Assign pinout')
        self.assign_pinout_button.setToolTip('Assign an existing pinout library definition to this component')
        self.assign_pinout_button.clicked.connect(self.assign_selected_pinout)
        self.assign_pinout_button.setEnabled(False)
        component_actions.addWidget(self.assign_pinout_button)
        self.new_pinout_button = QPushButton('New pinout')
        self.new_pinout_button.setToolTip('Create a new pinout definition linked to this component')
        self.new_pinout_button.clicked.connect(self.add_selected_pinout)
        self.new_pinout_button.setEnabled(False)
        component_actions.addWidget(self.new_pinout_button)
        component_actions.addStretch(1)
        rv.addLayout(component_actions)
        vertical.addWidget(alias_panel)
        vertical.setChildrenCollapsible(False)
        vertical.setStretchFactor(0, 3)
        vertical.setStretchFactor(1, 2)
        vertical.setSizes([420, 230])
        rv.addWidget(vertical, 1)
        main.addWidget(right)
        main.setChildrenCollapsible(False)
        main.setStretchFactor(0, 3)
        main.setStretchFactor(1, 2)
        main.setSizes([830, 500])
        v.addWidget(main, 1)
        self.refresh()

    def add_marking_alias(self):
        cid = self.selected_id()
        if cid is not None:
            dialog = AliasDialog(self.app, select_target=False)
            if dialog.exec() == QDialog.DialogCode.Accepted:
                self._change_alias(cid, None, dialog.record)

    def refresh_aliases(self, cid=None, *, focus=None):
        if cid is None and self.add_alias_button.isEnabled():
            cid = self.selected_id()
        self.alias_rows = self.app.component_stage.alias_view(self.app.db, cid) if cid is not None else {}
        self.alias_table.clearSelection()
        self.alias_table.setRowCount(len(self.alias_rows))
        for index, (marking, data) in enumerate(sorted(self.alias_rows.items())):
            change = 'Delete' if data.get('remove') else 'Staged' if data['staged'] else ''
            for column, value in enumerate((marking, ', '.join(data['packages']), data['source'], change)):
                self.alias_table.setItem(index, column, QTableWidgetItem(value))
            if marking == focus:
                self.alias_table.selectRow(index)
        self._update_alias_actions()

    def _selected_alias(self):
        rows = self.alias_table.selectionModel().selectedRows()
        item = self.alias_table.item(rows[0].row(), 0) if rows else None
        return item.text() if item else None

    def _update_alias_actions(self):
        data = self.alias_rows.get(self._selected_alias())
        editable = data is not None and not data.get('remove')
        self.edit_alias_button.setEnabled(editable)
        self.delete_alias_button.setEnabled(editable)

    def edit_alias(self):
        cid, marking = self.selected_id(), self._selected_alias()
        if marking is None:
            return
        dialog = AliasDialog(self.app, marking, existing=self.alias_rows[marking])
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._change_alias(cid, marking, dialog.record)

    def delete_alias(self):
        marking = self._selected_alias()
        if marking is not None:
            self._change_alias(self.selected_id(), marking)

    def _change_alias(self, cid, marking, replacement=None):
        try:
            self.app.component_stage.change_alias(self.app.db, cid, original=marking, replacement=replacement)
        except ValueError as exc:
            QMessageBox.warning(self, 'Aliases', str(exc))
            return
        self.app.component_changed()
        self.refresh_aliases(cid, focus=replacement['marking'] if replacement else None)

    def export_selected_json(self):
        ids = [index.data(Qt.ItemDataRole.UserRole)
               for index in self.table.selectionModel().selectedRows()]
        if not ids:
            QMessageBox.information(self, 'Export ICDB JSON', 'Select one or more component rows.')
            return
        self.app.import_page.export_json(ids)

    def selected_id(self):
        rows = self.table.selectionModel().selectedRows()
        row = rows[0].row() if len(rows) == 1 else -1
        if row < 0:
            return None
        item = self.table.item(row, 0)
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _search_rows(self, text, alias_ids):
        """Database rows for the search; an empty search skips the per-row LIKE function."""
        if not text.strip():
            return self.app.db.execute('''SELECT id,part_number,function,manufacturer FROM components
                ORDER BY part_number COLLATE NOCASE LIMIT ?''', (self.ROW_LIMIT + 1,)).fetchall()
        pattern = search_pattern(text)
        return self.app.db.execute('''SELECT id,part_number,function,manufacturer FROM components
            WHERE part_number LIKE ? ESCAPE '\\' OR function LIKE ? ESCAPE '\\' OR manufacturer LIKE ? ESCAPE '\\'
                OR id IN (SELECT value FROM json_each(?))
            ORDER BY part_number COLLATE NOCASE LIMIT ?''',
            (pattern, pattern, pattern, json.dumps(sorted(alias_ids)), self.ROW_LIMIT + 1)).fetchall()

    def _pinout_labels(self):
        """component id -> set of package labels. Library labels are cached per definition
        (keyed by revision and signature), so JSON is parsed once per changed definition,
        not once per assignment on every refresh."""
        db = self.app.db
        pinouts = {}
        for cid, pkg in db.execute('SELECT component_id,package FROM pinout_links'):
            pinouts.setdefault(cid, set()).add(pkg or 'General')
        if not self.app.has_table('pl_assignments'):
            return pinouts
        cache = self._label_cache
        current = {r[0]: (r[1], r[2]) for r in db.execute('''SELECT d.id,d.revision,d.signature FROM pl_definitions d
            WHERE EXISTS (SELECT 1 FROM pl_assignments m WHERE m.definition_id=d.id)''')}
        stale = [ident for ident, key in current.items() if cache.get(ident, (None,))[0] != key]
        for offset in range(0, len(stale), 500):
            chunk = stale[offset:offset+500]
            for ident, project_json in db.execute('SELECT id,project_json FROM pl_definitions WHERE id IN ('
                                                  + ','.join('?' for _ in chunk) + ')', chunk):
                try:
                    label = package_label(json.loads(project_json))
                except (ValueError, KeyError, TypeError):
                    label = None
                cache[ident] = (current[ident], label)
        for ident in set(cache) - set(current):
            del cache[ident]
        for cid, ident in db.execute("SELECT component_id,definition_id FROM pl_assignments"):
            label = cache.get(ident, (None, None))[1]
            if label:
                pinouts.setdefault(cid, set()).add(label)
        return pinouts

    def refresh(self, focus_id=None):
        if focus_id is None:
            focus_id = self.selected_id()
        text = self.search.text()
        stage = self.app.component_stage
        pattern = search_pattern(text) if text.strip() else None
        alias_ids = set()
        if pattern is not None:
            keys = {tuple(row) for row in self.app.db.execute(
                "SELECT component_id,marking FROM component_marking_aliases WHERE marking LIKE ? ESCAPE '\\'", (pattern,))}
            for row in stage.aliases:
                key = (row['component_id'], row['marking'])
                if row.get('remove'):
                    keys.discard(key)
                elif unicode_like(pattern, key[1], '\\'):
                    keys.add(key)
            alias_ids = {cid for cid, _ in keys}
        rows = self._search_rows(text, alias_ids)
        truncated = len(rows) > self.ROW_LIMIT
        rows = rows[:self.ROW_LIMIT]
        # Overlay staged component edits without modifying the database.
        visible = []
        for row in rows:
            values = stage.view(row['id'], dict(row))
            if values is None:
                continue
            record = dict(row)
            record.update(values)
            visible.append(record)
        # Make new and renamed entries discoverable in the current search, using the
        # same wildcard/case rules as the database search.
        listed = {r['id'] for r in rows}
        def matches(values):
            return pattern is None or any(unicode_like(pattern, values.get(field) or '', '\\')
                                          for field in ('part_number', 'function', 'manufacturer'))
        for cid, values in [*stage.added.items(),
                            *[(cid, state['after']) for cid, state in stage.edits.items() if cid not in listed]]:
            if cid in alias_ids or matches(values):
                visible.append({'id': cid, **values})
        rows = visible

        pinouts = self._pinout_labels()
        self._populating = True
        self.table.setUpdatesEnabled(False)
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(rows))
        selected_row = -1
        for i, record in enumerate(rows):
            self._fill_row(i, record, pinouts.get(record['id'], ()))
            if record['id'] == focus_id:
                selected_row = i
        self.table.setSortingEnabled(True)
        self.table.setUpdatesEnabled(True)
        self._populating = False
        if selected_row >= 0:
            for i in range(self.table.rowCount()):
                cell = self.table.item(i, 0)
                if cell and cell.data(Qt.ItemDataRole.UserRole) == focus_id:
                    # Reselecting the same row emits no selection signal, so refresh the
                    # details explicitly; otherwise they show values from before an edit.
                    self.table.blockSignals(True)
                    self.table.selectRow(i)
                    self.table.blockSignals(False)
                    self.table.scrollToItem(cell)
                    self.show_details()
                    break
        else:
            self.table.clearSelection()
            self._clear_details()
        if truncated:
            self.app.message(f'Showing the first {self.ROW_LIMIT:,} matching components; refine the search to see the rest')
        else:
            self.app.message(f'{len(rows):,} components displayed')

    def _fill_row(self, i, record, packages):
        vals = (record['part_number'], record['function'], ', '.join(sorted(packages)))
        for j, value in enumerate(vals):
            item = QTableWidgetItem(value or '')
            item.setData(Qt.ItemDataRole.UserRole, record['id'])
            if j == 2:
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(i, j, item)

    def _clear_details(self):
        self.selection_title.setText('No component selected')
        self.delete_button.setEnabled(False)
        self.edit_button.setEnabled(False)
        self.choice.blockSignals(True)
        self.choice.clear()
        self.choice.blockSignals(False)
        self.links = []
        self.pinout.set_image()
        self.edit_pinout_button.setEnabled(False)
        self.search_datasheet_button.setEnabled(False)
        self.assign_pinout_button.setEnabled(False)
        self.new_pinout_button.setEnabled(False)
        self.add_alias_button.setEnabled(False)
        self.refresh_aliases()

    def inline_change(self, item):
        if self._populating or item is None or item.column() > 1:
            return
        cid = item.data(Qt.ItemDataRole.UserRole)
        if cid is None:
            return
        fields = ['part_number', 'function']
        try:
            if item.column() == 0:
                current = self._record(cid)
                error = self.device_error(item.text(), '', current['manufacturer'] if current else '', ignore=cid)
                if error:
                    raise ValueError(error)
            self.app.component_stage.update(self.app.db, cid,
                                            **{fields[item.column()]: item.text()})
        except Exception as exc:
            self.refresh(cid)
            QMessageBox.warning(self, 'Edit component', str(exc))
            return
        self.app.component_changed()
        # Update just this row (normalized values) instead of rebuilding the whole table.
        self._update_row(cid)

    def _update_row(self, cid):
        stage = self.app.component_stage
        if cid < 0:
            values = stage.added.get(cid)
        else:
            row = self.app.db.execute('SELECT part_number,function,manufacturer FROM components WHERE id=?',
                                      (cid,)).fetchone()
            values = stage.view(cid, dict(row)) if row else None
        if values is None:
            self.refresh()
            return
        self._populating = True
        sorting = self.table.isSortingEnabled()
        self.table.setSortingEnabled(False)
        try:
            for r in range(self.table.rowCount()):
                cell = self.table.item(r, 0)
                if cell is not None and cell.data(Qt.ItemDataRole.UserRole) == cid:
                    for col, field in ((0, 'part_number'), (1, 'function')):
                        target = self.table.item(r, col)
                        if target is not None and target.text() != (values[field] or ''):
                            target.setText(values[field] or '')
                    break
        finally:
            self.table.setSortingEnabled(sorting)
            self._populating = False
        if self.selected_id() == cid:
            self.show_details()

    def show_details(self):
        cid = self.selected_id()
        self.delete_button.setEnabled(cid is not None)
        self.edit_button.setEnabled(cid is not None)
        self.choice.blockSignals(True)
        self.choice.clear()
        self.links = []
        self.edit_pinout_button.setEnabled(False)
        self.search_datasheet_button.setEnabled(cid is not None)
        self.assign_pinout_button.setEnabled(cid is not None)
        self.new_pinout_button.setEnabled(cid is not None)
        self.add_alias_button.setEnabled(False)
        if cid is None:
            self.choice.blockSignals(False)
            self._clear_details()
            self.delete_button.setEnabled(self.table.selectionModel().hasSelection())
            return
        if cid < 0:
            self.choice.blockSignals(False)
            record = self.app.component_stage.added.get(cid)
            if record:
                self.selection_title.setText(record['part_number'] + ' (unsaved)')
                self.add_alias_button.setEnabled(True)
                self.refresh_aliases(cid)
                self._load_pinout_choices(cid)
            else:
                self._clear_details()
            return
        record = self.app.db.execute('SELECT * FROM components WHERE id=?', (cid,)).fetchone()
        record = self.app.component_stage.view(cid, dict(record)) if record is not None else None
        if record is None:
            self.choice.blockSignals(False)
            self._clear_details()
            return
        self.add_alias_button.setEnabled(True)
        self.selection_title.setText(' · '.join(filter(None, (record['part_number'], record['manufacturer'])))
                                     or 'Unnamed component')
        self.refresh_aliases(cid)
        self._load_pinout_choices(cid)

    def _load_pinout_choices(self, cid):
        self.choice.blockSignals(True)
        # Links written by Publish duplicate an assigned library definition listed below;
        # show only the definition. Other image references (manual, legacy) stay listed.
        published = set()
        if self.app.has_table('pl_publications'):
            published = {r[0] for r in self.app.db.execute('''SELECT p.link_id FROM pl_publications p
                JOIN pl_assignments m ON m.id=p.assignment_id
                WHERE m.component_id=? AND p.link_id IS NOT NULL''', (cid,))}
        for r in self.app.pinouts.links(component_id=cid):
            if r['id'] in published:
                continue
            self.links.append(('image', dict(r)))
            self.choice.addItem(('Default · ' if r['is_default'] else '') + (r['label'] or r['original_name']) + ' · ' + (r['package'] or 'General'))
        definitions = {str(row['id']): row['project_json'] for row in self.app.db.execute('''
            SELECT d.id,d.project_json FROM pl_assignments m JOIN pl_definitions d
                ON d.id=m.definition_id WHERE m.component_id=? ORDER BY d.id''', (cid,))}
        page = getattr(self.app, 'library_page', None)
        session = page.session_payload() if page is not None else {'drafts': {}, 'deletions': {}}
        drafts = session['drafts']
        for key in session['deletions']:
            definitions.pop(key, None)
        for key, draft in drafts.items():
            if cid in draft['draft_members'] and key not in session['deletions']:
                definitions.setdefault(key, None)
            else:
                definitions.pop(key, None)
        for key, saved_json in definitions.items():
            try:
                if key in drafts:
                    try:
                        data = self.app._pinout_data_from_draft(drafts[key])
                    except ValueError:
                        if saved_json is None:
                            continue
                        data = json.loads(saved_json)
                else:
                    data = json.loads(saved_json)
                label = f"{data['device']} · {package_label(data)}"
            except (ValueError, KeyError, TypeError):
                continue
            ident = int(key) if key.isdecimal() else None
            self.links.append(('definition', {'id': ident, 'draft_key': key if ident is None else None, 'project': data}))
            self.choice.addItem(label + (' (staged)' if key in drafts else ' (library)'))
        self.choice.blockSignals(False)
        self.show_pinout()

    def show_pinout(self, *_):
        index = self.choice.currentIndex()
        if not 0 <= index < len(self.links):
            self.edit_pinout_button.setEnabled(False)
            self.pinout.set_image()
            return
        kind, data = self.links[index]
        self.edit_pinout_button.setEnabled(kind == 'definition')
        try:
            if kind == 'image':
                self.pinout.set_image(qt_image_from_pil(load_reference_image(self.app.pinouts.path(data))))
            else:
                self.pinout.set_svg(diagram(project(data['project'])).svg().encode('utf-8'))
        except Exception as exc:
            self.pinout.set_image()
            self.app.message(f'Pinout unavailable: {exc}')

    def edit_selected_pinout(self):
        index = self.choice.currentIndex()
        if not 0 <= index < len(self.links) or self.links[index][0] != 'definition':
            return
        link = self.links[index][1]
        ident = link['id']
        if ident is not None:
            self.app.open_pinout_definition(ident)
        else:
            page = self.app.library_page
            key = link['draft_key']
            if page._active_draft_key != key and key in page.pending_pinouts:
                page.stash_current()
                page.restore_draft(page.pending_pinouts.pop(key), key=key)
                page._update_delete_button()
            self.app.tabs.setCurrentWidget(page)

    def _selected_component_for_pinout(self):
        cid = self.selected_id()
        if cid is None or cid in self.app.component_stage.deleted:
            return None, None
        if cid < 0:
            record = self.app.component_stage.added.get(cid)
        else:
            saved = self.app.db.execute('SELECT * FROM components WHERE id=?', (cid,)).fetchone()
            record = self.app.component_stage.view(cid, dict(saved)) if saved else None
        return cid, record

    def add_selected_pinout(self):
        """Default to a new definition, already linked to the selected component."""
        cid, record = self._selected_component_for_pinout()
        if not record:
            QMessageBox.warning(self, 'New pinout', 'Selected component is no longer available.')
            return
        page = self.app.library_page
        self.app.tabs.setCurrentWidget(page)
        page.new_definition()
        page.title.setText(record['part_number'])
        page._link_component_id = cid
        page._stage_group({cid})
        page._update_use_existing_button()
        page.render()  # the title was set programmatically, which does not queue a preview
        self.app.message(f"New pinout for {record['part_number']} staged. Save commits the pinout and association.")

    def assign_selected_pinout(self):
        """Associate the selected saved/staged component with a library pinout draft."""
        cid = self.selected_id()
        if cid is None or cid in self.app.component_stage.deleted:
            return
        if cid < 0:
            record = self.app.component_stage.added.get(cid)
        else:
            saved = self.app.db.execute('SELECT * FROM components WHERE id=?', (cid,)).fetchone()
            record = self.app.component_stage.view(cid, dict(saved)) if saved else None
        if not record:
            QMessageBox.warning(self, 'Assign pinout', 'Selected component is no longer available.')
            return
        picker = PinoutAssignmentDialog(self, self.app.db, record['part_number'])
        if picker.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            # Navigation preserves drafts for other definitions, including edits made
            # before this association was requested from the Components tab.
            self.app.open_pinout_definition(picker.definition_id)
            page = self.app.library_page
            if page.definition_id != picker.definition_id:
                return
            if cid in page._draft_members:
                QMessageBox.information(self, 'Assign pinout',
                    'This component is already assigned to the selected pinout.')
                return
            page._stage_group(page._draft_members | {cid})
            if cid in page._draft_members:
                self.app.message(f"Pinout assigned to {record['part_number']} (unsaved). Save to commit.")
        except Exception as exc:
            QMessageBox.critical(self, 'Assign pinout', str(exc))

    def _record(self, cid):
        """The component as staged (None if it no longer exists or is staged for deletion)."""
        stage = self.app.component_stage
        if cid < 0:
            return stage.added.get(cid)
        row = self.app.db.execute('SELECT * FROM components WHERE id=?', (cid,)).fetchone()
        return stage.view(cid, dict(row)) if row is not None else None

    def device_error(self, part, function='', manufacturer='', ignore=None):
        """What Save would refuse about these values, said before anything is staged."""
        if not str(part).strip():
            return 'Enter a part number.'
        duplicate = self.app.component_stage.find_duplicate(self.app.db, part, manufacturer, ignore)
        if duplicate:
            maker = str(manufacturer).strip()
            return (f'{duplicate}' + (f' ({maker})' if maker else '') + ' already exists in ICDB or is '
                    'staged. Use a different part number or manufacturer.')
        return None

    def add(self):
        dialog = DeviceDialog(self, validate=self.device_error)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            cid = self.app.component_stage.add(*dialog.values())
            self.app.component_changed()
            self.refresh(cid)
        except Exception as exc:
            QMessageBox.critical(self, 'Add component', str(exc))

    def edit(self):
        cid = self.selected_id()
        if cid is None:
            return
        if cid < 0:
            record = self.app.component_stage.added.get(cid)
        else:
            row = self.app.db.execute('SELECT * FROM components WHERE id=?', (cid,)).fetchone()
            record = self.app.component_stage.view(cid, dict(row)) if row is not None else None
        if record is None:
            QMessageBox.information(self, 'Edit component', 'This component no longer exists.')
            self.refresh()
            return
        dialog = DeviceDialog(self, record,
                              validate=lambda *values: self.device_error(*values, ignore=cid))
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            self.app.component_stage.update(self.app.db, cid, **dict(zip(
                ('part_number','function','manufacturer'), dialog.values())))
            self.app.component_changed()
            self.refresh(cid)
        except Exception as exc:
            QMessageBox.critical(self, 'Edit component', str(exc))

    def delete(self):
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return
        ids = [row.data(Qt.ItemDataRole.UserRole) for row in rows]
        target = rows[0].data() if len(rows) == 1 else f'{len(rows)} selected devices'
        if QMessageBox.question(self, 'Delete component',
            f'Stage deletion of {target}, including associated links? Use Save to commit.',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return
        try:
            # Deleting a component also removes it from pinout groups (also staged ones);
            # Save drops deleted components from every pinout draft's membership.
            self.app.component_stage.delete_many(self.app.db, ids)
            self.app.component_changed()
            if not self.app.library_page.prune_missing_members():
                self.app.library_page.refresh_members()
            self.refresh()
        except Exception as exc:
            QMessageBox.critical(self, 'Delete component', str(exc))

    def datasheet(self):
        cid = self.selected_id()
        if cid is None:
            return
        if cid < 0:
            row = self.app.component_stage.added.get(cid)
        else:
            saved = self.app.db.execute('SELECT * FROM components WHERE id=?', (cid,)).fetchone()
            row = self.app.component_stage.view(cid, dict(saved)) if saved else None
        if row:
            webbrowser.open(part_search_url(row['part_number'], row['manufacturer']))

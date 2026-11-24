"""Pinout library tab: definition list, editor, preview and groups."""
import copy
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
    QSplitter, QTableWidget, QTableWidgetItem, QAbstractItemView,
    QHeaderView, QLabel, QLineEdit, QPushButton, QMessageBox, QCheckBox,
    QSpinBox,
)
from pin_library import package_label, project, validate_data
from builder import search_pattern, unicode_like
from library_queries import definition_rows
from pinout import diagram, PACKAGES, ROLES
from ui.common import NoWheelComboBox
from ui.pinout_view import PinoutView
from ui.pinout_library.actions import PinoutActionsMixin
from ui.pinout_library.drafts import PinoutDraftsMixin
from ui.pinout_library.groups import PinoutGroupsMixin
from ui.pinout_library.pin_editor import PinEditorMixin


class PinoutLibraryPage(PinEditorMixin, PinoutDraftsMixin, PinoutGroupsMixin, PinoutActionsMixin, QWidget):
    def __init__(self, app):
        super().__init__()
        self.app = app
        self.definition_id = None
        self.data = None
        self.loading = False
        self.changed = False
        self.editing = True  # the editor always edits the open pinout
        self._new = False
        self._last_id = None
        self._base_revision = None
        self._base_members = set()
        self._draft_members = set()
        self._group_undo = []
        self._pin_fields_changed = False
        self._link_component_id = None
        self.pending_pinouts = {}  # key -> raw editor payload, revision and member snapshots
        self.pending_deletions = {}  # definition id -> revision/member snapshot for staged deletion
        self._active_draft_key = None
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)
        # Library commands belong to the library pane, not a full-width toolbar.
        self.search = QLineEdit()
        self.search.setPlaceholderText('Search pinouts or linked devices…')
        self.search.returnPressed.connect(self.refresh)
        self.filter = NoWheelComboBox()
        self.filter.addItems(['All pinouts', 'Assigned groups', 'Without assigned parts'])
        self.filter.currentIndexChanged.connect(lambda *_: self.refresh())
        self.new_button = QPushButton('New pinout')
        self.new_button.clicked.connect(self.new_definition)
        self.delete_button = QPushButton('Delete pinout')
        self.delete_button.setToolTip('Delete this pinout definition if no devices or imported sources refer to it.')
        self.delete_button.clicked.connect(self.delete_definition)
        self.use_existing_button = QPushButton('Use existing definition')
        self.use_existing_button.setToolTip('Link this component to an existing pinout rather than creating one')
        self.use_existing_button.clicked.connect(self.use_existing_definition)
        self.use_existing_button.hide()
        self.save_as_button = QPushButton('Duplicate pinout')
        self.save_as_button.setToolTip('Stage the current editor contents as another pinout definition. '
                                       'Edit package/pin data to distinguish variants; linked devices remain with the original.')
        self.save_as_button.clicked.connect(lambda: self.save(as_new=True))
        # Save/Revert/View changes remain in the application-wide tab bar.

        self.workspace = QSplitter(Qt.Orientation.Horizontal)
        self.workspace.setChildrenCollapsible(False)
        # Library browser
        library = QWidget()
        lv = QVBoxLayout(library)
        lv.setContentsMargins(0,0,0,0)
        lv.addWidget(QLabel('LIBRARY'))
        library_actions = QHBoxLayout()
        library_actions.addWidget(self.new_button)
        library_actions.addWidget(self.delete_button)
        library_actions.addStretch(1)
        lv.addLayout(library_actions)
        lv.addWidget(self.search)
        lv.addWidget(self.filter)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(['Title', 'Package', 'Devices'])
        self.table.verticalHeader().hide()
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSortingEnabled(True)
        header = self.table.horizontalHeader()
        for col, width in enumerate((240, 115, 80)):
            header.setSectionResizeMode(col, QHeaderView.ResizeMode.Interactive)
            self.table.setColumnWidth(col, width)
        header.setStretchLastSection(True)
        self.table.itemSelectionChanged.connect(self.load_selected)
        lv.addWidget(self.table,1)
        self.workspace.addWidget(library)

        # The pin editor is always present in the middle panel.
        editor = QWidget()
        editor_layout = QVBoxLayout(editor)
        editor_layout.setContentsMargins(0, 0, 0, 0)
        editor_layout.setSpacing(8)
        editor_layout.addWidget(QLabel('PINOUT EDITOR'))
        self.editor_hint = QLabel('Select a pinout in the library, or choose New pinout.')
        self.editor_hint.setWordWrap(True)
        editor_layout.addWidget(self.editor_hint)

        pins_page = QWidget()
        pv = QVBoxLayout(pins_page)
        pin_bar = QHBoxLayout()
        for label, action in [('Add pin', self.add_pin), ('Remove pin', self.remove_pins), ('Paste', self.paste_pins)]:
            btn = QPushButton(label)
            btn.clicked.connect(action)
            pin_bar.addWidget(btn)
        pin_bar.addStretch()
        pv.addLayout(pin_bar)
        self.pins = QTableWidget(0, 4)
        self.pins.setHorizontalHeaderLabels(['Number','Name','Role','Description'])
        self.pins.verticalHeader().hide()
        self.pins.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        for col,width in enumerate((70,135,100,220)):
            self.pins.horizontalHeader().setSectionResizeMode(col,QHeaderView.ResizeMode.Interactive)
            self.pins.setColumnWidth(col,width)
        self.pins.horizontalHeader().setStretchLastSection(True)
        self._install_role_delegate()
        self.pins.itemChanged.connect(self.mark_changed)
        pv.addWidget(self.pins,1)

        # Pinout properties
        props_page = QWidget()
        props = QVBoxLayout(props_page)
        properties_actions = QHBoxLayout()
        properties_actions.addWidget(self.save_as_button)
        properties_actions.addWidget(self.use_existing_button)
        properties_actions.addStretch(1)
        props.addLayout(properties_actions)
        form = QFormLayout()
        self.title = QLineEdit()
        self.package = NoWheelComboBox()
        self.package.setEditable(True)
        self.package.addItems(PACKAGES)
        self.source = QLineEdit()
        self.count = QSpinBox()
        # Same limit as pin_library.validate_data (storage); the renderer's own limit is lower
        # and is reported by the preview. A smaller range showed imported large parts wrongly.
        self.count.setRange(1,4096)
        self.count.valueChanged.connect(self.set_pin_count)
        form.addRow('Title',self.title)
        form.addRow('Package',self.package)
        form.addRow('Pin count',self.count)
        form.addRow('Source',self.source)
        props.addLayout(form)
        self.pad_enabled = QCheckBox('Exposed pad')
        self.pad_number = QLineEdit('EP')
        self.pad_name = QLineEdit()
        self.pad_role = NoWheelComboBox()
        self.pad_role.setEditable(True)
        self.pad_role.lineEdit().setReadOnly(True)
        self.pad_role.addItems(ROLES)
        props.addWidget(self.pad_enabled)
        props_form = QFormLayout()
        props_form.addRow('Pad number',self.pad_number)
        props_form.addRow('Pad name',self.pad_name)
        props_form.addRow('Pad role',self.pad_role)
        props.addLayout(props_form)
        props.addStretch()
        editor_layout.addWidget(props_page)
        editor_layout.addWidget(pins_page, 1)
        # Edits are only kept for an open pinout; with none open the fields were
        # editable but every change was silently ignored.
        self._editor_pages = (props_page, pins_page)
        self.workspace.addWidget(editor)

        preview_splitter = QSplitter(Qt.Orientation.Vertical)
        preview_splitter.setChildrenCollapsible(False)
        preview_panel = QWidget()
        preview_layout = QVBoxLayout(preview_panel)
        preview_layout.setContentsMargins(0, 0, 0, 0)
        preview_layout.addWidget(QLabel('PINOUT PREVIEW'))
        self.preview = PinoutView()
        self.preview.setMinimumHeight(100)
        preview_layout.addWidget(self.preview, 1)
        hint = QLabel('Wheel: zoom   Drag: pan   Double-click: fit')
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        preview_layout.addWidget(hint)
        preview_splitter.addWidget(preview_panel)

        groups_page = QWidget()
        gv = QVBoxLayout(groups_page)
        gv.setContentsMargins(0, 0, 0, 0)
        gv.addWidget(QLabel('Groups'))
        group_tools = QHBoxLayout()
        self.add_members_button = QPushButton('Add devices')
        self.add_members_button.clicked.connect(self.add_members)
        group_tools.addWidget(self.add_members_button)
        self.remove_members_button = QPushButton('Remove devices')
        self.remove_members_button.clicked.connect(self.remove_members)
        group_tools.addWidget(self.remove_members_button)
        self.undo_group_button = QPushButton('Undo draft')
        self.undo_group_button.clicked.connect(self.undo_group)
        group_tools.addWidget(self.undo_group_button)
        self.members = QTableWidget(0, 2)
        self.members.setHorizontalHeaderLabels(['Part number','Function'])
        self.members.verticalHeader().hide()
        self.members.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.members.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.members.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        for col,width in enumerate((150, 200)):
            self.members.horizontalHeader().setSectionResizeMode(col,QHeaderView.ResizeMode.Interactive)
            self.members.setColumnWidth(col,width)
        self.members.horizontalHeader().setStretchLastSection(True)
        self.members.setSortingEnabled(True)
        self.members.itemSelectionChanged.connect(self.update_group_actions)
        self.members.itemDoubleClicked.connect(self.open_group_member)
        gv.addWidget(self.members,1)
        group_tools.addStretch(1)
        gv.addLayout(group_tools)
        preview_splitter.addWidget(groups_page)
        preview_splitter.setStretchFactor(0, 3)
        preview_splitter.setStretchFactor(1, 2)
        preview_splitter.setSizes([420, 230])
        self.workspace.addWidget(preview_splitter)

        self.workspace.setStretchFactor(0,3)
        self.workspace.setStretchFactor(1,4)
        self.workspace.setStretchFactor(2,4)
        self.workspace.setSizes([350,475,475])
        root.addWidget(self.workspace,1)

        for control in (self.title,self.source,self.pad_number,self.pad_name):
            control.textEdited.connect(self.mark_changed)
        self.package.currentTextChanged.connect(self.mark_changed)
        self.pad_enabled.toggled.connect(self.mark_changed)
        self.pad_role.currentTextChanged.connect(self.mark_changed)
        self.edit_warning_text = ''
        self.preview_timer = QTimer(self)
        self.preview_timer.setSingleShot(True)
        self.preview_timer.setInterval(250)
        self.preview_timer.timeout.connect(self.render)
        self.pins.itemChanged.connect(self.queue_preview)
        self.draft_timer = QTimer(self)
        self.draft_timer.setSingleShot(True)
        self.draft_timer.setInterval(450)
        self.draft_timer.timeout.connect(self.app.save_draft)
        self.title.textEdited.connect(self.queue_preview)
        self.package.currentTextChanged.connect(self.queue_preview)
        self.count.valueChanged.connect(self.queue_preview)
        self.pad_enabled.toggled.connect(self.queue_preview)
        self.pad_number.textEdited.connect(self.queue_preview)
        self.pad_name.textEdited.connect(self.queue_preview)
        self.pad_role.currentTextChanged.connect(self.queue_preview)
        self._update_editor_enabled()
        saved = self.app.settings.value('pinout_library/splitter')
        if saved is not None:
            self.workspace.restoreState(saved)
        self.workspace.splitterMoved.connect(lambda *_: self.app.settings.setValue('pinout_library/splitter',self.workspace.saveState()))
        self.refresh()

    def _update_editor_enabled(self):
        open_ = self.data is not None
        for page in self._editor_pages:
            page.setEnabled(open_)
        self.editor_hint.setVisible(not open_)

    def _reload_current(self):
        if self.definition_id is None:
            return
        self.loading = True
        ident,data = self.app.library.get(self.definition_id)
        self.data = data
        self._populate_editor(data)
        self.loading = False
        self.changed = False
        self._reset_group_draft()
        self.render()
        self.refresh_members()

    def _show_definition(self, ident):
        key = str(ident)
        if key in self.pending_pinouts:
            draft = self.pending_pinouts.pop(key)
            self._active_draft_key = key
            self.restore_draft(draft)
            return
        _, data = self.app.library.get(ident)
        self.loading = True
        self.definition_id = ident
        self._active_draft_key = key
        self._new = False
        self._link_component_id = None
        self.data = data
        self._populate_editor(data)
        self.loading = False
        self.changed = False
        self.render()
        self._reset_group_draft()
        self.refresh_members()
        self._update_use_existing_button()
        self._update_delete_button()
        self.app.update_draft_ui()

    def queue_preview(self,*_):
        if self.editing and not self.loading and self.data is not None:
            self.preview_timer.start()

    def _staged_new_rows(self, drafts):
        """List rows for new pinouts that exist only as staged drafts, filtered like the
        database rows. Without them a new draft disappeared from view as soon as another
        pinout was opened, yet Save still wrote it."""
        text = self.search.text()
        pattern = search_pattern(text) if text.strip() else None
        group = self.filter.currentText()
        rows = []
        for key, draft in drafts.items():
            if not str(key).startswith('new:'):
                continue
            raw = draft['raw']
            title = str(raw.get('title') or '').strip() or 'Untitled'
            package = f"{str(raw.get('package') or '').strip()}-{len(raw.get('pins', []))}"
            if raw.get('pad_enabled'):
                package += '-EP'
            uses = len(draft.get('draft_members', []))
            if (group == 'Assigned groups' and not uses) or (group == 'Without assigned parts' and uses):
                continue
            if pattern is not None and not (unicode_like(pattern, title, '\\')
                                            or unicode_like(pattern, package, '\\')):
                continue
            rows.append({'id': key, 'title': title, 'package': package, 'uses': uses, 'staged': 'new'})
        return rows

    def _current_row_key(self):
        return self._active_draft_key if self._new else self.definition_id

    def _update_delete_button(self):
        if self._new:
            self.delete_button.setText('Discard new pinout')
        else:
            self.delete_button.setText('Undo deletion' if str(self.definition_id) in self.pending_deletions
                                       else 'Delete pinout')

    def refresh(self):
        current = self._current_row_key()
        try:
            rows = definition_rows(self.app.db, self.search.text(), self.filter.currentText())
        except Exception as exc:
            self.app.message(f'Could not load pinouts: {exc}')
            return
        drafts = self.session_payload()['drafts']
        saved_count = len(rows)
        for row in rows:
            if str(row['id']) in drafts:
                row['staged'] = 'edited'
        rows = self._staged_new_rows(drafts) + rows
        # Disable sorting during population so a sorted insertion never
        # moves the row currently being filled. Re-enable after all rows exist.
        was_sorting = self.table.isSortingEnabled()
        header = self.table.horizontalHeader()
        sort_col, sort_order = header.sortIndicatorSection(), header.sortIndicatorOrder()
        self.table.blockSignals(True)
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(rows))
        for i, row in enumerate(rows):
            staged = row.get('staged')
            title = row['title'] or ''
            if str(row['id']) in self.pending_deletions:
                title += ' [Delete pending]'
            elif staged == 'new':
                title += ' (new, unsaved)'
            elif staged == 'edited':
                title += ' (edited)'
            for j, value in enumerate((title, row['package'], row['uses'])):
                it = QTableWidgetItem()
                if j == 2:
                    it.setData(Qt.ItemDataRole.EditRole, int(value or 0))
                else:
                    it.setText(str(value or ''))
                if j == 0:
                    it.setData(Qt.ItemDataRole.UserRole, row['id'])
                if staged:
                    font = QFont(it.font())
                    font.setItalic(True)
                    it.setFont(font)
                    it.setToolTip('Staged change; Save commits it, Revert discards it.')
                self.table.setItem(i, j, it)
        self.table.setSortingEnabled(was_sorting)
        if was_sorting and 0 <= sort_col < self.table.columnCount():
            self.table.sortItems(sort_col, sort_order)
        target = -1
        for i in range(self.table.rowCount()):
            item = self.table.item(i, 0)
            if item is not None and item.data(Qt.ItemDataRole.UserRole) == current:
                target = i
                break
        self.table.blockSignals(False)
        if target >= 0:
            self.table.selectRow(target)
        elif self._new:
            # A new pinout the search or filter hides stays open in the editor.
            pass
        elif rows:
            self.table.selectRow(0)
            self.load_selected()
        elif not self.changed:
            self.definition_id = None
            self.clear()
        # else: keep unsaved editor contents although no row matches.
        self._update_delete_button()
        staged = len(rows) - saved_count
        self.app.message(f'{saved_count:,} pinout definitions' + (f', {staged} new unsaved' if staged else ''))

    def clear(self):
        self.data = None
        self.loading = True
        self.title.clear()
        self.package.setCurrentText('')
        self.source.clear()
        self.pins.setRowCount(0)
        self.changed = False
        self.preview.set_image()
        self.count.setValue(1)
        self.pad_enabled.setChecked(False)
        self.pad_number.setText('EP')
        self.pad_name.clear()
        self.pad_role.setCurrentText('Signal')
        self._update_edit_warning(None)
        self._reset_group_draft()
        self.refresh_members()
        self.loading = False
        self._link_component_id = None
        self._update_use_existing_button()
        self._update_editor_enabled()

    def load_selected(self):
        row = self.table.currentRow()
        if row < 0:
            return
        item = self.table.item(row, 0)
        if item is None:
            return
        ident = item.data(Qt.ItemDataRole.UserRole)
        if ident is None or ident == self._current_row_key():
            return
        self.draft_timer.stop()
        self.preview_timer.stop()
        stashed_new = self._new and self.changed
        self.stash_current()
        try:
            if isinstance(ident, str):  # a staged new pinout
                draft = self.pending_pinouts.pop(ident, None)
                if draft is None:
                    QTimer.singleShot(0, self.refresh)
                    return
                self.restore_draft(draft, key=ident)
                self._update_delete_button()
            else:
                self._show_definition(ident)
        except Exception as exc:
            QMessageBox.critical(self, 'Open pinout', str(exc))
            return
        if stashed_new:
            # The new pinout just set aside needs its own row in the list.
            QTimer.singleShot(0, self.refresh)
        self.app.update_draft_ui()
        # During PinoutLibraryPage.__init__, MainWindow.library_page is not
        # assigned yet. There is no user draft to journal at this point.
        if getattr(self.app, 'library_page', None) is self:
            self.app.save_draft()

    def mark_changed(self, *_):
        if not self.loading and self.editing and self.data is not None:
            self._pin_fields_changed = True
            self.changed = True
            self.app.update_draft_ui()
            self.draft_timer.start()

    def read_data(self):
        if self.data is None:
            raise ValueError('Select a pinout first')
        updated = copy.deepcopy(self.data)
        updated['device'] = self.title.text().strip()
        updated['package'] = self.package.currentText().strip()
        updated['source'] = self.source.text().strip()
        updated['count'] = self.pins.rowCount()
        if self.pad_enabled.isChecked():
            updated['exposed_pad'] = dict(enabled=True, number=self.pad_number.text().strip(),
                name=self.pad_name.text().strip(), role=self.pad_role.currentText(), description='')
        else:
            updated.pop('exposed_pad', None)
        keys = ('number', 'name', 'role', 'description')
        updated['pins'] = [dict(zip(keys, [(self._pin_role(i) if j == 2 else
                                  (self.pins.item(i,j).text() if self.pins.item(i,j) else '')) for j in range(4)]))
                           for i in range(self.pins.rowCount())]
        for pin in updated['pins']:
            number = pin['number'].strip()
            pin['number'] = int(number) if number.isdecimal() else number
        validate_data(updated)
        return updated

    def render(self):
        self._update_editor_enabled()
        data = None
        try:
            data = self.read_data()
            self.preview.set_svg(diagram(project(data)).svg().encode('utf-8'))
        except Exception as exc:
            self.preview.set_image()
            self.app.message(f'Preview unavailable: {exc}')
        self._update_edit_warning(data)

    def _update_edit_warning(self, data):
        """Say at edit time what Save would refuse: a package or pin-count change on a
        pinout that keeps assigned devices (removals are applied before the pin data)."""
        message = details = ''
        if data is not None and not self._new and self.definition_id is not None and self.data is not None:
            kept = self._base_members & self._draft_members
            try:
                before, after = package_label(self.data), package_label(data)
            except Exception:
                before = after = None
            if kept and before != after:
                message = (f'{before} → {after} cannot be saved while {len(kept)} device(s) use '
                           f'“{self.data.get("device", "this pinout")}”')
                details = (f'{len(kept)} assigned device(s) use this pinout, so its package and pin count '
                           f'cannot change ({before} → {after}). Use Duplicate pinout for a package '
                           'variant, or remove the devices first.')
        self.edit_warning_text = message
        self.app.set_status_warning('pinout_package', message, details, page=self)



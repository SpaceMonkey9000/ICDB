"""CSV and JSON import previews and full database JSON export."""
from collections import Counter
from pathlib import Path

from import_batch import ACTIONS, exclude_rows
from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem, QAbstractItemView,
    QHeaderView, QLabel, QPushButton, QMessageBox, QFileDialog,
)


class ImportPage(QWidget):
    """Simple two-column component importer, with a mandatory preview."""
    def __init__(self, owner):
        super().__init__()
        self.owner = owner
        self.files = []
        self.preview_components = None  # staged-component fingerprint the preview used
        self.review_after_save = False
        layout = QVBoxLayout(self)
        toolbar = QHBoxLayout()
        self.choose_button = QPushButton('Choose files…')
        self.choose_button.clicked.connect(self.choose)
        toolbar.addWidget(self.choose_button)
        export_all = QPushButton('Export all JSON…')
        export_all.clicked.connect(lambda: self.export_json())
        toolbar.addWidget(export_all)
        self.import_button = QPushButton('Stage import')
        self.import_button.setEnabled(False)
        self.import_button.clicked.connect(self.commit_preview)
        toolbar.addWidget(self.import_button)
        self.delete_button = QPushButton('Delete')
        self.delete_button.setToolTip('Exclude selected rows from the import or clear saved review rows.')
        self.delete_button.setEnabled(False)
        self.delete_button.clicked.connect(self.delete_review_rows)
        toolbar.addWidget(self.delete_button)
        toolbar.addStretch()
        layout.addLayout(toolbar)
        self.preview = QTableWidget(0, 5)
        self.preview.setHorizontalHeaderLabels(['Part or pinout', 'Description or package', 'Action', 'Details', 'File'])
        self.preview.verticalHeader().hide()
        self.preview.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.preview.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.preview.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.preview.itemSelectionChanged.connect(self.update_delete_button)
        delete_shortcut = QShortcut(QKeySequence(Qt.Key.Key_Delete), self.preview)
        delete_shortcut.setContext(Qt.ShortcutContext.WidgetShortcut)
        delete_shortcut.activated.connect(self.delete_review_rows)
        header = self.preview.horizontalHeader()
        header.setSortIndicator(-1, Qt.SortOrder.AscendingOrder)
        self.preview.setSortingEnabled(True)
        for col in (0, 1, 2):
            header.setSectionResizeMode(col, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Interactive)
        self.preview.setColumnWidth(4, 180)
        self.preview.setColumnWidth(0, 180)
        self.preview.setColumnWidth(1, 360)
        self.preview.setColumnWidth(2, 150)
        layout.addWidget(self.preview, 1)
        self.summary = QLabel('Choose CSV or JSON files to preview.')
        layout.addWidget(self.summary)

    def set_import_pending(self, pending):
        self.choose_button.setEnabled(not pending)
        if pending:
            self.import_button.setEnabled(False)
        self.update_delete_button()

    def choose(self):
        if self.owner.component_stage.pending_import:
            return
        paths, _ = QFileDialog.getOpenFileNames(
            self, 'Import components', str(self.owner.data), 'Import files (*.csv *.json)')
        if not paths:
            return
        fingerprint = self.owner.start_import_preview(
            paths, self.preview_ready, on_error=lambda message: self.summary.setText(message))
        if fingerprint is None:
            return
        self.clear_preview()
        self.preview_components = fingerprint
        self.summary.setText('Reading import files…')

    @staticmethod
    def file_rows(files):
        return [(*row, Path(entry['path']).name) for entry in files for row in entry['rows']]

    def show_rows(self, rows, references=()):
        # Populate whole rows before Qt applies the selected column sort.
        self.preview.setSortingEnabled(False)
        self.preview.setRowCount(0)
        self.preview.setRowCount(len(rows))
        for index, row in enumerate(rows):
            for col, value in enumerate(row):
                self.preview.setItem(index, col, QTableWidgetItem(str(value)))
        for index, reference in enumerate(references):
            self.preview.item(index, 0).setData(Qt.ItemDataRole.UserRole, reference)
        self.preview.setSortingEnabled(True)
        self.update_delete_button()

    def preview_ready(self, files):
        self.files = files
        rows = self.file_rows(files)
        references = [(index, key) for index, entry in enumerate(files) for key in entry['row_keys']]
        self.show_rows(rows, references)
        counts = Counter(row[2] for row in rows)
        details = ' · '.join(f'{count} {status.lower()}' for status, count in counts.items())
        self.summary.setText(f'{len(files)} file(s) · ' + (details or 'No import rows'))
        self.import_button.setEnabled(any(counts[action] for action in ACTIONS))

    def clear_preview(self):
        self.files = []
        self.import_button.setEnabled(False)
        self.review_after_save = False
        self.preview.setRowCount(0)
        self.update_delete_button()

    def commit_preview(self):
        if not self.files:
            return
        if (self.preview_components is not None
                and self.preview_components != self.owner.component_fingerprint()):
            # Components were staged or changed while this preview was shown.
            fingerprint = self.owner.start_import_preview(self.files, self.preview_ready)
            if fingerprint is not None:
                self.preview_components = fingerprint
                self.summary.setText('Component changes were staged since this preview; '
                                     'previewing again. Check the result, then stage the import.')
            return
        try:
            self.owner.stage_import('files', self.files, self.file_rows(self.files),
                                    components=self.preview_components)
        except ValueError as exc:
            QMessageBox.warning(self, 'Stage import', str(exc))
            return
        self.import_button.setEnabled(False)
        self.update_delete_button()
        self.summary.setText('Import staged. Use Save to commit or Revert to discard.')

    def repreview_staged_import(self):
        """Plan the staged import again against the current staged components."""
        staged = self.owner.component_stage.pending_import
        if not staged or staged.get('kind') != 'files':
            return
        result = {}

        def replanned(files):
            current = self.owner.component_stage.pending_import
            if current is not staged:
                return  # reverted or saved meanwhile
            current.update(payload=files, rows=self.file_rows(files), components=result['fingerprint'])
            self.files = []
            self.show_rows(self.file_rows(files))
            self.set_import_pending(True)
            self.summary.setText('Staged import previewed again with the staged component changes. '
                                 'Check it, then Save.')
            self.owner.component_changed()  # journal the new plan
            self.owner.tabs.setCurrentWidget(self)

        fingerprint = self.owner.start_import_preview(staged['payload'], replanned)
        if fingerprint is not None:
            result['fingerprint'] = fingerprint
            self.summary.setText('Previewing the staged import again…')

    def restore_staged_import(self, staged):
        rows = staged['rows']
        if staged['kind'] == 'csv':
            path, _ = staged['payload']
            rows = [(*row[1:], Path(path).name) for row in rows]
        self.show_rows(rows)
        self.set_import_pending(True)
        self.summary.setText('Import staged. Use Save to commit or Revert to discard.')

    def finish_staged_import(self, *, saved):
        staged = self.owner.component_stage.pending_import
        skipped = []
        if saved and staged['kind'] != 'csv':
            skipped = [row for row in staged['rows'] if row[2] in ('Conflict', 'Unresolved link')]
        self.clear_preview()
        if skipped:
            self.show_rows(skipped)
            self.review_after_save = True
            self.update_review_summary()
        else:
            self.summary.setText('Staged import saved.' if saved else 'Staged import discarded.')

    def update_delete_button(self):
        editable = self.review_after_save or (self.files and not self.owner.component_stage.pending_import)
        self.delete_button.setEnabled(bool(editable and self.preview.selectionModel().hasSelection()))

    def delete_review_rows(self):
        if not self.delete_button.isEnabled():
            return
        rows = self.preview.selectionModel().selectedRows()
        if self.review_after_save:
            for row in sorted((index.row() for index in rows), reverse=True):
                self.preview.removeRow(row)
            self.update_review_summary()
            return

        selected = {}
        for index in rows:
            file_index, key = index.data(Qt.ItemDataRole.UserRole)
            selected.setdefault(file_index, set()).add(tuple(key) if isinstance(key, list) else key)
        files = [exclude_rows(entry, selected[i]) if i in selected else entry
                 for i, entry in enumerate(self.files)]
        fingerprint = self.owner.start_import_preview(files, self.preview_ready)
        if fingerprint is not None:
            self.preview_components = fingerprint

    def update_review_summary(self):
        remaining = self.preview.rowCount()
        if remaining:
            self.summary.setText(f'Import saved. Skipped rows left to review: {remaining}.')
        else:
            self.summary.setText('Import saved. Review cleared.')
        self.update_delete_button()

    def export_json(self, selected=None):
        if not self.owner.can_run_database_job('json_export'):
            return
        path, _ = QFileDialog.getSaveFileName(self, 'Export ICDB JSON',
                                              str(self.owner.data / 'icdb-export.json'),
                                              'ICDB JSON (*.json)')
        if path:
            if not path.lower().endswith('.json'):
                path += '.json'
            self.owner.run_job('json_export', (path, selected), self.json_exported)

    def json_exported(self, result):
        parts, pinouts = result
        QMessageBox.information(self, 'ICDB JSON export', f'Exported {parts} parts and {pinouts} pinouts.')


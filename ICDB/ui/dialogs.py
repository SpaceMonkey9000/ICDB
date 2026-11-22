"""Add-device and assign-pinout dialogs."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QVBoxLayout, QFormLayout,
    QTableWidget, QTableWidgetItem, QAbstractItemView,
    QLabel, QLineEdit, QDialog, QDialogButtonBox, QMessageBox,
)
from library_queries import definition_rows


class DeviceDialog(QDialog):
    """Add or edit a device. `validate(part, function, manufacturer)` returns an error
    message or None; the dialog stays open on an error, so typed values are not lost."""

    def __init__(self, parent, record=None, validate=None):
        super().__init__(parent)
        self.validate = validate
        self.setWindowTitle('Edit device' if record else 'Add device')
        self.setMinimumWidth(430)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.part = QLineEdit(record['part_number'] if record else '')
        self.function = QLineEdit(record['function'] if record else '')
        self.manufacturer = QLineEdit(record['manufacturer'] if record else '')
        form.addRow('Part number', self.part)
        form.addRow('Function', self.function)
        form.addRow('Manufacturer', self.manufacturer)
        layout.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def values(self):
        return self.part.text(), self.function.text(), self.manufacturer.text()

    def accept(self):
        error = 'Enter a part number.' if not self.part.text().strip() else None
        if error is None and self.validate is not None:
            error = self.validate(*self.values())
        if error:
            QMessageBox.warning(self, self.windowTitle(), error)
            self.part.setFocus()
            return
        super().accept()


class PinoutAssignmentDialog(QDialog):
    """Choose an existing native pinout definition to associate with one component."""

    def __init__(self, parent, db, part_number):
        super().__init__(parent)
        self.db = db
        self.definition_id = None
        self.setWindowTitle(f'Use existing definition — {part_number}')
        self.resize(700, 480)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel('Select an existing pinout definition. The association is staged until Save.'))
        self.query = QLineEdit(self)
        self.query.setPlaceholderText('Search pinout title, package or linked part number…')
        self.query.textChanged.connect(self.refresh)
        layout.addWidget(self.query)
        self.table = QTableWidget(0, 3, self)
        self.table.setHorizontalHeaderLabels(['Title', 'Package', 'Assigned devices'])
        self.table.verticalHeader().hide()
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSortingEnabled(True)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setColumnWidth(0, 320)
        self.table.setColumnWidth(1, 155)
        self.table.cellDoubleClicked.connect(lambda *_: self.choose())
        layout.addWidget(self.table, 1)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok |
                                        QDialogButtonBox.StandardButton.Cancel, parent=self)
        self.buttons.accepted.connect(self.choose)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self.refresh()

    def refresh(self, *_):
        rows = definition_rows(self.db, self.query.text())
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(rows))
        for index, record in enumerate(rows):
            for col, value in enumerate((record['title'], record['package'], record['uses'])):
                item = QTableWidgetItem(str(value or ''))
                if col == 0:
                    item.setData(Qt.ItemDataRole.UserRole, int(record['id']))
                elif col == 2:
                    item.setData(Qt.ItemDataRole.EditRole, int(value or 0))
                self.table.setItem(index, col, item)
        self.table.setSortingEnabled(True)
        if rows:
            self.table.selectRow(0)
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(bool(rows))

    def choose(self):
        row = self.table.currentRow()
        item = self.table.item(row, 0) if row >= 0 else None
        if item is None:
            return
        self.definition_id = int(item.data(Qt.ItemDataRole.UserRole))
        self.accept()

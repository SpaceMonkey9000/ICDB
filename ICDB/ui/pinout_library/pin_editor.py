"""Pin table editing for the pinout library: roles, rows, pin count and paste."""
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QApplication, QTableWidgetItem, QMessageBox, QStyledItemDelegate,
)
from pinout import parse_table, ROLES
from ui.common import NoWheelComboBox

ROLE_COLUMN = 2


class RoleDelegate(QStyledItemDelegate):
    """Role cells are plain items; a combo box exists only while one cell is edited.

    One persistent combo box widget per pin made opening a 1000-pin definition take
    over a second, and every read of the table had to search those widgets."""

    def createEditor(self, parent, option, index):
        editor = NoWheelComboBox(parent)
        editor.addItems(ROLES)
        # Commit as soon as a role is picked, like the previous always-visible list.
        editor.activated.connect(lambda *_: (self.commitData.emit(editor),
                                             self.closeEditor.emit(editor)))
        return editor

    def setEditorData(self, editor, index):
        value = index.data(Qt.ItemDataRole.EditRole)
        editor.setCurrentText(value if value in ROLES else 'Signal')
        QTimer.singleShot(0, editor.showPopup)

    def setModelData(self, editor, model, index):
        if model.data(index, Qt.ItemDataRole.EditRole) != editor.currentText():
            model.setData(index, editor.currentText(), Qt.ItemDataRole.EditRole)


class PinEditorMixin:
    """Pin table editing. Mixed into PinoutLibraryPage."""

    def _install_role_delegate(self):
        self._role_delegate = RoleDelegate(self.pins)
        self.pins.setItemDelegateForColumn(ROLE_COLUMN, self._role_delegate)
        # A single click opens the role list, so it behaves like the old visible list.
        self.pins.clicked.connect(
            lambda index: self.pins.edit(index) if index.column() == ROLE_COLUMN else None)

    def _pin_role(self, row):
        item = self.pins.item(row, ROLE_COLUMN)
        return item.text() if item and item.text() else 'Signal'

    def _role_combobox(self, row, role='Signal'):
        """Set a row's role cell (kept under its old name for callers and tests)."""
        self.pins.setItem(row, ROLE_COLUMN, QTableWidgetItem(role if role in ROLES else 'Signal'))

    def _populate_editor(self,data):
        self.title.setText(data['device'])
        self.package.setCurrentText(data['package'])
        self.source.setText(data.get('source',''))
        self.count.setValue(int(data['count']))
        pad = data.get('exposed_pad') or {}
        self.pad_enabled.setChecked(bool(pad.get('enabled',True)) if pad else False)
        self.pad_number.setText(str(pad.get('number','EP')))
        self.pad_name.setText(pad.get('name',''))
        self.pad_role.setCurrentText(pad.get('role','Signal'))
        pins = data.get('pins',[])
        self.pins.setUpdatesEnabled(False)
        try:
            self.pins.setRowCount(len(pins))
            for i,pin in enumerate(pins):
                for j,key in enumerate(('number','name','role','description')):
                    if j != 2:
                        self.pins.setItem(i,j,QTableWidgetItem(str(pin.get(key,''))))
                self._role_combobox(i, str(pin.get('role', 'Signal')))
        finally:
            self.pins.setUpdatesEnabled(True)

    def _row_has_content(self, row):
        number = self.pins.item(row, 0)
        name = self.pins.item(row, 1)
        description = self.pins.item(row, 3)
        return ((name is not None and name.text().strip() not in ('', 'NC'))
                or (description is not None and description.text().strip() != '')
                or self._pin_role(row) not in ('NC', 'Signal')
                or (number is not None and number.text().strip() not in ('', str(row + 1))))

    def set_pin_count(self, count):
        if self.loading:
            return
        old = self.pins.rowCount()
        if count < old and any(self._row_has_content(r) for r in range(count, old)):
            if QMessageBox.question(self, 'Reduce pin count',
                    f'Remove pin rows {count + 1}–{old}? Some of them contain pin data.',
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
                self.count.blockSignals(True)
                self.count.setValue(old)
                self.count.blockSignals(False)
                return
        self.loading = True
        self.pins.setRowCount(count)
        for row in range(old, count):
            for col, value in ((0, str(row+1)), (1, 'NC'), (3, '')):
                self.pins.setItem(row, col, QTableWidgetItem(value))
            self._role_combobox(row, 'NC')
        self.loading = False
        self.mark_changed()

    def add_pin(self):
        self.count.setValue(self.pins.rowCount()+1)

    def remove_pins(self):
        rows = sorted({item.row() for item in self.pins.selectedItems()}, reverse=True)
        if not rows:
            return
        self.loading = True
        for row in rows:
            self.pins.removeRow(row)
        self.loading = False
        if self.pins.rowCount() == 0:
            self.pins.setRowCount(1)
            for col, value in ((0, '1'), (1, 'NC'), (3, '')):
                self.pins.setItem(0, col, QTableWidgetItem(value))
            self._role_combobox(0, 'NC')
        self.count.setValue(self.pins.rowCount())
        self.mark_changed()

    def paste_pins(self):
        """Replace the pin table with pasted rows (tab, semicolon or comma separated).

        pinout.parse_table skips an optional header row and normalizes role names."""
        if self.data is None:
            QMessageBox.information(self, 'Paste pins', 'Select or create a pinout first.')
            return
        text = QApplication.clipboard().text()
        if not text.strip():
            return
        try:
            pins = parse_table(text)
        except ValueError as exc:
            QMessageBox.warning(self, 'Paste pins', str(exc))
            return
        if self.pins.rowCount() and QMessageBox.question(self, 'Paste pins',
                f'Replace the {self.pins.rowCount()} current pin rows with {len(pins)} pasted pins?',
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return
        self.loading = True
        self.pins.setRowCount(len(pins))
        for row, pin in enumerate(pins):
            for col, value in ((0, str(pin.number)), (1, pin.name), (3, pin.description)):
                self.pins.setItem(row, col, QTableWidgetItem(value))
            self._role_combobox(row, pin.role)
        self.count.setValue(len(pins))
        self.loading = False
        self.mark_changed()
        self.queue_preview()

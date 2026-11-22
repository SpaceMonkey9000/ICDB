"""Select a committed ICDB device for an experimental marking alias."""
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QFormLayout, QLineEdit,
                               QListWidget, QListWidgetItem, QMessageBox)
from PySide6.QtCore import Qt
from marking_aliases import alias_record


class AliasDialog(QDialog):
    def __init__(self, owner, marking='', part='', manufacturer='', *, existing=None, select_target=True):
        super().__init__(owner)
        self.owner = owner
        self.select_target = select_target and existing is None
        self.setWindowTitle('Edit alias' if existing is not None else 'Add alias')
        self.resize(*(560, 340) if self.select_target else (480, 160))
        layout = QFormLayout(self)
        self.marking = QLineEdit(marking)
        self.packages = QLineEdit(', '.join(existing['packages']) if existing is not None else '')
        self.packages.setPlaceholderText('Optional, e.g. SSOP-16, TSSOP-16')
        self.source = QLineEdit(existing['source'] if existing is not None else '')
        layout.addRow('Marking', self.marking)
        if self.select_target:
            self.search = QLineEdit(part)
            self.targets = QListWidget()
            layout.addRow('Find target device', self.search)
            layout.addRow(self.targets)
        layout.addRow('Packages', self.packages)
        layout.addRow('Source', self.source)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._confirm)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)
        if not self.select_target:
            return
        self.search.textChanged.connect(self._refresh)
        self._refresh(part)
        for i in range(self.targets.count()):
            item = self.targets.item(i)
            _, name, maker = item.data(Qt.ItemDataRole.UserRole)
            if name.casefold() == part.casefold() and maker.casefold() == manufacturer.casefold():
                self.targets.setCurrentItem(item)
                break

    def _refresh(self, value):
        self.targets.clear()
        value = value.strip()
        if not value:
            return
        for row in self.owner.db.execute("""SELECT id,part_number,manufacturer FROM components
                WHERE instr(upper(part_number),upper(?))>0
                ORDER BY upper(part_number)<>upper(?),part_number,manufacturer LIMIT 100""", (value,value)):
            item = QListWidgetItem(f"{row['part_number']} · {row['manufacturer'] or 'Manufacturer unspecified'}")
            item.setData(Qt.ItemDataRole.UserRole, tuple(row))
            self.targets.addItem(item)

    def _confirm(self):
        if self.select_target and self.targets.currentItem() is None:
            QMessageBox.warning(self, 'Marking alias', 'Select a target device.')
            return
        try:
            data = alias_record(self.marking.text(), self.packages.text(), self.source.text())
        except ValueError as exc:
            QMessageBox.warning(self, 'Marking alias', str(exc))
            return
        if self.select_target:
            cid, part, maker = self.targets.currentItem().data(Qt.ItemDataRole.UserRole)
            data.update(component_id=cid, identity=[part, maker])
        self.record = data
        self.accept()

"""Opening and staging parts requested by ICOCR (--open-part, --add-part)."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QMessageBox, QDialog,
)
from qt_open_component import resolve_part
from ui.dialogs import DeviceDialog
from ui.alias_dialog import AliasDialog


class IcocrHandoffMixin:
    """Navigation requested from ICOCR and from component actions. Mixed into MainWindow."""

    def stage_alias(self, marking='', part='', manufacturer=''):
        dialog = AliasDialog(self, marking, part, manufacturer)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        draft = dialog.record
        try:
            self.component_stage.change_alias(self.db, draft['component_id'], replacement=draft)
        except ValueError as exc:
            QMessageBox.warning(self, 'Add alias', str(exc))
            return
        self.component_changed()
        self.components.refresh_aliases()

    def open_pinout_definition(self, ident):
        """Select the exact accepted library definition without discarding staged edits."""
        page = self.library_page
        if page.definition_id == ident and not page._new:
            self.tabs.setCurrentWidget(page)
            return
        page.stash_current()
        page.search.clear()
        page.filter.setCurrentIndex(0)
        page.refresh()
        for row in range(page.table.rowCount()):
            item = page.table.item(row, 0)
            if item and item.data(Qt.ItemDataRole.UserRole) == ident:
                self.tabs.setCurrentWidget(page)
                page.table.selectRow(row)
                page.load_selected()
                page.table.scrollToItem(item)
                self.update_draft_ui()
                return
        QMessageBox.warning(self, 'Edit pinout', f'Pinout definition #{ident} was not found.')

    def stage_component_from_icocr(self, part):
        """Stage an imported observation as a new record, never commit without Save."""
        part = str(part or '').strip()
        if not part:
            raise ValueError('Part number is required')
        # Existing database and pending additions must never be duplicated silently.
        for cid, staged in self.component_stage.added.items():
            if staged['part_number'].casefold() == part.casefold():
                self.tabs.setCurrentWidget(self.components)
                self.components.search.setText(staged['part_number'])
                self.components.refresh(cid)
                return
        try:
            ident, canonical = resolve_part(self.db, part)
        except LookupError:
            ident = None
        if ident is not None:
            self.open_component_part(part)
            QMessageBox.information(self, 'Already in ICDB',
                f'{part} already exists. No duplicate was staged.')
            return
        dialog = DeviceDialog(self.components, {'part_number': part, 'function': '', 'manufacturer': ''},
                              validate=self.components.device_error)
        dialog.setWindowTitle('Add to ICDB — staged draft')
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        cid = self.component_stage.add(*dialog.values())
        self.component_changed()
        self.tabs.setCurrentWidget(self.components)
        self.components.search.setText('')
        self.components.refresh(cid)
        self.components.table.setFocus()
        self.message('New component staged from ICOCR. Review changes and Save to commit.')

    def open_component_part(self, part):
        """Navigate to one exact component; never modify or discard existing drafts."""
        ident, canonical_part = resolve_part(self.db, part)
        self.tabs.setCurrentWidget(self.components)
        self.components.search.setText(canonical_part)
        self.components.refresh(focus_id=ident)
        if self.components.selected_id() != ident:
            raise LookupError(f'Component {canonical_part!r} could not be selected')
        self.components.table.setFocus()
        self.statusBar().showMessage(f'Opened {canonical_part} from ICOCR')

    def navigate_requested_part(self):
        part, self.requested_part = self.requested_part, None
        if not part:
            return
        try:
            self.open_component_part(part)
        except (LookupError, ValueError) as exc:
            QMessageBox.warning(self, 'Open in ICDB', str(exc))

    def navigate_requested_add(self):
        part, self.requested_add_part = self.requested_add_part, None
        if part:
            try:
                self.stage_component_from_icocr(part)
            except (ValueError, LookupError) as exc:
                QMessageBox.warning(self, 'Add to ICDB', str(exc))

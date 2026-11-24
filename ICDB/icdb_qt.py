"""ICDB Qt migration: Components, Pinout Library and simple component CSV Import.

Matching is not exposed. Original database schema and import/publish backends are reused.
"""
import argparse
import json
import sys
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QSettings, QStandardPaths
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QHBoxLayout, QTabWidget, QLabel, QPushButton, QMessageBox, QFileDialog,
)

from builder import connect, UI_BUSY_TIMEOUT_SECONDS
from shared_data import data_directory, database_file, save_directory
from pinouts import Pinouts
from pin_library import Library
from version import APP_VERSION
from data_lock import DataLease
from qt_draft_store import draft_file
from qt_component_draft import ComponentDraft
from ui.common import apply_palette, use_dark_windows_titlebar
from ui.components_page import ComponentsPage
from ui.import_page import ImportPage
from ui.settings_dialog import SettingsDialog
from ui.pinout_library.page import PinoutLibraryPage
from ui.icocr_handoff import IcocrHandoffMixin
from ui.job_runner import JobRunnerMixin
from ui.session import SessionMixin

ROOT = Path(__file__).resolve().parent


def app_icon():
    """Locate ICO in source, PyInstaller one-folder and one-file deployments."""
    candidates = [ROOT / 'ICDB.ico']
    if getattr(sys, '_MEIPASS', None):
        candidates.insert(0, Path(sys._MEIPASS) / 'ICDB.ico')
    if getattr(sys, 'frozen', False):
        candidates.append(Path(sys.executable).resolve().parent / 'ICDB.ico')
    for path in candidates:
        if path.is_file():
            icon = QIcon(str(path))
            if not icon.isNull():
                return icon
    return QIcon()



class MainWindow(SessionMixin, IcocrHandoffMixin, JobRunnerMixin, QMainWindow):
    def __init__(self, data, *, create_database=False):
        super().__init__()
        self.setWindowIcon(app_icon())
        self.data = data
        self.settings = QSettings('ICSuite', 'ICDB-PySide6')
        self.dark_theme = str(self.settings.value('appearance/theme', 'light')) == 'dark'
        self.invert_pinout = str(self.settings.value('appearance/invert_pinout', 'true')).lower() in ('true','1','yes')
        self.setWindowTitle(f'ICDB {APP_VERSION}')
        self.job = None
        self.job_done = None
        self.job_error = None
        self.lease = DataLease(data)
        self.db = None
        try:
            # Short busy timeout: the UI connection must not freeze for long behind a worker's write lock.
            database = database_file(data)
            if not database.is_file():
                if not create_database:
                    raise FileNotFoundError(f'ICDB database not found at {database}')
                database.parent.mkdir(parents=True, exist_ok=True)
            self.db = connect(database, timeout=UI_BUSY_TIMEOUT_SECONDS)
            self.pinouts = Pinouts(self.db, data)
            self.library = Library(self.pinouts)
        except Exception:
            if self.db is not None:
                self.db.close()
            self.lease.close()
            raise
        self.resize(1360, 860)
        self._startup_recovery_pending = True
        self.requested_part = None
        self.requested_add_part = None
        self.requested_alias = None
        self._protect_existing_draft = False  # a kept pinout draft is on disk
        self._protect_component_draft = False  # a kept component draft is on disk
        draft_root = self.data / 'prototype-state'
        self.draft_path = draft_file(Path(draft_root) / 'drafts', database_file(data))
        tabs = QTabWidget()
        self.tabs = tabs
        self.component_stage = ComponentDraft()
        self._component_recovery_pending = True
        self.component_draft_path = self.draft_path.with_name(
            self.draft_path.name.replace('pinout-', 'components-', 1))
        self.component_draft_timer = QTimer(self)
        self.component_draft_timer.setSingleShot(True)
        self.component_draft_timer.setInterval(450)
        self.component_draft_timer.timeout.connect(self.save_component_draft)
        # Persistent warnings live on the right of the status bar, apart from the
        # transient messages on the left that every refresh overwrites.
        self._status_warnings = {}  # key -> (text, details, page or None)
        self.status_warning = QLabel()
        self.status_warning.setStyleSheet('font-weight: 600; padding: 0 6px;')  # palette text colour
        self.status_warning.hide()
        self.statusBar().addPermanentWidget(self.status_warning)
        tabs.currentChanged.connect(lambda *_: self._show_status_warnings())
        self.components = ComponentsPage(self)
        self.library_page = PinoutLibraryPage(self)
        tabs.addTab(self.components, 'Components')
        tabs.addTab(self.library_page, 'Pinout library')
        self.import_page = ImportPage(self)
        tabs.addTab(self.import_page, 'Import')
        top_tools = QWidget()
        tools_layout = QHBoxLayout(top_tools)
        tools_layout.setContentsMargins(4, 0, 2, 0)
        tools_layout.setSpacing(7)
        self.draft_notice = QLabel('Unsaved changes', tabs)
        self.draft_notice.setToolTip('Staged changes in Components or Pinout Library are not saved to the database.')
        self.draft_notice.setStyleSheet('font-weight: 700;')
        self.draft_notice.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.draft_notice.adjustSize()
        tabs.installEventFilter(self)
        # Saved pinout changes that ICOCR cannot see yet (publication refused or failed).
        self.unpublished = False
        self._publish_retry = False
        self._publish_targets = set()  # pinout ids for the next automatic publish; None = all
        self.publish_notice = QPushButton('Publish to ICOCR')
        self.publish_notice.setToolTip('Saved pinout changes are not yet published to ICOCR. '
                                       'Click to publish them now.')
        self.publish_notice.setStyleSheet('font-weight: 700;')
        self.publish_notice.clicked.connect(self.publish_pending_now)
        self.publish_notice.hide()
        tools_layout.addWidget(self.publish_notice)
        self.global_review = QPushButton('View changes')
        self.global_review.clicked.connect(self.review_changes)
        tools_layout.addWidget(self.global_review)
        self.global_save = QPushButton('Save')
        self.global_save.setToolTip('Save every staged component, alias, import and pinout change as one SQLite transaction.')
        self.global_save.clicked.connect(self.save_all)
        tools_layout.addWidget(self.global_save)
        self.global_revert = QPushButton('Revert')
        self.global_revert.setToolTip('Discard all staged component and pinout changes.')
        self.global_revert.clicked.connect(self.revert_all)
        tools_layout.addWidget(self.global_revert)
        settings_button = QPushButton('Settings')
        settings_button.setToolTip('Application settings')
        settings_button.clicked.connect(self.open_settings)
        tools_layout.addWidget(settings_button)
        tabs.setCornerWidget(top_tools, Qt.Corner.TopRightCorner)
        self.update_draft_ui()
        self.setCentralWidget(tabs)
        self.statusBar().showMessage('Ready')
        self.set_theme(self.dark_theme)
        QTimer.singleShot(0, lambda: use_dark_windows_titlebar(self))
        # One sequential routine: two separate zero-timers let the second dialog open inside
        # the first one's event loop, i.e. before the pinout session had been restored.
        QTimer.singleShot(0, self.offer_recovery)
        QTimer.singleShot(0, self.position_draft_notice)

    def update_draft_ui(self):
        if not hasattr(self, 'draft_notice'):
            return
        pending = bool(self.library_page.has_pending() or self.component_stage.changed)
        self.draft_notice.setVisible(pending)
        self.position_draft_notice()
        self.global_save.setEnabled(pending)
        self.global_revert.setEnabled(pending)
        self.global_review.setEnabled(pending)
        self.import_page.set_import_pending(bool(self.component_stage.pending_import))

    def set_status_warning(self, key, text='', details='', page=None):
        """Show (or with empty text, clear) a warning in the status bar. A warning tied
        to a page is shown only while that tab is open."""
        if text:
            self._status_warnings[key] = (text, details or text, page)
        else:
            self._status_warnings.pop(key, None)
        self._show_status_warnings()

    def _show_status_warnings(self):
        current = self.tabs.currentWidget()
        shown = [(text, details) for text, details, page in self._status_warnings.values()
                 if page is None or page is current]
        self.status_warning.setText('   '.join('Warning: ' + text for text, _ in shown))
        self.status_warning.setToolTip('\n\n'.join(details for _, details in shown))
        self.status_warning.setVisible(bool(shown))

    def set_unpublished(self, pending):
        self.unpublished = bool(pending)
        self.publish_notice.setVisible(self.unpublished)

    def publish_pending_now(self):
        if self.library_page.has_pending() or self.component_stage.changed:
            QMessageBox.information(self, 'Publish to ICOCR',
                'Save or Revert the staged changes first, then publish.')
            return
        self.run_job('publish', None, lambda result: self.publish_complete(result, 'Publish result'))

    def eventFilter(self, obj, event):
        if obj is self.tabs and event.type() == event.Type.Resize:
            QTimer.singleShot(0, self.position_draft_notice)
        return super().eventFilter(obj, event)

    def position_draft_notice(self):
        if not hasattr(self, 'draft_notice'):
            return
        label = self.draft_notice
        label.adjustSize()
        x = (self.tabs.width() - label.width()) // 2
        y = max(0, (self.tabs.tabBar().height() - label.height()) // 2)
        label.move(x, y)
        label.raise_()

    def open_settings(self):
        SettingsDialog(self).exec()

    def set_theme(self, dark):
        self.dark_theme = bool(dark)
        self.settings.setValue('appearance/theme', 'dark' if dark else 'light')
        apply_palette(QApplication.instance(), dark)
        for viewer in (self.components.pinout, self.library_page.preview):
            viewer.set_theme(dark, self.invert_pinout)

    def set_invert_pinout(self, enabled):
        self.invert_pinout = bool(enabled)
        self.settings.setValue('appearance/invert_pinout', self.invert_pinout)
        self.set_theme(self.dark_theme)

    def has_table(self, name):
        return self.db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None

    def message(self, value):
        self.statusBar().showMessage(value)

    def refresh(self):
        self.components.refresh()
        self.library_page.refresh()

    def change_data(self):
        """Choose the shared DATA folder for ICDB and ICOCR. Applies on the next start."""
        folder = QFileDialog.getExistingDirectory(self, 'Choose the shared DATA folder', str(self.data))
        if not folder:
            return False
        try:
            saved = save_directory(folder)
        except (OSError, ValueError) as exc:
            QMessageBox.critical(self, 'DATA folder', f'The DATA folder could not be saved:\n{exc}')
            return False
        if not database_file(saved).is_file():
            QMessageBox.warning(self, 'DATA folder',
                f'No ICDB database was found in {saved}. ICDB will ask before creating one at the next start.')
        QMessageBox.information(self, 'DATA folder',
            f'DATA folder saved:\n{saved}\n\nRestart ICDB and ICOCR to use it.')
        return True

    def closeEvent(self, event):
        if self.job is not None:
            QMessageBox.information(self, 'Database operation running',
                'Finish the database operation before closing.')
            event.ignore()
            return
        if self.library_page.has_pending() or self.component_stage.changed:
            while True:
                dialog = QMessageBox(self)
                dialog.setWindowTitle('Unsaved changes')
                dialog.setText(self.pending_summary() + ' are not saved.')
                dialog.setInformativeText('Save commits everything together. Keep Draft preserves the editing session.')
                save_button = dialog.addButton('Save', QMessageBox.ButtonRole.AcceptRole)
                review_button = dialog.addButton('View changes', QMessageBox.ButtonRole.ActionRole)
                keep_button = dialog.addButton('Keep Draft', QMessageBox.ButtonRole.ActionRole)
                discard_button = dialog.addButton('Discard', QMessageBox.ButtonRole.DestructiveRole)
                dialog.addButton('Cancel', QMessageBox.ButtonRole.RejectRole)
                dialog.exec()
                selected = dialog.clickedButton()
                if selected == review_button:
                    self.review_changes()
                    continue
                if selected == save_button:
                    if not self.save_all(confirmed=True):
                        event.ignore()
                        return
                elif selected == keep_button:
                    self.library_page.draft_timer.stop()
                    if not ((not self.library_page.has_pending() or self.save_draft()) and
                            (not self.component_stage.changed or self.save_component_draft())):
                        QMessageBox.warning(self, 'Recovery draft',
                            'Recovery draft could not be written. Exit cancelled.')
                        event.ignore()
                        return
                elif selected == discard_button:
                    # Discard this session's work; drafts kept from earlier sessions stay.
                    self.library_page.draft_timer.stop()
                    self.clear_draft()
                    self.component_draft_timer.stop()
                    self.clear_component_draft()
                else:
                    event.ignore()
                    return
                break
        self._closed = True
        self.db.close()
        self.lease.close()
        super().closeEvent(event)


def self_test(application, report=None):
    """Start the complete window against throw-away DATA and settings, then close it.
    Used by the build to check that a packaged exe starts. Nothing in the user's
    DATA folder, settings or drafts is read or written."""
    import tempfile
    import traceback
    global QSettings
    result = {'ok': False, 'version': APP_VERSION}
    QStandardPaths.setTestModeEnabled(True)
    with tempfile.TemporaryDirectory() as tmp:
        native_settings = QSettings
        ini = str(Path(tmp) / 'settings.ini')
        QSettings = lambda *a: native_settings(ini, native_settings.Format.IniFormat)
        try:
            data = Path(tmp) / 'DATA'
            data.mkdir()
            database = database_file(data)
            database.parent.mkdir(parents=True, exist_ok=True)
            connect(database).close()
            window = MainWindow(data)
            window.show()
            application.processEvents()
            result.update(ok=True, screens=window.tabs.count())
            window.close()
            application.processEvents()
        except Exception as exc:
            result.update(error=str(exc), details=traceback.format_exc())
        finally:
            QSettings = native_settings
    if report:
        Path(report).write_text(json.dumps(result, indent=2), 'utf-8')
    else:
        print(json.dumps(result))
    return 0 if result['ok'] else 1


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--data', help='Override DATA directory for this run without saving the setting')
    parser.add_argument('--open-part', help='Select an exact part number from ICOCR History')
    parser.add_argument('--add-part', help='Stage a new component from ICOCR History')
    parser.add_argument('--add-alias', help='Stage a marking alias from ICOCR')
    parser.add_argument('--alias-part', default='')
    parser.add_argument('--alias-manufacturer', default='')
    parser.add_argument('--self-test', action='store_true',
                        help='Open the main window against temporary DATA, close it and exit')
    parser.add_argument('--report', help='With --self-test: write a JSON result to this file')
    args = parser.parse_args()
    application = QApplication(sys.argv[:1])
    application.setStyle('Fusion')
    application.setWindowIcon(app_icon())
    if args.self_test:
        return self_test(application, args.report)
    try:
        # --data applies to this session only; otherwise ICLENS_DATA, the saved setting,
        # or the default location (shared_data.data_directory).
        data = Path(args.data).expanduser().resolve() if args.data else data_directory(ROOT)
    except Exception as exc:
        QMessageBox.critical(None, 'ICDB startup failed', str(exc))
        return 1
    database = database_file(data)
    create_database = not database.is_file()
    if create_database:
        answer = QMessageBox.question(
            None, 'Create ICDB database?',
            f'No ICDB database was found at:\n{database}\n\nCreate a new empty database here?',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return 0
    try:
        window = MainWindow(data, create_database=create_database)
    except Exception as exc:
        import traceback
        traceback.print_exc()
        QMessageBox.critical(None, 'ICDB startup failed', f'{exc}\n\nDetails:\n{traceback.format_exc(limit=5)}')
        return 1
    window.requested_part = args.open_part
    window.requested_add_part = args.add_part
    if args.add_alias:
        window.requested_alias = (args.add_alias, args.alias_part, args.alias_manufacturer)
    window.show()
    return application.exec()


if __name__ == '__main__':
    raise SystemExit(main())

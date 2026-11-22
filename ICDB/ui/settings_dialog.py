"""Settings dialog: Appearance, Data and Tools tabs."""
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
    QTabWidget, QGroupBox, QLabel, QLineEdit, QPushButton, QMessageBox, QDialog, QDialogButtonBox, QCheckBox,
)
from database_version import database_version
from shared_data import data_directory
from ui.common import APP_ROOT, NoWheelComboBox, use_dark_windows_titlebar


class SettingsDialog(QDialog):
    """Main application settings; no File or View menus."""
    def __init__(self, owner):
        super().__init__(owner)
        self.owner = owner
        self.setWindowTitle('ICDB Settings')
        self.resize(590, 350)
        QTimer.singleShot(0, lambda: use_dark_windows_titlebar(self))
        layout = QVBoxLayout(self)
        tabs = QTabWidget()
        appearance = QWidget()
        appearance_form = QFormLayout(appearance)
        self.theme = NoWheelComboBox()
        self.theme.addItem('Light', 'light')
        self.theme.addItem('Dark graphite', 'dark')
        self.theme.setCurrentIndex(1 if owner.dark_theme else 0)
        appearance_form.addRow('Appearance', self.theme)
        self.invert_pinout = QCheckBox('Invert pinout images in dark mode')
        self.invert_pinout.setChecked(owner.invert_pinout)
        self.invert_pinout.toggled.connect(owner.set_invert_pinout)
        appearance_form.addRow('', self.invert_pinout)
        self.theme.currentIndexChanged.connect(self.set_theme)
        tabs.addTab(appearance, 'Appearance')
        data = QWidget()
        data_layout = QVBoxLayout(data)
        data_layout.addWidget(QLabel('Shared DATA folder (applies on next launch)'))
        folder_row = QHBoxLayout()
        self.data_path = QLineEdit(str(owner.data))
        self.data_path.setReadOnly(True)
        folder_row.addWidget(self.data_path, 1)
        browse = QPushButton('Change…')
        browse.clicked.connect(self.change_data)
        folder_row.addWidget(browse)
        data_layout.addLayout(folder_row)
        database_info = QGroupBox('Database information')
        info_form = QFormLayout(database_info)
        devices = owner.db.execute('SELECT COUNT(*) FROM components').fetchone()[0]
        pinouts = owner.db.execute('SELECT COUNT(*) FROM pl_definitions').fetchone()[0]
        info_form.addRow('Database version', QLabel(database_version(owner.db)))
        info_form.addRow('Devices', QLabel(f'{devices:,}'))
        info_form.addRow('Pinout definitions', QLabel(f'{pinouts:,}'))
        data_layout.addWidget(database_info)
        data_layout.addStretch(1)
        tabs.addTab(data, 'Data')
        tools = QWidget()
        tool_layout = QVBoxLayout(tools)
        publish = QPushButton('Publish pinouts')
        publish.setToolTip('Incrementally publish accepted pinouts and update ICOCR links.')
        publish.clicked.connect(lambda: self.run_svg_tool('publish'))
        tool_layout.addWidget(publish)
        rebuild = QPushButton('Rebuild all SVGs')
        rebuild.setToolTip('Force regeneration of every eligible accepted pinout SVG.')
        rebuild.clicked.connect(lambda: self.run_svg_tool('rebuild'))
        tool_layout.addWidget(rebuild)
        tool_layout.addWidget(QLabel('Publish updates changed pinouts and their ICOCR links; unchanged SVGs are reused.'))
        tool_layout.addWidget(QLabel('Rebuild regenerates all accepted SVGs, even if unchanged. Original definitions remain intact.'))
        tool_layout.addWidget(QLabel('Pinouts changed by Save are published automatically; use these for everything else.'))
        tool_layout.addStretch(1)
        tabs.addTab(tools,'Tools')
        layout.addWidget(tabs, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.accept)
        layout.addWidget(buttons)

    def run_svg_tool(self, operation):
        if self.owner.library_page.has_pending() or self.owner.component_stage.changed:
            QMessageBox.warning(self, 'Unsaved changes',
                                'Save or Revert staged edits before publishing SVGs.')
            return
        force = operation == 'rebuild'
        title = 'Rebuild all SVGs' if force else 'Publish pinouts'
        message = ('Regenerate all eligible accepted SVGs, including unchanged ones?\n'
                   'This updates SVG files and ICOCR database links.' if force else
                   'Publish changed accepted pinouts and update ICOCR database links?\n'
                   'Unchanged SVGs will be reused.')
        if QMessageBox.question(self, title, message,
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return
        self.owner.run_job(operation, None,
                           lambda result: self.owner.publish_complete(result, title + ' result'))

    def set_theme(self, *_):
        self.owner.set_theme(self.theme.currentData() == 'dark')

    def change_data(self):
        if self.owner.change_data():
            self.data_path.setText(str(data_directory(APP_ROOT)))

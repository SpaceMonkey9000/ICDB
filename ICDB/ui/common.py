"""Shared Qt helpers: SVG and image rendering, palettes, Windows title bars, small widgets."""
import sys
from urllib.parse import urlencode
from PySide6.QtCore import Qt, QByteArray
from PySide6.QtGui import QImage, QPainter, QPalette, QColor
from PySide6.QtWidgets import (
    QComboBox,
)
from PySide6.QtSvg import QSvgRenderer
from pathlib import Path

# The application folder (icdb_qt.py lives here; this module is in ui/).
APP_ROOT = Path(__file__).resolve().parent.parent


def use_dark_windows_titlebar(widget):
    """Set a dark native Win10/11 title bar without replacing Qt Fusion chrome.

    This is an OS-level preference, not a custom title bar. Unsupported
    platforms/Windows builds leave their native title bars unchanged.
    """
    if sys.platform != 'win32':
        return False
    try:
        import ctypes
        from ctypes import wintypes
        hwnd = wintypes.HWND(int(widget.winId()))
        value = ctypes.c_int(1)
        dwm = ctypes.windll.dwmapi.DwmSetWindowAttribute
        for attribute in (20, 19):  # DWMWA_USE_IMMERSIVE_DARK_MODE (modern / older)
            if dwm(hwnd, attribute, ctypes.byref(value), ctypes.sizeof(value)) == 0:
                return True
    except (AttributeError, OSError, ValueError):
        pass
    return False


def part_search_url(part, manufacturer=''):
    return 'https://www.google.com/search?' + urlencode({'q': f'"{part.strip()}" {manufacturer.strip()} datasheet pdf'.strip()})


def qt_image_from_pil(im):
    image = im.convert('RGBA')
    data = image.tobytes('raw', 'RGBA')
    return QImage(data, image.width, image.height, image.width * 4, QImage.Format.Format_RGBA8888).copy()


def render_svg(svg_bytes, dark=False):
    renderer = QSvgRenderer(QByteArray(svg_bytes))
    if not renderer.isValid():
        raise ValueError('Invalid pinout SVG')
    natural = renderer.defaultSize()
    if natural.width() <= 0 or natural.height() <= 0:
        raise ValueError('Invalid pinout SVG dimensions')
    # The Qt view supports zoom; rendering at the native SVG size produces
    # visibly pixelated diagrams when the source SVG is only a few hundred px.
    # Supersample for consistent preview resolution without modifying the SVG.
    # Never render below the native size (large packages exceed 2400 px), but cap memory use.
    longest = max(natural.width(), natural.height())
    scale = max(1.0, min(6.0, 2400.0 / longest))
    max_pixels = 36_000_000
    if natural.width() * natural.height() * scale * scale > max_pixels:
        scale = (max_pixels / (natural.width() * natural.height())) ** 0.5
    w, h = max(1, round(natural.width() * scale)), max(1, round(natural.height() * scale))
    image = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.white)
    p = QPainter(image)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
    renderer.render(p)
    p.end()
    if dark:
        image.invertPixels(QImage.InvertMode.InvertRgb)
    return image


def display_image(image, dark=False):
    """Create a theme-specific display copy without changing stored source files."""
    if image is None or not dark:
        return image  # QImage is implicitly shared; no deep copy needed to display it
    copy = image.copy()
    copy.invertPixels(QImage.InvertMode.InvertRgb)
    return copy


def apply_palette(application, dark=False):
    """Set a complete application palette including input fields and tooltips."""
    palette = QPalette()
    if dark:
        colors = {
            QPalette.ColorRole.Window: '#30343B',
            QPalette.ColorRole.WindowText: '#ECEFF2',
            QPalette.ColorRole.Base: '#25282E',
            QPalette.ColorRole.AlternateBase: '#343941',
            QPalette.ColorRole.Text: '#ECEFF2',
            QPalette.ColorRole.Button: '#404650',
            QPalette.ColorRole.ButtonText: '#ECEFF2',
            QPalette.ColorRole.Highlight: '#516C8B',
            QPalette.ColorRole.HighlightedText: '#FFFFFF',
            QPalette.ColorRole.ToolTipBase: '#25282E',
            QPalette.ColorRole.ToolTipText: '#ECEFF2',
            QPalette.ColorRole.PlaceholderText: '#9CA5B0',
        }
    else:
        colors = {
            QPalette.ColorRole.Window: '#F0F0F0',
            QPalette.ColorRole.WindowText: '#171717',
            QPalette.ColorRole.Base: '#FFFFFF',
            QPalette.ColorRole.AlternateBase: '#F6F6F6',
            QPalette.ColorRole.Text: '#171717',
            QPalette.ColorRole.Button: '#E6E6E6',
            QPalette.ColorRole.ButtonText: '#171717',
            QPalette.ColorRole.Highlight: '#3478B8',
            QPalette.ColorRole.HighlightedText: '#FFFFFF',
            QPalette.ColorRole.ToolTipBase: '#FFFFDC',
            QPalette.ColorRole.ToolTipText: '#171717',
            QPalette.ColorRole.PlaceholderText: '#777777',
        }
    if not dark:
        # Subtle native table/header separators in Light mode. Manufacturer data
        # remains in the database and component details; only its column is hidden.
        colors[QPalette.ColorRole.Mid] = '#EBEBEB'
        colors[QPalette.ColorRole.Dark] = '#E6E6E6'
    for role, color in colors.items():
        palette.setColor(role, QColor(color))
    # Disabled widgets must look disabled (setColor above applies to every colour group).
    disabled = QColor('#7C848E' if dark else '#A0A0A0')
    for role in (QPalette.ColorRole.Text, QPalette.ColorRole.WindowText, QPalette.ColorRole.ButtonText):
        palette.setColor(QPalette.ColorGroup.Disabled, role, disabled)
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Base,
                     QColor('#2B2F35' if dark else '#F4F4F4'))
    application.setPalette(palette)
    # Use one application-wide rule so dynamically created dialogs and every
    # QTableWidget share the same faint row/column grid, including Import and
    # group selection. Dark mode keeps Qt Fusion's original grid appearance.
    application.setStyleSheet('QTableView { gridline-color: #ECECEC; }' if not dark else '')


class NoWheelComboBox(QComboBox):
    """Wheel moves surrounding scroll area, never changes the selected option."""
    def wheelEvent(self, event):
        event.ignore()

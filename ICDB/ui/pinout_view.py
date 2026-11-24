"""Zoomable pinout viewer: native vector SVG plus raster reference photos."""
import re
from PySide6.QtCore import Qt, QByteArray
from PySide6.QtGui import QPixmap, QPainter, QColor
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtSvgWidgets import QGraphicsSvgItem
from PySide6.QtWidgets import QGraphicsView, QGraphicsScene, QGraphicsPixmapItem
from ui.common import display_image


def _inverted_svg(svg_bytes):
    """Invert generated SVG attribute colours without changing the saved drawing."""
    def swap(match):
        rgb = match.group(2)
        inverted = b'#' + b''.join(f'{255-int(rgb[i:i+2], 16):02x}'.encode('ascii') for i in (1, 3, 5))
        return match.group(1) + inverted + match.group(3)
    return re.sub(rb"((?:fill|stroke)=[\"'])(#[0-9a-fA-F]{6})([\"'])", swap, svg_bytes)


class PinoutView(QGraphicsView):
    """Wheel zoom, drag to pan, and double-click to fit; vectors remain vectors."""
    def __init__(self):
        super().__init__()
        self.dark = False
        self.invert = True
        self.original_image = None
        self.original_svg = None
        self._renderer = None
        self._item = None
        self.setScene(QGraphicsScene(self))
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.TextAntialiasing |
                            QPainter.RenderHint.SmoothPixmapTransform)
        self.manual_zoom = False
        self.setMinimumHeight(200)
        self._show_item()

    def set_theme(self, dark, invert=True):
        self.dark = bool(dark)
        self.invert = bool(invert)
        self._show_item()

    def _show_item(self):
        previous_renderer = self._renderer
        self.scene().clear()
        self._item = None
        self._renderer = None
        if previous_renderer is not None:
            previous_renderer.deleteLater()
        self.setBackgroundBrush(QColor('#25282E' if self.dark else '#FFFFFF'))
        if self.original_svg is not None:
            svg = _inverted_svg(self.original_svg) if self.dark and self.invert else self.original_svg
            renderer = QSvgRenderer(QByteArray(svg), self)
            if not renderer.isValid():
                renderer.deleteLater()
                raise ValueError('Invalid pinout SVG')
            item = QGraphicsSvgItem()
            item.setSharedRenderer(renderer)
            # Avoid a fixed-size raster cache when zooming the vector item.
            item.setCacheMode(QGraphicsSvgItem.CacheMode.NoCache)
            self.scene().addItem(item)
            self._renderer = renderer
            self._item = item
            if self.dark and self.invert:
                self.setBackgroundBrush(QColor('#000000'))
            else:
                self.setBackgroundBrush(QColor('#FFFFFF'))
        elif self.original_image is not None:
            image = display_image(self.original_image, self.dark and self.invert)
            if image is not None and not image.isNull():
                item = QGraphicsPixmapItem(QPixmap.fromImage(image))
                self.scene().addItem(item)
                self._item = item
                self.setBackgroundBrush(QColor(image.pixelColor(0, 0)))
        if self._item is not None:
            self.scene().setSceneRect(self._item.boundingRect())
        else:
            self.scene().setSceneRect(0, 0, 0, 0)

    def set_svg(self, svg_bytes):
        """Display generated SVG directly, without the QImage conversion."""
        self.original_svg = bytes(svg_bytes) if svg_bytes is not None else None
        self.original_image = None
        self._show_item()
        self.manual_zoom = False
        self.fit()

    def set_image(self, image=None):
        """Keep raster support for imported reference images."""
        self.original_image = image
        self.original_svg = None
        self._show_item()
        self.manual_zoom = False
        self.fit()

    def fit(self):
        if self._item is not None and not self._item.boundingRect().isEmpty():
            self.fitInView(self._item, Qt.AspectRatioMode.KeepAspectRatio)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if not self.manual_zoom:
            self.fit()

    def wheelEvent(self, event):
        if self._item is None or not event.angleDelta().y():
            event.ignore()
            return
        factor = 1.2 if event.angleDelta().y() > 0 else 1 / 1.2
        self.scale(factor, factor)
        self.manual_zoom = True
        event.accept()

    def mouseDoubleClickEvent(self, event):
        self.manual_zoom = False
        self.fit()
        event.accept()

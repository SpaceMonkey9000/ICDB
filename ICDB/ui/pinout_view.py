"""Zoomable, pannable pinout diagram view."""
from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap, QPainter, QColor
from PySide6.QtWidgets import (
    QGraphicsView, QGraphicsScene, QGraphicsPixmapItem,
)
from ui.common import display_image


class PinoutView(QGraphicsView):
    """Mouse wheel zoom, left/middle drag, double click fit."""
    def __init__(self):
        super().__init__()
        self.dark = False
        self.invert = True
        self.original_image = None
        self.setScene(QGraphicsScene(self))
        self.pix = QGraphicsPixmapItem()
        self.scene().addItem(self.pix)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setBackgroundBrush(Qt.GlobalColor.white)
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        self.manual_zoom = False
        self.setMinimumHeight(200)

    def set_theme(self, dark, invert=True):
        self.dark = bool(dark)
        self.invert = bool(invert)
        self._update_pixmap()

    def _update_pixmap(self):
        image = display_image(self.original_image, self.dark and self.invert)
        self.pix.setPixmap(QPixmap.fromImage(image) if image is not None else QPixmap())
        # The surrounding canvas uses the background colour of the actual rendered image.
        # SVGs are initially rendered on a white background; dark inversion makes it black.
        if image is not None and not image.isNull():
            self.setBackgroundBrush(QColor(image.pixelColor(0, 0)))
        else:
            self.setBackgroundBrush(QColor('#25282E' if self.dark else '#FFFFFF'))

    def set_image(self, image=None):
        # Implicitly shared: later caller modifications detach, so no deep copy is needed.
        self.original_image = image
        self._update_pixmap()
        self.scene().setSceneRect(self.pix.boundingRect())
        self.manual_zoom = False
        self.fit()

    def fit(self):
        if self.pix.pixmap().isNull():
            return
        self.fitInView(self.pix, Qt.AspectRatioMode.KeepAspectRatio)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if not self.manual_zoom:
            self.fit()

    def wheelEvent(self, event):
        if self.pix.pixmap().isNull():
            return
        factor = 1.2 if event.angleDelta().y() > 0 else 1 / 1.2
        self.scale(factor, factor)
        self.manual_zoom = True
        event.accept()

    def mouseDoubleClickEvent(self, event):
        self.manual_zoom = False
        self.fit()
        event.accept()

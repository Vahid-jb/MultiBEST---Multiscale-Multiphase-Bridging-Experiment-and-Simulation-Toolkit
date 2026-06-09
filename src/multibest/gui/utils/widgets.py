# SPDX-FileCopyrightText: 2026 bright-ideas-clan
#
# SPDX-License-Identifier: GPL-3.0-or-later

from PySide6.QtCore import Qt
from PySide6.QtGui import QPainter, QPixmap
from PySide6.QtWidgets import QGraphicsScene, QGraphicsView


class ImageViewer(QGraphicsView):
    def __init__(self):
        super().__init__()

        self.scene = QGraphicsScene(self)
        self.setScene(self.scene)

        self.pixmap_item = None
        self.zoom_factor = 1.25

        # enable drag-to-pan
        self.setDragMode(QGraphicsView.ScrollHandDrag)

        # correct render hints
        self.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)

    def set_image(self, path):
        pix = QPixmap(path)
        if pix.isNull():
            print("Failed to load image")
            return

        self.scene.clear()
        self.pixmap_item = self.scene.addPixmap(pix)

        self.setSceneRect(self.pixmap_item.boundingRect())
        self.resetTransform()

        # optional: fit to window initially
        self.fitInView(self.pixmap_item, Qt.KeepAspectRatio)

    def wheelEvent(self, event):
        if not self.pixmap_item:
            return

        if event.angleDelta().y() > 0:
            factor = self.zoom_factor
        else:
            factor = 1 / self.zoom_factor

        self.scale(factor, factor)

    def clear(self) -> None:
        """Clears the current image from the viewer."""
        self.scene.clear()
        self.pixmap_item = None
        self.resetTransform()

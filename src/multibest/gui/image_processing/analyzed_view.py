# SPDX-FileCopyrightText: 2026 bright-ideas-clan
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Read-only analyzed-image viewer widget.

Displays a BGR overlay ndarray (contours + labels) from analysis.render_overlay()
inside a QGraphicsView with pan and zoom.
"""

from __future__ import annotations

import numpy as np
import qtawesome as qta
from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QImage, QPixmap, QWheelEvent
from PySide6.QtWidgets import (
    QGraphicsPixmapItem,
    QGraphicsScene,
    QGraphicsView,
    QHBoxLayout,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

_ICON_COLOR = "#cccccc"


class _ZoomableView(QGraphicsView):
    """QGraphicsView that forwards wheel events to the parent widget's zoom methods."""

    def __init__(self, scene, owner: AnalyzedViewWidget) -> None:
        super().__init__(scene)
        self._owner = owner

    def wheelEvent(self, event: QWheelEvent) -> None:
        if event.angleDelta().y() > 0:
            self._owner.zoom_in()
        else:
            self._owner.zoom_out()
        event.accept()


class AnalyzedViewWidget(QWidget):
    """Read-only viewer for the analysis overlay image."""

    _ZOOM_STEP = 1.25
    _ZOOM_MIN = 0.05
    _ZOOM_MAX = 16.0

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._overlay: np.ndarray | None = None
        self._zoom_level: float = 1.0

        self._scene = QGraphicsScene(self)
        self._view = _ZoomableView(self._scene, self)
        self._view.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self._view.setBackgroundBrush(Qt.GlobalColor.black)

        self._pixmap_item = QGraphicsPixmapItem()
        self._scene.addItem(self._pixmap_item)

        # Zoom toolbar at the top
        zoom_bar = QWidget()
        zoom_bar.setObjectName("zoomBar")
        zoom_bar.setFixedHeight(36)
        bar_h = QHBoxLayout(zoom_bar)
        bar_h.setContentsMargins(8, 0, 8, 0)
        bar_h.setSpacing(3)

        for icon_name, slot, tooltip in [
            ("fa5s.search-minus", self.zoom_out, "Zoom out  (scroll down)"),
            ("fa5s.compress", self.zoom_fit, "Fit image to view"),
            ("fa5s.search-plus", self.zoom_in, "Zoom in  (scroll up)"),
        ]:
            btn = QPushButton()
            btn.setIcon(qta.icon(icon_name, color=_ICON_COLOR))
            btn.setIconSize(QSize(14, 14))
            btn.setFixedSize(28, 28)
            btn.setToolTip(tooltip)
            btn.clicked.connect(slot)
            bar_h.addWidget(btn)

        bar_h.addStretch()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(zoom_bar)
        layout.addWidget(self._view)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load_overlay(self, bgr: np.ndarray) -> None:
        """Display a BGR uint8 ndarray (from analysis.render_overlay)."""
        self._overlay = bgr
        rgb = bgr[..., ::-1].copy()
        h, w = rgb.shape[:2]
        qimg = QImage(rgb.data, w, h, w * 3, QImage.Format.Format_RGB888)
        self._pixmap_item.setPixmap(QPixmap.fromImage(qimg))
        self._scene.setSceneRect(0, 0, w, h)
        self._zoom_level = 1.0
        self._view.resetTransform()
        QTimer.singleShot(0, self.zoom_fit)

    def zoom_in(self) -> None:
        if self._zoom_level * self._ZOOM_STEP <= self._ZOOM_MAX:
            self._zoom_level *= self._ZOOM_STEP
            self._view.scale(self._ZOOM_STEP, self._ZOOM_STEP)

    def zoom_out(self) -> None:
        if self._zoom_level / self._ZOOM_STEP >= self._ZOOM_MIN:
            self._zoom_level /= self._ZOOM_STEP
            self._view.scale(1 / self._ZOOM_STEP, 1 / self._ZOOM_STEP)

    def zoom_fit(self) -> None:
        if self._overlay is None:
            return
        self._view.fitInView(self._pixmap_item, Qt.AspectRatioMode.KeepAspectRatio)
        self._zoom_level = 1.0

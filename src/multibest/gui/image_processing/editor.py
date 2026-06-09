# SPDX-FileCopyrightText: 2026 bright-ideas-clan
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""ImageEditorWidget — interactive canvas for the Image Processing module.

Provides a QGraphicsView canvas with tool support, undo/redo, live-preview
adjustments (threshold, blur, contrast), and zoom/pan navigation.
"""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import QEvent, QObject, QPoint, QRect, Qt, Signal
from PySide6.QtGui import QImage, QPixmap, QTransform
from PySide6.QtWidgets import (
    QGraphicsPixmapItem,
    QGraphicsScene,
    QGraphicsView,
    QLabel,
    QRubberBand,
    QVBoxLayout,
    QWidget,
)

from multibest.gui.utils.theme import QLEMENTINE_DARK, apply_preview_placeholder
from multibest.image_processing import ops
from multibest.image_processing.history import HistoryStack
from multibest.image_processing.tools.drawing import EraserTool, PenTool
from multibest.image_processing.tools.fill import FillTool
from multibest.image_processing.tools.selection import CropTool, CutTool

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _array_to_qimage(image: np.ndarray) -> QImage:
    """Convert a uint8 NumPy array to a QImage (data is copied)."""
    img = np.ascontiguousarray(image)
    if img.ndim == 2:
        h, w = img.shape
        qi = QImage(img.data, w, h, w, QImage.Format.Format_Grayscale8)
    elif img.ndim == 3 and img.shape[2] == 3:
        h, w, _ = img.shape
        qi = QImage(img.data, w, h, 3 * w, QImage.Format.Format_RGB888)
    elif img.ndim == 3 and img.shape[2] == 4:
        h, w, _ = img.shape
        qi = QImage(img.data, w, h, 4 * w, QImage.Format.Format_RGBA8888)
    else:
        raise ValueError(f"Unsupported image shape: {img.shape}")
    return qi.copy()  # detach from Python memory


# ---------------------------------------------------------------------------
# Event filter for mouse interaction
# ---------------------------------------------------------------------------


class _CanvasEventFilter(QObject):
    """Routes viewport mouse events to the active tool."""

    def __init__(self, editor: ImageEditorWidget) -> None:
        super().__init__()
        self._editor = editor

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        et = event.type()
        relevant = (
            QEvent.Type.MouseButtonPress,
            QEvent.Type.MouseMove,
            QEvent.Type.MouseButtonRelease,
        )
        if et not in relevant:
            return False

        tool = self._editor._active_tool
        tool_name = self._editor._active_tool_name

        # Pan is handled natively by QGraphicsView.ScrollHandDrag
        if tool is None or tool_name == "pan":
            return False

        # Map viewport → scene → pixmap-item (image) coordinates
        view_pos: QPoint = event.position().toPoint()
        scene_pos = self._editor._view.mapToScene(view_pos)
        item_pos = self._editor._pixmap_item.mapFromScene(scene_pos)
        x, y = int(item_pos.x()), int(item_pos.y())

        lmb = Qt.MouseButton.LeftButton
        if et == QEvent.Type.MouseButtonPress and event.button() == lmb:
            tool.on_press(x, y)
            return True
        if et == QEvent.Type.MouseMove:
            self._editor.cursor_moved.emit(x, y)
            if event.buttons() & lmb:
                tool.on_move(x, y)
                return True
        if et == QEvent.Type.MouseButtonRelease and event.button() == lmb:
            tool.on_release(x, y)
            return True

        return False


# ---------------------------------------------------------------------------
# Main widget
# ---------------------------------------------------------------------------


class ImageEditorWidget(QWidget):
    """Canvas-based image editor — the ``viz_widget`` of ImageProcessingWindow.

    Signals
    -------
    tool_changed(str):
        Emitted when the active tool name changes.
    image_committed():
        Emitted after every history commit (draw, fill, undo, redo, reset).
    cursor_moved(int, int):
        Emitted on mouse move; carries image pixel (x, y).
    zoom_changed(float):
        Emitted after zoom changes; carries the new scale factor.
    """

    tool_changed = Signal(str)
    image_committed = Signal()
    cursor_moved = Signal(int, int)
    zoom_changed = Signal(float)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        self._history = HistoryStack()
        self._adjustment_base: np.ndarray | None = None
        self._adjustment_preview: np.ndarray | None = None
        self._zoom = 1.0
        self._active_tool_name: str | None = None
        self._active_tool = None

        self._setup_canvas()
        self._setup_tools()
        self._setup_rubber_band()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _setup_canvas(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._scene = QGraphicsScene(self)
        self._view = QGraphicsView(self._scene)
        self._view.setDragMode(QGraphicsView.DragMode.NoDrag)
        self._view.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._view.setStyleSheet(f"background: {QLEMENTINE_DARK['background_workspace']}; border: none;")
        self._view.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)

        self._pixmap_item = QGraphicsPixmapItem()
        self._pixmap_item.setTransformationMode(Qt.TransformationMode.FastTransformation)
        self._scene.addItem(self._pixmap_item)

        self._event_filter = _CanvasEventFilter(self)
        self._view.viewport().installEventFilter(self._event_filter)

        layout.addWidget(self._view)

        self._placeholder = QLabel("Import an image to start", self)
        self._placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        apply_preview_placeholder(self._placeholder)
        self._placeholder.raise_()

    def _setup_tools(self) -> None:
        self._pen_tool = PenTool(self)
        self._eraser_tool = EraserTool(self)
        self._fill_tool = FillTool(self)
        self._crop_tool = CropTool(self, self._on_selection_changed)
        self._cut_tool = CutTool(self, on_selection=self._on_selection_changed)
        self._tool_map = {
            "pen": self._pen_tool,
            "eraser": self._eraser_tool,
            "fill": self._fill_tool,
            "crop": self._crop_tool,
            "cut": self._cut_tool,
        }

    def _setup_rubber_band(self) -> None:
        self._rubber_band = QRubberBand(QRubberBand.Shape.Rectangle, self._view.viewport())
        self._rubber_band.hide()

    # ------------------------------------------------------------------
    # EditorInterface — used by tools
    # ------------------------------------------------------------------

    def get_image(self) -> np.ndarray:
        """Return a copy of the current committed image."""
        current = self._history.current()
        if current is None:
            return np.zeros((1, 1, 3), dtype=np.uint8)
        return current.copy()

    def get_original_image(self) -> np.ndarray | None:
        """Return the original (first-loaded) image."""
        return self._history.original()

    def commit(self, image: np.ndarray) -> None:
        """Push *image* to history and refresh the canvas."""
        self._history.push(image)
        self._adjustment_base = None
        self._adjustment_preview = None
        self._refresh_canvas(self._history.current())
        self.image_committed.emit()

    def set_preview(self, image: np.ndarray) -> None:
        """Show *image* without pushing to history (live preview)."""
        self._refresh_canvas(image)

    def cancel_preview(self) -> None:
        """Restore the last committed image."""
        current = self._history.current()
        if current is not None:
            self._refresh_canvas(current)

    # ------------------------------------------------------------------
    # Load / save
    # ------------------------------------------------------------------

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._placeholder.setGeometry(self.rect())

    def load_image(self, image: np.ndarray) -> None:
        """Load a new image, resetting history."""
        self._history = HistoryStack()
        self._history.push(image)
        self._adjustment_base = None
        self._adjustment_preview = None
        self._zoom = 1.0
        self._view.setTransform(QTransform())
        self._refresh_canvas(self._history.current())
        self._fit_in_view()
        self._placeholder.hide()
        self.image_committed.emit()

    def unload_image(self) -> None:
        """Remove the current image and return to the empty state."""
        self._history = HistoryStack()
        self._adjustment_base = None
        self._adjustment_preview = None
        self._zoom = 1.0
        self._view.setTransform(QTransform())
        self._pixmap_item.setPixmap(QPixmap())
        self._scene.setSceneRect(self._pixmap_item.boundingRect())
        self._placeholder.show()

    def current_image(self) -> np.ndarray | None:
        """Return the current committed image, or None if no image is loaded."""
        return self._history.current()

    def has_image(self) -> bool:
        return self._history.current() is not None

    # ------------------------------------------------------------------
    # Tool management
    # ------------------------------------------------------------------

    def set_tool(self, name: str) -> None:
        """Activate the named tool.

        Recognised names: 'pen', 'eraser', 'fill', 'crop', 'cut', 'pan'.
        """
        if self._active_tool is not None:
            self._active_tool.deactivate()

        self._rubber_band.hide()
        self._active_tool_name = name
        self._active_tool = self._tool_map.get(name)

        if name == "pan":
            self._view.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        else:
            self._view.setDragMode(QGraphicsView.DragMode.NoDrag)

        if self._active_tool is not None:
            self._active_tool.activate()

        self.tool_changed.emit(name)
        self._update_status()

    def active_tool_name(self) -> str | None:
        return self._active_tool_name

    def get_crop_tool(self) -> CropTool:
        return self._crop_tool

    def get_cut_tool(self) -> CutTool:
        return self._cut_tool

    # ------------------------------------------------------------------
    # Adjustment preview (threshold / blur / contrast)
    # ------------------------------------------------------------------

    def preview_threshold(self, value: int) -> None:
        """Show threshold preview without committing."""
        self._ensure_adjustment_base()
        if self._adjustment_base is not None:
            self._adjustment_preview = ops.threshold(self._adjustment_base, value)
            self._refresh_canvas(self._adjustment_preview)

    def preview_blur(self, sigma: float) -> None:
        """Show Gaussian blur preview without committing."""
        self._ensure_adjustment_base()
        if self._adjustment_base is not None:
            self._adjustment_preview = ops.gaussian_blur(self._adjustment_base, sigma)
            self._refresh_canvas(self._adjustment_preview)

    def preview_contrast(self, factor: float) -> None:
        """Show contrast adjustment preview without committing."""
        self._ensure_adjustment_base()
        if self._adjustment_base is not None:
            self._adjustment_preview = ops.contrast(self._adjustment_base, factor)
            self._refresh_canvas(self._adjustment_preview)

    def commit_adjustment(self) -> None:
        """Commit the current adjustment preview to history."""
        if self._adjustment_preview is not None:
            self.commit(self._adjustment_preview)
        else:
            self._adjustment_base = None

    def cancel_adjustment(self) -> None:
        """Cancel adjustment preview and restore the last committed image."""
        self._adjustment_base = None
        self._adjustment_preview = None
        current = self._history.current()
        if current is not None:
            self._refresh_canvas(current)

    # ------------------------------------------------------------------
    # History operations
    # ------------------------------------------------------------------

    def undo(self) -> None:
        if not self._history.can_undo:
            return
        self._history.undo()
        self._adjustment_base = None
        self._adjustment_preview = None
        self._refresh_canvas(self._history.current())
        self.image_committed.emit()

    def redo(self) -> None:
        if not self._history.can_redo:
            return
        self._history.redo()
        self._adjustment_base = None
        self._adjustment_preview = None
        self._refresh_canvas(self._history.current())
        self.image_committed.emit()

    def reset(self) -> None:
        if not self.has_image():
            return
        self._history.reset()
        self._adjustment_base = None
        self._adjustment_preview = None
        self._refresh_canvas(self._history.current())
        self.image_committed.emit()

    # ------------------------------------------------------------------
    # Zoom
    # ------------------------------------------------------------------

    def zoom_in(self) -> None:
        self._zoom = min(self._zoom * 1.25, 8.0)
        self._apply_zoom()

    def zoom_out(self) -> None:
        self._zoom = max(self._zoom / 1.25, 0.1)
        self._apply_zoom()

    def zoom_fit(self) -> None:
        """Fit the current image in the view."""
        self._fit_in_view()

    def zoom_level(self) -> float:
        return self._zoom

    # ------------------------------------------------------------------
    # Tool property setters (wired from control panel)
    # ------------------------------------------------------------------

    def set_pen_color(self, color: tuple) -> None:
        self._pen_tool.color = color

    def set_pen_width(self, width: int) -> None:
        self._pen_tool.width = width

    def set_eraser_width(self, width: int) -> None:
        self._eraser_tool.width = width

    def set_fill_color(self, color: tuple) -> None:
        self._fill_tool.color = color

    def set_fill_tolerance(self, tolerance: int) -> None:
        self._fill_tool.tolerance = tolerance

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _ensure_adjustment_base(self) -> None:
        if self._adjustment_base is None:
            current = self._history.current()
            if current is not None:
                self._adjustment_base = current.copy()

    def _refresh_canvas(self, image: np.ndarray | None) -> None:
        if image is None:
            return
        qi = _array_to_qimage(image)
        px = QPixmap.fromImage(qi)
        self._pixmap_item.setPixmap(px)
        self._scene.setSceneRect(self._pixmap_item.boundingRect())
        self._update_status()

    def _fit_in_view(self) -> None:
        if self._pixmap_item.pixmap().isNull():
            return
        self._view.fitInView(self._pixmap_item, Qt.AspectRatioMode.KeepAspectRatio)
        # Record the new zoom so it stays consistent
        transform = self._view.transform()
        self._zoom = transform.m11()
        self.zoom_changed.emit(self._zoom)

    def _apply_zoom(self) -> None:
        self._view.setTransform(QTransform().scale(self._zoom, self._zoom))
        self.zoom_changed.emit(self._zoom)
        self._update_status()

    def _update_status(self) -> None:
        """Hook for subclasses or future status-bar integration; intentionally empty."""

    def _on_selection_changed(self, selection: tuple | None) -> None:
        """Update the rubber band overlay when a selection tool reports changes."""
        if selection is None:
            self._rubber_band.hide()
            return
        x1, y1, x2, y2 = selection
        tl = self._view.mapFromScene(self._pixmap_item.mapToScene(x1, y1))
        br = self._view.mapFromScene(self._pixmap_item.mapToScene(x2, y2))
        rect = QRect(tl, br).normalized()
        self._rubber_band.setGeometry(rect)
        self._rubber_band.show()

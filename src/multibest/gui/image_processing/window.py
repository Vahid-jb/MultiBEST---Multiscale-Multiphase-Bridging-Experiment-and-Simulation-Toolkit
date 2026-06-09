# SPDX-FileCopyrightText: 2026 bright-ideas-clan
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Image Processing GUI module.

Provides a fully integrated in-process image editor powered by
OpenCV and Pillow — no external application required.
"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import qtawesome as qta
from PySide6.QtCore import QPoint, QRect, QSize, Qt
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLayout,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QSpinBox,
    QSplitter,
    QStackedWidget,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from multibest.gui.image_processing.analyzed_view import AnalyzedViewWidget
from multibest.gui.image_processing.editor import ImageEditorWidget
from multibest.gui.utils.base_window import BaseModuleWindow
from multibest.gui.utils.theme import QLEMENTINE_DARK, apply_module_title, make_action_button, make_primary_button
from multibest.image_processing import analysis
from multibest.image_processing import replica as _replica_mod

# ---------------------------------------------------------------------------
# Tool panel pages (shown inside the tool stacked widget based on active tool)
# ---------------------------------------------------------------------------

_TOOL_PAGES = {
    "pen": 1,
    "eraser": 2,
    "fill": 3,
    "crop": 4,
    "cut": 4,  # crop and cut share the Apply/Cancel page
    "pan": 0,
}

_ADJUSTMENT_PAGES = {
    "threshold": 1,
    "blur": 2,
    "contrast": 3,
}

_DARK_ICON = "#cccccc"
_DARK_ICON_DISABLED = "#3a3a3a"


def _make_vsep() -> QFrame:
    sep = QFrame()
    sep.setFrameShape(QFrame.Shape.VLine)
    sep.setFixedWidth(1)
    sep.setStyleSheet(f"background: {QLEMENTINE_DARK['border']}; border: none;")
    return sep


class _FlowLayout(QLayout):
    """Row layout that wraps items to the next row when the row is full."""

    def __init__(self, parent: QWidget | None = None, h_spacing: int = 3, v_spacing: int = 2) -> None:
        super().__init__(parent)
        self._items: list = []
        self._h_spacing = h_spacing
        self._v_spacing = v_spacing

    def addItem(self, item) -> None:  # type: ignore[override]
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int):
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index: int):
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        return self._arrange(QRect(0, 0, width, 0), apply=False)

    def setGeometry(self, rect: QRect) -> None:
        super().setGeometry(rect)
        self._arrange(rect, apply=True)

    def sizeHint(self) -> QSize:
        return self.minimumSize()

    def minimumSize(self) -> QSize:
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        m = self.contentsMargins()
        return size + QSize(m.left() + m.right(), m.top() + m.bottom())

    def _arrange(self, rect: QRect, *, apply: bool) -> int:
        m = self.contentsMargins()
        r = rect.adjusted(m.left(), m.top(), -m.right(), -m.bottom())
        x, y, row_h = r.x(), r.y(), 0
        for item in self._items:
            w = item.widget()
            if w is not None and not w.isVisible():
                continue
            sh = item.sizeHint()
            next_x = x + sh.width() + self._h_spacing
            if row_h and next_x - self._h_spacing > r.right():
                x = r.x()
                y += row_h + self._v_spacing
                next_x = x + sh.width() + self._h_spacing
                row_h = 0
            if apply:
                item.setGeometry(QRect(QPoint(x, y), sh))
            x = next_x
            row_h = max(row_h, sh.height())
        return y + row_h - r.y() + m.top() + m.bottom()


class _ToolBar(QWidget):
    """Toolbar that self-adjusts its fixed height when its width changes."""

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        fl = self.layout()
        if fl is not None:
            h = max(fl.heightForWidth(event.size().width()), 36)
            if self.height() != h:
                self.setFixedHeight(h)


class ImageProcessingWindow(BaseModuleWindow):
    """Image Processing module — integrated canvas editor."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Image Processing")

        self._current_file: Path | None = None
        self._pen_color = (0, 0, 0)
        self._fill_color = (0, 0, 0)
        self._cached_report: str | None = None
        self._cached_overlay: np.ndarray | None = None

        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        main_layout = QHBoxLayout(main_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)

        # ── Right panel (editor canvas) — created first so controls can wire to it ──
        self._editor = ImageEditorWidget()

        # ── Left panel (controls) ─────────────────────────────────────
        self.left_scroll = QScrollArea()
        self.left_scroll.setWidgetResizable(True)
        self.left_scroll.setFrameShape(QFrame.Shape.NoFrame)

        left_content = QWidget()
        left_layout = QVBoxLayout(left_content)
        left_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        left_layout.setContentsMargins(18, 18, 18, 18)
        left_layout.setSpacing(14)
        self.left_scroll.setWidget(left_content)

        self._splitter = QSplitter(Qt.Orientation.Horizontal)
        self._splitter.addWidget(self.left_scroll)

        header = QLabel("Image Processing")
        apply_module_title(header)
        left_layout.addWidget(header)

        # I/O
        self._build_io_group(left_layout)

        # Analysis
        self._build_analysis_group(left_layout)

        # Replicas
        self._build_replica_group(left_layout)

        left_layout.addStretch()

        # Clear button — pinned at the bottom of the left panel
        self._build_clear_button(left_layout)

        # ── Right panel: tabbed view (Edit / Analyzed) ────────────────
        self._analyzed_view = AnalyzedViewWidget()
        self._viz_tabs = QTabWidget()

        # Edit tab: tool toolbar → settings panel → canvas
        edit_container = QWidget()
        edit_vbox = QVBoxLayout(edit_container)
        edit_vbox.setContentsMargins(0, 0, 0, 0)
        edit_vbox.setSpacing(0)

        self._tool_toolbar = self._build_tool_toolbar()
        edit_vbox.addWidget(self._tool_toolbar)

        self._tool_settings_stack = self._build_tool_settings_widget()
        self._tool_settings_stack.setVisible(False)
        self._tool_settings_stack.setMaximumHeight(80)
        edit_vbox.addWidget(self._tool_settings_stack)

        self._adjustment_settings_stack = self._build_adjustment_settings_widget()
        self._adjustment_settings_stack.setVisible(False)
        self._adjustment_settings_stack.setMaximumHeight(80)
        edit_vbox.addWidget(self._adjustment_settings_stack)

        edit_vbox.addWidget(self._editor)

        self._viz_tabs.addTab(edit_container, "Edit")
        self._viz_tabs.addTab(self._analyzed_view, "Analyzed")
        self._viz_tabs.tabBar().setTabVisible(1, False)
        self._splitter.addWidget(self._viz_tabs)
        self._splitter.setStretchFactor(0, 1)
        self._splitter.setStretchFactor(1, 3)
        for widget in (self.left_scroll, self._viz_tabs):
            sp = widget.sizePolicy()
            sp.setHorizontalPolicy(QSizePolicy.Policy.Ignored)
            widget.setSizePolicy(sp)
            widget.setMinimumWidth(0)
        main_layout.addWidget(self._splitter)

        # ── Wire everything ───────────────────────────────────────────
        self._editor.tool_changed.connect(self._on_tool_changed)
        self._editor.image_committed.connect(self._on_image_committed)

        # ── Required by BaseModuleWindow ──────────────────────────────
        self.control_widget = self.left_scroll
        self.viz_widget = self._viz_tabs

        self._calc_btns = []
        self._stop_btns = []
        self._set_image_dependent_enabled(False)

    # ------------------------------------------------------------------
    # UI builders
    # ------------------------------------------------------------------

    def _build_clear_button(self, parent_layout: QVBoxLayout) -> None:
        self.clear_btn = make_action_button("Delete Image", "delete")
        self.clear_btn.setIcon(qta.icon("fa5s.trash-alt", color="#ffffff", color_disabled="#6a3030"))
        self.clear_btn.setIconSize(QSize(14, 14))
        self.clear_btn.setStyleSheet(f"""
QPushButton {{
    background: {QLEMENTINE_DARK["error"]};
    color: {QLEMENTINE_DARK["status_foreground"]};
    border: none;
    border-radius: 6px;
    padding: 6px 12px;
    font-weight: bold;
}}
QPushButton:hover    {{ background: #f47c83; }}
QPushButton:pressed  {{ background: #cf5f66; }}
QPushButton:disabled {{
    background: {QLEMENTINE_DARK["neutral_disabled"]};
    color: {QLEMENTINE_DARK["secondary_disabled"]};
}}
""")
        self.clear_btn.clicked.connect(self._clear_canvas)
        parent_layout.addWidget(self.clear_btn)

    def _clear_canvas(self) -> None:
        self._editor.unload_image()
        self._current_file = None
        self._cached_report = None
        self._cached_overlay = None
        self.save_btn.setEnabled(False)
        self._save_report_btn.setVisible(False)
        self._save_analyzed_btn.setVisible(False)
        self._viz_tabs.tabBar().setTabVisible(1, False)
        self._viz_tabs.setCurrentIndex(0)
        self._set_image_dependent_enabled(False)

    def _build_io_group(self, parent_layout: QVBoxLayout) -> None:
        # Hidden QLineEdit — used by _load_image and tests; not shown in UI
        self.input_path = QLineEdit()

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        self.open_btn = make_primary_button("Import Image")
        self.save_btn = make_primary_button("Export Image")
        self.save_btn.setEnabled(False)
        self.open_btn.clicked.connect(self._open_image)
        self.save_btn.clicked.connect(self._save_result)
        btn_row.addWidget(self.open_btn)
        btn_row.addWidget(self.save_btn)
        parent_layout.addLayout(btn_row)

    def _build_tool_toolbar(self) -> QWidget:
        """Top toolbar: adjustments | tools | history | zoom. Wraps to next row when narrow."""
        bar = _ToolBar()
        bar.setObjectName("toolBar")
        bar_flow = _FlowLayout(bar, h_spacing=3, v_spacing=2)
        bar_flow.setContentsMargins(8, 4, 8, 4)

        # ── Adjustment buttons ────────────────────────────────────────
        adjustments = [
            ("threshold", "fa5s.sliders-h", "Threshold"),
            ("blur", "fa5s.tint", "Blur"),
            ("contrast", "fa5s.adjust", "Contrast"),
        ]
        self._adjustment_btns: dict[str, QPushButton] = {}
        for name, icon_name, tooltip in adjustments:
            btn = QPushButton()
            btn.setIcon(qta.icon(icon_name, color=_DARK_ICON, color_disabled=_DARK_ICON_DISABLED))
            btn.setIconSize(QSize(16, 16))
            btn.setFixedSize(30, 28)
            btn.setCheckable(True)
            btn.setToolTip(tooltip)
            btn.clicked.connect(lambda checked, n=name: self._activate_adjustment(n))
            bar_flow.addWidget(btn)
            self._adjustment_btns[name] = btn

        bar_flow.addWidget(_make_vsep())

        # ── Tool buttons ──────────────────────────────────────────────
        tools = [
            ("pen", "fa5s.pen", "Pen"),
            ("eraser", "fa5s.eraser", "Eraser"),
            ("fill", "fa5s.fill-drip", "Fill"),
            ("crop", "fa5s.crop", "Crop"),
            ("cut", "fa5s.cut", "Cut"),
            ("pan", "fa5s.hand-paper", "Pan"),
        ]
        self._tool_btns: dict[str, QPushButton] = {}
        for name, icon_name, tooltip in tools:
            btn = QPushButton()
            btn.setIcon(qta.icon(icon_name, color=_DARK_ICON, color_disabled=_DARK_ICON_DISABLED))
            btn.setIconSize(QSize(16, 16))
            btn.setFixedSize(30, 28)
            btn.setCheckable(True)
            btn.setToolTip(tooltip)
            btn.clicked.connect(lambda checked, n=name: self._editor.set_tool(n))
            bar_flow.addWidget(btn)
            self._tool_btns[name] = btn

        bar_flow.addWidget(_make_vsep())

        # ── History buttons ───────────────────────────────────────────
        self._history_btns: list[QPushButton] = []
        for icon_name, slot, tooltip in [
            ("fa5s.undo", self._editor.undo, "Undo"),
            ("fa5s.redo", self._editor.redo, "Redo"),
            ("fa5s.sync-alt", self._editor.reset, "Reset to original"),
        ]:
            btn = QPushButton()
            btn.setIcon(qta.icon(icon_name, color=_DARK_ICON, color_disabled=_DARK_ICON_DISABLED))
            btn.setIconSize(QSize(14, 14))
            btn.setFixedSize(28, 28)
            btn.setToolTip(tooltip)
            btn.clicked.connect(slot)
            bar_flow.addWidget(btn)
            self._history_btns.append(btn)

        bar_flow.addWidget(_make_vsep())

        # ── Zoom buttons ──────────────────────────────────────────────
        self._zoom_btns: list[QPushButton] = []
        for icon_name, slot, tooltip in [
            ("fa5s.search-minus", self._editor.zoom_out, "Zoom out"),
            ("fa5s.compress", self._edit_zoom_fit, "Fit to view"),
            ("fa5s.search-plus", self._editor.zoom_in, "Zoom in"),
        ]:
            btn = QPushButton()
            btn.setIcon(qta.icon(icon_name, color=_DARK_ICON, color_disabled=_DARK_ICON_DISABLED))
            btn.setIconSize(QSize(14, 14))
            btn.setFixedSize(28, 28)
            btn.setToolTip(tooltip)
            btn.clicked.connect(slot)
            bar_flow.addWidget(btn)
            self._zoom_btns.append(btn)

        return bar

    def _build_tool_settings_widget(self) -> QStackedWidget:
        """Tool configuration panel placed below the tool toolbar on the canvas."""
        stack = QStackedWidget()
        stack.setObjectName("toolSettingsPanel")

        # Page 0: empty (pan / no tool) — stack hidden when this is active
        stack.addWidget(QWidget())

        # Page 1: Pen
        pen_page = QWidget()
        pen_layout = QFormLayout(pen_page)
        pen_layout.setContentsMargins(8, 4, 8, 4)
        pen_layout.addRow("Color:", self._build_bw_row(self._pen_color, self._set_pen_color))
        self._pen_width_spin = QSpinBox()
        self._pen_width_spin.setRange(1, 50)
        self._pen_width_spin.setValue(3)
        self._pen_width_spin.valueChanged.connect(self._editor.set_pen_width)
        pen_layout.addRow("Width:", self._pen_width_spin)
        pen_cancel = make_action_button("Cancel", "cancel")
        pen_cancel.clicked.connect(self._close_tool_settings)
        pen_layout.addRow(pen_cancel)
        stack.addWidget(pen_page)

        # Page 2: Eraser
        eraser_page = QWidget()
        eraser_layout = QFormLayout(eraser_page)
        eraser_layout.setContentsMargins(8, 4, 8, 4)
        self._eraser_width_spin = QSpinBox()
        self._eraser_width_spin.setRange(1, 50)
        self._eraser_width_spin.setValue(20)
        self._eraser_width_spin.valueChanged.connect(self._editor.set_eraser_width)
        eraser_layout.addRow("Width:", self._eraser_width_spin)
        eraser_cancel = make_action_button("Cancel", "cancel")
        eraser_cancel.clicked.connect(self._close_tool_settings)
        eraser_layout.addRow(eraser_cancel)
        stack.addWidget(eraser_page)

        # Page 3: Fill
        fill_page = QWidget()
        fill_layout = QFormLayout(fill_page)
        fill_layout.setContentsMargins(8, 4, 8, 4)
        fill_layout.addRow("Color:", self._build_bw_row(self._fill_color, self._set_fill_color))
        self._fill_tol_slider = QSlider(Qt.Orientation.Horizontal)
        self._fill_tol_slider.setRange(0, 255)
        self._fill_tol_slider.setValue(32)
        self._fill_tol_slider.valueChanged.connect(self._editor.set_fill_tolerance)
        fill_layout.addRow("Tolerance:", self._fill_tol_slider)
        fill_cancel = make_action_button("Cancel", "cancel")
        fill_cancel.clicked.connect(self._close_tool_settings)
        fill_layout.addRow(fill_cancel)
        stack.addWidget(fill_page)

        # Page 4: Selection (Crop / Cut)
        sel_page = QWidget()
        sel_layout = QVBoxLayout(sel_page)
        sel_layout.setContentsMargins(8, 4, 8, 4)
        sel_layout.addWidget(QLabel("Drag a rectangle on the canvas, then click Apply."))
        sel_btns = QHBoxLayout()
        self._sel_apply_btn = make_action_button("Apply Selection", "apply")
        self._sel_cancel_btn = make_action_button("Cancel", "cancel")
        self._sel_apply_btn.clicked.connect(self._apply_selection)
        self._sel_cancel_btn.clicked.connect(self._cancel_selection)
        sel_btns.addWidget(self._sel_apply_btn)
        sel_btns.addWidget(self._sel_cancel_btn)
        sel_layout.addLayout(sel_btns)
        stack.addWidget(sel_page)

        return stack

    def _build_adjustment_settings_widget(self) -> QStackedWidget:
        """Adjustment configuration panel shown below the unified tool toolbar on the canvas."""
        stack = QStackedWidget()
        stack.setObjectName("toolSettingsPanel")

        # Page 0: empty (no adjustment active) — stack hidden when this is active
        stack.addWidget(QWidget())

        # Page 1: Threshold
        thresh_page = QWidget()
        thresh_layout = QFormLayout(thresh_page)
        thresh_layout.setContentsMargins(8, 4, 8, 4)
        self._thresh_slider = QSlider(Qt.Orientation.Horizontal)
        self._thresh_slider.setRange(0, 255)
        self._thresh_slider.setValue(128)
        self._thresh_slider.valueChanged.connect(self._preview_threshold)
        self._thresh_val_lbl = QLabel("128")
        self._thresh_val_lbl.setMinimumWidth(32)
        self._thresh_slider.valueChanged.connect(lambda v: self._thresh_val_lbl.setText(str(v)))
        thresh_row = QWidget()
        thresh_row_h = QHBoxLayout(thresh_row)
        thresh_row_h.setContentsMargins(0, 0, 0, 0)
        thresh_row_h.addWidget(self._thresh_slider)
        thresh_row_h.addWidget(self._thresh_val_lbl)
        thresh_layout.addRow("Value:", thresh_row)
        thresh_btns = QHBoxLayout()
        thresh_apply = make_action_button("Apply", "apply")
        thresh_cancel = make_action_button("Cancel", "cancel")
        thresh_apply.clicked.connect(self._apply_adjustment)
        thresh_cancel.clicked.connect(self._close_adjustment_settings)
        thresh_btns.addWidget(thresh_apply)
        thresh_btns.addWidget(thresh_cancel)
        thresh_layout.addRow(thresh_btns)
        stack.addWidget(thresh_page)

        # Page 2: Blur
        blur_page = QWidget()
        blur_layout = QFormLayout(blur_page)
        blur_layout.setContentsMargins(8, 4, 8, 4)
        self._blur_slider = QSlider(Qt.Orientation.Horizontal)
        self._blur_slider.setRange(1, 200)  # /10 → 0.1–20.0
        self._blur_slider.setValue(10)
        self._blur_slider.valueChanged.connect(self._preview_blur)
        self._blur_val_lbl = QLabel("1.0")
        self._blur_val_lbl.setMinimumWidth(36)
        self._blur_slider.valueChanged.connect(lambda v: self._blur_val_lbl.setText(f"{v / 10:.1f}"))
        blur_row = QWidget()
        blur_row_h = QHBoxLayout(blur_row)
        blur_row_h.setContentsMargins(0, 0, 0, 0)
        blur_row_h.addWidget(self._blur_slider)
        blur_row_h.addWidget(self._blur_val_lbl)
        blur_layout.addRow("Sigma:", blur_row)
        blur_btns = QHBoxLayout()
        blur_apply = make_action_button("Apply", "apply")
        blur_cancel = make_action_button("Cancel", "cancel")
        blur_apply.clicked.connect(self._apply_adjustment)
        blur_cancel.clicked.connect(self._close_adjustment_settings)
        blur_btns.addWidget(blur_apply)
        blur_btns.addWidget(blur_cancel)
        blur_layout.addRow(blur_btns)
        stack.addWidget(blur_page)

        # Page 3: Contrast
        contrast_page = QWidget()
        contrast_layout = QFormLayout(contrast_page)
        contrast_layout.setContentsMargins(8, 4, 8, 4)
        self._contrast_slider = QSlider(Qt.Orientation.Horizontal)
        self._contrast_slider.setRange(-100, 100)
        self._contrast_slider.setValue(0)
        self._contrast_slider.valueChanged.connect(self._preview_contrast)
        self._contrast_val_lbl = QLabel("0")
        self._contrast_val_lbl.setMinimumWidth(36)
        self._contrast_slider.valueChanged.connect(lambda v: self._contrast_val_lbl.setText(str(v)))
        contrast_row = QWidget()
        contrast_row_h = QHBoxLayout(contrast_row)
        contrast_row_h.setContentsMargins(0, 0, 0, 0)
        contrast_row_h.addWidget(self._contrast_slider)
        contrast_row_h.addWidget(self._contrast_val_lbl)
        contrast_layout.addRow("Factor:", contrast_row)
        contrast_btns = QHBoxLayout()
        contrast_apply = make_action_button("Apply", "apply")
        contrast_cancel = make_action_button("Cancel", "cancel")
        contrast_apply.clicked.connect(self._apply_adjustment)
        contrast_cancel.clicked.connect(self._close_adjustment_settings)
        contrast_btns.addWidget(contrast_apply)
        contrast_btns.addWidget(contrast_cancel)
        contrast_layout.addRow(contrast_btns)
        stack.addWidget(contrast_page)

        return stack

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def _open_image(self) -> None:
        from PySide6.QtWidgets import QFileDialog

        start = self.input_path.text().strip() or str(Path.home())
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Open Image",
            start,
            "Images (*.tif *.tiff *.png *.jpg *.jpeg *.bmp);;All files (*)",
        )
        if path:
            self.input_path.setText(path)
            self._load_image()

    def _load_image(self) -> None:
        path = self.input_path.text().strip()
        if not self._validate_input_file(path):
            return
        try:
            from PIL import Image

            pil_img = Image.open(path)
            image = np.asarray(pil_img.convert("RGB"))
            self._editor.load_image(image)
            self._current_file = Path(path)
            self.save_btn.setEnabled(True)
            self._set_image_dependent_enabled(True)
            self.logger.log_message("INFO", f"Loaded: {path}  shape={image.shape}")
        except Exception as exc:
            self.logger.log_message("ERROR", f"Failed to load image: {exc}")

    def _save_result(self) -> None:
        image = self._editor.current_image()
        if image is None:
            self.logger.log_message("ERROR", "No image to save. Load an image first.")
            return
        from PySide6.QtWidgets import QFileDialog

        stem = self._current_file.stem if self._current_file else "output"
        default = str(Path.home() / "Desktop" / f"multibest_processed_{stem}.png")
        path, _ = QFileDialog.getSaveFileName(self, "Export Image", default, "PNG (*.png)")
        if not path:
            return
        if not path.endswith(".png"):
            path += ".png"
        if image.ndim == 3:
            image = np.dot(image[..., :3], [0.2989, 0.5870, 0.1140]).astype(np.uint8)
        try:
            from PIL import Image as PILImage

            PILImage.fromarray(image).save(path)
            self.logger.log_message("INFO", f"Saved: {path}")
        except Exception as exc:
            self.logger.log_message("ERROR", f"Failed to save: {exc}")

    # ------------------------------------------------------------------
    # Tool / adjustment helpers
    # ------------------------------------------------------------------

    def _edit_zoom_fit(self) -> None:
        self._editor.zoom_fit()

    def _activate_adjustment(self, name: str) -> None:
        """Show an adjustment settings page; cancel any active tool preview."""
        self._editor.cancel_adjustment()
        page = _ADJUSTMENT_PAGES.get(name, 0)
        self._adjustment_settings_stack.setCurrentIndex(page)
        self._adjustment_settings_stack.setVisible(page > 0)
        for adj_name, btn in self._adjustment_btns.items():
            btn.setChecked(adj_name == name)
        for btn in self._tool_btns.values():
            btn.setChecked(False)
        self._tool_settings_stack.setCurrentIndex(0)
        self._tool_settings_stack.setVisible(False)
        if not self._editor.has_image():
            return
        if name == "threshold":
            self._preview_threshold(self._thresh_slider.value())
        elif name == "blur":
            self._preview_blur(self._blur_slider.value())
        elif name == "contrast":
            self._preview_contrast(self._contrast_slider.value())

    def _preview_threshold(self, value: int) -> None:
        if self._editor.has_image():
            self._editor.preview_threshold(value)

    def _preview_blur(self, raw: int) -> None:
        if self._editor.has_image():
            self._editor.preview_blur(raw / 10.0)

    def _preview_contrast(self, value: int) -> None:
        if self._editor.has_image():
            self._editor.preview_contrast(float(value))

    def _apply_adjustment(self) -> None:
        self._editor.commit_adjustment()
        self._hide_adjustment_panel()

    def _close_adjustment_settings(self) -> None:
        self._editor.cancel_adjustment()
        self._hide_adjustment_panel()

    def _hide_adjustment_panel(self) -> None:
        self._adjustment_settings_stack.setCurrentIndex(0)
        self._adjustment_settings_stack.setVisible(False)
        for btn in self._adjustment_btns.values():
            btn.setChecked(False)

    def _set_image_dependent_enabled(self, enabled: bool) -> None:
        self._tool_toolbar.setEnabled(enabled)
        self._analysis_group.setEnabled(enabled)
        self._replica_group.setEnabled(enabled)
        self.clear_btn.setEnabled(enabled)
        if enabled:
            self._restore_form_defaults()
        else:
            self._clear_form_values()

    def _clear_form_values(self) -> None:
        self._analysis_thresh_spin.setValue(self._analysis_thresh_spin.minimum())
        self._connectivity_combo.setCurrentIndex(-1)
        self._invert_chk.setChecked(False)
        self._include_white_chk.setChecked(False)
        self._include_black_chk.setChecked(False)
        self._replica_count_spin.setValue(self._replica_count_spin.minimum())
        self._replica_seed_spin.setValue(self._replica_seed_spin.minimum())
        self._replica_min_spin.setValue(self._replica_min_spin.minimum())
        self._replica_max_spin.setValue(self._replica_max_spin.minimum())
        self._replica_sigma_spin.setValue(self._replica_sigma_spin.minimum())
        self._replica_cleanup_spin.setValue(self._replica_cleanup_spin.minimum())

    def _restore_form_defaults(self) -> None:
        self._analysis_thresh_spin.setValue(127)
        self._connectivity_combo.setCurrentIndex(0)
        self._invert_chk.setChecked(False)
        self._include_white_chk.setChecked(True)
        self._include_black_chk.setChecked(True)
        self._replica_count_spin.setValue(5)
        self._replica_seed_spin.setValue(12345)
        self._replica_min_spin.setValue(500)
        self._replica_max_spin.setValue(5000)
        self._replica_sigma_spin.setValue(1.2)
        self._replica_cleanup_spin.setValue(2)

    def _apply_selection(self) -> None:
        tool_name = self._editor.active_tool_name()
        if tool_name == "crop":
            self._editor.get_crop_tool().apply()
        elif tool_name == "cut":
            self._editor.get_cut_tool().apply()
        self._close_tool_settings()

    def _cancel_selection(self) -> None:
        tool_name = self._editor.active_tool_name()
        if tool_name == "crop":
            self._editor.get_crop_tool().cancel()
        elif tool_name == "cut":
            self._editor.get_cut_tool().cancel()
        self._close_tool_settings()

    def _close_tool_settings(self) -> None:
        self._tool_settings_stack.setCurrentIndex(0)
        self._tool_settings_stack.setVisible(False)
        self._editor.set_tool("pan")

    def _build_analysis_group(self, parent_layout: QVBoxLayout) -> None:
        group = QGroupBox("Analysis")
        form = QFormLayout(group)

        self._analysis_thresh_spin = QSpinBox()
        self._analysis_thresh_spin.setRange(-1, 255)
        self._analysis_thresh_spin.setSpecialValueText(" ")
        form.addRow("Threshold:", self._analysis_thresh_spin)

        self._connectivity_combo = QComboBox()
        self._connectivity_combo.setPlaceholderText(" ")
        self._connectivity_combo.addItems(["8-connected", "4-connected"])
        form.addRow("Connectivity:", self._connectivity_combo)

        self._invert_chk = QCheckBox("Invert")
        self._include_white_chk = QCheckBox("Include white")
        self._include_black_chk = QCheckBox("Include black")
        form.addRow(self._invert_chk)
        form.addRow(self._include_white_chk)
        form.addRow(self._include_black_chk)

        self._analyze_btn = make_primary_button("Analyze")
        self._save_report_btn = make_action_button("Save report", "save")
        self._save_analyzed_btn = make_action_button("Save analyzed image", "save")
        self._save_report_btn.setVisible(False)
        self._save_analyzed_btn.setVisible(False)
        self._analyze_btn.clicked.connect(self._run_analysis)
        self._save_report_btn.clicked.connect(self._save_report)
        self._save_analyzed_btn.clicked.connect(self._save_analyzed_image)
        form.addRow(self._analyze_btn)
        form.addRow(self._save_report_btn)
        form.addRow(self._save_analyzed_btn)

        self._analysis_group = group
        parent_layout.addWidget(group)

    def _build_replica_group(self, parent_layout: QVBoxLayout) -> None:
        group = QGroupBox("Replica Generation")
        form = QFormLayout(group)

        self._replica_count_spin = QSpinBox()
        self._replica_count_spin.setRange(0, 100)
        self._replica_count_spin.setSpecialValueText(" ")
        form.addRow("Count:", self._replica_count_spin)

        self._replica_seed_spin = QSpinBox()
        self._replica_seed_spin.setRange(-1, 999999999)
        self._replica_seed_spin.setSpecialValueText(" ")
        form.addRow("Random seed:", self._replica_seed_spin)

        self._replica_min_spin = QSpinBox()
        self._replica_min_spin.setRange(0, 1000000)
        self._replica_min_spin.setSpecialValueText(" ")
        form.addRow("Min black region:", self._replica_min_spin)

        self._replica_max_spin = QSpinBox()
        self._replica_max_spin.setRange(0, 1000000)
        self._replica_max_spin.setSpecialValueText(" ")
        form.addRow("Max black region:", self._replica_max_spin)

        self._replica_sigma_spin = QDoubleSpinBox()
        self._replica_sigma_spin.setRange(-0.1, 10.0)
        self._replica_sigma_spin.setSingleStep(0.1)
        self._replica_sigma_spin.setSpecialValueText(" ")
        form.addRow("Boundary σ:", self._replica_sigma_spin)

        self._replica_cleanup_spin = QSpinBox()
        self._replica_cleanup_spin.setRange(-1, 20)
        self._replica_cleanup_spin.setSpecialValueText(" ")
        form.addRow("Cleanup width:", self._replica_cleanup_spin)

        self._generate_btn = make_primary_button("Generate Replicas")
        self._generate_btn.clicked.connect(self._generate_replicas)
        form.addRow(self._generate_btn)

        self._replica_group = group
        parent_layout.addWidget(group)

    # ------------------------------------------------------------------
    # Analysis actions
    # ------------------------------------------------------------------

    def _run_analysis(self) -> None:
        image = self._editor.current_image()
        if image is None:
            self.logger.log_message("ERROR", "No image loaded. Load an image first.")
            return
        include_white = self._include_white_chk.isChecked()
        include_black = self._include_black_chk.isChecked()
        if not include_white and not include_black:
            self.logger.log_message("ERROR", "At least one of Include white / Include black must be checked.")
            return

        threshold = self._analysis_thresh_spin.value()
        connectivity = 1 if self._connectivity_combo.currentIndex() == 1 else 2
        invert = self._invert_chk.isChecked()

        gray = analysis.to_grayscale(image)
        binary = analysis.to_binary(gray, threshold=threshold, invert=invert)

        if include_white:
            white_rows, white_labels = analysis.label_sections(binary, "white", connectivity)
        else:
            white_rows, white_labels = [], np.zeros_like(gray, dtype=np.int32)

        if include_black:
            black_rows, black_labels = analysis.label_sections(~binary, "black", connectivity)
        else:
            black_rows, black_labels = [], np.zeros_like(gray, dtype=np.int32)

        stem = self._current_file.stem if self._current_file else "canvas"
        report = analysis.build_report_text(
            image_label=stem,
            gray=gray,
            threshold=threshold,
            connectivity=connectivity,
            invert=invert,
            white_rows=white_rows,
            black_rows=black_rows,
            replica_count=self._replica_count_spin.value(),
            min_black_region=self._replica_min_spin.value(),
            max_black_region=self._replica_max_spin.value(),
            boundary_smoothing_sigma=self._replica_sigma_spin.value(),
            boundary_cleanup_width=self._replica_cleanup_spin.value(),
        )
        overlay = analysis.render_overlay(
            gray,
            white_labels,
            black_labels,
            white_rows,
            black_rows,
            draw_white=include_white,
            draw_black=include_black,
        )

        self._cached_report = report
        self._cached_overlay = overlay
        self._analyzed_view.load_overlay(overlay)
        self._viz_tabs.tabBar().setTabVisible(1, True)
        self._viz_tabs.setCurrentIndex(1)
        self._save_report_btn.setVisible(True)
        self._save_analyzed_btn.setVisible(True)
        self.logger.log_message(
            "INFO",
            f"Analysis complete: {len(white_rows)} white sections, {len(black_rows)} black sections.",
        )
        for line in report.splitlines():
            if line.strip():
                self.logger.log_message("REPORT", line)

    def _save_report(self) -> None:
        if self._cached_report is None:
            self.logger.log_message("ERROR", "No analysis report. Run Analyze first.")
            return
        from PySide6.QtWidgets import QFileDialog

        stem = self._current_file.stem if self._current_file else "canvas"
        default = str(Path.home() / "Desktop" / f"multibest_{stem}_analysis.txt")
        path, _ = QFileDialog.getSaveFileName(self, "Save Report", default, "Text files (*.txt)")
        if not path:
            return
        try:
            Path(path).write_text(self._cached_report, encoding="utf-8")
            self.logger.log_message("INFO", f"Report saved: {path}")
        except Exception as exc:
            self.logger.log_message("ERROR", f"Failed to save report: {exc}")

    def _save_analyzed_image(self) -> None:
        if self._cached_overlay is None:
            self.logger.log_message("ERROR", "No analyzed image. Run Analyze first.")
            return
        from PySide6.QtWidgets import QFileDialog

        stem = self._current_file.stem if self._current_file else "canvas"
        default = str(Path.home() / "Desktop" / f"multibest_{stem}_analyzed.png")
        path, _ = QFileDialog.getSaveFileName(self, "Save Analyzed Image", default, "PNG (*.png)")
        if not path:
            return
        try:
            cv2.imwrite(path, self._cached_overlay)
            self.logger.log_message("INFO", f"Analyzed image saved: {path}")
        except Exception as exc:
            self.logger.log_message("ERROR", f"Failed to save analyzed image: {exc}")

    def _generate_replicas(self) -> None:
        image = self._editor.current_image()
        if image is None:
            self.logger.log_message("ERROR", "No image loaded. Load an image first.")
            return
        min_region = self._replica_min_spin.value()
        max_region = self._replica_max_spin.value()
        if min_region > max_region:
            self.logger.log_message("ERROR", "Min black region size cannot exceed max black region size.")
            return
        from PySide6.QtWidgets import QFileDialog

        output_dir = QFileDialog.getExistingDirectory(self, "Select Output Directory", str(Path.home()))
        if not output_dir:
            return

        threshold = self._analysis_thresh_spin.value()
        invert = self._invert_chk.isChecked()
        gray = analysis.to_grayscale(image)
        binary = analysis.to_binary(gray, threshold=threshold, invert=invert)

        count = self._replica_count_spin.value()
        rng = np.random.default_rng(self._replica_seed_spin.value())
        sigma = self._replica_sigma_spin.value()
        cleanup = self._replica_cleanup_spin.value()
        stem = self._current_file.stem if self._current_file else "canvas"

        try:
            from PIL import Image as PILImage

            for i in range(1, count + 1):
                mask = _replica_mod.generate_replica(
                    binary,
                    min_black_region=min_region,
                    max_black_region=max_region,
                    rng=rng,
                    boundary_smoothing_sigma=sigma,
                    boundary_cleanup_width=cleanup,
                )
                out_path = Path(output_dir) / f"multibest_{stem}_replica_{i}.png"
                PILImage.fromarray(mask.astype(np.uint8) * 255).save(str(out_path))
            self.logger.log_message("INFO", f"Generated {count} replicas in: {output_dir}")
        except Exception as exc:
            self.logger.log_message("ERROR", f"Failed to generate replicas: {exc}")

    # ------------------------------------------------------------------
    # B/W color selectors
    # ------------------------------------------------------------------

    def _build_bw_row(self, current: tuple[int, int, int], slot) -> QWidget:
        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        group = QButtonGroup(row)
        group.setExclusive(True)
        for label, rgb in (("Black", (0, 0, 0)), ("White", (255, 255, 255))):
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setChecked(current == rgb)
            btn.clicked.connect(lambda _checked, c=rgb: slot(c))
            group.addButton(btn)
            h.addWidget(btn)
        row.setStyleSheet(f"""
QPushButton {{
    color: {QLEMENTINE_DARK["secondary"]};
    background: {QLEMENTINE_DARK["neutral"]};
    border: 1px solid {QLEMENTINE_DARK["border"]};
    border-radius: 5px;
    padding: 2px 10px;
}}
QPushButton:hover   {{ background: {QLEMENTINE_DARK["neutral_hovered"]}; }}
QPushButton:checked {{
    background: {QLEMENTINE_DARK["primary"]};
    color: {QLEMENTINE_DARK["primary_foreground"]};
    border-color: {QLEMENTINE_DARK["primary_pressed"]};
}}
""")
        return row

    def _set_pen_color(self, rgb: tuple[int, int, int]) -> None:
        self._pen_color = rgb
        self._editor.set_pen_color(rgb)

    def _set_fill_color(self, rgb: tuple[int, int, int]) -> None:
        self._fill_color = rgb
        self._editor.set_fill_color(rgb)

    # ------------------------------------------------------------------
    # Editor signal handlers
    # ------------------------------------------------------------------

    def _on_tool_changed(self, name: str) -> None:
        for tool_name, btn in self._tool_btns.items():
            btn.setChecked(tool_name == name)
        page = _TOOL_PAGES.get(name, 0)
        self._tool_settings_stack.setCurrentIndex(page)
        self._tool_settings_stack.setVisible(page > 0)
        # Deactivate any active adjustment
        self._adjustment_settings_stack.setCurrentIndex(0)
        self._adjustment_settings_stack.setVisible(False)
        for btn in self._adjustment_btns.values():
            btn.setChecked(False)

    def _on_image_committed(self) -> None:
        img = self._editor.current_image()
        if img is not None:
            self.logger.log_message(
                "INFO",
                f"Image updated: shape={img.shape}  dtype={img.dtype}  mean={np.mean(img):.1f}",
            )

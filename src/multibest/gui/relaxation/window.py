# SPDX-FileCopyrightText: 2026 bright-ideas-clan
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Relaxation GUI module.

Provides controls for preparing GFN-xTB and SevenNet relaxation inputs.
"""

from __future__ import annotations

import math
import os
from collections.abc import Iterable
from pathlib import Path

os.environ.setdefault("OVITO_GUI_MODE", "1")

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QScrollArea,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

try:
    from ovito.gui import create_qwidget
    from ovito.io import import_file
    from ovito.vis import Viewport

    HAS_OVITO = True
except Exception:
    create_qwidget = None
    import_file = None
    Viewport = None
    HAS_OVITO = False

from multibest.gui.utils.base_window import BaseModuleWindow
from multibest.gui.utils.general import browse_directory, browse_file, create_file, get_script_path, is_pyinstaller
from multibest.gui.utils.ovito_scene import clear_ovito_scene
from multibest.gui.utils.theme import (
    QLEMENTINE_DARK,
    NoWheelComboBox,
    NoWheelDoubleSpinBox,
    NoWheelSpinBox,
    apply_module_title,
    apply_panel_title,
    apply_preview_panel,
    apply_preview_placeholder,
    apply_subtle_text,
    make_action_button,
    make_path_row,
    make_primary_button,
    make_stop_button,
)
from multibest.gui.utils.visualization import MatplotlibWidget


class RelaxationWindow(BaseModuleWindow):
    """
    Main Window for the Relaxation application.

    Attributes:
        gfn_input (QLineEdit): Field for the GFN-xTB input file path.
        gfn_output (QLineEdit): Field for the GFN-xTB output file path.
        sevennet_input (QLineEdit): Field for the SevenNet input file path.
        sevennet_output_dir (QLineEdit): Field for the SevenNet output directory.
    """

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Relaxation")
        self.resize(900, 650)
        self._last_engine = ""
        self._last_output_file = ""
        self._last_output_dir = ""
        self._ovito_widget = None
        self._pipeline = None
        self._viewport = None

        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        main_layout = QHBoxLayout(main_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Left Panel - Controls
        self.control_tabs = QTabWidget()
        self.gfn_tab = self._build_gfn_tab()
        self.sevennet_tab = self._build_sevennet_tab()
        self.control_tabs.addTab(self.gfn_tab, "GFN-xTB")
        self.control_tabs.addTab(self.sevennet_tab, "SevenNet")
        self.control_tabs.currentChanged.connect(self._update_preview)
        main_layout.addWidget(self.control_tabs, 1)

        # Right Panel - Result visualization
        self.result_panel = self._build_visualization()
        main_layout.addWidget(self.result_panel, 1)

        self.control_widget = self.control_tabs
        self.viz_widget = self.result_panel
        self._update_preview()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_gfn_tab(self) -> QWidget:
        scroll, layout = self._make_scroll_tab()

        # Header
        header = QLabel("GFN-xTB relaxation")
        apply_module_title(header)
        layout.addWidget(header)

        # Input/Output Config Group
        io_group = QGroupBox("I/O Configuration")
        io_layout = QFormLayout(io_group)
        self.gfn_input = self._add_path_row(io_layout, "Input file:", "file")
        self.gfn_restart_mode = self._add_combo_row(io_layout, "Restart mode:", ["scratch", "restart"])

        # Restart file row — only visible when restart mode is "restart"
        self.gfn_restart = QLineEdit()
        _structure_filter = "Structure files (*.xyz *.cif *.lmp *.data);;All files (*)"
        self._gfn_restart_row = make_path_row(
            self.gfn_restart,
            "Browse",
            lambda: browse_file(self, self.gfn_restart, _structure_filter),
        )
        io_layout.addRow("Restart file:", self._gfn_restart_row)
        self.gfn_restart.textChanged.connect(self._update_preview)
        self._gfn_restart_row.setVisible(False)

        def _on_restart_mode_changed(text: str) -> None:
            visible = text == "restart"
            self._gfn_restart_row.setVisible(visible)
            lbl = io_layout.labelForField(self._gfn_restart_row)
            if lbl:
                lbl.setVisible(visible)

        self.gfn_restart_mode.currentTextChanged.connect(_on_restart_mode_changed)
        _restart_lbl = io_layout.labelForField(self._gfn_restart_row)
        if _restart_lbl:
            _restart_lbl.setVisible(False)

        self.gfn_output = self._add_path_row(io_layout, "Output file:", "save")
        self.gfn_output_format = self._add_combo_row(io_layout, "Output format:", ["xyz", "cif", "lammps-data"])
        layout.addWidget(io_group)

        # Method Group
        method_group = QGroupBox("Method")
        method_layout = QFormLayout(method_group)
        self.gfn_method = self._add_combo_row(method_layout, "Method:", ["GFN2-xTB", "GFN1-xTB", "GFN0-xTB"])
        self.gfn_xtb_optimization = self._add_combo_row(method_layout, "XTB optimization:", ["True", "False"])
        layout.addWidget(method_group)

        # Elements Group
        self.gfn_elements_group = QGroupBox("Elements")
        self.gfn_elements_layout = QVBoxLayout(self.gfn_elements_group)
        self.gfn_element_rows: list[tuple[QLineEdit, QLineEdit, QLineEdit]] = []
        self._gfn_element_row_layouts: list[QHBoxLayout] = []
        self.add_gfn_element_row()
        self.add_gfn_element_row()
        self.gfn_add_element_btn = make_action_button("Add more elements", "add")
        self.gfn_add_element_btn.clicked.connect(self.add_gfn_element_row)
        self.gfn_elements_layout.addWidget(self.gfn_add_element_btn)
        layout.addWidget(self.gfn_elements_group)

        # Parameters Group
        relaxation_group = QGroupBox("Relaxation")
        relaxation_layout = QFormLayout(relaxation_group)
        self.gfn_optimizer = self._add_combo_row(relaxation_layout, "Optimizer:", ["fire", "lbfgs"])
        self.gfn_steps = self._add_spin_row(relaxation_layout, "Steps:", 1, 1_000_000, 500)
        self.gfn_max_iteration = self._add_spin_row(relaxation_layout, "Max iteration:", 1, 1_000_000, 1000)
        self.gfn_fmax = self._add_double_row(relaxation_layout, "fmax:", 0.0, 1_000_000.0, 0.05)
        self.gfn_traj = self._add_combo_row(method_layout, "Trajectory:", ["False", "True"])
        self.gfn_accuracy = self._add_double_row(relaxation_layout, "Accuracy:", 0.0, 1_000_000.0, 1.0)
        self.gfn_electronic_temperature = self._add_double_row(
            relaxation_layout, "Electronic temperature:", 0.0, 1_000_000.0, 300.0
        )
        self.gfn_pbc = self._add_combo_row(relaxation_layout, "PBC:", ["False", "True"])
        self.gfn_constraints = self._add_combo_row(relaxation_layout, "Constraints:", ["none", "bottom", "custom"])
        self.gfn_custom_constraints = self._add_line_row(relaxation_layout, "Custom constraints:")
        layout.addWidget(relaxation_group)

        # Run Button
        self.gfn_write_btn = make_primary_button("Run Relaxation")
        self.stop_btn = make_stop_button()
        self.gfn_write_btn.clicked.connect(self._write_current_parameters)
        self.stop_btn.clicked.connect(self._stop_calculation)
        _btn_row = QHBoxLayout()
        _btn_row.addWidget(self.gfn_write_btn)
        _btn_row.addWidget(self.stop_btn)
        _btn_row.addStretch()
        layout.addLayout(_btn_row)
        layout.addStretch()

        self._calc_btns.append(self.gfn_write_btn)
        self._stop_btns.append(self.stop_btn)
        return scroll

    def _build_sevennet_tab(self) -> QWidget:
        scroll, layout = self._make_scroll_tab()

        # Header
        header = QLabel("SevenNet relaxation")
        apply_module_title(header)
        layout.addWidget(header)

        # Input/Output Config Group
        io_group = QGroupBox("I/O Configuration")
        io_layout = QFormLayout(io_group)
        self.sevennet_input = self._add_path_row(io_layout, "Input file:", "file")
        self.sevennet_output_dir = self._add_path_row(io_layout, "Output directory:", "directory")
        layout.addWidget(io_group)

        # Method Group
        method_group = QGroupBox("Method")
        method_layout = QFormLayout(method_group)
        self.sevennet_method = self._add_combo_row(method_layout, "Method:", ["SevenNet"])
        self.sevennet_model = self._add_combo_row(
            method_layout,
            "Model:",
            ["7net-mf-ompa", "7net-omat", "7net-l3i5", "7net-0"],
        )
        self.sevennet_modal = self._add_combo_row(method_layout, "Modal:", ["mpa", "omat24"])
        self._sevennet_modal_label = method_layout.labelForField(self.sevennet_modal)
        self.sevennet_model.currentTextChanged.connect(self._update_sevennet_modal_availability)
        self._update_sevennet_modal_availability(self.sevennet_model.currentText())
        self.sevennet_device = self._add_combo_row(method_layout, "Device:", ["auto", "cpu", "cuda"])
        layout.addWidget(method_group)

        # Parameters Group
        relaxation_group = QGroupBox("Relaxation")
        relaxation_layout = QFormLayout(relaxation_group)
        self.sevennet_optimizer = self._add_combo_row(relaxation_layout, "Optimizer:", ["fire", "lbfgs", "bfgs"])
        self.sevennet_steps = self._add_spin_row(relaxation_layout, "Steps:", 1, 1_000_000, 500)
        self.sevennet_fmax = self._add_double_row(relaxation_layout, "fmax:", 0.0, 1_000_000.0, 0.05)
        self.sevennet_pbc = self._add_combo_row(relaxation_layout, "PBC:", ["True", "False"])
        self.sevennet_constraints = self._add_combo_row(
            relaxation_layout,
            "Constraints:",
            ["none", "custom"],
        )
        self.sevennet_custom_constraints = self._add_line_row(relaxation_layout, "Custom constraints:")
        layout.addWidget(relaxation_group)

        # Run Button
        self.sevennet_write_btn = make_primary_button("Run Relaxation")
        self.sevennet_stop_btn = make_stop_button()
        self.sevennet_write_btn.clicked.connect(self._write_current_parameters)
        self.sevennet_stop_btn.clicked.connect(self._stop_calculation)
        _btn_row = QHBoxLayout()
        _btn_row.addWidget(self.sevennet_write_btn)
        _btn_row.addWidget(self.sevennet_stop_btn)
        _btn_row.addStretch()
        layout.addLayout(_btn_row)
        layout.addStretch()

        self._calc_btns.append(self.sevennet_write_btn)
        self._stop_btns.append(self.sevennet_stop_btn)
        return scroll

    def _make_scroll_tab(self) -> tuple[QScrollArea, QVBoxLayout]:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)
        scroll.setWidget(content)
        return scroll, layout

    def _build_visualization(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        self.result_title = QLabel("Relaxation results")
        apply_panel_title(self.result_title)
        layout.addWidget(self.result_title)

        self.result_summary = QLabel()
        self.result_summary.setWordWrap(True)
        apply_subtle_text(self.result_summary)
        layout.addWidget(self.result_summary)

        # Each visualization gets its own tab to keep the panel uncluttered.
        self.result_tabs = QTabWidget()
        layout.addWidget(self.result_tabs, 1)

        # 3D Structure tab — OVITO viewport
        self.viewport_container = QFrame()
        apply_preview_panel(self.viewport_container)
        self.viewport_layout = QVBoxLayout(self.viewport_container)
        self.viewport_layout.setContentsMargins(0, 0, 0, 0)
        self.structure_label = QLabel("3D view of the relaxed atomistic structure\nOVITO viewport will appear here")
        self.structure_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.structure_label.setWordWrap(True)
        apply_preview_placeholder(self.structure_label)
        self.viewport_layout.addWidget(self.structure_label)
        self.result_tabs.addTab(self.viewport_container, "3D Structure")

        # Plots tab — energy / force / Mulliken summaries
        self.result_plot = MatplotlibWidget(width=6, height=3, dpi=100)
        self._plots_tab_index = self.result_tabs.addTab(self.result_plot, "Plots")

        # Details tab — text summary of metrics
        self.result_details = QTextEdit()
        self.result_details.setReadOnly(True)
        from PySide6.QtGui import QFontDatabase

        mono = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont).family()
        self.result_details.setStyleSheet(
            f"font-family: '{mono}';"
            f" background-color: {QLEMENTINE_DARK['background_main_1']};"
            f" color: {QLEMENTINE_DARK['secondary']};"
            f" border: 1px solid {QLEMENTINE_DARK['border']};"
            " border-radius: 6px;"
        )
        self.result_tabs.addTab(self.result_details, "Details")

        self._plot_placeholder()
        return panel

    def _add_path_row(self, layout: QFormLayout, label: str, mode: str) -> QLineEdit:
        line_edit = QLineEdit()
        structure_filter = "Structure files (*.xyz *.cif *.lmp *.data);;All files (*)"
        if mode == "file":

            def on_click() -> None:
                browse_file(self, line_edit, structure_filter)

            action = "browse"
        elif mode == "save":

            def on_click() -> None:
                create_file(self, line_edit, structure_filter)

            action = "save"
        else:

            def on_click() -> None:
                browse_directory(self, line_edit)

            action = "browse"
        layout.addRow(label, make_path_row(line_edit, "Browse", on_click, action=action))
        line_edit.textChanged.connect(self._update_preview)
        return line_edit

    def _add_line_row(self, layout: QFormLayout, label: str) -> QLineEdit:
        line_edit = QLineEdit()
        line_edit.textChanged.connect(self._update_preview)
        layout.addRow(label, line_edit)
        return line_edit

    def _add_combo_row(self, layout: QFormLayout, label: str, values: list[str]) -> NoWheelComboBox:
        combo = NoWheelComboBox()
        combo.addItems(values)
        combo.currentTextChanged.connect(self._update_preview)
        layout.addRow(label, combo)
        return combo

    def _add_spin_row(self, layout: QFormLayout, label: str, minimum: int, maximum: int, value: int) -> NoWheelSpinBox:
        spin = NoWheelSpinBox()
        spin.setRange(minimum, maximum)
        spin.setValue(value)
        spin.valueChanged.connect(self._update_preview)
        layout.addRow(label, spin)
        return spin

    def _add_double_row(
        self,
        layout: QFormLayout,
        label: str,
        minimum: float,
        maximum: float,
        value: float,
    ) -> NoWheelDoubleSpinBox:
        spin = NoWheelDoubleSpinBox()
        spin.setRange(minimum, maximum)
        spin.setDecimals(6)
        spin.setValue(value)
        spin.valueChanged.connect(self._update_preview)
        layout.addRow(label, spin)
        return spin

    # ------------------------------------------------------------------
    # Data helpers
    # ------------------------------------------------------------------

    def add_gfn_element_row(self) -> None:
        """Add an element/charge/spin row to the GFN-xTB element list."""
        element = QLineEdit()
        element.setPlaceholderText("Element")
        charge = QLineEdit()
        charge.setPlaceholderText("Charge")
        spin = QLineEdit()
        spin.setPlaceholderText("Spin / atom")
        for widget in (element, charge, spin):
            widget.textChanged.connect(self._update_preview)

        row = QHBoxLayout()
        row.addWidget(element)
        row.addWidget(charge)
        row.addWidget(spin)
        row_widgets = (element, charge, spin)

        remove_btn = make_action_button("Remove", "remove")
        remove_btn.setMaximumWidth(90)
        remove_btn.clicked.connect(lambda checked=False, widgets=row_widgets: self.remove_gfn_element_row(widgets))
        row.addWidget(remove_btn)

        self.gfn_element_rows.append(row_widgets)
        self._gfn_element_row_layouts.append(row)

        insert_index = max(0, self.gfn_elements_layout.count() - 1)
        self.gfn_elements_layout.insertLayout(insert_index, row)
        self._update_preview()

    def remove_gfn_element_row(self, row_widgets: tuple[QLineEdit, QLineEdit, QLineEdit]) -> None:
        """Remove a GFN-xTB element row, leaving one empty row available."""
        if row_widgets not in self.gfn_element_rows:
            return

        if len(self.gfn_element_rows) == 1:
            for widget in row_widgets:
                widget.clear()
            self._update_preview()
            return

        index = self.gfn_element_rows.index(row_widgets)
        self.gfn_element_rows.pop(index)
        row_layout = self._gfn_element_row_layouts.pop(index)
        self.gfn_elements_layout.removeItem(row_layout)
        self._delete_layout_widgets(row_layout)
        self._update_preview()

    def _delete_layout_widgets(self, layout: QHBoxLayout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _collect_gfn_elements(self) -> list[dict[str, str]]:
        elements = []
        for element, charge, spin in self.gfn_element_rows:
            if any(field.text().strip() for field in (element, charge, spin)):
                elements.append(
                    {
                        "element": element.text().strip(),
                        "charge": charge.text().strip(),
                        "spin": spin.text().strip(),
                    }
                )
        return elements

    def _current_method_key(self) -> str:
        return "gfn_xtb" if self.control_tabs.currentIndex() == 0 else "sevennet"

    def _sevennet_model_has_modal(self, model: str) -> bool:
        return model in {"7net-mf-ompa", "7net-omat"}

    def _update_sevennet_modal_availability(self, model: str) -> None:
        available = self._sevennet_model_has_modal(model)
        self.sevennet_modal.setEnabled(available)
        self.sevennet_modal.setVisible(available)
        if self._sevennet_modal_label:
            self._sevennet_modal_label.setVisible(available)
        self._update_preview()

    def collect_parameters(self) -> dict[str, object]:
        """Return the currently selected method's parameters."""
        if self._current_method_key() == "gfn_xtb":
            return {
                "method": self.gfn_method.currentText(),
                "xtb_optimization": self.gfn_xtb_optimization.currentText(),
                "input_file": self.gfn_input.text().strip(),
                "restart_mode": self.gfn_restart_mode.currentText(),
                "restart_file": self.gfn_restart.text().strip(),
                "output_file": self.gfn_output.text().strip(),
                "output_format": self.gfn_output_format.currentText(),
                "elements": self._collect_gfn_elements(),
                "optimizer": self.gfn_optimizer.currentText(),
                "steps": self.gfn_steps.value(),
                "max_iteration": self.gfn_max_iteration.value(),
                "fmax": self.gfn_fmax.value(),
                "accuracy": self.gfn_accuracy.value(),
                "electronic_temperature": self.gfn_electronic_temperature.value(),
                "pbc": self.gfn_pbc.currentText(),
                "constraints": self.gfn_constraints.currentText(),
                "custom_constraints": self.gfn_custom_constraints.text().strip(),
                "trajectory": self.gfn_traj.currentText(),
            }

        return {
            "method": self.sevennet_method.currentText(),
            "input_file": self.sevennet_input.text().strip(),
            "output_directory": self.sevennet_output_dir.text().strip(),
            "model": self.sevennet_model.currentText(),
            "modal": self.sevennet_modal.currentText()
            if self._sevennet_model_has_modal(self.sevennet_model.currentText())
            else "",
            "device": self.sevennet_device.currentText(),
            "optimizer": self.sevennet_optimizer.currentText(),
            "steps": self.sevennet_steps.value(),
            "fmax": self.sevennet_fmax.value(),
            "pbc": self.sevennet_pbc.currentText(),
            "constraints": self.sevennet_constraints.currentText(),
            "custom_constraints": self.sevennet_custom_constraints.text().strip(),
        }

    def _update_preview(self) -> None:
        if not hasattr(self, "result_summary"):
            return

        params = self.collect_parameters()
        if self._current_method_key() == "gfn_xtb":
            output = str(params["output_file"]).strip() or "Choose an output file"
            summary = (
                f"GFN-xTB will relax {os.path.basename(str(params['input_file'])) or 'an input structure'} "
                f"with {params['optimizer']} for up to {params['steps']} steps. "
                f"Target fmax: {params['fmax']} eV/A."
            )
            detail_lines = [
                "Engine: GFN-xTB",
                f"Method: {params['method']}",
                f"Output: {output}",
                f"Format: {params['output_format']}",
                f"PBC: {params['pbc']}",
                f"Constraints: {params['constraints']}",
            ]
        else:
            output_dir = str(params["output_directory"]).strip() or "Choose an output directory"
            summary = (
                f"SevenNet will relax {os.path.basename(str(params['input_file'])) or 'an input structure'} "
                f"with {params['model']} on {params['device']} for up to {params['steps']} steps. "
                f"Target fmax: {params['fmax']} eV/A."
            )
            detail_lines = [
                "Engine: SevenNet",
                f"Model: {params['model']}",
                f"Output directory: {output_dir}",
                f"PBC: {params['pbc']}",
                f"Constraints: {params['constraints']}",
            ]
            if params["modal"]:
                detail_lines.insert(2, f"Modal: {params['modal']}")

        self.result_summary.setText(summary)
        if not self._last_output_file:
            self.result_details.setPlainText("\n".join(detail_lines))
        self._update_plot_visibility()

    def _update_plot_visibility(self) -> None:
        """Show plots only for GFN-xTB, whose backend produces meaningful plot data."""
        if not hasattr(self, "result_tabs"):
            return
        self.result_tabs.setTabVisible(self._plots_tab_index, self._current_method_key() == "gfn_xtb")

    def _write_current_parameters(self) -> None:
        """Validate, write the selected backend's input file, and launch it."""
        engine = self._current_method_key()
        params = self.collect_parameters()
        if not self._validate_input_file(str(params["input_file"])):
            return
        params["input_file"] = os.path.abspath(str(params["input_file"]))

        if engine == "gfn_xtb":
            self.gfn_input.setText(str(params["input_file"]))
            self._run_gfn_xtb(params)
            return

        self.sevennet_input.setText(str(params["input_file"]))
        self._run_sevennet(params)

    def _run_gfn_xtb(self, params: dict[str, object]) -> None:
        output_file = str(params["output_file"])
        if not output_file:
            self.logger.log_message("ERROR", "Please choose an output file first.")
            return

        output_file = os.path.abspath(output_file)
        self.gfn_output.setText(output_file)
        params["output_file"] = output_file
        output_dir = os.path.dirname(output_file) or os.getcwd()
        if not self._validate_output_dir(output_dir):
            return

        restart_mode = str(params.get("restart_mode", "scratch"))
        restart_file = str(params.get("restart_file", "")).strip() if restart_mode == "restart" else ""
        if restart_file and not self._validate_input_file(restart_file):
            return
        if restart_file:
            restart_file = os.path.abspath(restart_file)
            self.gfn_restart.setText(restart_file)
            params["restart_file"] = restart_file

        backend_params = self._gfn_backend_params(params)
        param_file = os.path.join(output_dir, "gfn_xtb_input.txt")
        self._write_backend_input(param_file, backend_params, self._gfn_element_lines(params))
        self._last_engine = "gfn_xtb"
        self._last_output_file = output_file
        self._last_output_dir = output_dir
        self._start_backend(
            name="GFN-xTB relaxation",
            script_path=self._relaxation_script_path("gfn2-xtb", "GFN2-xTB.py"),
            param_file=param_file,
            cwd=output_dir,
        )

    def _run_sevennet(self, params: dict[str, object]) -> None:
        output_dir = str(params["output_directory"]).strip()
        if not self._validate_output_dir(output_dir):
            return

        output_dir = os.path.abspath(output_dir)
        self.sevennet_output_dir.setText(output_dir)
        params["output_directory"] = output_dir
        output_file = self._sevennet_output_file(params, output_dir)
        backend_params = self._sevennet_backend_params(params, output_file)
        param_file = os.path.join(output_dir, "sevennet_input.txt")
        self._write_backend_input(param_file, backend_params)
        self._last_engine = "sevennet"
        self._last_output_file = output_file
        self._last_output_dir = output_dir
        self._start_backend(
            name="SevenNet relaxation",
            script_path=self._relaxation_script_path("sevennet", "SevenNet.py"),
            param_file=param_file,
            cwd=output_dir,
        )

    def _gfn_backend_params(self, params: dict[str, object]) -> dict[str, object]:
        restart_mode = str(params.get("restart_mode", "scratch"))
        restart_file = str(params.get("restart_file", "")).strip() if restart_mode == "restart" else ""
        return {
            "method": params["method"],
            "restart_mode": "restart" if restart_mode == "restart" else "scratch",
            "restart_file": restart_file,
            "input": params["input_file"],
            "output": params["output_file"],
            "use_xtb_opt": params["xtb_optimization"],
            "optimizer": params["optimizer"],
            "steps": params["steps"],
            "max_iterations": params["max_iteration"],
            "fmax": params["fmax"],
            "accuracy": params["accuracy"],
            "electronic_temperature": params["electronic_temperature"],
            "pbc": params["pbc"],
            "trajectory": params["trajectory"],
            "output_format": params["output_format"],
            "constraints": self._backend_constraints(str(params["constraints"])),
            "custom_constraints": params["custom_constraints"],
        }

    def _sevennet_backend_params(self, params: dict[str, object], output_file: str) -> dict[str, object]:
        return {
            "method": params["method"],
            "input": params["input_file"],
            "output": output_file,
            "model": params["model"],
            "modal": params["modal"],
            "device": params["device"],
            "optimizer": params["optimizer"],
            "steps": params["steps"],
            "fmax": params["fmax"],
            "pbc": str(params["pbc"]).lower(),
            "constraints": self._backend_constraints(str(params["constraints"])),
            "custom_constraints": params["custom_constraints"],
        }

    def _gfn_element_lines(self, params: dict[str, object]) -> list[str]:
        lines = []
        elements = params.get("elements", [])
        if not isinstance(elements, list):
            return lines

        for row in elements:
            if not isinstance(row, dict):
                continue
            element = str(row.get("element", "")).strip()
            if not element:
                continue
            charge = str(row.get("charge", "")).strip() or "0.0"
            spin = str(row.get("spin", "")).strip() or "0.0"
            lines.append(f"{element} {charge} {spin}")
        return lines

    def _sevennet_output_file(self, params: dict[str, object], output_dir: str) -> str:
        input_file = str(params["input_file"])
        input_stem = os.path.splitext(os.path.basename(input_file))[0] or "relaxed_structure"
        return os.path.join(output_dir, f"{input_stem}_relaxed.xyz")

    # ------------------------------------------------------------------
    # Visualization helpers
    # ------------------------------------------------------------------

    def _plot_placeholder(self) -> None:
        """Draw the empty-state plot used before a backend has produced results."""
        self._reset_structure_view()
        figure = self.result_plot.get_figure()
        figure.clear()
        figure.patch.set_facecolor(QLEMENTINE_DARK["background_main_2"])
        ax = figure.add_subplot(111)
        ax.set_facecolor(QLEMENTINE_DARK["background_main_2"])
        ax.axis("off")
        ax.text(
            0.5,
            0.5,
            "Run a relaxation to plot energy,\nforces and charge/spin summaries.",
            ha="center",
            va="center",
            color=QLEMENTINE_DARK["secondary_alternative"],
            fontsize=12,
        )
        self.result_plot.get_canvas().draw()

    def _plot_relaxation_results(self) -> None:
        """Render the final relaxed structure and companion result files."""
        output_file = self._resolved_last_output_file()
        if not output_file:
            self.logger.log_message("ERROR", "Relaxation output file was not found.")
            return

        try:
            structure = self._load_structure(output_file)
            metrics = self._read_result_metrics(output_file)
            mulliken = self._read_mulliken_results(output_file)
            self._load_ovito_structure(output_file)
            if self._last_engine == "gfn_xtb":
                self.result_plot.plot(self._draw_relaxation_figure, metrics, mulliken)
        except Exception as exc:
            self.logger.log_message("ERROR", f"Failed to visualize relaxation results:\n{exc}")
            return

        engine_label = "GFN-xTB" if self._last_engine == "gfn_xtb" else "SevenNet"
        self.result_title.setText(f"{engine_label} relaxation results")
        self.result_summary.setText(f"Loaded {len(structure['symbols'])} atoms from {os.path.basename(output_file)}.")
        self.result_details.setPlainText(self._result_details_text(output_file, metrics, mulliken))

    def _resolved_last_output_file(self) -> str:
        output_file = self._last_output_file
        if output_file and os.path.isfile(output_file):
            return output_file
        if output_file and self._last_output_dir:
            resolved = os.path.join(self._last_output_dir, os.path.basename(output_file))
            if os.path.isfile(resolved):
                return resolved
        return ""

    # Map output-file extensions to ASE format names. ASE cannot infer the
    # format for several of these (e.g. ``.lmp``), so we resolve it explicitly.
    _EXT_TO_ASE_FORMAT = {
        ".xyz": "xyz",
        ".extxyz": "extxyz",
        ".cif": "cif",
        ".lmp": "lammps-data",
        ".data": "lammps-data",
        ".lammps": "lammps-data",
    }

    @classmethod
    def _ase_read_format(cls, path: str) -> str:
        """Resolve an explicit ASE format from the extension, or "" to auto-detect."""
        return cls._EXT_TO_ASE_FORMAT.get(os.path.splitext(path)[1].lower(), "")

    def _load_structure(self, path: str) -> dict[str, object]:
        try:
            from ase.io import read

            fmt = self._ase_read_format(path)
            if fmt == "lammps-data":
                atoms = read(path, format=fmt, atom_style="atomic")
            elif fmt:
                atoms = read(path, format=fmt)
            else:
                atoms = read(path)
            return {
                "symbols": atoms.get_chemical_symbols(),
                "positions": np.asarray(atoms.get_positions(), dtype=float),
            }
        except Exception:
            return self._load_xyz_structure(path)

    def _load_xyz_structure(self, path: str) -> dict[str, object]:
        with open(path, encoding="utf-8") as handle:
            lines = [line.strip() for line in handle if line.strip()]

        if len(lines) < 3:
            raise ValueError("Output structure is too short to parse as XYZ.")

        try:
            atom_count = int(lines[0])
        except ValueError as exc:
            raise ValueError("ASE could not read the output, and it is not an XYZ file.") from exc

        symbols = []
        positions = []
        for line in lines[2 : 2 + atom_count]:
            fields = line.split()
            if len(fields) < 4:
                continue
            symbols.append(fields[0])
            positions.append([float(fields[1]), float(fields[2]), float(fields[3])])

        if not symbols:
            raise ValueError("No atom coordinates were found in the output file.")
        return {"symbols": symbols, "positions": np.asarray(positions, dtype=float)}

    @staticmethod
    def _ovito_import_kwargs(path: str) -> dict[str, str]:
        """Return reader options so OVITO can open every output format we emit.

        OVITO auto-detects xyz and CIF from their contents, but LAMMPS data
        files (``.lmp``/``.data``/``.lammps``) need an explicit ``atom_style``
        that matches what the relaxation backends write.
        """
        ext = os.path.splitext(path)[1].lower()
        if ext in {".lmp", ".data", ".lammps"}:
            return {"atom_style": "atomic"}
        return {}

    def _load_ovito_structure(self, path: str) -> None:
        """Load the relaxed atomistic structure into the OVITO viewport when available."""
        if not HAS_OVITO or import_file is None or create_qwidget is None or Viewport is None:
            self._set_structure_placeholder("OVITO is not available; showing calculation summaries only.")
            return

        try:
            self._clear_ovito_scene()

            pipeline = import_file(path, **self._ovito_import_kwargs(path))
            # Warm the cache before scene insertion so the first viewport paint
            # does not reuse the previous run's stale data (noticeable on OVITO
            # >=3.15 when relaxing several structures in a row).
            pipeline.compute()
            pipeline.add_to_scene()

            viewport = Viewport(type=Viewport.Type.PERSPECTIVE)
            widget = create_qwidget(viewport)
            self._replace_viewport_widget(widget)
            viewport.zoom_all()

            self._pipeline = pipeline
            self._viewport = viewport
            self._ovito_widget = widget
        except Exception as exc:
            self._set_structure_placeholder(f"OVITO could not load the relaxed structure:\n{exc}")
            self.logger.log_message("ERROR", f"Failed to load relaxed structure in OVITO:\n{exc}")

    def _reset_structure_view(self) -> None:
        self._clear_ovito_scene()

        self._set_structure_placeholder("3D view of the relaxed atomistic structure\nOVITO viewport will appear here")

    def _clear_ovito_scene(self) -> None:
        if not HAS_OVITO:
            self._pipeline = None
            self._viewport = None
            return

        clear_ovito_scene(lambda message: self.logger.log_message("WARNING", message))
        self._pipeline = None
        self._viewport = None

    def _set_structure_placeholder(self, text: str) -> None:
        label = QLabel(text)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setWordWrap(True)
        apply_preview_placeholder(label)
        self._replace_viewport_widget(label)
        self.structure_label = label

    def _replace_viewport_widget(self, new_widget: QWidget) -> None:
        if getattr(self, "structure_label", None) is not None:
            self.viewport_layout.removeWidget(self.structure_label)
            self.structure_label.deleteLater()
            self.structure_label = None

        if getattr(self, "_ovito_widget", None) is not None:
            self.viewport_layout.removeWidget(self._ovito_widget)
            self._ovito_widget.deleteLater()
            self._ovito_widget = None

        self.viewport_layout.addWidget(new_widget, 1)

    def _read_result_metrics(self, output_file: str) -> dict[str, float]:
        if self._last_engine == "sevennet":
            return self._read_metric_file(str(Path(output_file).with_suffix(".energy")))

        output_path = Path(output_file)
        electronic_file = Path(self._last_output_dir or output_path.parent) / f"{output_path.stem}_electronic.txt"
        return self._read_metric_file(str(electronic_file))

    def _read_metric_file(self, path: str) -> dict[str, float]:
        metrics: dict[str, float] = {}
        if not os.path.isfile(path):
            return metrics

        label_map = {
            "Final_energy": "Final energy",
            "Total Energy": "Total energy",
            "Max_force": "Max force",
            "Max Force": "Max force",
            "RMS Force": "RMS force",
        }
        with open(path, encoding="utf-8") as handle:
            for raw_line in handle:
                if ":" not in raw_line:
                    continue
                key, value = raw_line.split(":", 1)
                key = key.strip()
                label = label_map.get(key)
                if label is None:
                    continue
                number = self._first_float(value)
                if number is not None:
                    metrics[label] = number
        return metrics

    def _read_mulliken_results(self, output_file: str) -> dict[str, list[float]]:
        if self._last_engine != "gfn_xtb":
            return {}

        output_path = Path(output_file)
        mulliken_file = Path(self._last_output_dir or output_path.parent) / f"{output_path.stem}_mulliken.txt"
        if not mulliken_file.is_file():
            return {}

        indices: list[int] = []
        charges: list[float] = []
        spins: list[float] = []
        with open(mulliken_file, encoding="utf-8") as handle:
            for raw_line in handle:
                line = raw_line.strip()
                if not line or line.startswith("#"):
                    continue
                fields = line.split()
                if len(fields) < 4:
                    continue
                try:
                    indices.append(int(fields[0]))
                    charges.append(float(fields[2]))
                    spins.append(float(fields[3]))
                except ValueError:
                    continue

        if not indices:
            return {}
        return {"indices": indices, "charges": charges, "spins": spins}

    def _first_float(self, text: str) -> float | None:
        for part in text.replace(",", " ").split():
            try:
                value = float(part.strip("[]"))
            except ValueError:
                continue
            if math.isfinite(value):
                return value
        return None

    def _draw_relaxation_figure(
        self,
        figure,
        metrics: dict[str, float],
        mulliken: dict[str, list[float]],
    ) -> None:
        figure.patch.set_facecolor("#2b2b2b")
        gs = figure.add_gridspec(1, 2, width_ratios=[1.0, 1.0])
        ax_metrics = figure.add_subplot(gs[0, 0])
        ax_extra = figure.add_subplot(gs[0, 1])

        self._draw_metrics(ax_metrics, metrics)
        if mulliken:
            self._draw_mulliken(ax_extra, mulliken)
        else:
            self._draw_result_note(ax_extra, "No Mulliken charge/spin file was produced for this run.")

        figure.tight_layout(pad=2.0)

    def _draw_structure(self, ax, structure: dict[str, object], output_file: str) -> None:
        symbols = list(structure["symbols"])
        positions = np.asarray(structure["positions"], dtype=float)
        unique_symbols = sorted(set(symbols))
        colors = [
            "#6bb6ff",
            "#ffcc66",
            "#84d784",
            "#ff8a80",
            "#c7a4ff",
            "#68d8d6",
            "#f7a8c4",
            "#d7d36a",
        ]

        self._style_dark_axis(ax)
        for index, symbol in enumerate(unique_symbols):
            mask = np.asarray([item == symbol for item in symbols])
            pts = positions[mask]
            ax.scatter(
                pts[:, 0],
                pts[:, 1],
                pts[:, 2],
                s=38,
                color=colors[index % len(colors)],
                edgecolor="#101010",
                linewidth=0.4,
                label=f"{symbol} ({len(pts)})",
                depthshade=True,
            )

        ax.set_title("Final relaxed geometry", color="#f0f0f0", pad=12)
        ax.set_xlabel("x")
        ax.set_ylabel("y")
        ax.set_zlabel("z")
        ax.legend(loc="upper left", fontsize=8, facecolor="#2b2b2b", edgecolor="#555555", labelcolor="#f0f0f0")
        self._set_equal_3d_limits(ax, positions)
        ax.text2D(0.02, 0.02, os.path.basename(output_file), transform=ax.transAxes, color="#cfcfcf", fontsize=8)

    def _draw_metrics(self, ax, metrics: dict[str, float]) -> None:
        self._style_dark_axis(ax)
        force_items = [(key, value) for key, value in metrics.items() if "force" in key.lower()]
        energy_items = [(key, value) for key, value in metrics.items() if "energy" in key.lower()]

        if force_items:
            labels = [item[0] for item in force_items]
            values = [item[1] for item in force_items]
            y_pos = np.arange(len(values))
            ax.barh(y_pos, values, color="#6bb6ff")
            ax.set_yticks(y_pos, labels)
            ax.set_xlabel("eV/A")
            for y_value, value in zip(y_pos, values, strict=True):
                ax.text(value, y_value, f" {value:.4g}", va="center", color="#f0f0f0", fontsize=8)
        else:
            self._draw_result_note(ax, "No force summary file was found.")
            return

        if energy_items:
            energy_text = ", ".join(f"{label}: {value:.6g} eV" for label, value in energy_items)
            ax.set_title(energy_text, color="#f0f0f0", fontsize=10)
        else:
            ax.set_title("Force summary", color="#f0f0f0")

    def _draw_mulliken(self, ax, mulliken: dict[str, list[float]]) -> None:
        self._style_dark_axis(ax)
        indices = mulliken["indices"]
        charges = mulliken["charges"]
        spins = mulliken["spins"]
        ax.axhline(0.0, color="#777777", linewidth=0.8)
        ax.plot(indices, charges, marker="o", markersize=3, linewidth=1.0, color="#ffcc66", label="Charge")
        if any(abs(spin) > 1e-12 for spin in spins):
            ax.plot(indices, spins, marker="s", markersize=3, linewidth=1.0, color="#84d784", label="Spin")
        ax.set_title("Mulliken populations", color="#f0f0f0")
        ax.set_xlabel("Atom index")
        ax.set_ylabel("Population")
        ax.legend(loc="best", fontsize=8, facecolor="#2b2b2b", edgecolor="#555555", labelcolor="#f0f0f0")

    def _draw_result_note(self, ax, text: str) -> None:
        ax.set_facecolor("#252525")
        ax.axis("off")
        ax.text(0.5, 0.5, text, ha="center", va="center", color="#d8d8d8", fontsize=10, wrap=True)

    def _style_dark_axis(self, ax) -> None:
        ax.set_facecolor("#252525")
        ax.tick_params(colors="#d8d8d8")
        ax.xaxis.label.set_color("#d8d8d8")
        ax.yaxis.label.set_color("#d8d8d8")
        if hasattr(ax, "zaxis"):
            ax.zaxis.label.set_color("#d8d8d8")
        for spine in ax.spines.values():
            spine.set_color("#777777")
        ax.grid(color="#454545", alpha=0.45)

    def _set_equal_3d_limits(self, ax, positions: np.ndarray) -> None:
        if positions.size == 0:
            return

        minima = positions.min(axis=0)
        maxima = positions.max(axis=0)
        centers = (minima + maxima) / 2.0
        span = float(max(maxima - minima))
        if span <= 0.0:
            span = 1.0
        radius = span / 2.0
        ax.set_xlim(centers[0] - radius, centers[0] + radius)
        ax.set_ylim(centers[1] - radius, centers[1] + radius)
        ax.set_zlim(centers[2] - radius, centers[2] + radius)

    def _result_details_text(
        self,
        output_file: str,
        metrics: dict[str, float],
        mulliken: dict[str, list[float]],
    ) -> str:
        lines = [f"Output: {output_file}"]
        if metrics:
            lines.append("")
            lines.append("Metrics")
            for key, value in metrics.items():
                unit = "eV" if "energy" in key.lower() else "eV/A"
                lines.append(f"  {key}: {value:.8g} {unit}")
        if mulliken:
            charges = mulliken["charges"]
            spins = mulliken["spins"]
            lines.append("")
            lines.append("Mulliken")
            lines.append(f"  Charge range: {min(charges):.6g} to {max(charges):.6g}")
            lines.append(f"  Total charge: {sum(charges):.6g}")
            if any(abs(spin) > 1e-12 for spin in spins):
                lines.append(f"  Spin range: {min(spins):.6g} to {max(spins):.6g}")
                lines.append(f"  Total spin: {sum(spins):.6g}")
        return "\n".join(lines)

    def _backend_constraints(self, constraint: str) -> str:
        if constraint == "fix_atoms":
            return "custom"
        if constraint == "fix_cell":
            self.logger.log_message(
                "INFO",
                "The selected backend does not expose fixed-cell constraints; writing constraints = none.",
            )
            return "none"
        return constraint

    def _relaxation_script_path(self, *parts: str) -> str:
        if is_pyinstaller():
            return get_script_path("..", "relaxation", *parts)

        multibest_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
        return os.path.join(multibest_dir, "relaxation", *parts)

    def _write_backend_input(
        self,
        param_file: str,
        params: dict[str, object],
        extra_lines: Iterable[str] | None = None,
    ) -> None:
        self.logger.log_message("INFO", f"Writing parameter file: {param_file}")
        with open(param_file, "w", encoding="utf-8") as handle:
            for key, value in params.items():
                handle.write(f"{key} = {value}\n")

            lines = list(extra_lines or [])
            if lines:
                handle.write("\n")
                for line in lines:
                    handle.write(f"{line}\n")

    def _start_backend(self, name: str, script_path: str, param_file: str, cwd: str) -> None:
        # Drop the previous run's structure so a new run starts from a clean
        # slate (mirrors the input convertor); the result is rebuilt on finish.
        self._reset_structure_view()
        self._set_running(True)
        self.runner.on_finished_cb = self._make_finish_callback(name, self._plot_relaxation_results)
        self.runner.start(script_path, args=[param_file], cwd=cwd)

        self._update_preview()
        self.logger.log_message("INFO", f"Started {name}.")


if __name__ == "__main__":
    import sys

    from PySide6.QtWidgets import QApplication

    from multibest.gui.utils.theme import apply_dark_theme

    app = QApplication(sys.argv)
    apply_dark_theme(app)
    window = RelaxationWindow()
    window.show()
    sys.exit(app.exec())

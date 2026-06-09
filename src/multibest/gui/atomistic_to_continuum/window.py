# SPDX-FileCopyrightText: 2026 bright-ideas-clan
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Atomistic-to-continuum GUI application.

This module provides the user interface for microstructure analysis and
continuum model generation from atomistic input files.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from multibest.gui.utils import stl_preview
from multibest.gui.utils.base_window import BaseModuleWindow
from multibest.gui.utils.general import browse_directory, browse_file
from multibest.gui.utils.mesh_viewer import MeshViewer
from multibest.gui.utils.theme import (
    NoWheelComboBox,
    NoWheelDoubleSpinBox,
    NoWheelSpinBox,
    apply_dark_theme,
    apply_module_title,
    apply_preview_panel,
    apply_preview_placeholder,
    make_action_button,
    make_path_row,
    make_primary_button,
    make_stop_button,
)

GENERATED_MESHES = (
    ("Grains", "grains_mesh.stl"),
    ("Non-grains", "nongrains_mesh.stl"),
    ("Microstructure", "microstructure_mesh.stl"),
)


class AtomisticToContinuumWindow(BaseModuleWindow):
    """Main window for the atomistic-to-continuum interface."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Atomistic to Continuum")
        self.resize(800, 600)

        self.grain_inputs: list[QLineEdit] = []
        self.nongrain_inputs: list[QLineEdit] = []
        self.grain_input_rows: list[tuple[QWidget, QLabel, QLineEdit, QPushButton]] = []
        self.nongrain_input_rows: list[tuple[QWidget, QLabel, QLineEdit, QPushButton]] = []
        self._mesh_preview_paths: list[str] = []
        self._last_mesh_preview_path = ""

        main_layout, left_layout = self._build_split_layout()

        header = QLabel("Atomistic to continuum")
        apply_module_title(header)
        left_layout.addWidget(header)

        self._build_io_group(left_layout)
        self._build_microstructure_group(left_layout)
        self._build_continuum_group(left_layout)
        left_layout.addStretch()

        self.control_widget = self.left_scroll
        self.viz_widget = self._build_visualization()
        main_layout.addWidget(self.viz_widget, 2)

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_io_group(self, parent_layout: QVBoxLayout) -> None:
        group = QGroupBox("I/O Configuration")
        layout = QFormLayout(group)

        self.output_dir = QLineEdit()
        layout.addRow(
            "Output directory:",
            make_path_row(self.output_dir, "Browse", lambda: browse_directory(self, self.output_dir)),
        )

        parent_layout.addWidget(group)

    def _build_microstructure_group(self, parent_layout: QVBoxLayout) -> None:
        group = QGroupBox("Microstructure analysis")
        layout = QFormLayout(group)

        self.analysis_input = QLineEdit()
        layout.addRow("Input:", self._browse_row(self.analysis_input))

        self.rmsd_cutoff = NoWheelDoubleSpinBox()
        self.rmsd_cutoff.setRange(0.0, 1_000_000.0)
        self.rmsd_cutoff.setDecimals(4)
        self.rmsd_cutoff.setValue(0.1)
        layout.addRow("rmsd cutoff:", self.rmsd_cutoff)

        self.min_grain_size = NoWheelSpinBox()
        self.min_grain_size.setRange(0, 1_000_000_000)
        self.min_grain_size.setValue(100)
        layout.addRow("min grain size:", self.min_grain_size)

        self.analysis_btn = make_primary_button("Analyze")
        self.stop_analysis_btn = make_stop_button()
        self.analysis_btn.clicked.connect(self._run_microstructure_analysis)
        self.stop_analysis_btn.clicked.connect(self._stop_calculation)
        layout.addRow("", self._button_row(self.analysis_btn, self.stop_analysis_btn))

        self._calc_btns.append(self.analysis_btn)
        self._stop_btns.append(self.stop_analysis_btn)
        parent_layout.addWidget(group)

    def _build_continuum_group(self, parent_layout: QVBoxLayout) -> None:
        group = QGroupBox("Continuum model generation")
        layout = QVBoxLayout(group)

        self.grain_inputs_layout = QVBoxLayout()
        layout.addLayout(self.grain_inputs_layout)
        self._add_grain_input()

        add_grain_btn = make_action_button("Add more input file grains", "add")
        add_grain_btn.clicked.connect(self._add_grain_input)
        layout.addWidget(add_grain_btn)

        self.nongrain_inputs_layout = QVBoxLayout()
        layout.addLayout(self.nongrain_inputs_layout)
        self._add_nongrain_input()

        add_nongrain_btn = make_action_button("Add more input file nongrains", "add")
        add_nongrain_btn.clicked.connect(self._add_nongrain_input)
        layout.addWidget(add_nongrain_btn)

        reps_group = QGroupBox("Repetitions")
        reps_layout = QFormLayout(reps_group)
        self.rep_x = self._positive_int_spinbox(1)
        self.rep_y = self._positive_int_spinbox(1)
        self.rep_z = self._positive_int_spinbox(1)
        reps_layout.addRow("rep x:", self.rep_x)
        reps_layout.addRow("rep y:", self.rep_y)
        reps_layout.addRow("rep z:", self.rep_z)
        layout.addWidget(reps_group)

        method_group = QGroupBox("Method")
        method_layout = QVBoxLayout(method_group)
        self.method = NoWheelComboBox()
        self.method.addItem("alpha shape", "alpha_shape")
        self.method.addItem("gaussian", "gaussian")
        self.method.currentIndexChanged.connect(self._sync_method_params)
        method_layout.addWidget(self.method)

        self.method_params_stack = QStackedWidget()
        self.method_params_stack.addWidget(self._build_alpha_shape_params())
        self.method_params_stack.addWidget(self._build_gaussian_params())
        method_layout.addWidget(self.method_params_stack)
        layout.addWidget(method_group)

        self.generate_btn = make_primary_button("Generate")
        self.stop_generate_btn = make_stop_button()
        self.generate_btn.clicked.connect(self._run_continuum_generation)
        self.stop_generate_btn.clicked.connect(self._stop_calculation)
        layout.addLayout(self._button_row(self.generate_btn, self.stop_generate_btn))

        self._calc_btns.append(self.generate_btn)
        self._stop_btns.append(self.stop_generate_btn)
        parent_layout.addWidget(group)

    def _build_visualization(self) -> QWidget:
        container = QFrame()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        layout.addWidget(stl_preview.build_mesh_preview_toolbar(self))

        self.mesh_preview_frame = QFrame()
        self.mesh_preview_frame.setMinimumSize(420, 340)
        apply_preview_panel(self.mesh_preview_frame)
        preview_layout = QVBoxLayout(self.mesh_preview_frame)

        self.mesh_viz_label = QLabel(
            "3D view of the generated STL meshes\n\nRun continuum generation to preview results."
        )
        self.mesh_viz_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.mesh_viz_label.setWordWrap(True)
        apply_preview_placeholder(self.mesh_viz_label)
        preview_layout.addWidget(self.mesh_viz_label)

        self.mesh_viewer = MeshViewer(self.mesh_preview_frame)
        self.mesh_viewer.hide()
        preview_layout.addWidget(self.mesh_viewer)

        layout.addWidget(self.mesh_preview_frame, 1)
        return container

    def _build_alpha_shape_params(self) -> QWidget:
        group = QWidget()
        layout = QFormLayout(group)

        self.alpha_radius = NoWheelDoubleSpinBox()
        self.alpha_radius.setRange(0.0, 1_000_000.0)
        self.alpha_radius.setDecimals(4)
        self.alpha_radius.setValue(2.5)
        layout.addRow("radius:", self.alpha_radius)

        self.alpha_smoothing_level = NoWheelSpinBox()
        self.alpha_smoothing_level.setRange(0, 1_000_000)
        self.alpha_smoothing_level.setValue(1)
        layout.addRow("smoothing level:", self.alpha_smoothing_level)
        return group

    def _build_gaussian_params(self) -> QWidget:
        group = QWidget()
        layout = QFormLayout(group)

        self.gaussian_grid_resolution = self._positive_int_spinbox(200)
        layout.addRow("grid resolution:", self.gaussian_grid_resolution)

        self.gaussian_radius_scaling = NoWheelDoubleSpinBox()
        self.gaussian_radius_scaling.setRange(0.0, 10_000.0)
        self.gaussian_radius_scaling.setSuffix(" %")
        self.gaussian_radius_scaling.setDecimals(3)
        self.gaussian_radius_scaling.setValue(100.0)
        layout.addRow("radius scaling:", self.gaussian_radius_scaling)

        self.gaussian_isolevel = NoWheelDoubleSpinBox()
        self.gaussian_isolevel.setRange(-1_000_000.0, 1_000_000.0)
        self.gaussian_isolevel.setDecimals(6)
        self.gaussian_isolevel.setValue(0.6)
        layout.addRow("isolevel:", self.gaussian_isolevel)
        return group

    def _browse_row(self, line_edit: QLineEdit) -> QWidget:
        file_filter = "Atomistic files (*.xyz *.lammps *.lmp *.dump *.cif);;All files (*)"
        return make_path_row(line_edit, "Browse", lambda: browse_file(self, line_edit, file_filter))

    def _button_row(self, calc_btn: QPushButton, stop_btn: QPushButton) -> QHBoxLayout:
        row = QHBoxLayout()
        row.addWidget(calc_btn)
        row.addWidget(stop_btn)
        row.addStretch()
        return row

    def _positive_int_spinbox(self, value: int) -> NoWheelSpinBox:
        spinbox = NoWheelSpinBox()
        spinbox.setRange(1, 1_000_000_000)
        spinbox.setValue(value)
        return spinbox

    def _add_grain_input(self) -> None:
        self._add_file_input(
            self.grain_inputs,
            self.grain_input_rows,
            self.grain_inputs_layout,
            "input_file_grains",
        )

    def _add_nongrain_input(self) -> None:
        self._add_file_input(
            self.nongrain_inputs,
            self.nongrain_input_rows,
            self.nongrain_inputs_layout,
            "input_file_nongrains",
        )

    def _add_file_input(
        self,
        inputs: list[QLineEdit],
        rows: list[tuple[QWidget, QLabel, QLineEdit, QPushButton]],
        layout: QVBoxLayout,
        label_prefix: str,
    ) -> None:
        line_edit = QLineEdit()
        row, label, remove_btn = self._labeled_file_row(
            line_edit,
            lambda: self._remove_file_input(inputs, rows, layout, label_prefix, line_edit),
        )
        inputs.append(line_edit)
        rows.append((row, label, line_edit, remove_btn))
        layout.addWidget(row)
        self._sync_file_input_rows(rows, label_prefix)

    def _remove_file_input(
        self,
        inputs: list[QLineEdit],
        rows: list[tuple[QWidget, QLabel, QLineEdit, QPushButton]],
        layout: QVBoxLayout,
        label_prefix: str,
        line_edit: QLineEdit,
    ) -> None:
        if len(inputs) <= 1:
            return

        index = inputs.index(line_edit)
        row = rows[index][0]
        inputs.pop(index)
        rows.pop(index)
        layout.removeWidget(row)
        row.deleteLater()
        self._sync_file_input_rows(rows, label_prefix)

    def _sync_file_input_rows(
        self,
        rows: list[tuple[QWidget, QLabel, QLineEdit, QPushButton]],
        label_prefix: str,
    ) -> None:
        can_remove = len(rows) > 1
        for index, (_row, label, _line_edit, remove_btn) in enumerate(rows, start=1):
            label.setText(f"{label_prefix.replace('_', ' ')} {index}:")
            remove_btn.setEnabled(can_remove)

    def _labeled_file_row(
        self,
        line_edit: QLineEdit,
        remove_callback: Callable[[], None],
    ) -> tuple[QWidget, QLabel, QPushButton]:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        label_widget = QLabel()
        layout.addWidget(label_widget)
        layout.addWidget(line_edit)

        file_filter = "Continuum input files (*.txt *.dat *.xyz *.lmp);;All files (*)"
        btn = make_action_button("Browse", "browse")
        btn.clicked.connect(lambda: browse_file(self, line_edit, file_filter))
        layout.addWidget(btn)

        remove_btn = make_action_button("Remove", "remove")
        remove_btn.clicked.connect(remove_callback)
        layout.addWidget(remove_btn)
        return row, label_widget, remove_btn

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    def _sync_method_params(self, index: int) -> None:
        self.method_params_stack.setCurrentIndex(index)

    def _run_microstructure_analysis(self) -> None:
        input_path = self.analysis_input.text().strip()
        if not self._validate_input_file(input_path):
            return
        output_dir = self.output_dir.text().strip()
        if not self._validate_output_dir(output_dir):
            return

        params = {
            "input_file": input_path,
            "rmsd_cutoff": self.rmsd_cutoff.value(),
            "min_grain_size": self.min_grain_size.value(),
        }
        param_file = os.path.join(output_dir, "input_micro_analysis.txt")
        self._write_and_run(
            param_file,
            params,
            ("..", "atomistic_to_continuum", "micro_analysis.py"),
            output_dir,
            self._make_finish_callback("Microstructure analysis"),
        )

    def _run_continuum_generation(self) -> None:
        grain_paths = self._paths_from_inputs(self.grain_inputs)
        nongrain_paths = self._paths_from_inputs(self.nongrain_inputs)

        if not self._validate_file_group(grain_paths, "input file grains"):
            return
        if not self._validate_file_group(nongrain_paths, "input file nongrains"):
            return
        output_dir = self.output_dir.text().strip()
        if not self._validate_output_dir(output_dir):
            return

        params = {
            "rep_x": self.rep_x.value(),
            "rep_y": self.rep_y.value(),
            "rep_z": self.rep_z.value(),
            "method": self.method.currentData() or self.method.currentText(),
            **self._method_params(),
        }
        params.update({f"input_file_grains_{i}": path for i, path in enumerate(grain_paths, start=1)})
        params.update({f"input_file_nongrains_{i}": path for i, path in enumerate(nongrain_paths, start=1)})

        param_file = os.path.join(output_dir, "input_mesh_generation.txt")
        self._write_and_run(
            param_file,
            params,
            ("..", "atomistic_to_continuum", "mesh_generation.py"),
            output_dir,
            self._make_finish_callback(
                "Continuum generation",
                lambda: self._refresh_mesh_visualization(output_dir),
            ),
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _paths_from_inputs(self, inputs: list[QLineEdit]) -> list[str]:
        return [line_edit.text().strip() for line_edit in inputs if line_edit.text().strip()]

    def _validate_file_group(self, paths: list[str], label: str) -> bool:
        if not paths:
            self.logger.log_message("ERROR", f"Please choose at least one {label} file first.")
            return False

        for path in paths:
            if not os.path.isfile(path):
                self.logger.log_message("ERROR", f"File not found:\n{path}")
                return False
        return True

    def _method_params(self) -> dict[str, float | int]:
        if (self.method.currentData() or self.method.currentText()) == "alpha_shape":
            return {
                "radius": self.alpha_radius.value(),
                "smoothing_level": self.alpha_smoothing_level.value(),
            }

        return {
            "grid_resolution": self.gaussian_grid_resolution.value(),
            "radius_scaling": self.gaussian_radius_scaling.value(),
            "isolevel": self.gaussian_isolevel.value(),
        }

    # ------------------------------------------------------------------
    # Mesh preview
    # ------------------------------------------------------------------

    def _collect_generated_meshes(self, output_dir: str) -> list[str]:
        if not output_dir or not os.path.isdir(output_dir):
            return []

        paths = []
        for _label, filename in GENERATED_MESHES:
            path = os.path.join(output_dir, filename)
            if os.path.isfile(path):
                paths.append(path)
        return paths

    def _refresh_mesh_visualization(self, output_dir: str) -> None:
        paths = self._collect_generated_meshes(output_dir)
        self._set_mesh_choices(paths)
        if not paths:
            self.mesh_viewer.clear()
            self.mesh_viewer.hide()
            self.mesh_viz_label.setText("No generated STL meshes found.")
            self.mesh_viz_label.show()
            self.logger.log_message("WARNING", f"No generated STL meshes found in:\n{output_dir}")
            return

        self._load_mesh_preview(paths[0])

    def _set_mesh_choices(self, paths: list[str]) -> None:
        stl_preview.set_mesh_choices(self, paths, self._mesh_label_for_path, "STL mesh", "STL meshes")

    def _load_mesh_preview(self, path: str) -> None:
        stl_preview.load_mesh_preview(self, path, QApplication.processEvents)

    def _mesh_label_for_path(self, path: str) -> str:
        filename = Path(path).name
        for label, expected_filename in GENERATED_MESHES:
            if filename.lower() == expected_filename.lower():
                return f"{label} - {filename}"
        return filename


if __name__ == "__main__":
    import sys

    from multibest.gui.utils.qt_bootstrap import force_x11_if_wayland

    force_x11_if_wayland()

    app = QApplication(sys.argv)
    apply_dark_theme(app)
    window = AtomisticToContinuumWindow()
    window.show()
    sys.exit(app.exec())

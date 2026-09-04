# SPDX-FileCopyrightText: 2026 bright-ideas-clan
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Mesh Modification GUI Application.

Provides the control surface for importing a mesh, configuring refinement and
smoothing options, and previewing the generated mesh.
"""

from __future__ import annotations

import os

from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressDialog,
    QVBoxLayout,
)

from multibest.gui.utils import blender_controls
from multibest.gui.utils.base_window import BaseModuleWindow
from multibest.gui.utils.general import browse_directory, browse_file, create_file
from multibest.gui.utils.mesh_viewer import MeshViewer
from multibest.gui.utils.theme import (
    NoWheelComboBox,
    NoWheelDoubleSpinBox,
    NoWheelSpinBox,
    apply_dark_theme,
    apply_module_title,
    apply_preview_panel,
    apply_preview_placeholder,
    make_path_row,
    make_primary_button,
    make_stop_button,
)
from multibest.utils.blender import (
    BlenderError,
    blender_version,
    bundled_blender,
    discover_blender,
    get_download_info,
    install_blender,
    validate_blender,
)

MESH_FILE_FILTER = "Mesh files (*.obj *.stl *.ply *.vtk *.vtp);;All files (*)"
OUTPUT_MESH_FILE_FILTER = "Mesh files (*.obj *.stl *.ply);;All files (*)"
BLENDER_SETTINGS_KEY = "mesh_modification/blender_exec"
INPUT_FILE_NAME = "input_mesh_modification.txt"


class MeshModificationWindow(BaseModuleWindow):
    """Main window for the Mesh Modification module."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Mesh Modification")
        self.resize(900, 600)

        self._mesh_path = ""
        self._generated_mesh_path = ""

        main_layout, left_layout = self._build_split_layout()

        header = QLabel("Mesh modification")
        apply_module_title(header)
        left_layout.addWidget(header)

        left_layout.addWidget(self._build_import_group())
        left_layout.addWidget(self._build_refinement_group())
        left_layout.addWidget(self._build_smoothing_group())
        left_layout.addWidget(self._build_blender_group())
        left_layout.addStretch()

        self.apply_btn = make_primary_button("Apply Modification")
        self.stop_btn = make_stop_button()
        self.apply_btn.clicked.connect(self._run_mesh_modification)
        self.stop_btn.clicked.connect(self._stop_calculation)

        btn_row = QHBoxLayout()
        btn_row.addWidget(self.apply_btn)
        btn_row.addWidget(self.stop_btn)
        btn_row.addStretch()
        left_layout.addLayout(btn_row)

        self._calc_btns = [self.apply_btn]
        self._stop_btns = [self.stop_btn]

        self.right_container = QFrame()
        self.right_layout = QVBoxLayout(self.right_container)
        self.right_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.addWidget(self.right_container, 2)

        self.preview_frame = QFrame()
        self.preview_frame.setMinimumSize(360, 300)
        apply_preview_panel(self.preview_frame)
        preview_layout = QVBoxLayout(self.preview_frame)

        self.preview_label = QLabel("3D view of the generated mesh")
        self.preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_label.setWordWrap(True)
        apply_preview_placeholder(self.preview_label)
        preview_layout.addWidget(self.preview_label)

        self.mesh_viewer = MeshViewer(self.preview_frame)
        self.mesh_viewer.hide()
        preview_layout.addWidget(self.mesh_viewer)

        self.right_layout.addWidget(self.preview_frame)
        self.right_layout.addStretch()

        self.control_widget = self.left_scroll
        self.viz_widget = self.right_container
        self._refresh_blender_status()

    def _build_import_group(self) -> QGroupBox:
        group = QGroupBox("Mesh Input")
        layout = QFormLayout(group)

        self.mesh_input = QLineEdit()
        self.mesh_input.setPlaceholderText("/path/to/mesh")
        self.mesh_input.editingFinished.connect(self._sync_imported_mesh)

        layout.addRow(
            "Mesh file:",
            make_path_row(
                self.mesh_input,
                "Import Mesh",
                lambda: browse_file(self, self.mesh_input, MESH_FILE_FILTER),
                action="import",
            ),
        )

        return group

    def _build_refinement_group(self) -> QGroupBox:
        group = QGroupBox("Refinement")
        layout = QFormLayout(group)

        self.refinement = NoWheelSpinBox()
        self.refinement.setRange(0, 1000)
        self.refinement.setValue(0)
        layout.addRow("Refinement:", self.refinement)

        self.start_voxel = NoWheelDoubleSpinBox()
        self.start_voxel.setRange(0.0, 1_000_000.0)
        self.start_voxel.setDecimals(6)
        self.start_voxel.setValue(1.0)
        layout.addRow("Start voxel:", self.start_voxel)

        self.step = NoWheelDoubleSpinBox()
        self.step.setRange(0.0, 1_000_000.0)
        self.step.setDecimals(6)
        self.step.setValue(0.1)
        layout.addRow("Step:", self.step)

        return group

    def _build_blender_group(self) -> QGroupBox:
        return blender_controls.build_blender_group(self, BLENDER_SETTINGS_KEY, bundled_blender)

    def _build_smoothing_group(self) -> QGroupBox:
        group = QGroupBox("Smoothing")
        layout = QFormLayout(group)

        self.iterations = NoWheelSpinBox()
        self.iterations.setRange(0, 1000)
        self.iterations.setValue(10)
        layout.addRow("Iterations:", self.iterations)

        self.smoothing = NoWheelSpinBox()
        self.smoothing.setRange(0, 1000)
        self.smoothing.setValue(1)
        layout.addRow("Smoothing:", self.smoothing)

        self.smoothing_method = NoWheelComboBox()
        self.smoothing_method.addItems(["Taubin", "Pymeshlab", "Blender"])
        layout.addRow("Smoothing method:", self.smoothing_method)

        self.fill_hole_threshold = NoWheelDoubleSpinBox()
        self.fill_hole_threshold.setRange(0.0, 1_000_000.0)
        self.fill_hole_threshold.setDecimals(6)
        layout.addRow("Fill hole threshold:", self.fill_hole_threshold)

        self.output_file = QLineEdit()
        self.output_file.setPlaceholderText("/path/to/generated_mesh.obj")
        layout.addRow(
            "Output file:",
            make_path_row(
                self.output_file,
                "Browse",
                lambda: create_file(self, self.output_file, OUTPUT_MESH_FILE_FILTER),
                action="save",
            ),
        )

        self.output_dir = QLineEdit()
        self.output_dir.setPlaceholderText("/path/to/output/directory")
        layout.addRow(
            "Output directory:",
            make_path_row(self.output_dir, "Browse", lambda: browse_directory(self, self.output_dir)),
        )

        return group

    def _sync_imported_mesh(self) -> None:
        """Record the currently selected mesh path and update the preview."""
        mesh_path = self.mesh_input.text().strip()
        if not mesh_path:
            self._mesh_path = ""
            self._generated_mesh_path = ""
            self._clear_preview()
            return

        if os.path.isfile(mesh_path):
            self._mesh_path = mesh_path
            self._generated_mesh_path = mesh_path
            self._load_mesh_preview(mesh_path, "Imported mesh")

    def _collect_parameters(self) -> dict[str, str | int | float | bool]:
        """Return the current mesh modification parameters."""
        return {
            "mesh_file": self.mesh_input.text().strip(),
            "output_file": self.output_file.text().strip(),
            "output_dir": self.output_dir.text().strip(),
            "refinement": self.refinement.value(),
            "apply_refine": self.refinement.value() > 0,
            "start_voxel": self.start_voxel.value(),
            "step": self.step.value(),
            "iterations": self.iterations.value(),
            "smoothing": self.smoothing.value(),
            "smoothing_method": self.smoothing_method.currentText(),
            "fill_hole_threshold": self.fill_hole_threshold.value(),
            "blender_exec": self.blender_exec.text().strip(),
        }

    def _run_mesh_modification(self) -> None:
        """Validate inputs and launch the mesh modification backend."""
        mesh_path = self.mesh_input.text().strip()
        output_path = self.output_file.text().strip()
        output_dir = self.output_dir.text().strip()
        if not self._validate_input_file(mesh_path):
            return
        if not output_path:
            self.logger.log_message("ERROR", "Please choose an output file first.")
            return
        if not self._validate_output_dir(output_dir):
            return

        output_path = self._resolve_to_outdir(self.output_file, output_dir)

        params = self._collect_parameters()
        blender_exec = self._resolve_blender_for_run(params)
        if blender_exec is None and self._needs_blender(params):
            return
        if blender_exec:
            params["blender_exec"] = blender_exec

        self._mesh_path = mesh_path
        self._generated_mesh_path = output_path
        self.logger.log_message("INFO", f"Mesh modification parameters: {params}")

        param_file = os.path.join(output_dir, INPUT_FILE_NAME)
        self._write_and_run(
            param_file,
            params,
            ("..", "mesh_modification", "Mesh_Modification.py"),
            output_dir,
            self._make_finish_callback("Mesh modification", self._plot_mesh_modification),
            extra_args=["--input-file"],
        )

    def _settings(self) -> QSettings:
        return QSettings("MultiBEST", "MultiBEST")

    def _save_blender_path(self) -> None:
        blender_controls.save_blender_path(self, BLENDER_SETTINGS_KEY)

    def _browse_blender_exec(self) -> None:
        blender_controls.browse_blender_exec(self, QFileDialog.getOpenFileName)

    def _refresh_blender_status(self) -> None:
        blender_controls.refresh_blender_status(
            self,
            "Not found. Blender is only required for refinement or Blender smoothing.",
            bundled_blender,
            discover_blender,
        )

    def _test_blender_exec(self) -> None:
        blender_controls.test_blender_exec(self, discover_blender, blender_version, BlenderError)

    def _download_blender(self) -> None:
        blender_controls.download_blender(
            self,
            get_download_info,
            install_blender,
            BlenderError,
            QMessageBox,
            QProgressDialog,
            QApplication.processEvents,
        )

    def _needs_blender(self, params: dict[str, str | int | float | bool]) -> bool:
        if int(params["refinement"]) > 0:
            return True
        return int(params["smoothing"]) > 0 and str(params["smoothing_method"]).lower() == "blender"

    def _resolve_blender_for_run(self, params: dict[str, str | int | float | bool]) -> str | None:
        selected_path = str(params.get("blender_exec") or "")
        needs_blender = self._needs_blender(params)
        if not selected_path and not needs_blender:
            return None

        blender_exec = bundled_blender() or discover_blender(selected_path)
        if blender_exec and validate_blender(blender_exec):
            self.blender_exec.setText(str(blender_exec))
            self._save_blender_path()
            return str(blender_exec)

        if needs_blender:
            self.logger.log_message(
                "ERROR",
                "Blender is required for refinement or Blender smoothing. "
                "Choose an executable or use the Download button.",
            )
        return None

    def _plot_mesh_modification(self) -> None:
        """Load the generated mesh into the preview area."""
        output_path = self.output_file.text().strip()
        if output_path and not os.path.isfile(output_path):
            output_dir = self.output_dir.text().strip()
            if output_dir:
                resolved = os.path.join(output_dir, os.path.basename(output_path))
                if os.path.isfile(resolved):
                    output_path = resolved

        if not output_path or not os.path.isfile(output_path):
            self.logger.log_message("ERROR", f"Output mesh not found:\n{output_path}")
            return

        self._generated_mesh_path = output_path
        self._load_mesh_preview(output_path, "Generated mesh preview")

    def _load_mesh_preview(self, mesh_path: str, title: str) -> None:
        """Load *mesh_path* into the VTK preview area."""
        try:
            self.preview_label.hide()
            self.mesh_viewer.show()
            QApplication.processEvents()
            self.mesh_viewer.load_mesh(mesh_path)
        except (OSError, ValueError, RuntimeError) as exc:
            self.mesh_viewer.hide()
            self.preview_label.show()
            self.preview_label.setText(f"{title} unavailable:\n{exc}")
            self.logger.log_message("ERROR", f"Failed to visualize mesh:\n{exc}")
            return

        self.preview_label.setText(f"{title}:\n{os.path.basename(mesh_path)}")
        self.preview_label.hide()
        self.mesh_viewer.show()

    def _clear_preview(self) -> None:
        """Reset the VTK preview to its empty placeholder state."""
        self.mesh_viewer.clear()
        self.mesh_viewer.hide()
        self.preview_label.setText("3D view of the generated mesh")
        self.preview_label.show()


if __name__ == "__main__":
    import sys

    from multibest.gui.utils.qt_bootstrap import force_x11_if_wayland

    force_x11_if_wayland()

    app = QApplication(sys.argv)
    apply_dark_theme(app)
    window = MeshModificationWindow()
    window.show()
    sys.exit(app.exec())

# SPDX-FileCopyrightText: 2026 bright-ideas-clan
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Image-to-mesh GUI module."""

from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
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
    QWidget,
)

from multibest.gui.utils import blender_controls
from multibest.gui.utils.base_window import BaseModuleWindow
from multibest.gui.utils.general import (
    browse_directory,
    browse_file,
    create_file,
    get_base_dir,
    get_script_path,
    is_pyinstaller,
)
from multibest.gui.utils.mesh_viewer import MeshViewer
from multibest.gui.utils.theme import (
    NoWheelComboBox,
    NoWheelDoubleSpinBox,
    apply_dark_theme,
    apply_module_title,
    apply_preview_panel,
    apply_preview_placeholder,
    apply_subtle_text,
    make_action_button,
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

IMAGE_FILE_FILTER = "Images (*.png *.jpg *.jpeg *.bmp *.tif *.tiff);;All files (*)"
MESH_FILE_FILTER = "Mesh files (*.obj *.stl *.ply *.vtk *.vtp *.fbx);;All files (*)"
OUTPUT_MESH_FILE_FILTER = "Mesh files (*.obj *.stl *.ply);;All files (*)"
BLENDER_SETTINGS_KEY = "image_to_mesh/blender_exec"
GENERATED_MESH_TITLE = "Generated mesh"
PHASE_FILE_STEMS = {
    "Guest": "Guest_Phase",
    "Base": "Base_Phase",
    "Bulk": "Bulk_Phase",
}


class ImageToMeshWindow(BaseModuleWindow):
    """Main window for image-derived phase mesh generation and transforms."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Image To Mesh")
        self.resize(1000, 680)

        self._last_preview_path = ""
        self._generated_mesh_paths: dict[str, str] = {}

        main_layout, left_layout = self._build_split_layout()

        header = QLabel("Image to mesh")
        apply_module_title(header)
        left_layout.addWidget(header)

        left_layout.addWidget(self._build_mode_group())
        left_layout.addWidget(self._build_existing_mesh_group())
        left_layout.addWidget(self._build_generation_group())
        left_layout.addWidget(self._build_transform_group())
        left_layout.addWidget(self._build_blender_group())
        left_layout.addStretch()

        self.stop_btn = make_stop_button()
        self.stop_btn.clicked.connect(self._stop_calculation)

        btn_row = QHBoxLayout()
        btn_row.addWidget(self.stop_btn)
        btn_row.addStretch()
        left_layout.addLayout(btn_row)

        self._calc_btns = [self.run_btn, self.rescale_btn]
        self._stop_btns = [self.stop_btn]

        self.right_container = QFrame()
        self.right_layout = QVBoxLayout(self.right_container)
        self.right_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.addWidget(self.right_container, 2)

        self.preview_toolbar = QFrame()
        toolbar_layout = QHBoxLayout(self.preview_toolbar)
        toolbar_layout.setContentsMargins(0, 0, 0, 8)
        toolbar_layout.setSpacing(10)

        toolbar_label = QLabel("Preview mesh")
        toolbar_layout.addWidget(toolbar_label)

        self.preview_mesh_selector = NoWheelComboBox()
        self.preview_mesh_selector.setMinimumWidth(180)
        self.preview_mesh_selector.currentIndexChanged.connect(self._on_preview_mesh_selected)
        toolbar_layout.addWidget(self.preview_mesh_selector, 1)

        self.preview_mesh_count = QLabel("")
        apply_subtle_text(self.preview_mesh_count)
        toolbar_layout.addWidget(self.preview_mesh_count)

        reset_view_btn = make_action_button("Reset View", "reset")
        reset_view_btn.clicked.connect(self._reset_preview_camera)
        toolbar_layout.addWidget(reset_view_btn)

        self.right_layout.addWidget(self.preview_toolbar)
        self.preview_toolbar.hide()

        self.preview_frame = QFrame()
        self.preview_frame.setMinimumSize(420, 340)
        apply_preview_panel(self.preview_frame)
        preview_layout = QVBoxLayout(self.preview_frame)

        self.preview_label = QLabel(
            "3D view of the generated mesh\n\nThe exported mesh path and dimensions will appear here after a run."
        )
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

        self.generate_from_image.toggled.connect(self._sync_mode_ui)
        for checkbox in (self.phase_bulk, self.phase_guest, self.phase_base):
            checkbox.toggled.connect(self._sync_phase_choices)
        self.existing_mesh.editingFinished.connect(self._sync_existing_mesh_preview)
        self.transform_phase.currentIndexChanged.connect(self._on_transform_phase_changed)

        self._sync_phase_choices()
        self._sync_mode_ui(self.generate_from_image.isChecked())
        self._refresh_blender_status()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_mode_group(self) -> QGroupBox:
        group = QGroupBox("Workflow")
        layout = QVBoxLayout(group)

        self.generate_from_image = QCheckBox("Generate meshes from image")
        self.generate_from_image.setChecked(True)
        self.generate_from_image.setMinimumHeight(36)
        layout.addWidget(self.generate_from_image)

        note = QLabel(
            "Checked: generate phase meshes from an image, then optionally rescale one below. "
            "Unchecked: rescale an existing mesh."
        )
        note.setWordWrap(True)
        apply_subtle_text(note)
        layout.addWidget(note)
        return group

    def _build_existing_mesh_group(self) -> QGroupBox:
        group = QGroupBox("Existing Mesh")
        self._existing_mesh_group = group
        layout = QFormLayout(group)

        self.existing_mesh = QLineEdit()
        self.existing_mesh.setPlaceholderText("/path/to/mesh")
        layout.addRow(
            "Mesh file:",
            make_path_row(
                self.existing_mesh,
                "Browse",
                lambda: browse_file(self, self.existing_mesh, MESH_FILE_FILTER),
            ),
        )
        return group

    def _build_generation_group(self) -> QGroupBox:
        group = QGroupBox("Step 1 - Generate Phase Meshes")
        self._generation_group = group
        layout = QFormLayout(group)

        self.image_input = QLineEdit()
        self.image_input.setPlaceholderText("/path/to/binary_image.png")
        layout.addRow(
            "Image:",
            make_path_row(
                self.image_input,
                "Import Image",
                lambda: browse_file(self, self.image_input, IMAGE_FILE_FILTER),
                action="import",
            ),
        )

        self.generation_out_dir = QLineEdit()
        self.generation_out_dir.setPlaceholderText("/path/to/Output_mesh")
        layout.addRow(
            "Output directory:",
            make_path_row(
                self.generation_out_dir,
                "Browse",
                lambda: browse_directory(self, self.generation_out_dir),
            ),
        )

        self.phase_bulk = self._phase_checkbox("Bulk", True)
        self.phase_guest = self._phase_checkbox("Guest", True)
        self.phase_base = self._phase_checkbox("Base", True)
        phase_row = QVBoxLayout()
        phase_row.addWidget(self.phase_bulk)
        phase_row.addWidget(self.phase_guest)
        phase_row.addWidget(self.phase_base)
        layout.addRow("Phases:", phase_row)

        self.vertices = NoWheelComboBox()
        for label, value in (
            ("coarse", "coarse"),
            ("normal", "normal"),
            ("fine", "fine"),
            ("extra fine", "extra_fine"),
        ):
            self.vertices.addItem(label, value)
        self.vertices.setCurrentIndex(self.vertices.findData("fine"))
        layout.addRow("Vertices:", self.vertices)

        self.depth = NoWheelDoubleSpinBox()
        self.depth.setRange(0.0, 1_000_000.0)
        self.depth.setDecimals(6)
        self.depth.setValue(0.25)
        layout.addRow("Depth:", self.depth)

        self.export_format = NoWheelComboBox()
        self.export_format.addItems(["STL", "OBJ", "FBX"])
        layout.addRow("Mesh format:", self.export_format)

        self.run_btn = make_primary_button("Generate Meshes")
        self.run_btn.clicked.connect(self._run_generation)
        layout.addRow("", self.run_btn)

        return group

    def _build_transform_group(self) -> QGroupBox:
        group = QGroupBox("Step 2 - Rescale / Transform Mesh")
        layout = QFormLayout(group)

        self.transform_phase = NoWheelComboBox()
        layout.addRow("Generated mesh:", self.transform_phase)
        self.transform_phase_label = layout.labelForField(self.transform_phase)

        self.output_mesh = QLineEdit()
        self.output_mesh.setPlaceholderText("/path/to/export/rescaled_mesh.obj")
        layout.addRow(
            "Export mesh:",
            make_path_row(
                self.output_mesh,
                "Browse",
                lambda: create_file(self, self.output_mesh, OUTPUT_MESH_FILE_FILTER),
                action="save",
            ),
        )

        self.rotate_alpha = self._operator_spin(-360.0, 360.0, 0.0)
        self.rotate_beta = self._operator_spin(-360.0, 360.0, 0.0)
        self.rotate_gamma = self._operator_spin(-360.0, 360.0, 0.0)
        layout.addRow(
            "Rotate alpha/beta/gamma:",
            self._triple_row(self.rotate_alpha, self.rotate_beta, self.rotate_gamma),
        )

        self.displace_x = self._operator_spin(-1_000_000.0, 1_000_000.0, 0.0)
        self.displace_y = self._operator_spin(-1_000_000.0, 1_000_000.0, 0.0)
        self.displace_z = self._operator_spin(-1_000_000.0, 1_000_000.0, 0.0)
        layout.addRow("Displace x/y/z:", self._triple_row(self.displace_x, self.displace_y, self.displace_z))

        self.scale_x = self._operator_spin(-1_000_000.0, 1_000_000.0, 1.0)
        self.scale_y = self._operator_spin(-1_000_000.0, 1_000_000.0, 1.0)
        self.scale_z = self._operator_spin(-1_000_000.0, 1_000_000.0, 1.0)
        layout.addRow("Scale x/y/z:", self._triple_row(self.scale_x, self.scale_y, self.scale_z))

        self.rescale_btn = make_primary_button("Rescale / Export Mesh")
        self.rescale_btn.clicked.connect(self._run_selected_rescale)
        layout.addRow("", self.rescale_btn)
        return group

    def _build_blender_group(self) -> QGroupBox:
        return blender_controls.build_blender_group(self, BLENDER_SETTINGS_KEY, bundled_blender)

    # ------------------------------------------------------------------
    # Run flow
    # ------------------------------------------------------------------

    def _run_image_to_mesh(self) -> None:
        """Generate meshes from the selected image.

        Kept as a small compatibility wrapper for callers that used the
        previous combined generate/export action.
        """
        self._run_generation()

    def _run_selected_rescale(self) -> None:
        if self.generate_from_image.isChecked():
            input_mesh = self._selected_generated_mesh_path()
            if not input_mesh:
                self.logger.log_message("ERROR", "Generate and select a mesh before rescaling.")
                return
        else:
            self._clear_generated_mesh_choices()
            input_mesh = self.existing_mesh.text().strip()
        self._run_rescale(input_mesh, "Mesh rescaling")

    def _run_generation(self) -> None:
        image_path = self.image_input.text().strip()
        out_dir = self.generation_out_dir.text().strip()
        if not self._validate_input_file(image_path):
            return
        if not self._validate_output_dir(out_dir):
            return
        if not self._selected_phases():
            self.logger.log_message("ERROR", "Select at least one phase to generate.")
            return

        blender_exec = self._resolve_blender_for_run()
        if blender_exec is None:
            return

        script_path = self._blender_python_script_path()
        args = [
            "--background",
            "--python-exit-code",
            "1",
            "--python",
            script_path,
            "--",
            "--image",
            image_path,
            "--vertices",
            self.vertices.currentData() or self.vertices.currentText(),
            "--depth",
            str(self.depth.value()),
            "--format",
            self.export_format.currentText(),
            "--outdir",
            out_dir,
        ]
        for phase in self._selected_phases():
            args.append(f"--{phase.lower()}")
        self._set_running(True)
        self.runner.on_finished_cb = self._on_generation_finished
        self.logger.log_message("INFO", f"Running Blender image-to-mesh: {blender_exec} {' '.join(args)}")
        self.runner.start_program(str(blender_exec), args=args, cwd=out_dir)

    def _on_generation_finished(self, exit_code: int, exit_status: object) -> None:
        if exit_code != 0:
            self._set_running(False)
            self.logger.log_message("ERROR", f"Image-to-mesh generation failed with code {exit_code}.")
            return

        generated_meshes = self._collect_generated_meshes()
        selected_path = self._selected_generated_mesh_path()
        self._set_generated_mesh_choices(generated_meshes, selected_path)
        self.logger.log_message("INFO", "Image-to-mesh generation finished.")

        self._set_running(False)
        preview_path = selected_path or next(iter(generated_meshes.values()), "")
        if preview_path:
            self._load_mesh_preview(preview_path, self._preview_title_for_path(preview_path, GENERATED_MESH_TITLE))
        else:
            self.logger.log_message(
                "ERROR",
                "Image-to-mesh generation did not produce any selected mesh files. Check the Blender log above.",
            )

    def _run_rescale(self, input_mesh: str, operation_name: str, *, keep_running: bool = False) -> None:
        output_path = self.output_mesh.text().strip()
        if not self._validate_input_file(input_mesh):
            if keep_running:
                self._set_running(False)
            return
        if not output_path:
            self.logger.log_message("ERROR", "Please choose an export mesh path first.")
            if keep_running:
                self._set_running(False)
            return

        output_path = self._resolve_export_path(output_path, input_mesh)
        output_dir = os.path.dirname(output_path)
        if not self._validate_output_dir(output_dir):
            if keep_running:
                self._set_running(False)
            return
        self.output_mesh.setText(output_path)

        args = [
            "--input_mesh",
            input_mesh,
            "--scale_value",
            str(self.scale_x.value()),
            str(self.scale_y.value()),
            str(self.scale_z.value()),
            "--displace",
            str(self.displace_x.value()),
            str(self.displace_y.value()),
            str(self.displace_z.value()),
            "--output",
            output_path,
        ]
        args.extend(["--rotate", *self._rotation_args()])

        if not keep_running:
            self._set_running(True)
        self.runner.on_finished_cb = self._make_finish_callback(operation_name, self._plot_exported_mesh)
        script_path = get_script_path("..", "image_to_mesh", "rescale.py")
        self.logger.log_message("INFO", f"Running mesh operators: {script_path} {' '.join(args)}")
        self.runner.start(script_path, args=args, cwd=output_dir)

    # ------------------------------------------------------------------
    # State helpers
    # ------------------------------------------------------------------

    def _sync_mode_ui(self, generate: bool) -> None:
        self.existing_mesh_group.setVisible(not generate)
        self.generation_group.setVisible(generate)
        if not self._blender_bundled:
            self.blender_group.setVisible(generate)
        self.transform_phase.setVisible(generate)
        self.transform_phase_label.setVisible(generate)
        self.generate_from_image.setText(
            "Generate meshes from image: Yes" if generate else "Generate meshes from image: No"
        )
        self.run_btn.setVisible(generate)
        if not generate:
            self._clear_generated_mesh_choices()

    def _sync_phase_choices(self) -> None:
        current = self.transform_phase.currentText() if hasattr(self, "transform_phase") else ""
        self.transform_phase.clear()
        for phase in self._selected_phases():
            self.transform_phase.addItem(phase.capitalize())
        if current:
            index = self.transform_phase.findText(current)
            if index >= 0:
                self.transform_phase.setCurrentIndex(index)

    def _sync_existing_mesh_preview(self) -> None:
        mesh_path = self.existing_mesh.text().strip()
        if os.path.isfile(mesh_path):
            self._clear_generated_mesh_choices()
            self._load_mesh_preview(mesh_path, "Imported mesh")

    def _selected_phases(self) -> list[str]:
        phases = []
        if self.phase_bulk.isChecked():
            phases.append("bulk")
        if self.phase_guest.isChecked():
            phases.append("guest")
        if self.phase_base.isChecked():
            phases.append("base")
        return phases

    def _selected_generated_mesh_path(self) -> str:
        out_dir = self.generation_out_dir.text().strip()
        phase = self.transform_phase.currentText() or next((p.capitalize() for p in self._selected_phases()), "")
        path = self._generated_mesh_path_for_phase(phase, out_dir)
        return path if os.path.isfile(path) else ""

    def _generated_mesh_path_for_phase(self, phase: str, out_dir: str | None = None) -> str:
        out_dir = out_dir if out_dir is not None else self.generation_out_dir.text().strip()
        stem = PHASE_FILE_STEMS.get(phase, "")
        if not out_dir or not stem:
            return ""
        return os.path.join(out_dir, f"{stem}.{self.export_format.currentText().lower()}")

    def _collect_generated_meshes(self) -> dict[str, str]:
        meshes = {}
        out_dir = self.generation_out_dir.text().strip()
        for phase_key in self._selected_phases():
            phase = phase_key.capitalize()
            path = self._generated_mesh_path_for_phase(phase, out_dir)
            if os.path.isfile(path):
                meshes[phase] = path
        return meshes

    def _rotation_args(self) -> list[str]:
        rotations = []
        for axis, widget in (
            ("x", self.rotate_alpha),
            ("y", self.rotate_beta),
            ("z", self.rotate_gamma),
        ):
            rotations.extend([axis, str(widget.value())])
        return rotations

    def _resolve_export_path(self, output_path: str, input_mesh: str) -> str:
        if os.path.isabs(output_path):
            return output_path
        if self.generate_from_image.isChecked() and self.generation_out_dir.text().strip():
            base_dir = self.generation_out_dir.text().strip()
        else:
            base_dir = os.path.dirname(input_mesh) or os.getcwd()
        return os.path.abspath(os.path.join(base_dir, output_path))

    # ------------------------------------------------------------------
    # Blender helpers
    # ------------------------------------------------------------------

    def _settings(self) -> QSettings:
        return QSettings("MultiBEST", "MultiBEST")

    def _save_blender_path(self) -> None:
        blender_controls.save_blender_path(self, BLENDER_SETTINGS_KEY)

    def _browse_blender_exec(self) -> None:
        blender_controls.browse_blender_exec(self, QFileDialog.getOpenFileName)

    def _refresh_blender_status(self) -> None:
        blender_controls.refresh_blender_status(
            self,
            "Not found. Blender is required for image-to-mesh generation.",
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

    def _resolve_blender_for_run(self) -> str | None:
        blender_exec = bundled_blender() or discover_blender(self.blender_exec.text().strip())
        if blender_exec and validate_blender(blender_exec):
            self.blender_exec.setText(str(blender_exec))
            self._save_blender_path()
            return str(blender_exec)

        self.logger.log_message(
            "ERROR",
            "Blender is required for image-to-mesh generation. Choose an executable or use the Download button.",
        )
        return None

    @staticmethod
    def _blender_python_script_path() -> str:
        if is_pyinstaller():
            return os.path.join(get_base_dir(), "image_to_mesh", "Image_to_Mesh.py")
        return get_script_path("..", "image_to_mesh", "Image_to_Mesh.py")

    # ------------------------------------------------------------------
    # Preview helpers
    # ------------------------------------------------------------------

    def _plot_exported_mesh(self) -> None:
        output_path = self.output_mesh.text().strip()
        if not output_path or not os.path.isfile(output_path):
            self.logger.log_message("ERROR", f"Output mesh not found:\n{output_path}")
            return
        self._load_mesh_preview(output_path, "Exported mesh")

    def _set_generated_mesh_choices(self, meshes: dict[str, str], preferred_path: str = "") -> None:
        self._generated_mesh_paths = meshes
        self.preview_mesh_selector.blockSignals(True)
        self.preview_mesh_selector.clear()
        for phase, path in meshes.items():
            self.preview_mesh_selector.addItem(f"{phase} - {Path(path).name}", path)

        if preferred_path:
            index = self.preview_mesh_selector.findData(preferred_path)
            if index >= 0:
                self.preview_mesh_selector.setCurrentIndex(index)
        self.preview_mesh_selector.blockSignals(False)

        count = len(meshes)
        self.preview_mesh_count.setText(f"{count} mesh{'es' if count != 1 else ''}")
        self.preview_toolbar.setVisible(count > 1)

    def _clear_generated_mesh_choices(self) -> None:
        self._generated_mesh_paths = {}
        self.preview_mesh_selector.blockSignals(True)
        self.preview_mesh_selector.clear()
        self.preview_mesh_selector.blockSignals(False)
        self.preview_mesh_count.clear()
        self.preview_toolbar.hide()

    def _on_preview_mesh_selected(self, index: int) -> None:
        if index < 0:
            return
        mesh_path = self.preview_mesh_selector.itemData(index)
        if not mesh_path:
            return
        self._load_mesh_preview(str(mesh_path), self._preview_title_for_path(str(mesh_path), GENERATED_MESH_TITLE))
        phase = next((label for label, path in self._generated_mesh_paths.items() if path == mesh_path), "")
        if phase:
            transform_index = self.transform_phase.findText(phase)
            if transform_index >= 0 and transform_index != self.transform_phase.currentIndex():
                self.transform_phase.blockSignals(True)
                self.transform_phase.setCurrentIndex(transform_index)
                self.transform_phase.blockSignals(False)

    def _on_transform_phase_changed(self) -> None:
        if not self.generate_from_image.isChecked():
            return
        mesh_path = self._selected_generated_mesh_path()
        if not mesh_path:
            return
        selector_index = self.preview_mesh_selector.findData(mesh_path)
        if selector_index >= 0 and selector_index != self.preview_mesh_selector.currentIndex():
            self.preview_mesh_selector.blockSignals(True)
            self.preview_mesh_selector.setCurrentIndex(selector_index)
            self.preview_mesh_selector.blockSignals(False)
        self._load_mesh_preview(mesh_path, self._preview_title_for_path(mesh_path, GENERATED_MESH_TITLE))

    def _preview_title_for_path(self, mesh_path: str, fallback: str) -> str:
        for phase, path in self._generated_mesh_paths.items():
            if path == mesh_path:
                return f"Generated {phase} mesh"
        return fallback

    def _reset_preview_camera(self) -> None:
        self.mesh_viewer.reset_camera()

    def _load_mesh_preview(self, mesh_path: str, title: str) -> None:
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

        self._last_preview_path = mesh_path
        summary = self.mesh_viewer.mesh_data
        details = ""
        if summary:
            details = f"\nPoints: {summary.point_count:,} | Faces: {summary.face_count:,}"
        self.preview_label.setText(f"{title}:\n{Path(mesh_path).name}{details}")
        self.preview_label.hide()
        self.mesh_viewer.show()

    # ------------------------------------------------------------------
    # Small widget helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _phase_checkbox(text: str, checked: bool) -> QCheckBox:
        checkbox = QCheckBox(text)
        checkbox.setChecked(checked)
        checkbox.setMinimumHeight(34)
        return checkbox

    @staticmethod
    def _operator_spin(minimum: float, maximum: float, value: float) -> NoWheelDoubleSpinBox:
        spin = NoWheelDoubleSpinBox()
        spin.setRange(minimum, maximum)
        spin.setDecimals(6)
        spin.setValue(value)
        spin.setMinimumWidth(86)
        return spin

    @staticmethod
    def _triple_row(first: QWidget, second: QWidget, third: QWidget) -> QHBoxLayout:
        row = QHBoxLayout()
        row.addWidget(first)
        row.addWidget(second)
        row.addWidget(third)
        row.addStretch()
        return row

    @property
    def existing_mesh_group(self) -> QGroupBox:
        return self._existing_mesh_group

    @property
    def generation_group(self) -> QGroupBox:
        return self._generation_group

    @property
    def blender_group(self) -> QGroupBox:
        return self._blender_group


if __name__ == "__main__":
    import sys

    from multibest.gui.utils.qt_bootstrap import force_x11_if_wayland

    force_x11_if_wayland()

    app = QApplication(sys.argv)
    apply_dark_theme(app)
    window = ImageToMeshWindow()
    window.show()
    sys.exit(app.exec())

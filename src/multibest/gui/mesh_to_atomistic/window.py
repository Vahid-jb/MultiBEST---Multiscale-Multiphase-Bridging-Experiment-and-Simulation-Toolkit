# SPDX-FileCopyrightText: 2026 bright-ideas-clan
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Mesh-to-atomistic GUI module.

The window mirrors the phase-based workflow sketched in ``mesh_to_atomistic.png``:
users add base, guest, and void phases, fill per-phase mesh/CIF and transform
parameters, then choose merge/output options.
"""

from __future__ import annotations

import ntpath
import os
import shlex
from dataclasses import dataclass
from math import isclose

os.environ["OVITO_GUI_MODE"] = "1"

from ovito.gui import create_qwidget
from ovito.io import import_file
from ovito.vis import Viewport
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from multibest.gui.utils import ovito_scene
from multibest.gui.utils.base_window import BaseModuleWindow
from multibest.gui.utils.general import browse_directory, browse_file, get_script_path
from multibest.gui.utils.theme import (
    NoWheelComboBox,
    NoWheelDoubleSpinBox,
    NoWheelSpinBox,
    apply_framed_preview_placeholder,
    apply_module_title,
    make_action_button,
    make_path_row,
    make_primary_button,
    make_stop_button,
)

PHASE_BASE = "Base"
PHASE_GUEST = "Guest"
PHASE_VOID = "Void"
PHASE_TYPES = (PHASE_BASE, PHASE_GUEST, PHASE_VOID)
MERGE_OUTPUT_EXTENSIONS = (".lmp", ".xyz", ".cif")
PHASE_OUTPUT_EXTENSIONS = (".xyz",)
MERGE_OUTPUT_FILTER = "LAMMPS data (*.lmp);;XYZ (*.xyz);;CIF (*.cif)"
PHASE_OUTPUT_FILTER = "XYZ (*.xyz)"

DEFAULT_GLOBALS = {
    "merge_method": "mesh",
    "voxel_method": "triangle",
    "overlap_distance": 1.5,
}

DEFAULT_PHASE_VALUES = {
    PHASE_BASE: {
        "euler": (0.0, 0.0, 0.0),
        "particle_radius": 100,
        "pitch": 0.3,
        "padding": 5.0,
        "mask_dilate": 1,
        "dilate": 1.0,
        "close": 3,
    },
    PHASE_GUEST: {
        "euler": (10.0, 50.0, 60.0),
        "resolution": 600,
        "particle_radius": 100,
        "pitch": 0.3,
        "padding": 5.0,
        "mask_dilate": 1,
        "dilate": 1.0,
        "close": 3,
        "force_tri": True,
        "shrink_distance": 2.5,
    },
    PHASE_VOID: {
        "rotation": (10.0, 10.0, 10.0),
        "displacement": (50.0, -30.0, 0.0),
    },
}


@dataclass
class PhaseWidgets:
    """Widget handles for one phase tab."""

    phase_type: str
    mesh: QLineEdit
    cif: QLineEdit | None
    output_file: QLineEdit | None
    euler: tuple[NoWheelDoubleSpinBox, ...] | None
    displacement: tuple[NoWheelDoubleSpinBox, ...]
    rotation: tuple[NoWheelDoubleSpinBox, ...]
    pitch: NoWheelDoubleSpinBox | None
    padding: NoWheelDoubleSpinBox | None
    mask_dilate: QSpinBox | None
    dilate: NoWheelDoubleSpinBox | None
    close: QSpinBox | None
    force_tri: QCheckBox | None
    resolution: QSpinBox | None = None
    particle_radius: QSpinBox | None = None
    iso_value: NoWheelDoubleSpinBox | None = None
    shrink_distance: NoWheelDoubleSpinBox | None = None


class MeshToAtomisticWindow(BaseModuleWindow):
    """Main window for configuring mesh-to-atomistic model generation."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Mesh To Atomistic")
        self.resize(1000, 700)

        self.phase_widgets: list[PhaseWidgets] = []

        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        main_layout = QHBoxLayout(main_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)

        self.control_widget = self._build_controls()
        self.viz_widget = self._build_visualization()

        main_layout.addWidget(self.control_widget, 1)
        main_layout.addWidget(self.viz_widget, 1)

        self._apply_global_defaults()
        self._add_phase(PHASE_BASE)

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_controls(self) -> QScrollArea:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(14)
        scroll.setWidget(panel)

        header = QLabel("Mesh to Atomistic")
        apply_module_title(header)
        layout.addWidget(header)

        layout.addWidget(self._build_merge_group())
        layout.addWidget(self._build_output_group())
        layout.addWidget(self._build_add_phase_group())

        self.phase_tabs = QTabWidget()
        self.phase_tabs.setDocumentMode(True)
        layout.addWidget(self.phase_tabs)

        self.generate_btn = make_primary_button("Generate")
        self.stop_btn = make_stop_button()
        self.generate_btn.clicked.connect(self._run_generation)
        self.stop_btn.clicked.connect(self._stop_calculation)
        button_row = QHBoxLayout()
        button_row.addWidget(self.generate_btn)
        button_row.addWidget(self.stop_btn)
        button_row.addStretch()
        layout.addLayout(button_row)
        self._calc_btns = [self.generate_btn]
        self._stop_btns = [self.stop_btn]

        layout.addStretch()
        return scroll

    def _build_add_phase_group(self) -> QGroupBox:
        group = QGroupBox("Add Phase")
        layout = QHBoxLayout(group)
        layout.setSpacing(10)
        self.phase_add_buttons: dict[str, QPushButton] = {}
        for phase_type in PHASE_TYPES:
            button = make_action_button(phase_type, "add")
            button.setMinimumHeight(42)
            button.clicked.connect(lambda checked=False, value=phase_type: self._add_phase(value))
            layout.addWidget(button)
            self.phase_add_buttons[phase_type] = button
        self.remove_phase_btn = make_action_button("Remove selected phase", "remove")
        self.remove_phase_btn.setMinimumHeight(42)
        self.remove_phase_btn.clicked.connect(self._remove_current_phase)
        layout.addWidget(self.remove_phase_btn)
        layout.addStretch()
        return group

    def _build_merge_group(self) -> QGroupBox:
        group = QGroupBox("Merge")
        layout = QFormLayout(group)

        self.add_charge = QCheckBox("Charge")
        self.add_spin = QCheckBox("Spin")
        self.add_charge.toggled.connect(self._sync_charge_spin_choice)
        self.add_spin.toggled.connect(self._sync_charge_spin_choice)
        add_row = QHBoxLayout()
        add_row.addWidget(self.add_charge)
        add_row.addWidget(self.add_spin)
        add_row.addStretch()
        layout.addRow("Add:", add_row)

        self.merge_enabled = QCheckBox()
        self.merge_enabled.setChecked(True)
        layout.addRow("Merge:", self.merge_enabled)

        self.merge_method = NoWheelComboBox()
        self.merge_method.addItems(["mesh", "overlap"])
        layout.addRow("Merge method:", self.merge_method)

        self.overlap_distance = self._double_spin(decimals=4, minimum=0.0)
        layout.addRow("Overlap threshold:", self.overlap_distance)

        self.voxel_method = NoWheelComboBox()
        self.voxel_method.addItems(["triangle", "trimesh"])
        layout.addRow("Voxel method:", self.voxel_method)

        self.pbc = QCheckBox()
        self.pbc.setChecked(True)
        layout.addRow("PBC:", self.pbc)

        return group

    def _build_output_group(self) -> QGroupBox:
        group = QGroupBox("Output")
        layout = QFormLayout(group)

        self.output_dir = QLineEdit()
        layout.addRow(
            "Output directory:",
            make_path_row(self.output_dir, "Browse", lambda: browse_directory(self, self.output_dir)),
        )

        self.output_file = QLineEdit()
        self.output_file.setPlaceholderText("merged.lmp")
        output_btn = QPushButton("Browse")
        output_btn.clicked.connect(self._choose_merge_output_file)

        output_row = QHBoxLayout()
        output_row.addWidget(self.output_file)
        output_row.addWidget(output_btn)
        layout.addRow("Merged output file:", output_row)

        return group

    def _apply_global_defaults(self) -> None:
        self.merge_method.setCurrentText(DEFAULT_GLOBALS["merge_method"])
        self.voxel_method.setCurrentText(DEFAULT_GLOBALS["voxel_method"])
        self.overlap_distance.setValue(DEFAULT_GLOBALS["overlap_distance"])

    def _build_visualization(self) -> QWidget:
        container = QFrame()
        self.viz_layout = QVBoxLayout(container)
        self.viz_layout.setContentsMargins(18, 18, 18, 18)

        self.viz_label = QLabel("3D view of the generated atomistic model\nOutput Format\nOutput path")
        self.viz_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        apply_framed_preview_placeholder(self.viz_label)
        self.viz_layout.addWidget(self.viz_label, 1)

        self._ovito_widget = None
        self._pipeline = None
        self._viewport = None
        self._last_output_candidates: list[str] = []
        return container

    # ------------------------------------------------------------------
    # Phase construction
    # ------------------------------------------------------------------

    def _add_phase(self, phase_type: str, defaults: dict | None = None) -> None:
        if phase_type == PHASE_BASE and self._has_base_phase():
            self._update_phase_tab_labels()
            return
        defaults = defaults or DEFAULT_PHASE_VALUES.get(phase_type, {})

        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)

        mesh = self._path_row(
            layout,
            "Mesh path / MeshID:",
            "Mesh files (*.stl *.obj *.ply *.vtk *.mesh);;All files (*)",
        )
        cif = (
            None
            if phase_type == PHASE_VOID
            else self._path_row(layout, "CIF file:", "CIF files (*.cif);;All files (*)")
        )
        phase_output_file = None
        if phase_type != PHASE_VOID:
            phase_output_file = self._build_phase_output_group(layout, phase_type)

        euler = (
            None
            if phase_type == PHASE_VOID
            else self._add_vector_row(layout, "Euler angle (deg):", ["phi1", "phi", "phi2"])
        )
        displacement = self._add_vector_row(layout, "Displace (Angstrom):", ["x", "y", "z"])
        rotation = self._add_vector_row(layout, "Rotate phase (deg):", ["x", "y", "z"])
        if euler is not None:
            self._set_spin_values(euler, defaults.get("euler", (0.0, 0.0, 0.0)))
        self._set_spin_values(displacement, defaults.get("displacement", (0.0, 0.0, 0.0)))
        self._set_spin_values(rotation, defaults.get("rotation", (0.0, 0.0, 0.0)))

        pitch = padding = mask_dilate = dilate = close = force_tri = None
        resolution = particle_radius = iso_value = shrink_distance = None
        if phase_type != PHASE_VOID:
            voxel_group = QGroupBox("Voxelization")
            voxel_layout = QFormLayout(voxel_group)
            pitch = self._double_spin(decimals=4, minimum=0.0)
            padding = self._double_spin(decimals=2, minimum=0.0)
            mask_dilate = self._int_spin()
            dilate = self._double_spin(decimals=2, minimum=0.0)
            close = self._int_spin()
            particle_radius = self._int_spin(minimum=0)
            force_tri = QCheckBox()
            pitch.setValue(defaults.get("pitch", 0.0))
            padding.setValue(defaults.get("padding", 0.0))
            mask_dilate.setValue(defaults.get("mask_dilate", 0))
            dilate.setValue(defaults.get("dilate", 0.0))
            close.setValue(defaults.get("close", 0))
            particle_radius.setValue(defaults.get("particle_radius", 0))
            force_tri.setChecked(defaults.get("force_tri", False))
            voxel_layout.addRow("Pitch:", pitch)
            voxel_layout.addRow("Padding (Angstrom):", padding)
            voxel_layout.addRow("Mask dilate:", mask_dilate)
            voxel_layout.addRow("Dilate:", dilate)
            voxel_layout.addRow("Close:", close)
            voxel_layout.addRow("Particle radius (percent):", particle_radius)
            voxel_layout.addRow("Force tri:", force_tri)
            layout.addWidget(voxel_group)

        if phase_type == PHASE_GUEST:
            guest_group = QGroupBox("Guest Particle")
            guest_layout = QFormLayout(guest_group)
            resolution = self._int_spin(minimum=1, value=1)
            iso_value = self._double_spin(decimals=4)
            shrink_distance = self._double_spin(decimals=4)
            resolution.setValue(defaults.get("resolution", 1))
            iso_value.setValue(defaults.get("iso_value", 0.0))
            shrink_distance.setValue(defaults.get("shrink_distance", 0.0))
            guest_layout.addRow("Resolution:", resolution)
            guest_layout.addRow("Iso value:", iso_value)
            guest_layout.addRow("Shrink distance:", shrink_distance)
            layout.addWidget(guest_group)

        layout.addStretch()
        phase = PhaseWidgets(
            phase_type=phase_type,
            mesh=mesh,
            cif=cif,
            output_file=phase_output_file,
            euler=euler,
            displacement=displacement,
            rotation=rotation,
            pitch=pitch,
            padding=padding,
            mask_dilate=mask_dilate,
            dilate=dilate,
            close=close,
            force_tri=force_tri,
            resolution=resolution,
            particle_radius=particle_radius,
            iso_value=iso_value,
            shrink_distance=shrink_distance,
        )
        self.phase_widgets.append(phase)
        tab_index = self.phase_tabs.addTab(tab, f"Phase {len(self.phase_widgets)} - {phase_type}")
        self.phase_tabs.setCurrentIndex(tab_index)
        self._update_phase_tab_labels()

    def _has_base_phase(self) -> bool:
        """Return True when a base phase is already present."""
        return any(phase.phase_type == PHASE_BASE for phase in self.phase_widgets)

    def _remove_current_phase(self) -> None:
        """Remove the currently selected phase while keeping one phase available."""
        index = self.phase_tabs.currentIndex()
        if index < 0 or len(self.phase_widgets) <= 1:
            self._update_phase_tab_labels()
            return

        tab = self.phase_tabs.widget(index)
        self.phase_tabs.removeTab(index)
        if tab is not None:
            tab.deleteLater()
        self.phase_widgets.pop(index)
        self._update_phase_tab_labels()

    def _update_phase_tab_labels(self) -> None:
        """Refresh tab labels and removal availability after phase changes."""
        for index, phase in enumerate(self.phase_widgets):
            self.phase_tabs.setTabText(index, f"Phase {index + 1} - {phase.phase_type}")
        self.remove_phase_btn.setEnabled(len(self.phase_widgets) > 1)
        self.phase_add_buttons[PHASE_BASE].setEnabled(not self._has_base_phase())

    def _path_row(self, parent_layout: QVBoxLayout, label: str, file_filter: str) -> QLineEdit:
        row = QHBoxLayout()
        row.addWidget(QLabel(label))
        edit = QLineEdit()
        button = make_action_button("Browse", "browse")
        button.clicked.connect(lambda: browse_file(self, edit, file_filter))
        row.addWidget(edit, 1)
        row.addWidget(button)
        parent_layout.addLayout(row)
        return edit

    def _build_phase_output_group(self, parent_layout: QVBoxLayout, phase_type: str) -> QLineEdit:
        group = QGroupBox(f"{phase_type} Atomistic Output")
        layout = QFormLayout(group)

        output_file = QLineEdit()
        output_btn = QPushButton("Browse")
        output_btn.clicked.connect(
            lambda: self._choose_output_file(
                output_file,
                PHASE_OUTPUT_FILTER,
                ".xyz",
            )
        )
        output_row = QHBoxLayout()
        output_row.addWidget(output_file)
        output_row.addWidget(output_btn)
        layout.addRow("Output path:", output_row)

        parent_layout.addWidget(group)
        return output_file

    def _choose_output_file(self, line_edit: QLineEdit, file_filter: str, default_extension: str) -> None:
        """Open a save dialog and append the selected extension when needed."""
        filename, selected_filter = QFileDialog.getSaveFileName(self, "Output File", "", file_filter)
        if not filename:
            return
        line_edit.setText(self._ensure_selected_extension(filename, selected_filter, default_extension))

    def _choose_merge_output_file(self) -> None:
        """Choose the merged output file, storing paths inside the output directory as relative values."""
        initial_dir = self.output_dir.text().strip()
        filename, selected_filter = QFileDialog.getSaveFileName(
            self,
            "Merged Output File",
            initial_dir,
            MERGE_OUTPUT_FILTER,
        )
        if not filename:
            return
        filename = self._ensure_selected_extension(filename, selected_filter, ".lmp")
        self.output_file.setText(self._display_output_file_path(filename, initial_dir))

    def _display_output_file_path(self, filename: str, output_dir: str) -> str:
        path_module = self._path_module_for(filename, output_dir)
        if output_dir and self._is_absolute_path(filename):
            filename_path = path_module.normpath(filename)
            output_dir_path = path_module.normpath(output_dir)
            try:
                common_path = path_module.commonpath([filename_path, output_dir_path])
            except ValueError:
                return filename
            if common_path == output_dir_path:
                return path_module.relpath(filename_path, output_dir_path)
        return filename

    def _sync_charge_spin_choice(self, checked: bool) -> None:
        """Keep charge and spin mutually exclusive while allowing neither."""
        if not checked:
            return
        sender = self.sender()
        if sender is self.add_charge and self.add_spin.isChecked():
            self.add_spin.setChecked(False)
        elif sender is self.add_spin and self.add_charge.isChecked():
            self.add_charge.setChecked(False)

    def _add_vector_row(
        self,
        parent_layout: QVBoxLayout,
        label: str,
        names: list[str],
    ) -> tuple[NoWheelDoubleSpinBox, ...]:
        group = QGroupBox(label)
        layout = QGridLayout(group)
        widgets: list[NoWheelDoubleSpinBox] = []
        for column, name in enumerate(names):
            layout.addWidget(QLabel(name), 0, column)
            spin = self._double_spin(decimals=4)
            widgets.append(spin)
            layout.addWidget(spin, 1, column)
        parent_layout.addWidget(group)
        return tuple(widgets)

    def _double_spin(self, *, decimals: int = 3, minimum: float = -999999.0) -> NoWheelDoubleSpinBox:
        spin = NoWheelDoubleSpinBox()
        spin.setDecimals(decimals)
        spin.setRange(minimum, 999999.0)
        spin.setSingleStep(0.1)
        return spin

    def _int_spin(self, *, minimum: int = -999999, value: int = 0) -> NoWheelSpinBox:
        spin = NoWheelSpinBox()
        spin.setRange(minimum, 999999)
        spin.setValue(value)
        return spin

    # ------------------------------------------------------------------
    # Data collection / execution
    # ------------------------------------------------------------------

    def collect_parameters(self) -> dict:
        """Return all UI values in a backend-friendly dictionary."""
        return {
            "phases": [self._phase_parameters(phase) for phase in self.phase_widgets],
            "merge": {
                "add": {
                    "charge": self.add_charge.isChecked(),
                    "spin": self.add_spin.isChecked(),
                },
                "enabled": self.merge_enabled.isChecked(),
                "method": self.merge_method.currentText(),
                "overlap_distance": self.overlap_distance.value(),
                "voxel_method": self.voxel_method.currentText(),
                "pbc": self.pbc.isChecked(),
            },
            "output": {
                "path": self.output_file.text().strip(),
                "directory": self.output_dir.text().strip(),
                "format": self._output_format_from_path(self.output_file.text().strip(), default="lmp"),
            },
        }

    def _phase_parameters(self, phase: PhaseWidgets) -> dict:
        params = {
            "type": phase.phase_type.lower(),
            "mesh": phase.mesh.text().strip(),
            "cif": phase.cif.text().strip() if phase.cif is not None else None,
            "output": {
                "path": phase.output_file.text().strip() if phase.output_file is not None else "",
                "format": self._output_format_from_path(
                    phase.output_file.text().strip() if phase.output_file is not None else "",
                    default="xyz",
                ),
            },
            "displacement": self._spin_values(phase.displacement),
            "rotation": self._spin_values(phase.rotation),
        }
        if phase.euler is not None:
            params["euler"] = self._spin_values(phase.euler)
        if phase.pitch is not None:
            params["voxel"] = {
                "pitch": phase.pitch.value(),
                "padding": phase.padding.value(),
                "mask_dilate": phase.mask_dilate.value(),
                "dilate": phase.dilate.value(),
                "close": phase.close.value(),
                "particle_radius": phase.particle_radius.value(),
                "force_tri": phase.force_tri.isChecked(),
            }
        if phase.phase_type == PHASE_GUEST:
            params["particle"] = {
                "resolution": phase.resolution.value(),
                "iso_value": phase.iso_value.value(),
                "shrink_distance": phase.shrink_distance.value(),
            }
        return params

    def _spin_values(self, widgets: tuple[NoWheelDoubleSpinBox, ...]) -> list[float]:
        return [widget.value() for widget in widgets]

    def _set_spin_values(self, widgets: tuple[NoWheelDoubleSpinBox, ...], values: tuple[float, float, float]) -> None:
        for widget, value in zip(widgets, values, strict=True):
            widget.setValue(value)

    def _run_generation(self) -> None:
        """Validate inputs, write the backend input file, and launch generation."""
        self._reset_visualization()

        params = self.collect_parameters()
        output_dir = params["output"]["directory"]
        if not self._validate_output_dir(output_dir):
            return

        output_file = self.output_file.text().strip()
        if not output_file:
            self.logger.log_message("ERROR", "Please choose an output path first.")
            return

        output_file = self._ensure_output_extension(output_file, params["output"]["format"])
        self.output_file.setText(output_file)
        output_path = self._resolve_path(output_file, output_dir)
        params["output"]["path"] = output_path
        params["output"]["format"] = self._output_format_from_path(output_path, default="lmp")
        self._prepare_phase_outputs(params, output_dir)

        if not self._validate_generation_inputs(params):
            return

        self._last_output_candidates = [output_path, *self._phase_output_paths(params, output_dir)]
        param_file = os.path.join(output_dir, "mesh_to_atomistic_input.txt")
        self.logger.log_message("INFO", f"Writing parameter file: {param_file}")
        with open(param_file, "w", encoding="utf-8") as handle:
            handle.write(self._format_backend_input(params, output_dir))

        self._set_running(True)
        self.runner.on_finished_cb = self._make_finish_callback("Mesh-to-atomistic generation", self._plot_generation)
        script_path = get_script_path("..", "mesh_to_atomistic", "gpt-mod-1.py")
        self.runner.start(script_path, args=[param_file], cwd=output_dir)

    def _prepare_phase_outputs(self, params: dict, output_dir: str) -> None:
        """Resolve and normalize per-phase atomistic output paths."""
        for index, phase in enumerate(params["phases"], start=1):
            if phase["type"] == "void":
                continue
            phase_output = phase["output"]
            path = phase_output["path"] or self._default_phase_output_path(index, phase, output_dir)
            if phase_output["path"]:
                path = self._resolve_path(path, output_dir)
            path = self._ensure_output_extension(path, phase_output["format"] or "xyz")
            phase_output["path"] = path
            phase_output["format"] = self._output_format_from_path(path, default="xyz")

            widget = self.phase_widgets[index - 1].output_file
            if widget is not None:
                widget.setText(path)

    def _validate_generation_inputs(self, params: dict) -> bool:
        """Return True when the collected UI values are runnable by gpt-mod-1."""
        if not self._validate_output_extension(params["output"]["path"], MERGE_OUTPUT_EXTENSIONS, "Merge output"):
            return False

        for index, phase in enumerate(params["phases"], start=1):
            if not self._validate_phase_inputs(index, phase):
                return False
            if phase["type"] != "void" and not self._validate_output_extension(
                phase["output"]["path"],
                PHASE_OUTPUT_EXTENSIONS,
                f"Phase {index} output",
            ):
                return False

        if params["merge"]["enabled"] and not any(phase["type"] == "base" for phase in params["phases"]):
            self.logger.log_message("ERROR", "Merging requires one base phase.")
            return False
        return True

    def _validate_output_extension(self, path: str, allowed_extensions: tuple[str, ...], label: str) -> bool:
        extension = os.path.splitext(path)[1].lower()
        if extension in allowed_extensions:
            return True
        allowed = ", ".join(allowed_extensions)
        self.logger.log_message("ERROR", f"{label}: output extension must be one of: {allowed}.")
        return False

    def _validate_phase_inputs(self, index: int, phase: dict) -> bool:
        phase_label = f"Phase {index} ({phase['type']})"
        mesh = phase["mesh"]
        if not mesh:
            self.logger.log_message("ERROR", f"{phase_label}: please choose a mesh file first.")
            return False
        if not os.path.isfile(mesh):
            self.logger.log_message("ERROR", f"{phase_label}: mesh file not found:\n{mesh}")
            return False
        if phase["type"] not in ("base", "guest"):
            return True
        return self._validate_crystal_phase_inputs(phase_label, phase)

    def _validate_crystal_phase_inputs(self, phase_label: str, phase: dict) -> bool:
        cif = phase.get("cif")
        if not cif:
            self.logger.log_message("ERROR", f"{phase_label}: please choose a CIF file first.")
            return False
        if not os.path.isfile(cif):
            self.logger.log_message("ERROR", f"{phase_label}: CIF file not found:\n{cif}")
            return False
        if phase["voxel"]["pitch"] <= 0:
            self.logger.log_message("ERROR", f"{phase_label}: pitch must be greater than zero.")
            return False
        return True

    def _format_backend_input(self, params: dict, output_dir: str) -> str:
        """Serialize UI parameters to the text format consumed by gpt-mod-1.py."""
        lines = [f"total_num_phases {len(params['phases'])}", ""]
        lines.append(self._format_global_options(params))

        for index, phase in enumerate(params["phases"], start=1):
            lines.append(self._format_phase_line(index, phase, output_dir))
        lines.append("")
        return "\n".join(lines)

    def _phase_output_paths(self, params: dict, output_dir: str) -> list[str]:
        return [
            self._phase_output_path(index, phase, output_dir)
            for index, phase in enumerate(params["phases"], start=1)
            if phase["type"] != "void"
        ]

    def _format_global_options(self, params: dict) -> str:
        merge = params["merge"]
        parts = []
        if merge["enabled"]:
            parts.extend(["--merge", "on"])
        parts.extend(["--merge_method", merge["method"]])
        if merge["pbc"]:
            parts.extend(["--pbc", "on"])
        parts.extend(["--out", params["output"]["path"]])
        if merge["add"]["charge"]:
            parts.append("--charge")
        if merge["add"]["spin"]:
            parts.append("--spin")
        parts.extend(
            [
                "--overlap_distance",
                merge["overlap_distance"],
                "--voxel-method",
                merge["voxel_method"],
            ]
        )
        return self._join_tokens(parts)

    def _format_phase_line(self, index: int, phase: dict, output_dir: str) -> str:
        parts = [f"phase_{index}", phase["type"], phase["mesh"]]
        if self._has_nonzero_values(phase["rotation"]):
            parts.extend(["--rotate", *phase["rotation"]])
        if self._has_nonzero_values(phase["displacement"]):
            parts.extend(["--displace", *phase["displacement"]])

        if phase["type"] != "void":
            phase_output = self._phase_output_path(index, phase, output_dir)
            voxel = phase["voxel"]
            parts.extend(["--cif", phase["cif"]])
            if phase["type"] == "guest":
                particle = phase["particle"]
                parts.extend(["--resolution", particle["resolution"]])
            parts.extend(["--particle_radius", voxel["particle_radius"]])
            parts.extend(["--pitch", voxel["pitch"]])
            if phase["type"] == "guest":
                particle = phase["particle"]
                parts.extend(["--shrink_distance", particle["shrink_distance"]])
            parts.extend(["--padding-angstrom", voxel["padding"]])
            parts.extend(["--mask-dilate", voxel["mask_dilate"]])
            parts.extend(["--euler", *phase["euler"]])
            parts.extend(["--dilate", voxel["dilate"]])
            parts.extend(["--close", voxel["close"]])
            if voxel["force_tri"]:
                parts.append("--force-tri")
            parts.extend(["--out", phase_output])

        if phase["type"] == "guest":
            particle = phase["particle"]
            if particle["iso_value"]:
                parts.extend(["--iso_value", particle["iso_value"]])

        return self._join_tokens(parts)

    def _has_nonzero_values(self, values: list[float]) -> bool:
        return any(not isclose(value, 0.0, abs_tol=1e-12) for value in values)

    def _phase_output_path(self, index: int, phase: dict, output_dir: str) -> str:
        return phase.get("output", {}).get("path") or self._default_phase_output_path(index, phase, output_dir)

    def _default_phase_output_path(self, index: int, phase: dict, output_dir: str) -> str:
        return self._join_output_path(output_dir, f"phase_{index}_{phase['type']}.xyz")

    def _resolve_path(self, path: str, output_dir: str) -> str:
        if path and not self._is_absolute_path(path):
            return self._join_output_path(output_dir, path)
        return path

    def _is_absolute_path(self, path: str) -> bool:
        return os.path.isabs(path) or ntpath.isabs(path)

    def _join_output_path(self, output_dir: str, path: str) -> str:
        path_module = self._path_module_for(output_dir, path)
        joined = path_module.join(output_dir, path)
        if path_module is ntpath and "/" in output_dir and "\\" not in output_dir:
            return joined.replace("\\", "/")
        return joined

    def _path_module_for(self, *paths: str):
        if any(ntpath.splitdrive(path)[0] for path in paths):
            return ntpath
        return os.path

    def _join_tokens(self, values: list[object]) -> str:
        return " ".join(self._quote_token(self._format_value(value)) for value in values)

    def _quote_token(self, value: str) -> str:
        if value and not any(char.isspace() for char in value):
            return value
        return shlex.quote(value)

    def _format_value(self, value: object) -> str:
        if isinstance(value, float):
            return f"{value:g}"
        return str(value)

    def _ensure_output_extension(self, path: str, output_format: str) -> str:
        if os.path.splitext(path)[1]:
            return path
        extensions = {"lammps": ".lmp", "lmp": ".lmp", "xyz": ".xyz", "cif": ".cif"}
        normalized_format = output_format.strip().lower().lstrip(".")
        return path + extensions.get(normalized_format, f".{normalized_format}" if normalized_format else "")

    def _ensure_selected_extension(self, path: str, selected_filter: str, default_extension: str) -> str:
        if os.path.splitext(path)[1]:
            return path
        return path + self._extension_from_filter(selected_filter, default_extension)

    def _extension_from_filter(self, selected_filter: str, default_extension: str) -> str:
        for extension in (".lmp", ".xyz", ".cif"):
            if f"*{extension}" in selected_filter:
                return extension
        return default_extension

    def _output_format_from_path(self, path: str, *, default: str) -> str:
        extension = os.path.splitext(path)[1].lower().lstrip(".")
        return extension or default

    def _plot_generation(self) -> None:
        """Load the generated atomistic output into an OVITO viewport."""
        path = next((candidate for candidate in self._last_output_candidates if os.path.isfile(candidate)), "")
        if not path or not os.path.isfile(path):
            self.logger.log_message("ERROR", f"Output file not found:\n{self.output_file.text().strip()}")
            return

        try:
            self._clear_ovito_scene()
            pipeline = self._import_atomistic_file(path)
            pipeline.compute()
            pipeline.add_to_scene()

            vp = Viewport(type=Viewport.Type.PERSPECTIVE)
            widget = create_qwidget(vp)
            self._replace_visualization_widget(widget)
            vp.zoom_all()

            self._pipeline = pipeline
            self._viewport = vp
            self._ovito_widget = widget
        except Exception as e:
            self.logger.log_message("ERROR", f"Failed to load/visualize file:\n{e}")

    def _clear_ovito_scene(self) -> None:
        ovito_scene.clear_ovito_scene(lambda message: self.logger.log_message("WARNING", message))
        self._pipeline = None
        self._viewport = None

    def _import_atomistic_file(self, path: str):
        return ovito_scene.import_atomistic_file(
            path,
            self._import_kwargs(path),
            import_file,
            lambda message: self.logger.log_message("INFO", message),
        )

    def _import_kwargs(self, path: str) -> dict[str, str]:
        """Return OVITO ``import_file`` kwargs for LAMMPS data files.

        Mirrors the writer's mode selection in
        :func:`multibest.mesh_to_atomistic.manipulate.write_lammps_output`:
        spin wins over charge.
        """
        if os.path.splitext(path)[1].lower() not in (".lmp", ".data", ".lammps"):
            return {}
        if self.add_spin.isChecked():
            return {"atom_style": "spin"}
        if self.add_charge.isChecked():
            return {"atom_style": "charge"}
        return {"atom_style": "atomic"}

    def _reset_visualization(self) -> None:
        self._clear_ovito_scene()

        label = QLabel("3D view of the generated atomistic model\nOutput Format\nOutput path")
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        apply_framed_preview_placeholder(label)
        self._replace_visualization_widget(label)
        self.viz_label = label

    def _replace_visualization_widget(self, new_widget: QWidget) -> None:
        if getattr(self, "viz_label", None) is not None:
            self.viz_layout.removeWidget(self.viz_label)
            self.viz_label.deleteLater()
            self.viz_label = None

        if getattr(self, "_ovito_widget", None) is not None:
            self.viz_layout.removeWidget(self._ovito_widget)
            self._ovito_widget.deleteLater()
            self._ovito_widget = None

        self.viz_layout.addWidget(new_widget, 1)

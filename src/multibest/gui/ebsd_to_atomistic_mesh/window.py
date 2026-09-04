# SPDX-FileCopyrightText: 2026 bright-ideas-clan
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""EBSD-to-atomistic/mesh GUI module.

This module provides the control surface for the two-phase workflow sketched
in ``ebsd_to_atomistic.png``: EBSD input preparation produces intermediate
files that are consumed by data processing, mesh rescaling, and atomistic
model assembly.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

os.environ["OVITO_GUI_MODE"] = "1"

from ovito.gui import create_qwidget
from ovito.io import import_file
from ovito.vis import Viewport
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
    QPushButton,
    QScrollArea,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from multibest.gui.utils import dream3d_controls, stl_preview
from multibest.gui.utils.base_window import BaseModuleWindow
from multibest.gui.utils.general import (
    browse_directory,
    browse_file,
    create_file,
    get_script_path,
    get_source_script_path,
)
from multibest.gui.utils.mesh_viewer import MeshViewer
from multibest.gui.utils.ovito_scene import clear_ovito_scene
from multibest.gui.utils.theme import (
    NoWheelComboBox,
    NoWheelDoubleSpinBox,
    NoWheelSpinBox,
    add_run_row,
    apply_framed_preview_placeholder,
    apply_info_callout,
    apply_module_title,
    apply_preview_panel,
    apply_preview_placeholder,
    make_action_button,
    make_path_row,
    make_primary_button,
    make_stop_button,
)
from multibest.utils.dream3d import Dream3DError, discover_dream3d_python, install_dream3d_env

EBSD_FILE_FILTER = "EBSD files (*.ang *.ctf *.h5ebsd *.h5);;All files (*)"
TEXT_FILE_FILTER = "Text files (*.txt *.dat *.csv);;All files (*)"
CSV_FILE_FILTER = "CSV files (*.csv)"
CIF_FILE_FILTER = "CIF files (*.cif);;All files (*)"
DREAM3D_FILE_FILTER = "DREAM3D files (*.dream3d)"
XYZ_FILE_FILTER = "XYZ files (*.xyz)"
DEFAULT_STL_PREFIX = "TriangleFeature_"
OUTPUT_FILE_DIALOG_TITLE = "Output File"

# (menu label, reference_frame_index, file_extension). The currently supported
# file extensions map to their corresponding backend reference-frame transforms.
H5EBSD_FORMAT_OPTIONS: tuple[tuple[str, int, str], ...] = (
    (".ang", 0, ".ang"),
    (".ctf", 1, ".ctf"),
)
DREAM3D_SETTINGS_KEY = "ebsd_to_atomistic_mesh/dream3d_python"
DREAM3DNX_MISSING_MESSAGE = (
    "DREAM3D-NX/SIMPLNX is required for EBSD preparation, but no Python environment "
    "providing the 'simplnx' and 'orientationanalysis' modules was found. Use the "
    "'DREAM3D-NX environment' controls to Install a managed environment, or Browse "
    "to an existing DREAM3D-NX Python interpreter."
)
DREAM3D_STATUS_MISSING_MESSAGE = (
    "Not found. Required only for EBSD preparation — use Install to set it up, or select an existing interpreter."
)


@dataclass
class PhaseWidgets:
    """Widget handles for one atomistic phase row."""

    name: QLineEdit
    cif_file: QLineEdit
    row: QWidget
    remove_btn: QPushButton


class EbsdToAtomisticMeshWindow(BaseModuleWindow):
    """Main window for configuring EBSD-to-atomistic/mesh workflows."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("EBSD To Atomistic / Mesh")
        self.resize(1100, 760)

        self.phase_widgets: list[PhaseWidgets] = []
        self._dream3d_python = ""
        self._mesh_preview_paths: list[str] = []
        self._last_mesh_preview_path = ""
        self._atomistic_output_candidates: list[str] = []
        self._atomistic_pipeline = None
        self._atomistic_viewport = None
        self._atomistic_ovito_widget: QWidget | None = None

        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        main_layout = QHBoxLayout(main_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)

        self.control_widget = self._build_controls()
        self.viz_widget = self._build_visualization()

        main_layout.addWidget(self.control_widget, 1)
        main_layout.addWidget(self.viz_widget, 1)

        self._add_phase("phase 1")
        self._add_phase("phase 2")

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

        header = QLabel("EBSD to Atomistic / Mesh")
        apply_module_title(header)
        layout.addWidget(header)

        tabs = QTabWidget()
        tabs.setObjectName("workflowPhaseTabs")
        tabs.addTab(self._build_phase_one_tab(), "Stage 1 - EBSD preparation")
        tabs.addTab(self._build_phase_two_tab(), "Stage 2 - Mesh / atomistic")
        layout.addWidget(tabs)

        layout.addStretch()
        return scroll

    def _build_phase_one_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(12)

        layout.addWidget(self._build_dream3d_group())
        layout.addWidget(self._build_h5_group())
        self.ebsd_extrusion_group = self._build_initial_input_group()
        self.raw_ebsd_group = self._build_raw_ebsd_group()
        layout.addWidget(self.ebsd_extrusion_group)
        layout.addWidget(self.raw_ebsd_group)
        layout.addWidget(self._build_threshold_group())
        layout.addWidget(self._build_general_filter_group())
        layout.addWidget(self._build_ebsd_output_group())

        self.h5ebsd_file_exists.toggled.connect(self._sync_h5_branch_ui)
        self._sync_h5_branch_ui(self.h5ebsd_file_exists.isChecked())

        self.input_2d_ebsd_data.textChanged.connect(self._sync_threshold_ui)
        self.h5ebsd_format.currentTextChanged.connect(self._sync_threshold_ui)
        self.file_extension.currentIndexChanged.connect(self._sync_threshold_ui)
        self._sync_threshold_ui()

        self.process_ebsd_btn = make_primary_button("Run")
        self.process_ebsd_stop_btn = make_stop_button()
        self.process_ebsd_btn.clicked.connect(self._run_ebsd_processing)
        self.process_ebsd_stop_btn.clicked.connect(self._stop_calculation)
        add_run_row(layout, self.process_ebsd_btn, self.process_ebsd_stop_btn)
        self._sync_ebsd_dimension_ui(self.ebsd_is_3d.isChecked())
        self._calc_btns.append(self.generate_replicas_btn)
        self._calc_btns.append(self.process_ebsd_btn)
        self._stop_btns.append(self.process_ebsd_stop_btn)

        layout.addStretch()
        return tab

    def _build_phase_two_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(12)

        layout.addWidget(self._build_phase_handoff())
        layout.addWidget(self._build_data_processing_group())
        layout.addWidget(self._build_rescaling_group())
        layout.addWidget(self._build_atomistic_group())

        layout.addStretch()
        return tab

    def _build_phase_handoff(self) -> QFrame:
        handoff = QFrame()

        layout = QHBoxLayout(handoff)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(12)

        label = QLabel("Use the files prepared in Stage 1 as inputs for conversion, rescaling, and atomistic assembly.")
        label.setObjectName("phaseHandoffLabel")
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setWordWrap(True)
        apply_info_callout(handoff, label)
        layout.addWidget(label)
        return handoff

    def _build_initial_input_group(self) -> QGroupBox:
        group = QGroupBox("2D/3D EBSD extrusion")
        layout = QFormLayout(group)

        self.ebsd_is_3d = QCheckBox()
        self.ebsd_is_3d.setText("3D EBSD input")
        self.ebsd_is_3d.toggled.connect(self._sync_ebsd_dimension_ui)
        layout.addRow("EBSD dimension:", self.ebsd_is_3d)

        self.input_2d_ebsd_data = QLineEdit()
        self.input_2d_ebsd_row = self._browse_file_row(self.input_2d_ebsd_data, EBSD_FILE_FILTER)
        self.input_2d_ebsd_label = QLabel("2D EBSD data:")
        layout.addRow(self.input_2d_ebsd_label, self.input_2d_ebsd_row)

        self.replicate = self._int_spin(minimum=1, value=1)
        self.replicate_label = QLabel("replicate:")
        layout.addRow(self.replicate_label, self.replicate)

        self.generate_replicas_btn = make_primary_button("Generate", max_width=160)
        self.generate_replicas_btn.clicked.connect(self._run_ebsd_replication)
        layout.addRow("", self.generate_replicas_btn)

        self._sync_ebsd_dimension_ui(self.ebsd_is_3d.isChecked())
        return group

    def _build_h5_group(self) -> QGroupBox:
        group = QGroupBox("H5EBSD source")
        layout = QVBoxLayout(group)

        self.h5ebsd_file_exists = QCheckBox()
        self.h5ebsd_file_exists.setText("H5EBSD file already exists")
        layout.addWidget(self.h5ebsd_file_exists)

        self.existing_h5_group = QGroupBox("Existing H5EBSD file")
        existing_layout = QFormLayout(self.existing_h5_group)

        self.start_slice = self._int_spin(value=1)
        self.end_slice = self._int_spin(value=4)
        existing_layout.addRow("start slice:", self.start_slice)
        existing_layout.addRow("end slice:", self.end_slice)

        self.h5ebsd_format = NoWheelComboBox()
        self.h5ebsd_format.addItems(["CTF", "Ang"])
        existing_layout.addRow("format:", self.h5ebsd_format)

        self.h5ebsd_file = QLineEdit()
        existing_layout.addRow("h5ebsd file:", self._browse_file_row(self.h5ebsd_file, EBSD_FILE_FILTER))
        layout.addWidget(self.existing_h5_group)
        return group

    def _build_raw_ebsd_group(self) -> QGroupBox:
        group = QGroupBox("Build H5EBSD from EBSD file stack")
        layout = QFormLayout(group)

        self.input_dir = QLineEdit()
        layout.addRow("input dir:", self._browse_directory_row(self.input_dir))

        self.file_prefix = QLineEdit()
        self.file_suffix = QLineEdit()
        self.file_extension = NoWheelComboBox()
        self.file_extension.addItems([label for label, _ref, _ext in H5EBSD_FORMAT_OPTIONS])
        self.file_prefix.setText("Slice_")
        layout.addRow("file prefix:", self.file_prefix)
        layout.addRow("file suffix:", self.file_suffix)
        layout.addRow("file extension:", self.file_extension)

        self.stacking_order_index = NoWheelComboBox()
        self.stacking_order_index.addItems(["0", "1"])
        self.stacking_order_index.setCurrentText("1")
        layout.addRow("stacking order index:", self.stacking_order_index)

        self.start_index = self._int_spin(value=1)
        self.end_index = self._int_spin(value=4)
        self.start_index.valueChanged.connect(self._sync_index_range)
        self.end_index.valueChanged.connect(self._sync_index_range)
        self._sync_index_range()
        self.padding_digits = self._int_spin(minimum=0, value=1)
        self.increment_index = self._int_spin(minimum=1, value=1)
        self.z_spacing = self._double_spin(minimum=0.0, value=0.25)
        layout.addRow("start index:", self.start_index)
        layout.addRow("end index:", self.end_index)
        layout.addRow("padding digits:", self.padding_digits)
        layout.addRow("increment index:", self.increment_index)
        layout.addRow("z spacing:", self.z_spacing)

        self.output_h5ebsd_file = QLineEdit()
        layout.addRow("output h5ebsd file:", self.output_h5ebsd_file)
        return group

    def _build_threshold_group(self) -> QGroupBox:
        group = QGroupBox("Threshold filters")
        outer = QVBoxLayout(group)

        self.ang_threshold_group = QGroupBox("ANG format thresholds")
        ang_layout = QFormLayout(self.ang_threshold_group)
        self.image_quality_threshold = self._double_spin(value=120.0)
        self.confidence_index_threshold = self._double_spin(value=0.1)
        ang_layout.addRow("image quality threshold:", self.image_quality_threshold)
        ang_layout.addRow("confidence index threshold:", self.confidence_index_threshold)
        outer.addWidget(self.ang_threshold_group)

        self.ctf_threshold_group = QGroupBox("CTF format thresholds")
        ctf_layout = QFormLayout(self.ctf_threshold_group)
        self.band_contrast_threshold = self._double_spin(value=50.0)
        self.mad_threshold = self._double_spin(value=1.0)
        ctf_layout.addRow("band contrast threshold:", self.band_contrast_threshold)
        ctf_layout.addRow("mad threshold:", self.mad_threshold)
        outer.addWidget(self.ctf_threshold_group)

        return group

    def _build_general_filter_group(self) -> QGroupBox:
        group = QGroupBox("General filter parameters")
        layout = QFormLayout(group)

        self.align_misorientation_tolerance = self._double_spin(value=5.0)
        self.bad_data_misorientation_tolerance = self._double_spin(value=5.0)
        self.bad_data_number_of_neighbors = self._int_spin(value=4)
        self.neighbor_correlation_min_confidence = self._double_spin(value=0.2)
        self.neighbor_correlation_level = self._int_spin(value=2)
        self.neighbor_correlation_misorientation_tolerance = self._double_spin(value=5.0)
        self.segment_misorientation_tolerance = self._double_spin(value=5.0)
        self.merge_twins_angle_tolerance = self._double_spin(value=2.0)
        self.merge_twins_axis_tolerance = self._double_spin(value=3.0)
        self.min_allowed_features_size = self._int_spin(value=16)
        self.min_feature_phase_number = self._int_spin(value=0)
        self.min_num_neighbors = self._int_spin(value=2)
        self.min_num_neighbors_phase = self._int_spin(value=0)
        self.min_allowed_defect_size = self._int_spin(value=1000)
        self.dilate_iterations = self._int_spin(value=2)
        self.erode_iterations = self._int_spin(value=2)
        self.reference_direction = QLineEdit()
        self.reference_direction.setText("0.0,0.0,1.0")
        self.smoothing_iterations = self._int_spin(value=25)

        for label, widget in (
            ("align misorientation tolerance:", self.align_misorientation_tolerance),
            ("bad data misorientation tolerance:", self.bad_data_misorientation_tolerance),
            ("bad data number of neighbors:", self.bad_data_number_of_neighbors),
            ("neighbor correlation min confidence:", self.neighbor_correlation_min_confidence),
            ("neighbor correlation level:", self.neighbor_correlation_level),
            ("neighbor correlation misorientation tolerance:", self.neighbor_correlation_misorientation_tolerance),
            ("segment misorientation tolerance:", self.segment_misorientation_tolerance),
            ("merge twins angle tolerance:", self.merge_twins_angle_tolerance),
            ("merge twins axis tolerance:", self.merge_twins_axis_tolerance),
            ("min allowed features size:", self.min_allowed_features_size),
            ("min feature phase number:", self.min_feature_phase_number),
            ("min num neighbors:", self.min_num_neighbors),
            ("min num neighbors phase:", self.min_num_neighbors_phase),
            ("min allowed defect size:", self.min_allowed_defect_size),
            ("dilate iterations:", self.dilate_iterations),
            ("erode iterations:", self.erode_iterations),
            ("reference direction:", self.reference_direction),
            ("smoothing iterations:", self.smoothing_iterations),
        ):
            layout.addRow(label, widget)
        return group

    def _build_dream3d_group(self) -> QGroupBox:
        group = dream3d_controls.build_dream3d_group(self, DREAM3D_SETTINGS_KEY)
        self._refresh_dream3d_status()
        return group

    def _settings(self) -> QSettings:
        return QSettings("MultiBEST", "MultiBEST")

    def _save_dream3d_path(self) -> None:
        dream3d_controls.save_dream3d_path(self, DREAM3D_SETTINGS_KEY)

    def _browse_dream3d_python(self) -> None:
        dream3d_controls.browse_dream3d_python(self, QFileDialog.getOpenFileName)

    def _refresh_dream3d_status(self) -> None:
        dream3d_controls.refresh_dream3d_status(self, DREAM3D_STATUS_MISSING_MESSAGE, discover_dream3d_python)

    def _test_dream3d_python(self) -> None:
        dream3d_controls.test_dream3d_python(self, discover_dream3d_python)

    def _install_dream3d_env(self) -> None:
        dream3d_controls.install_dream3d_env(
            self,
            install_dream3d_env,
            Dream3DError,
            QMessageBox,
            QProgressDialog,
            QApplication.processEvents,
        )

    def _build_ebsd_output_group(self) -> QGroupBox:
        group = QGroupBox("EBSD outputs")
        layout = QFormLayout(group)

        self.ebsd_visualization = QCheckBox()
        self.generate_all_slices = QCheckBox()
        self.generate_all_slices.setChecked(True)
        layout.addRow("ebsd visualization:", self.ebsd_visualization)
        layout.addRow("generate all slices:", self.generate_all_slices)

        self.visualization_output_dir = QLineEdit()
        layout.addRow("visualization output dir:", self._browse_directory_row(self.visualization_output_dir))

        self.stl_output_dir = QLineEdit()
        layout.addRow("stl output dir:", self._browse_directory_row(self.stl_output_dir))

        self.grain_data_file = QLineEdit()
        layout.addRow("grain data file:", self._create_csv_file_row(self.grain_data_file))

        self.output_dream3d_file = QLineEdit()
        layout.addRow("output dream3d file:", self._create_dream3d_file_row(self.output_dream3d_file))
        return group

    def _build_data_processing_group(self) -> QGroupBox:
        group = QGroupBox("Data processing and plotting")
        layout = QFormLayout(group)

        self.data_processing_input = QLineEdit()
        layout.addRow("grain data CSV:", self._browse_file_row(self.data_processing_input, TEXT_FILE_FILTER))

        self.processed_data_file = QLineEdit()
        layout.addRow("processed data TXT:", self._create_file_row(self.processed_data_file))

        self.convert_data_btn = make_primary_button("Convert", max_width=160)
        self.convert_data_btn.clicked.connect(self._run_data_processing)
        layout.addRow("", self.convert_data_btn)
        self._calc_btns.append(self.convert_data_btn)
        return group

    def _build_rescaling_group(self) -> QGroupBox:
        group = QGroupBox("Rescaling")
        layout = QFormLayout(group)

        self.rescale_input_dir = QLineEdit()
        layout.addRow("input dir:", self._browse_directory_row(self.rescale_input_dir))

        self.rescale_input_prefix = QLineEdit()
        self.rescale_output_dir = QLineEdit()
        self.scale_factor = self._double_spin(minimum=0.0, value=1.0)
        self.rescale_input_prefix.setText(DEFAULT_STL_PREFIX)
        layout.addRow("input prefix:", self.rescale_input_prefix)
        layout.addRow("output dir:", self._browse_directory_row(self.rescale_output_dir))
        layout.addRow("scale factor:", self.scale_factor)

        self.rescale_btn = make_primary_button("Rescale", max_width=160)
        self.rescale_btn.clicked.connect(self._run_rescaling)
        layout.addRow("", self.rescale_btn)
        self._calc_btns.append(self.rescale_btn)
        return group

    def _build_atomistic_group(self) -> QGroupBox:
        group = QGroupBox("Making atomistic model")
        layout = QVBoxLayout(group)

        form = QFormLayout()
        self.grain_data = QLineEdit()
        self.stl_dir = QLineEdit()
        self.atomistic_output_dir = QLineEdit()
        self.stl_prefix = QLineEdit()
        self.stl_prefix.setText(DEFAULT_STL_PREFIX)
        form.addRow("processed data TXT:", self._browse_file_row(self.grain_data, TEXT_FILE_FILTER))
        form.addRow("stl dir:", self._browse_directory_row(self.stl_dir))
        form.addRow("output dir:", self._browse_directory_row(self.atomistic_output_dir))
        form.addRow("stl prefix:", self.stl_prefix)

        self.verification_fig = QCheckBox()
        self.assembly = QCheckBox()
        self.assembly_output = QLineEdit()
        self.assembly.setChecked(True)
        form.addRow("verification fig:", self.verification_fig)
        form.addRow("assembly:", self.assembly)
        form.addRow("assembly output:", self._create_xyz_file_row(self.assembly_output))
        layout.addLayout(form)

        self.phase_layout = QVBoxLayout()
        layout.addLayout(self.phase_layout)
        phase_button_row = QHBoxLayout()
        add_phase_btn = make_action_button("Add more phases", "add")
        add_phase_btn.clicked.connect(lambda: self._add_phase())
        phase_button_row.addWidget(add_phase_btn)
        phase_button_row.addStretch()
        layout.addLayout(phase_button_row)

        model_params = QGroupBox("Model parameters")
        model_layout = QFormLayout(model_params)
        self.pitch = self._double_spin(minimum=0.0, value=0.3)
        self.padding_angstrom = self._double_spin(minimum=0.0, value=5.0)
        self.mask_dilate = self._double_spin(value=1.0)
        self.dilate = self._double_spin(value=1.0)
        self.close_parameter = self._double_spin(value=5.0)
        model_layout.addRow("pitch:", self.pitch)
        model_layout.addRow("padding angstrom:", self.padding_angstrom)
        model_layout.addRow("mask dilate:", self.mask_dilate)
        model_layout.addRow("dilate:", self.dilate)
        model_layout.addRow("close:", self.close_parameter)
        layout.addWidget(model_params)

        self.atomistic_btn = make_primary_button("Make Atomistic")
        self.atomistic_stop_btn = make_stop_button()
        self.atomistic_btn.clicked.connect(self._run_atomistic_model)
        self.atomistic_stop_btn.clicked.connect(self._stop_calculation)
        add_run_row(layout, self.atomistic_btn, self.atomistic_stop_btn)
        self._calc_btns.append(self.atomistic_btn)
        self._stop_btns.append(self.atomistic_stop_btn)
        return group

    def _build_visualization(self) -> QWidget:
        container = QFrame()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(0)

        self.viz_tabs = QTabWidget()
        self.mesh_viz_tab = QWidget()
        mesh_tab_layout = QVBoxLayout(self.mesh_viz_tab)
        mesh_tab_layout.setContentsMargins(12, 12, 12, 12)
        mesh_tab_layout.setSpacing(12)

        mesh_tab_layout.addWidget(stl_preview.build_mesh_preview_toolbar(self))

        self.mesh_preview_frame = QFrame()
        apply_preview_panel(self.mesh_preview_frame)
        mesh_preview_layout = QVBoxLayout(self.mesh_preview_frame)
        self.mesh_viz_label = self._preview_label("3D view of the generated mesh\n(not editable)")
        apply_preview_placeholder(self.mesh_viz_label)
        mesh_preview_layout.addWidget(self.mesh_viz_label)
        self.mesh_viewer = MeshViewer(self.mesh_preview_frame)
        self.mesh_viewer.hide()
        mesh_preview_layout.addWidget(self.mesh_viewer)
        mesh_tab_layout.addWidget(self.mesh_preview_frame, 1)

        self.atomistic_viz_tab = QWidget()
        self.atomistic_viz_layout = QVBoxLayout(self.atomistic_viz_tab)
        self.atomistic_viz_layout.setContentsMargins(12, 12, 12, 12)
        self.atomistic_viz_label = self._preview_label("3D view of the generated\natomistic model")
        self.atomistic_viz_layout.addWidget(self.atomistic_viz_label, 1)

        self.viz_tabs.addTab(self.mesh_viz_tab, "STL meshes")
        self.viz_tabs.addTab(self.atomistic_viz_tab, "Atomistic model")
        layout.addWidget(self.viz_tabs, 1)
        self.viz_layout = layout
        return container

    def _preview_label(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setWordWrap(True)
        apply_framed_preview_placeholder(label)
        return label

    # ------------------------------------------------------------------
    # Row helpers
    # ------------------------------------------------------------------

    def _browse_file_row(self, line_edit: QLineEdit, file_filter: str) -> QWidget:
        return make_path_row(line_edit, "Browse", lambda: browse_file(self, line_edit, file_filter))

    def _browse_directory_row(self, line_edit: QLineEdit) -> QWidget:
        return make_path_row(line_edit, "Browse", lambda: browse_directory(self, line_edit))

    def _create_file_row(self, line_edit: QLineEdit) -> QWidget:
        return make_path_row(line_edit, "Browse", lambda: create_file(self, line_edit), action="save")

    def _create_csv_file_row(self, line_edit: QLineEdit) -> QWidget:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(line_edit)
        button = QPushButton("Browse")
        button.clicked.connect(lambda: self._choose_csv_file(line_edit))
        layout.addWidget(button)
        return row

    def _choose_csv_file(self, line_edit: QLineEdit) -> None:
        filename, _ = QFileDialog.getSaveFileName(self, OUTPUT_FILE_DIALOG_TITLE, "", CSV_FILE_FILTER)
        if filename:
            line_edit.setText(self._force_extension(filename, ".csv"))

    def _create_dream3d_file_row(self, line_edit: QLineEdit) -> QWidget:
        return make_path_row(line_edit, "Browse", lambda: self._choose_dream3d_file(line_edit), action="save")

    def _choose_dream3d_file(self, line_edit: QLineEdit) -> None:
        filename, _ = QFileDialog.getSaveFileName(self, OUTPUT_FILE_DIALOG_TITLE, "", DREAM3D_FILE_FILTER)
        if filename:
            line_edit.setText(self._force_extension(filename, ".dream3d"))

    def _create_xyz_file_row(self, line_edit: QLineEdit) -> QWidget:
        return make_path_row(line_edit, "Browse", lambda: self._choose_xyz_file(line_edit), action="save")

    def _choose_xyz_file(self, line_edit: QLineEdit) -> None:
        filename, _ = QFileDialog.getSaveFileName(self, OUTPUT_FILE_DIALOG_TITLE, "", XYZ_FILE_FILTER)
        if filename:
            line_edit.setText(self._force_extension(filename, ".xyz"))

    def _force_extension(self, path: str, extension: str) -> str:
        if not path:
            return path
        root, _ = os.path.splitext(path)
        return root + extension

    def _button_row(self, button: QPushButton) -> QHBoxLayout:
        row = QHBoxLayout()
        row.addWidget(button)
        row.addStretch()
        return row

    def _sync_h5_branch_ui(self, h5_exists: bool) -> None:
        """Show the active EBSD source branch selected by the H5EBSD checkbox."""
        self.existing_h5_group.setVisible(h5_exists)
        self.ebsd_extrusion_group.setVisible(not h5_exists)
        self.raw_ebsd_group.setVisible(not h5_exists)
        if hasattr(self, "generate_replicas_btn"):
            self._sync_ebsd_dimension_ui(self.ebsd_is_3d.isChecked())
        self._sync_threshold_ui()

    def _sync_index_range(self) -> None:
        """Keep the raw EBSD stack start index at or below its end index."""
        self.start_index.setMaximum(self.end_index.value())
        self.end_index.setMinimum(self.start_index.value())

    def _sync_ebsd_dimension_ui(self, is_3d: bool) -> None:
        """Show only the EBSD input fields relevant to the selected dimensionality."""
        for widget in (self.input_2d_ebsd_label, self.input_2d_ebsd_row, self.replicate_label, self.replicate):
            widget.setVisible(not is_3d)
        if hasattr(self, "generate_replicas_btn"):
            self.generate_replicas_btn.setVisible(not is_3d and not self.h5ebsd_file_exists.isChecked())

        self._sync_threshold_ui()

    def _selected_format_option(self) -> tuple[str, int, str]:
        """Return the H5EBSD format option backing the current menu selection."""
        index = self.file_extension.currentIndex()
        if 0 <= index < len(H5EBSD_FORMAT_OPTIONS):
            return H5EBSD_FORMAT_OPTIONS[index]
        return H5EBSD_FORMAT_OPTIONS[0]

    def _selected_file_extension(self) -> str:
        """Return the file extension implied by the current format menu selection."""
        return self._selected_format_option()[2]

    def _selected_reference_frame_index(self) -> int:
        """Return the reference frame index implied by the format menu selection."""
        return self._selected_format_option()[1]

    def _detect_ebsd_extension(self) -> str:
        """Return the lowercase file extension inferred from the active EBSD input."""
        if self.h5ebsd_file_exists.isChecked():
            return f".{self.h5ebsd_format.currentText().strip().lower()}"

        if self.ebsd_is_3d.isChecked():
            path = ""
        else:
            path = self.input_2d_ebsd_data.text().strip()

        if path:
            return os.path.splitext(path)[1].lower()

        if not hasattr(self, "file_extension"):
            return ""
        return self._selected_file_extension()

    def _sync_threshold_ui(self) -> None:
        """Show only the threshold sub-group that matches the detected EBSD format."""
        if not hasattr(self, "ang_threshold_group"):
            return
        ext = self._detect_ebsd_extension()
        self.ang_threshold_group.setVisible(ext != ".ctf")
        self.ctf_threshold_group.setVisible(ext != ".ang")

    def _add_phase(self, name: str | None = None, cif_file_path: str = "") -> None:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)

        phase_name = QLineEdit()
        phase_name.setText(name or f"phase {len(self.phase_widgets) + 1}")
        cif_file = QLineEdit()
        cif_file.setText(cif_file_path)
        layout.addWidget(phase_name)
        layout.addWidget(self._browse_file_row(cif_file, CIF_FILE_FILTER), 1)

        remove_btn = make_action_button("Remove", "remove")
        layout.addWidget(remove_btn)

        phase = PhaseWidgets(phase_name, cif_file, row, remove_btn)
        remove_btn.clicked.connect(lambda checked=False, phase_to_remove=phase: self._remove_phase(phase_to_remove))
        self.phase_layout.addWidget(row)
        self.phase_widgets.append(phase)
        self._sync_phase_remove_buttons()

    def _remove_phase(self, phase: PhaseWidgets) -> None:
        """Remove a phase row while keeping at least one phase available."""
        if len(self.phase_widgets) <= 1:
            self._sync_phase_remove_buttons()
            return

        if phase not in self.phase_widgets:
            return

        self.phase_widgets.remove(phase)
        self.phase_layout.removeWidget(phase.row)
        phase.row.deleteLater()
        self._sync_phase_remove_buttons()

    def _sync_phase_remove_buttons(self) -> None:
        """Enable phase removal only when more than one phase exists."""
        enabled = len(self.phase_widgets) > 1
        for phase in self.phase_widgets:
            phase.remove_btn.setEnabled(enabled)

    def _double_spin(
        self,
        *,
        decimals: int = 6,
        minimum: float = -1_000_000.0,
        value: float = 0.0,
    ) -> NoWheelDoubleSpinBox:
        spin = NoWheelDoubleSpinBox()
        spin.setDecimals(decimals)
        spin.setRange(minimum, 1_000_000.0)
        spin.setSingleStep(0.1)
        spin.setValue(value)
        return spin

    def _int_spin(self, *, minimum: int = 0, value: int = 0) -> NoWheelSpinBox:
        spin = NoWheelSpinBox()
        spin.setRange(minimum, 1_000_000_000)
        spin.setValue(value)
        return spin

    # ------------------------------------------------------------------
    # Data collection
    # ------------------------------------------------------------------

    def collect_parameters(self) -> dict:
        """Return every UI value in a backend-friendly dictionary."""
        return {
            "ebsd_processing": self._collect_ebsd_processing(),
            "data_processing": self._collect_data_processing(),
            "rescaling": self._collect_rescaling(),
            "atomistic_model": self._collect_atomistic_model(),
        }

    def _collect_ebsd_processing(self) -> dict:
        grain_data_file = self._force_extension(self.grain_data_file.text().strip(), ".csv")
        if grain_data_file != self.grain_data_file.text().strip():
            self.grain_data_file.setText(grain_data_file)

        output_dream3d_file = self._force_extension(self.output_dream3d_file.text().strip(), ".dream3d")
        if output_dream3d_file != self.output_dream3d_file.text().strip():
            self.output_dream3d_file.setText(output_dream3d_file)

        return {
            "input": {
                "ebsd_dimension": "3d" if self.ebsd_is_3d.isChecked() else "2d",
                "2d_ebsd_data": self.input_2d_ebsd_data.text().strip(),
                "replicate": self.replicate.value(),
                "h5ebsd_file_exists": self.h5ebsd_file_exists.isChecked(),
                "h5ebsd_format": self.h5ebsd_format.currentText().strip().lower(),
                "start_slice": self.start_slice.value(),
                "end_slice": self.end_slice.value(),
                "h5ebsd_file": self.h5ebsd_file.text().strip(),
            },
            "input_ebsd_files": {
                "input_dir": self.input_dir.text().strip(),
                "file_prefix": self.file_prefix.text().strip(),
                "file_suffix": self.file_suffix.text().strip(),
                "file_extension": self._selected_file_extension(),
                "stacking_order_index": int(self.stacking_order_index.currentText()),
                "reference_frame_index": self._selected_reference_frame_index(),
                "start_index": self.start_index.value(),
                "end_index": self.end_index.value(),
                "padding_digits": self.padding_digits.value(),
                "increment_index": self.increment_index.value(),
                "z_spacing": self.z_spacing.value(),
                "output_h5ebsd_file": self.output_h5ebsd_file.text().strip(),
            },
            "thresholds": {
                "band_contrast_threshold": self.band_contrast_threshold.value(),
                "mad_threshold": self.mad_threshold.value(),
                "image_quality_threshold": self.image_quality_threshold.value(),
                "confidence_index_threshold": self.confidence_index_threshold.value(),
            },
            "filters": self._collect_filter_parameters(),
            "outputs": {
                "ebsd_visualization": self.ebsd_visualization.isChecked(),
                "generate_all_slices": self.generate_all_slices.isChecked(),
                "visualization_output_dir": self.visualization_output_dir.text().strip(),
                "stl_output_dir": self.stl_output_dir.text().strip(),
                "grain_data_file": grain_data_file,
                "output_dream3d_file": output_dream3d_file,
            },
        }

    def _collect_filter_parameters(self) -> dict:
        return {
            "align_misorientation_tolerance": self.align_misorientation_tolerance.value(),
            "bad_data_misorientation_tolerance": self.bad_data_misorientation_tolerance.value(),
            "bad_data_number_of_neighbors": self.bad_data_number_of_neighbors.value(),
            "neighbor_correlation_min_confidence": self.neighbor_correlation_min_confidence.value(),
            "neighbor_correlation_level": self.neighbor_correlation_level.value(),
            "neighbor_correlation_misorientation_tolerance": self.neighbor_correlation_misorientation_tolerance.value(),
            "segment_misorientation_tolerance": self.segment_misorientation_tolerance.value(),
            "merge_twins_angle_tolerance": self.merge_twins_angle_tolerance.value(),
            "merge_twins_axis_tolerance": self.merge_twins_axis_tolerance.value(),
            "min_allowed_features_size": self.min_allowed_features_size.value(),
            "min_feature_phase_number": self.min_feature_phase_number.value(),
            "min_num_neighbors": self.min_num_neighbors.value(),
            "min_num_neighbors_phase": self.min_num_neighbors_phase.value(),
            "min_allowed_defect_size": self.min_allowed_defect_size.value(),
            "dilate_iterations": self.dilate_iterations.value(),
            "erode_iterations": self.erode_iterations.value(),
            "reference_direction": self.reference_direction.text().strip(),
            "smoothing_iterations": self.smoothing_iterations.value(),
        }

    def _collect_data_processing(self) -> dict:
        return {
            "input": self.data_processing_input.text().strip(),
            "processed_data": self.processed_data_file.text().strip(),
        }

    def _collect_rescaling(self) -> dict:
        return {
            "input_dir": self.rescale_input_dir.text().strip(),
            "input_prefix": self.rescale_input_prefix.text().strip(),
            "output_dir": self.rescale_output_dir.text().strip(),
            "scale_factor": self.scale_factor.value(),
        }

    def _collect_atomistic_model(self) -> dict:
        return {
            "grain_data": self.grain_data.text().strip(),
            "stl_dir": self.stl_dir.text().strip(),
            "output_dir": self.atomistic_output_dir.text().strip(),
            "stl_prefix": self.stl_prefix.text().strip(),
            "verification_fig": self.verification_fig.isChecked(),
            "assembly": self.assembly.isChecked(),
            "assembly_output": self.assembly_output.text().strip(),
            "phases": [
                {
                    "name": phase.name.text().strip(),
                    "cif_file": phase.cif_file.text().strip(),
                }
                for phase in self.phase_widgets
            ],
            "parameters": {
                "pitch": self.pitch.value(),
                "padding_angstrom": self.padding_angstrom.value(),
                "mask_dilate": self.mask_dilate.value(),
                "dilate": self.dilate.value(),
                "close": self.close_parameter.value(),
            },
        }

    # ------------------------------------------------------------------
    # Mesh preview
    # ------------------------------------------------------------------

    def _collect_stl_meshes(self, output_dir: str, prefix: str) -> list[str]:
        if not output_dir or not prefix or not os.path.isdir(output_dir):
            return []

        pattern = re.compile(rf"^{re.escape(prefix)}(\d+)\.stl$", re.IGNORECASE)
        matches: list[tuple[int, str, str]] = []
        for path in Path(output_dir).iterdir():
            match = pattern.match(path.name)
            if path.is_file() and match:
                matches.append((int(match.group(1)), path.name.lower(), str(path)))
        return [path for _index, _name, path in sorted(matches)]

    def _refresh_stl_visualization(self, output_dir: str, prefix: str) -> None:
        self.viz_tabs.setCurrentWidget(self.mesh_viz_tab)
        paths = self._collect_stl_meshes(output_dir, prefix)
        self._set_stl_mesh_choices(paths)
        if not paths:
            self.mesh_viewer.clear()
            self.mesh_viewer.hide()
            self.mesh_viz_label.setText(f"No generated STL files found\nPrefix: {prefix}")
            self.mesh_viz_label.show()
            self.logger.log_message("WARNING", f"No generated STL files found in:\n{output_dir}")
            return
        self._load_mesh_preview(paths[0])

    def _set_stl_mesh_choices(self, paths: list[str]) -> None:
        stl_preview.set_mesh_choices(self, paths, lambda path: Path(path).name, "STL file", "STL files")

    def _load_mesh_preview(self, path: str) -> None:
        stl_preview.load_mesh_preview(self, path, QApplication.processEvents)

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    def _run_ebsd_processing(self) -> None:

        params = self._collect_ebsd_processing()
        script_path, args, output_dir, label = self._prepare_ebsd_backend_run(params)
        if script_path is None or args is None or label is None:
            return

        self._set_running(True)
        stl_output_dir = params["outputs"]["stl_output_dir"]
        self.runner.on_finished_cb = self._make_finish_callback(
            label,
            lambda: self._refresh_stl_visualization(stl_output_dir, DEFAULT_STL_PREFIX),
        )
        # EBSD preparation depends on simplnx (DREAM3D-NX), which is not
        # redistributable with MultiBEST — run the script with the external
        # DREAM3D-NX interpreter resolved during validation.
        self.runner.start_program(self._dream3d_python, args=["-u", script_path, *args], cwd=output_dir)
        self.mesh_viz_label.setText(f"3D view of the generated mesh\nRunning: {label}")

    def _run_ebsd_replication(self) -> None:
        input_file = self.input_2d_ebsd_data.text().strip()
        if not self._validate_input_file(input_file):
            return

        output_dir = os.path.dirname(os.path.abspath(input_file))
        script_path = get_script_path("..", "ebsd_atomistic", "replicate.py")
        args = [input_file, "--replicate", str(self.replicate.value())]
        self._set_running(True)
        self.runner.on_finished_cb = self._make_finish_callback("2D EBSD replication")
        self.runner.start(script_path, args=args, cwd=output_dir)
        self.mesh_viz_label.setText("3D view of the generated mesh\nRunning: 2D EBSD replication")

    def _run_data_processing(self) -> None:
        input_file = self.data_processing_input.text().strip()
        if not self._validate_input_file(input_file):
            return
        output_file = self.processed_data_file.text().strip()
        if not output_file:
            self.logger.log_message("ERROR", "Please choose a processed data output file first.")
            return
        output_dir = os.path.dirname(os.path.abspath(output_file))
        if not self._validate_output_dir(output_dir):
            return

        script_path = get_script_path("..", "ebsd_atomistic", "euler_to_angle.py")
        self._set_running(True)
        self.runner.on_finished_cb = self._make_finish_callback("EBSD data processing")
        self.runner.start(script_path, args=["--input", input_file, "--output", output_file], cwd=output_dir)
        self.logger.log_message("INFO", f"Started EBSD data processing:\n{output_file}")

    def _run_rescaling(self) -> None:
        input_dir = self.rescale_input_dir.text().strip()
        if not input_dir:
            self.logger.log_message("ERROR", "Please choose a rescale input directory first.")
            return
        if not os.path.isdir(input_dir):
            self.logger.log_message("ERROR", f"Rescale input directory not found:\n{input_dir}")
            return
        if not self.rescale_input_prefix.text().strip():
            self.logger.log_message("ERROR", "Please enter an STL input prefix first.")
            return
        output_dir = self.rescale_output_dir.text().strip()
        if not self._validate_output_dir(output_dir):
            return

        params = self._collect_rescaling()
        script_path = get_script_path("..", "ebsd_atomistic", "stl_ebsd_rescale.py")
        args = [
            "--scale_factor",
            self._format_value(params["scale_factor"]),
            "--input_dir",
            params["input_dir"],
            "--input_prefix",
            params["input_prefix"],
            "--output_dir",
            params["output_dir"],
        ]
        self._set_running(True)
        self.runner.on_finished_cb = self._make_finish_callback(
            "EBSD STL rescaling",
            lambda: self._refresh_stl_visualization(params["output_dir"], params["input_prefix"]),
        )
        self.runner.start(script_path, args=args, cwd=output_dir)
        self.mesh_viz_label.setText(f"3D view of the generated mesh\nRescaling: {output_dir}")

    def _run_atomistic_model(self) -> None:
        output_dir = self.atomistic_output_dir.text().strip()
        if not self._validate_output_dir(output_dir):
            return
        params = self._collect_atomistic_model()
        if not self._validate_atomistic_inputs(params):
            return

        path = self._write_atomistic_input_file(output_dir, params)
        script_path = get_script_path("..", "ebsd_atomistic", "ebsd_stl_fill_atoms.py")
        gpt_script = get_script_path("..", "mesh_to_atomistic", "gpt-mod-1.py")
        self._atomistic_output_candidates = self._atomistic_result_candidates(params)
        self._refresh_stl_visualization(params["stl_dir"], params["stl_prefix"])
        self._reset_atomistic_visualization()
        self.viz_tabs.setCurrentWidget(self.atomistic_viz_tab)
        self._set_running(True)
        self.runner.on_finished_cb = self._make_finish_callback("EBSD atomistic model", self._plot_atomistic_model)
        self.runner.start(script_path, args=[path, "--gpt_script", gpt_script], cwd=output_dir)
        self.atomistic_viz_label.setText(
            f"3D view of the generated atomistic model\nPhases: {len(params['phases'])}\nInput: {path}"
        )

    def _atomistic_result_candidates(self, params: dict) -> list[str]:
        output_dir = params["output_dir"]
        candidates: list[str] = []
        if params["assembly"]:
            assembly_output = params["assembly_output"] or os.path.join(output_dir, "assembled_final.xyz")
            if not os.path.isabs(assembly_output):
                assembly_output = os.path.join(output_dir, assembly_output)
            candidates.append(assembly_output)

        prefix = params["stl_prefix"]
        try:
            grain_ids = self._atomistic_grain_ids(params["grain_data"])
        except Exception as exc:
            self.logger.log_message("WARNING", f"Could not precompute atomistic output names:\n{exc}")
            grain_ids = []
        candidates.extend(os.path.join(output_dir, f"{prefix}{grain_id}.xyz") for grain_id in grain_ids)
        return candidates

    def _atomistic_grain_ids(self, grain_data_path: str) -> list[str]:
        with open(grain_data_path, encoding="utf-8", errors="replace") as handle:
            lines = handle.readlines()
        if not lines:
            return []

        header = lines[0].strip().split("\t")
        grain_id_idx = header.index("grain_ID")
        phase_idx = header.index("Phases_Export")
        euler_indices = [
            header.index("AvgEulerAngles_Export_0"),
            header.index("AvgEulerAngles_Export_1"),
            header.index("AvgEulerAngles_Export_2"),
        ]

        grain_ids = []
        for line in lines[1:]:
            parts = line.strip().split("\t")
            if len(parts) <= max(grain_id_idx, phase_idx, *euler_indices):
                continue
            if parts[phase_idx].strip() == "0":
                continue
            eulers = [parts[index].strip() for index in euler_indices]
            if all(value == "0.000000" for value in eulers):
                continue
            grain_ids.append(parts[grain_id_idx].strip())
        return grain_ids

    def _plot_atomistic_model(self) -> None:
        path = next((candidate for candidate in self._atomistic_output_candidates if os.path.isfile(candidate)), "")
        if not path:
            self.logger.log_message("ERROR", "No generated atomistic XYZ output was found to visualize.")
            return

        try:
            self._clear_atomistic_scene()
            pipeline = import_file(path)
            pipeline.compute()
            pipeline.add_to_scene()

            viewport = Viewport(type=Viewport.Type.PERSPECTIVE)
            widget = create_qwidget(viewport)
            self._replace_atomistic_visualization_widget(widget)
            self.viz_tabs.setCurrentWidget(self.atomistic_viz_tab)
            viewport.zoom_all()

            self._atomistic_pipeline = pipeline
            self._atomistic_viewport = viewport
            self._atomistic_ovito_widget = widget
            self.logger.log_message("INFO", f"Loaded atomistic visualization:\n{path}")
        except Exception as exc:
            self.logger.log_message("ERROR", f"Failed to visualize atomistic output:\n{exc}")

    def _clear_atomistic_scene(self) -> None:
        clear_ovito_scene(lambda message: self.logger.log_message("WARNING", message))
        self._atomistic_pipeline = None
        self._atomistic_viewport = None

    def _reset_atomistic_visualization(self) -> None:
        self._clear_atomistic_scene()
        label = self._preview_label("3D view of the generated\natomistic model")
        self._replace_atomistic_visualization_widget(label)
        self.atomistic_viz_label = label

    def _replace_atomistic_visualization_widget(self, new_widget: QWidget) -> None:
        if self.atomistic_viz_label is not None:
            self.atomistic_viz_layout.removeWidget(self.atomistic_viz_label)
            self.atomistic_viz_label.deleteLater()
            self.atomistic_viz_label = None

        if self._atomistic_ovito_widget is not None:
            self.atomistic_viz_layout.removeWidget(self._atomistic_ovito_widget)
            self._atomistic_ovito_widget.deleteLater()
            self._atomistic_ovito_widget = None

        self.atomistic_viz_layout.addWidget(new_widget, 1)

    def _prepare_ebsd_backend_run(
        self,
        params: dict,
    ) -> tuple[str, list[str], str, str] | tuple[None, None, None, None]:
        output_dir = self._ebsd_output_dir(params)
        if not self._validate_output_dir(output_dir):
            return None, None, None, None
        if not self._validate_ebsd_processing_inputs(params):
            return None, None, None, None
        if not self._validate_dream3dnx_runtime():
            return None, None, None, None

        param_file = self._write_ebsd_input_file(output_dir, params)
        script_path = get_source_script_path("..", "ebsd_atomistic", "EBSD_Atomistic.py")
        return script_path, [param_file], output_dir, "EBSD preparation"

    def _ebsd_output_dir(self, params: dict) -> str:
        outputs = params["outputs"]
        output_candidates = (
            outputs["output_dream3d_file"],
            outputs["grain_data_file"],
            outputs["visualization_output_dir"],
            outputs["stl_output_dir"],
        )
        for value in output_candidates:
            if not value:
                continue
            if os.path.splitext(value)[1]:
                return os.path.dirname(os.path.abspath(value))
            return value
        return self.input_dir.text().strip()

    def _validate_ebsd_processing_inputs(self, params: dict) -> bool:
        input_params = params["input"]
        outputs = params["outputs"]
        if input_params["h5ebsd_file_exists"]:
            if not self._validate_input_file(input_params["h5ebsd_file"]):
                return False
        else:
            input_dir = params["input_ebsd_files"]["input_dir"]
            if not input_dir:
                self.logger.log_message("ERROR", "Please choose an EBSD input directory first.")
                return False
            if not os.path.isdir(input_dir):
                self.logger.log_message("ERROR", f"EBSD input directory not found:\n{input_dir}")
                return False
        required_outputs = {
            "output_dream3d_file": "Please choose an output Dream3D file first.",
            "stl_output_dir": "Please choose an STL output directory first.",
            "grain_data_file": "Please choose a grain data output file first.",
        }
        for key, message in required_outputs.items():
            if not outputs[key]:
                self.logger.log_message("ERROR", message)
                return False
        return True

    def _resolve_dream3d_python(self) -> str | None:
        """Return a working external DREAM3D-NX interpreter, caching the result."""
        saved = self.dream3d_python.text().strip()
        cached = self._dream3d_python
        if cached and (not saved or cached == saved) and os.path.isfile(cached):
            return cached

        found = discover_dream3d_python(saved)
        if not found:
            return None
        self._dream3d_python = str(found)
        self.dream3d_python.setText(str(found))
        self._save_dream3d_path()
        return self._dream3d_python

    def _validate_dream3dnx_runtime(self) -> bool:
        if self._resolve_dream3d_python() is None:
            self.logger.log_message("ERROR", DREAM3DNX_MISSING_MESSAGE)
            return False
        return True

    def _validate_atomistic_inputs(self, params: dict) -> bool:
        if not self._validate_input_file(params["grain_data"]):
            return False
        stl_dir = params["stl_dir"]
        if not stl_dir:
            self.logger.log_message("ERROR", "Please choose an STL directory first.")
            return False
        if not os.path.isdir(stl_dir):
            self.logger.log_message("ERROR", f"STL directory not found:\n{stl_dir}")
            return False
        if not params["phases"]:
            self.logger.log_message("ERROR", "Please define at least one phase.")
            return False
        for index, phase in enumerate(params["phases"], start=1):
            if not phase["cif_file"]:
                self.logger.log_message("ERROR", f"Phase {index}: please choose a CIF file first.")
                return False
            if not os.path.isfile(phase["cif_file"]):
                self.logger.log_message("ERROR", f"Phase {index}: CIF file not found:\n{phase['cif_file']}")
                return False
        if params["parameters"]["pitch"] <= 0:
            self.logger.log_message("ERROR", "Pitch must be greater than zero.")
            return False
        return True

    def _write_ebsd_input_file(self, output_dir: str, params: dict) -> str:
        param_file = os.path.join(output_dir, "input_EBSD_Atomistic.txt")
        self.logger.log_message("INFO", f"Writing EBSD input file: {param_file}")
        with open(param_file, "w", encoding="utf-8") as handle:
            handle.write(self._format_ebsd_input(params))
        return param_file

    def _write_atomistic_input_file(self, output_dir: str, params: dict) -> str:
        param_file = os.path.join(output_dir, "input_ebsd_stl_fill_atoms.txt")
        self.logger.log_message("INFO", f"Writing atomistic input file: {param_file}")
        with open(param_file, "w", encoding="utf-8") as handle:
            handle.write(self._format_atomistic_input(params))
        return param_file

    def _format_ebsd_input(self, params: dict) -> str:
        input_params = params["input"]
        file_params = params["input_ebsd_files"]
        outputs = params["outputs"]
        lines = ["# Generated by MultiBEST EBSD-to-atomistic UI"]
        if input_params["h5ebsd_file_exists"]:
            lines.extend(
                [
                    "has_h5ebsd yes",
                    f"h5ebsd_file {input_params['h5ebsd_file']}",
                    f"data_format {input_params['h5ebsd_format']}",
                    f"start_slice {input_params['start_slice']}",
                    f"end_slice {input_params['end_slice']}",
                ]
            )
        else:
            lines.extend(
                [
                    "has_h5ebsd no",
                    f"input_dir {file_params['input_dir']}",
                    f"file_prefix {file_params['file_prefix']}",
                    f"start_index {file_params['start_index']}",
                    f"end_index {file_params['end_index']}",
                    f"padding_digits {file_params['padding_digits']}",
                    f"file_extension {file_params['file_extension']}",
                    f"file_suffix {file_params['file_suffix']}",
                    f"increment_index {file_params['increment_index']}",
                    f"z_spacing {file_params['z_spacing']}",
                    f"reference_frame_index {file_params['reference_frame_index']}",
                    f"stacking_order_index {file_params['stacking_order_index']}",
                    f"output_h5ebsd_file {file_params['output_h5ebsd_file']}",
                ]
            )

        lines.extend(
            [
                f"output_dream3d {outputs['output_dream3d_file']}",
                f"stl_output_dir {outputs['stl_output_dir']}",
                f"grain_data_file {outputs['grain_data_file']}",
                f"ebsd_visualization {outputs['ebsd_visualization']}",
                f"generate_all_slices {outputs['generate_all_slices']}",
                f"visualization_output_dir {outputs['visualization_output_dir']}",
            ]
        )
        lines.extend(f"{key} {self._format_value(value)}" for key, value in params["thresholds"].items())
        for key, value in params["filters"].items():
            if key == "reference_direction":
                lines.append(f"{key} {value}")
            else:
                lines.append(f"{key} {self._format_value(value)}")
        lines.append("")
        return "\n".join(lines)

    def _format_atomistic_input(self, params: dict) -> str:
        setup = params["parameters"]
        lines = [
            "# Generated by MultiBEST EBSD-to-atomistic UI",
            f"grain_data {params['grain_data']}",
            f"stl_dir {params['stl_dir']}",
            f"output_dir {params['output_dir']}",
            f"stl_prefix {params['stl_prefix']}",
            f"verification_fig {self._on_off(params['verification_fig']).lower()}",
            "",
            f"assembly {self._on_off(params['assembly']).lower()}",
            f"assembly_output {params['assembly_output']}",
            "",
        ]
        for index, phase in enumerate(params["phases"], start=1):
            lines.append(f"phase {index} --cif {phase['cif_file']}")
        lines.extend(
            [
                "",
                "setup "
                f"--pitch {self._format_value(setup['pitch'])} "
                f"--padding-angstrom {self._format_value(setup['padding_angstrom'])} "
                f"--mask-dilate {self._format_value(setup['mask_dilate'])} "
                f"--dilate {self._format_value(setup['dilate'])} "
                f"--close {self._format_value(setup['close'])}",
                "",
            ]
        )
        return "\n".join(lines)

    def _on_off(self, value: bool) -> str:
        return "on" if value else "off"

    def _format_value(self, value: object) -> str:
        if isinstance(value, float):
            return f"{value:g}"
        return str(value)

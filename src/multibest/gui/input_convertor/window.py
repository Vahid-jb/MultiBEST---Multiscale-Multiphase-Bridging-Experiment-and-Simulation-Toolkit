# SPDX-FileCopyrightText: 2026 bright-ideas-clan
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Input Convertor GUI Application.

This application provides a graphical interface for converting atomistic
structure files.
It mimics the interface design specified in VCL.drawio under "Input convertor".
"""

from __future__ import annotations

import os

os.environ["OVITO_GUI_MODE"] = "1"

import numpy as np
from ovito.gui import create_qwidget
from ovito.io import import_file
from ovito.vis import Viewport
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from multibest.gui.utils import ovito_scene
from multibest.gui.utils.base_window import BaseModuleWindow
from multibest.gui.utils.general import (
    browse_directory,
    browse_file,
    create_file,
    get_script_path,
)
from multibest.gui.utils.theme import (
    NoWheelComboBox,
    apply_dark_theme,
    apply_module_title,
    apply_preview_placeholder,
    make_path_row,
    make_primary_button,
    make_stop_button,
)

ATOMISTIC_MODEL_PLACEHOLDER = "3D view of the generated atomistic model\n(OVITO viewport will appear here)"


class InputConvertorWindow(BaseModuleWindow):
    """
    Main Window for the Input Convertor application.

    Attributes:
        convert_input (QLineEdit): Field for input file path.
        convert_output (QLineEdit): Field for output file path.
        convert_structure_type (QComboBox): Selector for LAMMPS structure file type.
        convert_btn (QPushButton): Button to trigger conversion.
    """

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Input Convertor")
        self.resize(800, 600)

        main_layout, left_layout = self._build_split_layout()

        # Header
        header = QLabel("Input convertor")
        apply_module_title(header)
        left_layout.addWidget(header)

        # Input/Output Config Group
        io_group = QGroupBox("I/O Configuration")
        io_layout = QFormLayout(io_group)

        self.convert_input = QLineEdit()
        io_layout.addRow(
            "Input file:",
            make_path_row(
                self.convert_input,
                "Browse",
                lambda: browse_file(
                    self,
                    self.convert_input,
                    "Atomistic structures (*.xyz *.lammps *.lmp *.dump *.cif);;All files (*)",
                ),
            ),
        )

        self.convert_output = QLineEdit()
        io_layout.addRow(
            "Output file:",
            make_path_row(
                self.convert_output,
                "Browse",
                lambda: create_file(self, self.convert_output),
                action="save",
            ),
        )

        self.convert_out_dir = QLineEdit()
        io_layout.addRow(
            "Output directory:",
            make_path_row(self.convert_out_dir, "Browse", lambda: browse_directory(self, self.convert_out_dir)),
        )

        left_layout.addWidget(io_group)

        # Parameters Group
        params_group = QGroupBox("Parameters")
        params_layout = QVBoxLayout(params_group)

        params_layout.addWidget(QLabel("LAMMPS structure file type:"))
        self.convert_structure_type = NoWheelComboBox()
        self.convert_structure_type.addItems(["classic", "charge", "spin"])
        params_layout.addWidget(self.convert_structure_type)

        unskew_layout = QHBoxLayout()
        unskew_layout.addWidget(QLabel("Unskew and align:"))
        self.convert_unskew = NoWheelComboBox()
        self.convert_unskew.addItems(["yes", "no"])
        unskew_layout.addWidget(self.convert_unskew)
        params_layout.addLayout(unskew_layout)

        left_layout.addWidget(params_group)
        left_layout.addStretch()

        # Run Button
        self.convert_btn = make_primary_button("Convert")
        self.stop_btn = make_stop_button()
        self.convert_btn.clicked.connect(self._run_convert)
        self.stop_btn.clicked.connect(self._stop_calculation)
        _btn_row = QHBoxLayout()
        _btn_row.addWidget(self.convert_btn)
        _btn_row.addWidget(self.stop_btn)
        _btn_row.addStretch()
        left_layout.addLayout(_btn_row)

        self._calc_btns = [self.convert_btn]
        self._stop_btns = [self.stop_btn]

        # Right Panel - OVITO viewport host
        self.right_container = QFrame()
        self.right_layout_container = QVBoxLayout(self.right_container)
        self.right_layout_container.setContentsMargins(0, 0, 0, 0)
        main_layout.addWidget(self.right_container, 2)

        self.right_splitter = QSplitter(Qt.Orientation.Vertical)
        self.right_layout_container.addWidget(self.right_splitter)

        self.viewport_container = QWidget()
        self.viewport_layout = QVBoxLayout(self.viewport_container)
        self.viewport_layout.setContentsMargins(0, 0, 0, 0)
        self.right_splitter.addWidget(self.viewport_container)

        # Placeholder shown until first load
        self.vis_label = QLabel(ATOMISTIC_MODEL_PLACEHOLDER)
        self.vis_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        apply_preview_placeholder(self.vis_label)
        self.viewport_layout.addWidget(self.vis_label)

        # Bottom: Simulation Info Tabs
        self.info_tabs = QWidget()
        self.info_layout = QVBoxLayout(self.info_tabs)
        self.right_splitter.addWidget(self.info_tabs)

        self.info_tab_widget = QTabWidget()
        self.info_layout.addWidget(self.info_tab_widget)

        self.cell_table = QTableWidget()
        self.cell_table.setColumnCount(3)
        self.cell_table.setHorizontalHeaderLabels(["Property", "Value", "Unit/Extra"])
        self.cell_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.info_tab_widget.addTab(self.cell_table, "Simulation Cell")

        self.particles_table = QTableWidget()
        self.particles_table.setColumnCount(4)
        self.particles_table.setHorizontalHeaderLabels(["Type ID", "Name", "Count", "Color/Radius"])
        self.particles_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.info_tab_widget.addTab(self.particles_table, "Particle Types")

        self.right_splitter.setSizes([500, 200])

        # OVITO state
        self._ovito_widget = None
        self._pipeline = None
        self._viewport = None

        # Public interface for PolyCycleMainWindow
        self.control_widget = self.left_scroll
        self.viz_widget = self.right_container

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    def _run_convert(self) -> None:
        """Validate inputs, write parameter file, and launch the convertor script."""
        # Clean up old OVITO pipeline from scene
        if self._pipeline is not None:
            self._pipeline.remove_from_scene()
            self._pipeline = None

        # Clear tables
        self.cell_table.setRowCount(0)
        self.particles_table.setRowCount(0)

        lbl = QLabel(ATOMISTIC_MODEL_PLACEHOLDER)
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        apply_preview_placeholder(lbl)
        self._replace_viewport_widget(lbl)
        self.vis_label = lbl

        input_path = self.convert_input.text().strip()
        output_path = self.convert_output.text().strip()
        out_dir_path = self.convert_out_dir.text().strip()

        if not self._validate_input_file(input_path):
            return
        if not output_path:
            self.logger.log_message("ERROR", "Please choose an output file first.")
            return
        if not self._validate_output_dir(out_dir_path):
            return

        output_path = self._resolve_to_outdir(self.convert_output, out_dir_path)

        convertor_params = {
            "input_file": input_path,
            "output_file": output_path,
            "charge/spin": self.convert_structure_type.currentText(),
            "unskew_and_align": self.convert_unskew.currentText(),
        }

        param_file_path = os.path.join(out_dir_path, "convertor_input.txt")

        # Input Convertor uses space-separated params (not "key = value")
        self.logger.log_message("INFO", f"Writing parameter file with: {convertor_params}")
        with open(param_file_path, "w", encoding="utf-8") as f:
            for key, value in convertor_params.items():
                f.write(f"{key} {value}\n")

        self._set_running(True)
        self.runner.on_finished_cb = self._make_finish_callback("Conversion", self._plot_convert)
        script_path = get_script_path("..", "input_convertor", "input_convertor.py")
        self.runner.start(script_path, args=[param_file_path], cwd=out_dir_path)

    def _plot_convert(self) -> None:
        """Load the converted output file into the OVITO viewport."""
        path = self.convert_output.text().strip()
        # If the file is not found, try resolving against the output directory
        if path and not os.path.isfile(path):
            out_dir = self.convert_out_dir.text().strip()
            if out_dir:
                resolved = os.path.join(out_dir, os.path.basename(path))
                if os.path.isfile(resolved):
                    path = resolved
        if not path or not os.path.isfile(path):
            self.logger.log_message("ERROR", f"Output file not found:\n{path}")
            return

        try:
            self._clear_ovito_scene()
            pipeline = self._import_atomistic_file(path)
            # Warm the cache before scene insertion so the first viewport paint
            # does not trigger an implicit recompute (noticeable on OVITO >=3.15).
            data = pipeline.compute()
            pipeline.add_to_scene()

            vp = Viewport(type=Viewport.Type.PERSPECTIVE)
            widget = create_qwidget(vp)
            self._replace_viewport_widget(widget)
            vp.zoom_all()

            self._pipeline = pipeline
            self._viewport = vp
            self._ovito_widget = widget

            self._update_info_panels(data)

        except Exception as e:
            self.logger.log_message("ERROR", f"Failed to load/visualize file:\n{e}")

    def _import_atomistic_file(self, path: str):
        return ovito_scene.import_atomistic_file(
            path,
            self._import_kwargs(path),
            import_file,
            lambda message: self.logger.log_message("INFO", message),
        )

    def _import_kwargs(self, path: str) -> dict[str, str]:
        """Return OVITO ``import_file`` kwargs for LAMMPS data files.

        OVITO cannot reliably auto-detect ``charge``/``spin`` atom styles from
        column counts alone, so we pass the style the user selected.
        """
        if os.path.splitext(path)[1].lower() not in (".lmp", ".data", ".lammps"):
            return {}
        style_map = {"classic": "atomic", "charge": "charge", "spin": "spin"}
        style = style_map.get(self.convert_structure_type.currentText())
        return {"atom_style": style} if style else {}

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _clear_ovito_scene(self) -> None:
        ovito_scene.clear_ovito_scene(lambda message: self.logger.log_message("WARNING", message))
        self._pipeline = None
        self._viewport = None

    def _reset_visualization(self) -> None:
        self._clear_ovito_scene()

        self.cell_table.setRowCount(0)
        self.particles_table.setRowCount(0)

        lbl = QLabel(ATOMISTIC_MODEL_PLACEHOLDER)
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl.setStyleSheet("color: #aaa; font-size: 14px;")
        self._replace_viewport_widget(lbl)
        self.vis_label = lbl

    def _update_info_panels(self, data) -> None:
        """Updates the info tables with data from the OVITO DataCollection."""
        self._update_cell_table(data)
        self._update_particles_table(data)

    def _update_cell_table(self, data) -> None:
        """Update the simulation cell table with cell metadata."""
        self.cell_table.setRowCount(0)
        if not data.cell:
            return

        self._populate_table(self.cell_table, self._cell_rows(data.cell))

    def _cell_rows(self, cell) -> list[tuple[str, str, str]]:
        """Return display rows for the simulation cell table."""
        matrix = cell[:3, :3]
        origin = cell[:, 3]
        return [
            ("Vector A", f"{matrix[:, 0]}", ""),
            ("Vector B", f"{matrix[:, 1]}", ""),
            ("Vector C", f"{matrix[:, 2]}", ""),
            ("Origin", f"{origin[:3]}", ""),
            ("PBC", f"{cell.pbc}", ""),
            ("Volume", f"{cell.volume:.4f}", "ų"),
        ]

    def _update_particles_table(self, data) -> None:
        """Update the particle types table with particle metadata."""
        self.particles_table.setRowCount(0)
        if not data.particles or "Particle Type" not in data.particles:
            return

        ptypes = data.particles["Particle Type"]
        unique_types, counts = np.unique(ptypes, return_counts=True)
        type_defs = getattr(ptypes, "types", None)
        rows = [
            self._particle_type_row(type_id, count, type_defs)
            for type_id, count in zip(unique_types, counts, strict=True)
        ]
        self._populate_table(self.particles_table, rows)

    def _particle_type_row(self, type_id, count, type_defs) -> tuple[str, str, str, str]:
        """Return one display row for the particle types table."""
        type_def = self._find_particle_type_def(type_id, type_defs)
        name = getattr(type_def, "name", None) or f"Type {type_id}"
        color_radius = self._particle_color_radius(type_def)
        return str(type_id), name, str(count), color_radius

    def _find_particle_type_def(self, type_id, type_defs):
        """Find the OVITO particle type definition for a type id."""
        if not type_defs:
            return None

        return next((type_def for type_def in type_defs if type_def.id == type_id), None)

    def _particle_color_radius(self, type_def) -> str:
        """Return formatted particle radius and color metadata."""
        if not type_def:
            return ""

        return f"r={type_def.radius:.2f}, c={type_def.color}"

    def _populate_table(self, table: QTableWidget, rows) -> None:
        """Populate a table with stringified row values."""
        table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            for column_index, value in enumerate(row):
                table.setItem(row_index, column_index, QTableWidgetItem(str(value)))

    def _replace_viewport_widget(self, new_widget: QWidget) -> None:
        """Swap the OVITO viewport widget, removing any placeholder."""
        if getattr(self, "vis_label", None) is not None:
            self.viewport_layout.removeWidget(self.vis_label)
            self.vis_label.deleteLater()
            self.vis_label = None

        if getattr(self, "_ovito_widget", None) is not None:
            self.viewport_layout.removeWidget(self._ovito_widget)
            self._ovito_widget.deleteLater()
            self._ovito_widget = None

        self.viewport_layout.addWidget(new_widget)


if __name__ == "__main__":
    import sys

    from multibest.gui.utils.qt_bootstrap import force_x11_if_wayland

    force_x11_if_wayland()

    app = QApplication(sys.argv)
    apply_dark_theme(app)
    window = InputConvertorWindow()
    window.show()
    sys.exit(app.exec())

# SPDX-FileCopyrightText: 2026 bright-ideas-clan
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Reusable PyVista-backed mesh viewer widget for MultiBEST GUI modules."""

from __future__ import annotations

import os
from dataclasses import dataclass

import pyvista as pv
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget
from pyvistaqt import QtInteractor

from multibest.gui.utils.theme import QLEMENTINE_DARK, apply_preview_placeholder

SUPPORTED_SUFFIXES = (".obj", ".stl", ".ply", ".vtk", ".vtp")


@dataclass(frozen=True)
class MeshData:
    """Lightweight summary of the currently displayed mesh."""

    point_count: int
    face_count: int


class MeshViewer(QWidget):
    """Qt widget that renders mesh previews with PyVista's interactive plotter."""

    BACKGROUND_COLOR = QLEMENTINE_DARK["background_workspace"]
    MESH_COLOR = "#dbdbd2"
    EDGE_COLOR = "#2e2e2e"

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)

        self.status_label = QLabel("Mesh preview will appear after loading a mesh", self)
        apply_preview_placeholder(self.status_label)
        self.status_label.setWordWrap(True)
        self._layout.addWidget(self.status_label)

        self.plotter: QtInteractor | None = None
        self.current_path = ""
        self.mesh_data: MeshData | None = None
        self._mesh: pv.PolyData | None = None

    def showEvent(self, event) -> None:  # noqa: N802 (Qt override)
        super().showEvent(event)
        if self.plotter is None:
            self._init_plotter()

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt override)
        if self.plotter is not None:
            self.plotter.close()
            self.plotter = None
        super().closeEvent(event)

    def _init_plotter(self) -> None:
        self.plotter = QtInteractor(self)
        self.plotter.set_background(self.BACKGROUND_COLOR)
        self._layout.insertWidget(0, self.plotter, 1)
        if self._mesh is not None:
            self._render_current_mesh()

    def load_mesh(self, path: str) -> None:
        """Load and display a supported mesh file."""
        self._validate_path(path)
        mesh = pv.read(path)

        if mesh.n_points == 0:
            raise ValueError("Mesh contains no points.")
        if mesh.n_cells == 0:
            raise ValueError("Mesh contains no polygon faces to display.")

        self._mesh = mesh
        self.current_path = path
        self.mesh_data = MeshData(point_count=int(mesh.n_points), face_count=int(mesh.n_cells))
        self.status_label.setText(
            f"{os.path.basename(path)} | Points: {self.mesh_data.point_count:,} | Faces: {self.mesh_data.face_count:,}"
        )

        if self.plotter is not None:
            self._render_current_mesh()

    def clear(self) -> None:
        """Clear the current mesh preview."""
        self._mesh = None
        self.current_path = ""
        self.mesh_data = None
        self.status_label.setText("Mesh preview will appear after loading a mesh")
        if self.plotter is not None:
            self.plotter.clear()
            self.plotter.reset_camera()

    def reset_camera(self) -> None:
        """Reset the camera orientation and zoom so the full mesh is visible."""
        if self.plotter is not None:
            self._reset_plotter_view()

    def _render_current_mesh(self) -> None:
        assert self.plotter is not None and self._mesh is not None
        self.plotter.clear()
        self.plotter.add_mesh(
            self._mesh,
            color=self.MESH_COLOR,
            show_edges=True,
            edge_color=self.EDGE_COLOR,
            line_width=0.5,
            ambient=0.2,
            diffuse=0.75,
            specular=0.15,
            specular_power=20,
            smooth_shading=True,
        )
        self._reset_plotter_view()

    def _reset_plotter_view(self) -> None:
        assert self.plotter is not None
        self.plotter.view_isometric()
        self.plotter.reset_camera()

    @staticmethod
    def _validate_path(path: str) -> None:
        """Reject unsupported mesh formats before handing off to PyVista."""
        suffix = os.path.splitext(path)[1].lower()
        if suffix not in SUPPORTED_SUFFIXES:
            raise ValueError(f"Unsupported mesh format: {suffix or '<none>'}")

    @staticmethod
    def _reader_for_path(path: str):
        """Compatibility helper: return a VTK reader matching *path*'s extension."""
        import vtk

        suffix = os.path.splitext(path)[1].lower()
        readers = {
            ".obj": vtk.vtkOBJReader,
            ".stl": vtk.vtkSTLReader,
            ".ply": vtk.vtkPLYReader,
            ".vtk": vtk.vtkPolyDataReader,
            ".vtp": vtk.vtkXMLPolyDataReader,
        }
        try:
            return readers[suffix]()
        except KeyError as exc:
            raise ValueError(f"Unsupported mesh format: {suffix or '<none>'}") from exc

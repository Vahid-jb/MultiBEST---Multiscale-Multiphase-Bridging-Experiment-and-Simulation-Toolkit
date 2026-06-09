# SPDX-FileCopyrightText: 2026 bright-ideas-clan
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Shared visualization utilities for MultiBEST GUI applications.

Provides a unified Matplotlib widget and axis styling helpers.
"""

from __future__ import annotations

from matplotlib.axes import Axes
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg, NavigationToolbar2QT
from matplotlib.figure import Figure
from PySide6.QtWidgets import QVBoxLayout, QWidget


def style_axis_light(ax: Axes) -> None:
    """Apply a clean white/light style to *ax* — used by all plot functions."""
    ax.set_facecolor("white")
    ax.xaxis.label.set_color("black")
    ax.yaxis.label.set_color("black")
    ax.title.set_color("black")
    ax.tick_params(colors="black")
    for spine in ax.spines.values():
        spine.set_color("black")


class MatplotlibWidget(QWidget):
    """
    A unified widget for displaying Matplotlib plots in PySide6 applications.
    Includes a toolbar and canvas.
    """

    def __init__(
        self,
        parent: QWidget | None = None,
        width: int = 5,
        height: int = 4,
        dpi: int = 100,
    ) -> None:
        super().__init__(parent)

        # Use _layout to avoid shadowing QWidget.layout()
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)

        self.figure = Figure(figsize=(width, height), dpi=dpi)
        self.canvas = FigureCanvasQTAgg(self.figure)
        self.toolbar = NavigationToolbar2QT(self.canvas, self)

        self._layout.addWidget(self.toolbar)
        self._layout.addWidget(self.canvas)

        # Default styling to match dark theme
        self.figure.patch.set_facecolor("#2b2b2b")
        self.figure.patch.set_alpha(1.0)

    def get_figure(self) -> Figure:
        """The underlying Matplotlib Figure."""
        return self.figure

    def get_canvas(self) -> FigureCanvasQTAgg:
        """The FigureCanvasQTAgg embedded in this widget."""
        return self.canvas

    def plot(self, func, *args, **kwargs) -> None:
        """Clear the figure and call ``func(figure, *args, **kwargs)`` to render new content."""
        self.figure.clear()
        func(self.figure, *args, **kwargs)
        self.canvas.draw()

    def clear(self) -> None:
        """Clear the figure and redraw an empty canvas."""
        self.figure.clear()
        self.canvas.draw()

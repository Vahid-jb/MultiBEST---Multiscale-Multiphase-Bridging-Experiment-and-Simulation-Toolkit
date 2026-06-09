# SPDX-FileCopyrightText: 2026 bright-ideas-clan
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Base classes for image editor tools — no Qt dependency."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Protocol, runtime_checkable

import numpy as np


@runtime_checkable
class EditorInterface(Protocol):
    """Minimal interface that tools use to interact with the editor canvas."""

    def get_image(self) -> np.ndarray:
        """Return a copy of the current committed image."""
        pass

    def get_original_image(self) -> np.ndarray | None:
        """Return the original (first-loaded) image."""
        pass

    def commit(self, image: np.ndarray) -> None:
        """Push *image* to history and refresh the display."""
        pass

    def set_preview(self, image: np.ndarray) -> None:
        """Display *image* without adding it to history (live preview)."""
        pass

    def cancel_preview(self) -> None:
        """Restore the last committed image, discarding any active preview."""
        pass


class Tool(ABC):
    """Abstract base for all canvas interaction tools.

    Subclasses receive mouse events as integer image-pixel coordinates
    ``(x=column, y=row)`` — the editor maps Qt events before delegating.
    """

    def __init__(self, canvas: EditorInterface) -> None:
        self._canvas = canvas

    def activate(self) -> None:
        """Called when this tool becomes the active tool."""

    def deactivate(self) -> None:
        """Called when switching away from this tool."""

    @abstractmethod
    def on_press(self, x: int, y: int) -> None:
        """Mouse button pressed at image pixel (x, y)."""

    @abstractmethod
    def on_move(self, x: int, y: int) -> None:
        """Mouse moved to image pixel (x, y) with the button held."""

    @abstractmethod
    def on_release(self, x: int, y: int) -> None:
        """Mouse button released at image pixel (x, y)."""

    @property
    def cursor_name(self) -> str:
        """Qt cursor name: 'crosshair', 'openhand', 'closedhand', or 'arrow'."""
        return "crosshair"

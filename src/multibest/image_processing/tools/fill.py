# SPDX-FileCopyrightText: 2026 bright-ideas-clan
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Flood-fill tool."""

from __future__ import annotations

from collections.abc import Sequence

from multibest.image_processing.tools.base import EditorInterface, Tool


class FillTool(Tool):
    """Flood fill the clicked region with *color*."""

    def __init__(
        self,
        canvas: EditorInterface,
        color: Sequence[int] = (0, 0, 0),
        tolerance: int = 32,
    ) -> None:
        super().__init__(canvas)
        self.color = tuple(color)
        self.tolerance = tolerance

    def on_press(self, x: int, y: int) -> None:
        from multibest.image_processing.ops import flood_fill

        img = self._canvas.get_image()
        result = flood_fill(img, x, y, self.color, self.tolerance)
        self._canvas.commit(result)

    def on_move(self, x: int, y: int) -> None:
        """No-op: fill applies instantly on press; dragging has no effect."""

    def on_release(self, x: int, y: int) -> None:
        """No-op: fill applies instantly on press; releasing has no effect."""

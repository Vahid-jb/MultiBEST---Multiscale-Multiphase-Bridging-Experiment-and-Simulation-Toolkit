# SPDX-FileCopyrightText: 2026 bright-ideas-clan
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Pen and Eraser tools."""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np

from multibest.image_processing.tools.base import EditorInterface, Tool


class PenTool(Tool):
    """Freehand drawing tool.

    Strokes are accumulated during a mouse drag and committed on release,
    so undo reverts the entire stroke at once.
    """

    def __init__(
        self,
        canvas: EditorInterface,
        color: Sequence[int] = (0, 0, 0),
        width: int = 3,
    ) -> None:
        super().__init__(canvas)
        self.color = tuple(color)
        self.width = width
        self._stroke_base: np.ndarray | None = None
        self._current: np.ndarray | None = None
        self._last_pos: tuple[int, int] | None = None

    def on_press(self, x: int, y: int) -> None:
        from multibest.image_processing.ops import draw_line

        self._stroke_base = self._canvas.get_image()
        self._current = draw_line(self._stroke_base, (x, y), (x, y), self.color, self.width)
        self._last_pos = (x, y)
        self._canvas.set_preview(self._current)

    def on_move(self, x: int, y: int) -> None:
        if self._current is None or self._last_pos is None:
            return
        from multibest.image_processing.ops import draw_line

        self._current = draw_line(self._current, self._last_pos, (x, y), self.color, self.width)
        self._last_pos = (x, y)
        self._canvas.set_preview(self._current)

    def on_release(self, x: int, y: int) -> None:
        if self._current is not None:
            self._canvas.commit(self._current)
        self._stroke_base = None
        self._current = None
        self._last_pos = None


class EraserTool(Tool):
    """Eraser — restores original image pixels within a circular brush."""

    def __init__(self, canvas: EditorInterface, width: int = 20) -> None:
        super().__init__(canvas)
        self.width = width
        self._original: np.ndarray | None = None
        self._current: np.ndarray | None = None
        self._last_pos: tuple[int, int] | None = None

    def on_press(self, x: int, y: int) -> None:
        self._original = self._canvas.get_original_image()
        self._current = self._canvas.get_image()
        self._last_pos = (x, y)
        self._erase_at(x, y)
        self._canvas.set_preview(self._current)

    def on_move(self, x: int, y: int) -> None:
        if self._current is None or self._last_pos is None:
            return
        self._erase_segment(self._last_pos, (x, y))
        self._last_pos = (x, y)
        self._canvas.set_preview(self._current)

    def on_release(self, x: int, y: int) -> None:
        if self._current is not None:
            self._canvas.commit(self._current)
        self._original = None
        self._current = None
        self._last_pos = None

    def _erase_at(self, cx: int, cy: int) -> None:
        if self._original is None or self._current is None:
            return
        r = max(1, self.width // 2)
        h, w = self._current.shape[:2]
        y0, y1 = max(0, cy - r), min(h, cy + r + 1)
        x0, x1 = max(0, cx - r), min(w, cx + r + 1)
        if y0 >= y1 or x0 >= x1:
            return
        yy, xx = np.mgrid[y0:y1, x0:x1]
        mask = (xx - cx) ** 2 + (yy - cy) ** 2 <= r * r
        region = self._current[y0:y1, x0:x1]
        region[mask] = self._original[y0:y1, x0:x1][mask]

    def _erase_segment(self, p0: tuple[int, int], p1: tuple[int, int]) -> None:
        x0, y0 = p0
        x1, y1 = p1
        steps = max(abs(x1 - x0), abs(y1 - y0), 1)
        for i in range(steps + 1):
            t = i / steps
            self._erase_at(round(x0 + t * (x1 - x0)), round(y0 + t * (y1 - y0)))

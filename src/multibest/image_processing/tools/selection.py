# SPDX-FileCopyrightText: 2026 bright-ideas-clan
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Crop and Cut rectangle-selection tools."""

from __future__ import annotations

from collections.abc import Callable, Sequence

from multibest.image_processing.tools.base import EditorInterface, Tool

# Type alias for selection callback: receives (x1, y1, x2, y2) or None (cleared).
SelectionCallback = Callable[[tuple[int, int, int, int] | None], None]


class _RectSelectionTool(Tool):
    """Common base for rectangle-selection tools (Crop, Cut)."""

    def __init__(
        self,
        canvas: EditorInterface,
        on_selection: SelectionCallback | None = None,
    ) -> None:
        super().__init__(canvas)
        self._on_selection = on_selection
        self._start: tuple[int, int] | None = None
        self._end: tuple[int, int] | None = None

    @property
    def selection(self) -> tuple[int, int, int, int] | None:
        """Normalised (x1, y1, x2, y2) in image coords, or None."""
        if self._start is None or self._end is None:
            return None
        x1, y1 = self._start
        x2, y2 = self._end
        return (min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2))

    def on_press(self, x: int, y: int) -> None:
        self._start = (x, y)
        self._end = (x, y)
        self._notify()

    def on_move(self, x: int, y: int) -> None:
        self._end = (x, y)
        self._notify()

    def on_release(self, x: int, y: int) -> None:
        self.on_move(x, y)

    def cancel(self) -> None:
        """Cancel the active selection without applying."""
        self._clear()

    def deactivate(self) -> None:
        self._clear()

    def _clear(self) -> None:
        self._start = None
        self._end = None
        self._notify()

    def _notify(self) -> None:
        if self._on_selection is not None:
            self._on_selection(self.selection)


class CropTool(_RectSelectionTool):
    """Select a rectangle and crop the image to it on Apply."""

    def apply(self) -> None:
        """Crop the image to the current selection and push to history."""
        sel = self.selection
        if sel:
            from multibest.image_processing.ops import crop

            result = crop(self._canvas.get_image(), *sel)
            self._canvas.commit(result)
        self._clear()


class CutTool(_RectSelectionTool):
    """Select a rectangle and fill it with *color* (white by default) on Apply."""

    def __init__(
        self,
        canvas: EditorInterface,
        color: Sequence[int] = (255, 255, 255),
        on_selection: SelectionCallback | None = None,
    ) -> None:
        super().__init__(canvas, on_selection)
        self.color = tuple(color)

    def apply(self) -> None:
        """Fill the selected region with color and push to history."""
        sel = self.selection
        if sel:
            from multibest.image_processing.ops import cut

            result = cut(self._canvas.get_image(), *sel, color=self.color)
            self._canvas.commit(result)
        self._clear()

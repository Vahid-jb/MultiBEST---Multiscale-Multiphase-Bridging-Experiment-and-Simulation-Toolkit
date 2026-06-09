# SPDX-FileCopyrightText: 2026 bright-ideas-clan
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Snapshot-based undo/redo history for the image editor."""

from __future__ import annotations

import numpy as np


class HistoryStack:
    """Ring buffer of numpy image snapshots.

    Parameters
    ----------
    max_size:
        Maximum number of snapshots to keep. When exceeded, the oldest is dropped.
    """

    def __init__(self, max_size: int = 50) -> None:
        self._stack: list[np.ndarray] = []
        self._index: int = -1
        self._max = max_size

    # ------------------------------------------------------------------
    # State queries
    # ------------------------------------------------------------------

    def current(self) -> np.ndarray | None:
        """Return current image, or None if the stack is empty."""
        if self._index < 0:
            return None
        return self._stack[self._index]

    def original(self) -> np.ndarray | None:
        """Return the first (original) snapshot without changing position."""
        if not self._stack:
            return None
        return self._stack[0]

    @property
    def can_undo(self) -> bool:
        return self._index > 0

    @property
    def can_redo(self) -> bool:
        return self._index < len(self._stack) - 1

    # ------------------------------------------------------------------
    # Mutations
    # ------------------------------------------------------------------

    def push(self, image: np.ndarray) -> None:
        """Add *image* to history, discarding any redo branch."""
        del self._stack[self._index + 1 :]
        self._stack.append(image.copy())
        if len(self._stack) > self._max:
            self._stack.pop(0)
        self._index = len(self._stack) - 1

    def undo(self) -> np.ndarray:
        """Step back one snapshot and return it.

        Raises
        ------
        IndexError
            If there is nothing to undo.
        """
        if not self.can_undo:
            raise IndexError("Nothing to undo")
        self._index -= 1
        return self._stack[self._index]

    def redo(self) -> np.ndarray:
        """Step forward one snapshot and return it.

        Raises
        ------
        IndexError
            If there is nothing to redo.
        """
        if not self.can_redo:
            raise IndexError("Nothing to redo")
        self._index += 1
        return self._stack[self._index]

    def reset(self) -> np.ndarray:
        """Jump to the first snapshot (original image) and return it.

        Raises
        ------
        IndexError
            If the stack is empty.
        """
        if not self._stack:
            raise IndexError("History is empty")
        self._index = 0
        return self._stack[0]

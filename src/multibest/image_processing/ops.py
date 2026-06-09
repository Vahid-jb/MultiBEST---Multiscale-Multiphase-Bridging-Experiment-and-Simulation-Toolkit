# SPDX-FileCopyrightText: 2026 bright-ideas-clan
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Pure image processing operations.

All functions accept NumPy arrays (uint8) and return new arrays — never in-place.
Supports grayscale (H, W) and colour (H, W, 3) / (H, W, 4) inputs unless noted.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np


def _to_uint8(arr: np.ndarray) -> np.ndarray:
    return np.clip(arr, 0, 255).astype(np.uint8)


def threshold(image: np.ndarray, value: int) -> np.ndarray:
    """Binary threshold → grayscale output (0 or 255).

    Parameters
    ----------
    image:
        Grayscale (H, W) or colour (H, W, 3) uint8 image.
    value:
        Threshold level 0–255. Pixels *strictly above* value become 255.

    Returns
    -------
    np.ndarray
        (H, W) uint8 image; values are 0 or 255.
    """
    if image.ndim == 3:
        gray = np.mean(image[..., :3], axis=-1).astype(np.uint8)
    else:
        gray = image
    return np.where(gray > value, np.uint8(255), np.uint8(0))


def gaussian_blur(image: np.ndarray, sigma: float) -> np.ndarray:
    """Gaussian blur.

    Parameters
    ----------
    image:
        Grayscale or colour uint8 image.
    sigma:
        Blur radius in pixels. ``sigma=0`` returns an unchanged copy.

    Returns
    -------
    np.ndarray
        Same shape and dtype as *image*.
    """
    if sigma <= 0:
        return image.copy()

    from skimage.filters import gaussian

    if image.ndim == 3:
        blurred = gaussian(image.astype(np.float64), sigma=sigma, preserve_range=True, channel_axis=-1)
    else:
        blurred = gaussian(image.astype(np.float64), sigma=sigma, preserve_range=True)

    return _to_uint8(blurred)


def contrast(image: np.ndarray, factor: float) -> np.ndarray:
    """Adjust contrast.

    Parameters
    ----------
    image:
        Grayscale or colour uint8 image.
    factor:
        Contrast change −100 to +100 (0 = unchanged).
        Positive values increase contrast; negative decrease it.

    Returns
    -------
    np.ndarray
        Same shape and dtype as *image*.
    """
    scale = 1.0 + factor / 100.0
    result = (image.astype(np.float32) - 128.0) * scale + 128.0
    return _to_uint8(result)


def crop(image: np.ndarray, x1: int, y1: int, x2: int, y2: int) -> np.ndarray:
    """Crop image to the rectangle defined by columns x1–x2, rows y1–y2.

    Parameters
    ----------
    image:
        Source image (any number of channels).
    x1, y1:
        Top-left pixel (column, row), inclusive.
    x2, y2:
        Bottom-right pixel (column, row), exclusive.

    Returns
    -------
    np.ndarray
        Cropped copy; same number of channels as *image*.
        Returns a full copy if the rectangle is invalid.
    """
    h, w = image.shape[:2]
    x1, x2 = max(0, min(x1, w)), max(0, min(x2, w))
    y1, y2 = max(0, min(y1, h)), max(0, min(y2, h))
    if x2 <= x1 or y2 <= y1:
        return image.copy()
    return image[y1:y2, x1:x2].copy()


def cut(
    image: np.ndarray,
    x1: int,
    y1: int,
    x2: int,
    y2: int,
    color: Sequence[int] = (255, 255, 255),
) -> np.ndarray:
    """Fill the selected rectangle with *color* (white by default).

    Parameters
    ----------
    image:
        Source image (H, W) or (H, W, C).
    x1, y1:
        Top-left pixel (column, row), inclusive.
    x2, y2:
        Bottom-right pixel (column, row), exclusive.
    color:
        Fill colour — first element used for grayscale images.

    Returns
    -------
    np.ndarray
        Copy of *image* with the rectangle filled.
    """
    result = image.copy()
    h, w = image.shape[:2]
    x1, x2 = max(0, min(x1, w)), max(0, min(x2, w))
    y1, y2 = max(0, min(y1, h)), max(0, min(y2, h))
    if x2 <= x1 or y2 <= y1:
        return result
    if image.ndim == 2:
        result[y1:y2, x1:x2] = int(color[0])
    else:
        for i in range(image.shape[2]):
            result[y1:y2, x1:x2, i] = int(color[i]) if i < len(color) else 255
    return result


def flood_fill(
    image: np.ndarray,
    x: int,
    y: int,
    color: Sequence[int],
    tolerance: int = 32,
) -> np.ndarray:
    """Flood-fill starting at pixel (x, y) with *color*.

    Parameters
    ----------
    image:
        Grayscale (H, W) or RGB (H, W, 3) uint8 image.
    x, y:
        Seed pixel column and row (clamped to image bounds).
    color:
        Fill colour — first element used for grayscale images.
    tolerance:
        Maximum allowed colour distance from the seed colour (0–255).

    Returns
    -------
    np.ndarray
        Same shape and dtype as *image* with the filled region.
    """
    import cv2

    result = image.copy()
    h, w = image.shape[:2]
    x = max(0, min(int(x), w - 1))
    y = max(0, min(int(y), h - 1))
    mask = np.zeros((h + 2, w + 2), dtype=np.uint8)

    if image.ndim == 2:
        fill_color = int(color[0]) if hasattr(color, "__len__") else int(color)
        lo = hi = (int(tolerance),)
    else:
        n = image.shape[2]
        fill_color = tuple(int(c) for c in list(color)[:n])
        lo = hi = (int(tolerance),) * n

    cv2.floodFill(result, mask, (x, y), fill_color, loDiff=lo, upDiff=hi)
    return result


def draw_line(
    image: np.ndarray,
    pt1: tuple[int, int],
    pt2: tuple[int, int],
    color: Sequence[int],
    width: int = 3,
) -> np.ndarray:
    """Draw a line from *pt1* to *pt2*.

    Parameters
    ----------
    image:
        Grayscale (H, W) or RGB (H, W, 3) uint8 image.
    pt1, pt2:
        Start and end points as (column, row).
    color:
        Line colour — first element used for grayscale images.
    width:
        Line thickness in pixels.

    Returns
    -------
    np.ndarray
        Same shape and dtype as *image* with the line drawn.
    """
    import cv2

    result = image.copy()
    if image.ndim == 2:
        line_color: int | tuple = int(color[0]) if hasattr(color, "__len__") else int(color)
    else:
        n = image.shape[2]
        line_color = tuple(int(c) for c in list(color)[:n])

    cv2.line(result, (int(pt1[0]), int(pt1[1])), (int(pt2[0]), int(pt2[1])), line_color, max(1, int(width)))
    return result

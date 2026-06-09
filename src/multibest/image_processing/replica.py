# SPDX-FileCopyrightText: 2026 bright-ideas-clan
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Random binary replica generation.

Generates synthetic binary images that preserve the total black-pixel area
of the source image using randomised ellipsoidal blobs with boundary smoothing.

Pure functions — no Qt, no file I/O.
"""

from __future__ import annotations

import math

import cv2
import numpy as np
from scipy.ndimage import binary_fill_holes
from skimage.morphology import remove_small_holes, remove_small_objects


def generate_replica(
    binary: np.ndarray,
    *,
    min_black_region: int,
    max_black_region: int,
    rng: np.random.Generator,
    boundary_smoothing_sigma: float = 1.2,
    boundary_cleanup_width: int = 2,
) -> np.ndarray:
    """Return a same-shape boolean array with area-preserved random black blobs."""
    black_total = int(binary.size - np.count_nonzero(binary))
    h, w = binary.shape

    if black_total <= 0:
        return np.ones_like(binary, dtype=bool)

    black_canvas = np.zeros((h, w), dtype=np.uint8)
    for size in _generate_blob_sizes(black_total, min_black_region, max_black_region, rng):
        _draw_random_blob(black_canvas, size, rng)

    black_mask: np.ndarray = black_canvas > 0
    black_mask = _cleanup_black_mask(black_mask, max(2, min_black_region // 4))
    black_mask = _smooth_binary_boundary(black_mask, boundary_smoothing_sigma, boundary_cleanup_width)
    black_mask = _cleanup_black_mask(black_mask, max(2, min_black_region // 4))
    # Enforce area last so cleanup steps don't undo the correction.
    black_mask = _enforce_exact_black_area(black_mask, black_total, rng)

    replica = ~black_mask
    u8 = replica.astype(np.uint8) * 255
    _, u8 = cv2.threshold(u8, 127, 255, cv2.THRESH_BINARY)
    return u8 > 0


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _get_neighbors(r: int, c: int, h: int, w: int):
    for dr, dc in [(-1, 0), (1, 0), (0, -1), (0, 1), (-1, -1), (-1, 1), (1, -1), (1, 1)]:
        rr, cc = r + dr, c + dc
        if 0 <= rr < h and 0 <= cc < w:
            yield rr, cc


def _get_boundary_white_candidates(mask: np.ndarray) -> list[tuple[int, int]]:
    h, w = mask.shape
    candidates: set[tuple[int, int]] = set()
    for r, c in np.argwhere(mask):
        for rr, cc in _get_neighbors(int(r), int(c), h, w):
            if not mask[rr, cc]:
                candidates.add((rr, cc))
    return list(candidates)


def _get_boundary_black_candidates(mask: np.ndarray) -> list[tuple[int, int]]:
    h, w = mask.shape
    candidates = []
    for r, c in np.argwhere(mask):
        for rr, cc in _get_neighbors(int(r), int(c), h, w):
            if not mask[rr, cc]:
                candidates.append((int(r), int(c)))
                break
    return candidates


def _add_black_pixels(adjusted: np.ndarray, need: int, rng: np.random.Generator) -> None:
    """Grow the black mask by *need* pixels, preferring boundary neighbours."""
    candidates = _get_boundary_white_candidates(adjusted)
    rng.shuffle(candidates)
    added = 0
    for rr, cc in candidates:
        if not adjusted[rr, cc]:
            adjusted[rr, cc] = True
            added += 1
            if added >= need:
                return
    still_needed = need - added
    white_pos = np.argwhere(~adjusted)
    if still_needed > 0 and len(white_pos) > 0:
        idxs = rng.choice(len(white_pos), size=min(still_needed, len(white_pos)), replace=False)
        for idx in np.atleast_1d(idxs):
            adjusted[int(white_pos[int(idx), 0]), int(white_pos[int(idx), 1])] = True


def _remove_black_pixels(adjusted: np.ndarray, need: int, rng: np.random.Generator) -> None:
    """Shrink the black mask by *need* pixels, preferring boundary pixels."""
    candidates = _get_boundary_black_candidates(adjusted)
    rng.shuffle(candidates)
    removed = 0
    for rr, cc in candidates:
        if adjusted[rr, cc]:
            adjusted[rr, cc] = False
            removed += 1
            if removed >= need:
                return
    still_needed = need - removed
    black_pos = np.argwhere(adjusted)
    if still_needed > 0 and len(black_pos) > 0:
        idxs = rng.choice(len(black_pos), size=min(still_needed, len(black_pos)), replace=False)
        for idx in np.atleast_1d(idxs):
            adjusted[int(black_pos[int(idx), 0]), int(black_pos[int(idx), 1])] = False


def _enforce_exact_black_area(black_mask: np.ndarray, target_black: int, rng: np.random.Generator) -> np.ndarray:
    adjusted = black_mask.copy()
    current = int(np.count_nonzero(adjusted))

    if current < target_black:
        _add_black_pixels(adjusted, target_black - current, rng)
    elif current > target_black:
        _remove_black_pixels(adjusted, current - target_black, rng)

    return adjusted


def _remove_isolated_black_pixels(mask: np.ndarray) -> np.ndarray:
    u8 = mask.astype(np.uint8) * 255
    kernel = np.array([[-1, -1, -1], [-1, 1, -1], [-1, -1, -1]], dtype=np.int32)
    singles = cv2.morphologyEx(u8, cv2.MORPH_HITMISS, kernel)
    cleaned = u8.copy()
    cleaned[singles > 0] = 0
    return cleaned > 0


def _cleanup_black_mask(mask: np.ndarray, min_obj_size: int) -> np.ndarray:
    min_obj_size = max(2, int(min_obj_size))
    cleaned = mask.astype(bool)
    cleaned = _remove_isolated_black_pixels(cleaned)
    cleaned = remove_small_objects(cleaned, max_size=max(0, min_obj_size - 1), connectivity=2)
    cleaned = remove_small_holes(cleaned, max_size=max(0, min_obj_size - 1), connectivity=2)
    return binary_fill_holes(cleaned).astype(bool)


def _harden_binary_boundary(mask: np.ndarray, cleanup_width: int = 2) -> np.ndarray:
    if cleanup_width <= 0:
        return mask.copy()
    u8 = mask.astype(np.uint8) * 255
    k = max(1, int(cleanup_width))
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * k + 1, 2 * k + 1))
    eroded = cv2.erode(u8, kernel, iterations=1)
    cleaned = cv2.dilate(eroded, kernel, iterations=1)
    return cleaned > 0


def _smooth_binary_boundary(mask: np.ndarray, sigma: float = 1.2, cleanup_width: int = 2) -> np.ndarray:
    if sigma <= 0 and cleanup_width <= 0:
        return mask.copy()
    u8 = mask.astype(np.uint8) * 255
    if sigma > 0:
        blurred = cv2.GaussianBlur(u8, (0, 0), sigmaX=sigma, sigmaY=sigma, borderType=cv2.BORDER_DEFAULT)
        _, u8 = cv2.threshold(blurred, 127, 255, cv2.THRESH_BINARY)
    bw = u8 > 0
    bw = binary_fill_holes(bw)
    bw = _harden_binary_boundary(bw, cleanup_width=cleanup_width)
    return binary_fill_holes(bw).astype(bool)


def _draw_random_blob(canvas: np.ndarray, area_target: int, rng: np.random.Generator) -> None:
    h, w = canvas.shape
    cx = int(rng.integers(0, w))
    cy = int(rng.integers(0, h))
    base_r = max(3, int(round(math.sqrt(max(area_target, 1) / math.pi))))
    a = max(2, int(base_r * rng.uniform(0.7, 1.4)))
    b = max(2, int(base_r * rng.uniform(0.7, 1.4)))
    angle = float(rng.uniform(0, 180.0))
    cv2.ellipse(canvas, (cx, cy), (a, b), angle, 0, 360, 255, -1)
    for _ in range(int(rng.integers(2, 5))):
        dx = int(rng.integers(-a, a + 1))
        dy = int(rng.integers(-b, b + 1))
        cx2 = int(np.clip(cx + dx, 0, w - 1))
        cy2 = int(np.clip(cy + dy, 0, h - 1))
        a2 = max(2, int(a * rng.uniform(0.35, 0.9)))
        b2 = max(2, int(b * rng.uniform(0.35, 0.9)))
        cv2.ellipse(canvas, (cx2, cy2), (a2, b2), float(rng.uniform(0, 180.0)), 0, 360, 255, -1)


def _generate_blob_sizes(total_black: int, min_size: int, max_size: int, rng: np.random.Generator) -> list[int]:
    if total_black <= 0:
        return []
    min_size = max(1, int(min_size))
    max_size = max(min_size, int(max_size))
    sizes: list[int] = []
    remaining = int(total_black)
    while remaining > 0:
        upper = min(max_size, remaining)
        lower = min(min_size, upper)
        sizes.append(int(rng.integers(lower, upper + 1)))
        remaining -= sizes[-1]
    rng.shuffle(sizes)
    return sizes

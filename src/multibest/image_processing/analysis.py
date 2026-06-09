# SPDX-FileCopyrightText: 2026 bright-ideas-clan
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Binary image section area analysis.

Pure functions — no Qt, no file I/O. Accepts NumPy arrays, returns arrays / dataclasses / strings.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import cv2
import numpy as np
from skimage.measure import label, regionprops


@dataclass(frozen=True)
class SectionInfo:
    section_id: int
    phase: str
    area: int
    centroid: tuple[float, float]
    bbox: tuple[int, int, int, int]  # (min_row, min_col, max_row, max_col)


def to_grayscale(image: np.ndarray) -> np.ndarray:
    """Convert RGB/RGBA image to uint8 2-D grayscale; pass through 2-D unchanged."""
    if image.ndim == 2:
        return image
    return np.dot(image[..., :3], [0.299, 0.587, 0.114]).astype(np.uint8)


def to_binary(gray: np.ndarray, threshold: int, invert: bool = False) -> np.ndarray:
    """Threshold a grayscale image to a boolean mask (gray > threshold)."""
    binary = gray > threshold
    return ~binary if invert else binary


def label_sections(
    mask: np.ndarray,
    phase: str,
    connectivity: int,
) -> tuple[list[SectionInfo], np.ndarray]:
    """Label connected components in *mask* and return (section list, label array).

    connectivity=1 → 4-connected; connectivity=2 → 8-connected (skimage convention).
    """
    labels = label(mask.astype(np.uint8), connectivity=connectivity)
    props = regionprops(labels)
    rows = [
        SectionInfo(
            section_id=i,
            phase=phase,
            area=int(r.area),
            centroid=(round(float(r.centroid[0]), 3), round(float(r.centroid[1]), 3)),
            bbox=(int(r.bbox[0]), int(r.bbox[1]), int(r.bbox[2]), int(r.bbox[3])),
        )
        for i, r in enumerate(props, start=1)
    ]
    return rows, labels


def render_overlay(
    gray: np.ndarray,
    white_labels: np.ndarray,
    black_labels: np.ndarray,
    white_rows: list[SectionInfo],
    black_rows: list[SectionInfo],
    draw_white: bool,
    draw_black: bool,
) -> np.ndarray:
    """Return a BGR uint8 canvas with coloured contours and section-ID labels."""
    canvas = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
    font_scale, thickness, contour_thickness = _text_style(canvas.shape)

    if draw_white:
        _draw_phase(canvas, white_labels, white_rows, "white", font_scale, thickness, contour_thickness)
    if draw_black:
        _draw_phase(canvas, black_labels, black_rows, "black", font_scale, thickness, contour_thickness)
    return canvas


def build_report_text(
    *,
    image_label: str,
    gray: np.ndarray,
    threshold: int,
    connectivity: int,
    invert: bool,
    white_rows: list[SectionInfo],
    black_rows: list[SectionInfo],
    replica_count: int,
    min_black_region: int,
    max_black_region: int,
    boundary_smoothing_sigma: float,
    boundary_cleanup_width: int,
) -> str:
    """Build the multi-line text analysis report."""
    total_pixels = int(gray.shape[0] * gray.shape[1])
    binary = to_binary(gray, threshold, invert)
    white_pixels = int(np.count_nonzero(binary))
    black_pixels = total_pixels - white_pixels
    total_white_area = sum(r.area for r in white_rows)
    total_black_area = sum(r.area for r in black_rows)

    lines: list[str] = [
        "BINARY IMAGE SECTION AREA REPORT",
        "=" * 60,
        f"Input image: {image_label}",
        f"Image size: {gray.shape[1]} x {gray.shape[0]} pixels",
        f"Total pixels: {total_pixels}",
        f"Threshold used: {threshold}",
        f"Connectivity used: {connectivity} ({'8-connected' if connectivity == 2 else '4-connected'})",
        f"White pixels after thresholding: {white_pixels}",
        f"Black pixels after thresholding: {black_pixels}",
        f"Sum of all white section areas: {total_white_area}",
        f"Sum of all black section areas: {total_black_area}",
        f"Requested number of random replicas: {replica_count}",
        f"Replica black region minimum size: {min_black_region}",
        f"Replica black region maximum size: {max_black_region}",
        f"Boundary smoothing sigma: {boundary_smoothing_sigma}",
        f"Boundary cleanup width: {boundary_cleanup_width}",
        "",
        "WHITE SECTIONS",
        "-" * 60,
    ]
    if white_rows:
        lines.extend(f"Section W{r.section_id}: area = {r.area}" for r in white_rows)
    else:
        lines.append("No white sections found.")
    lines.append("")

    lines += ["BLACK SECTIONS", "-" * 60]
    if black_rows:
        lines.extend(f"Section B{r.section_id}: area = {r.area}" for r in black_rows)
    else:
        lines.append("No black sections found.")
    lines.append("")

    lines += [
        "DETAILED SECTION TABLE",
        "-" * 60,
    ]
    all_rows = white_rows + black_rows
    if all_rows:
        lines.append(
            "phase\tsection_id\tarea\tcentroid_row\tcentroid_col"
            "\tbbox_min_row\tbbox_min_col\tbbox_max_row\tbbox_max_col"
        )
        for r in all_rows:
            lines.append(
                f"{r.phase}\t{r.section_id}\t{r.area}\t{r.centroid[0]}\t{r.centroid[1]}"
                f"\t{r.bbox[0]}\t{r.bbox[1]}\t{r.bbox[2]}\t{r.bbox[3]}"
            )
    else:
        lines.append("No sections found.")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _text_style(shape: tuple) -> tuple[float, int, int]:
    h, w = shape[:2]
    base = min(h, w)
    font_scale = max(0.45, base / 700.0)
    thickness = max(1, int(math.ceil(base / 500.0)))
    contour_thickness = max(2, int(math.ceil(base / 300.0)))
    return font_scale, thickness, contour_thickness


def _hsv_to_bgr(h: int, s: int, v: int) -> tuple[int, int, int]:
    hsv = np.uint8([[[h, s, v]]])
    bgr = cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)[0, 0]
    return int(bgr[0]), int(bgr[1]), int(bgr[2])


def _distinct_color(index: int, total: int, phase: str) -> tuple[int, int, int]:
    if total <= 0:
        total = 1
    hue_offset = 15 if phase == "white" else 105
    hue = int((hue_offset + (180 * index / total)) % 180)
    return _hsv_to_bgr(hue, 220, 255)


def _draw_phase(
    canvas: np.ndarray,
    labels: np.ndarray,
    rows: list[SectionInfo],
    phase: str,
    font_scale: float,
    thickness: int,
    contour_thickness: int,
) -> None:
    total = len(rows)
    for idx, row in enumerate(rows, start=1):
        color = _distinct_color(idx, total, phase)
        mask = (labels == row.section_id).astype(np.uint8) * 255
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        cv2.drawContours(canvas, contours, -1, color, contour_thickness)
        x = int(round(row.centroid[1]))
        y = int(round(row.centroid[0]))
        prefix = "W" if phase == "white" else "B"
        _draw_label(canvas, f"{prefix}{row.section_id}", x, y, color, font_scale, thickness)


def _draw_label(
    canvas: np.ndarray,
    text: str,
    x: int,
    y: int,
    color: tuple[int, int, int],
    font_scale: float,
    thickness: int,
) -> None:
    font = cv2.FONT_HERSHEY_SIMPLEX
    (tw, th), baseline = cv2.getTextSize(text, font, font_scale, thickness)
    x = max(0, min(x, canvas.shape[1] - tw - 2))
    y = max(th + 2, min(y, canvas.shape[0] - baseline - 2))
    cv2.putText(canvas, text, (x, y), font, font_scale, color, thickness, cv2.LINE_AA)

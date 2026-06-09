# SPDX-FileCopyrightText: 2026 bright-ideas-clan
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Basic image processing operations using multibest.image_processing.

Demonstrates programmatic use of the pure-Python image processing backend
(scikit-image, OpenCV, Pillow) without launching the GUI.
"""

from __future__ import annotations

import numpy as np

from multibest.image_processing import ops
from multibest.image_processing.history import HistoryStack


def main() -> None:
    # ── Create a synthetic test image ────────────────────────────────
    img = np.zeros((64, 64, 3), dtype=np.uint8)
    img[16:48, 16:48] = (200, 100, 50)  # orange square
    img[24:40, 24:40] = (255, 255, 255)  # white inner square

    print(f"Original: shape={img.shape}  mean={img.mean():.1f}")

    # ── Threshold ────────────────────────────────────────────────────
    binary = ops.threshold(img, value=128)
    print(f"After threshold(128): shape={binary.shape}  unique={np.unique(binary).tolist()}")

    # ── Gaussian blur ────────────────────────────────────────────────
    blurred = ops.gaussian_blur(img, sigma=3.0)
    print(f"After gaussian_blur(sigma=3): mean={blurred.mean():.1f}")

    # ── Contrast ─────────────────────────────────────────────────────
    high_contrast = ops.contrast(img, factor=50.0)
    print(f"After contrast(+50): min={high_contrast.min()}  max={high_contrast.max()}")

    # ── Crop ─────────────────────────────────────────────────────────
    cropped = ops.crop(img, x1=16, y1=16, x2=48, y2=48)
    print(f"After crop(16,16,48,48): shape={cropped.shape}")

    # ── Cut (fill rectangle) ─────────────────────────────────────────
    cut_result = ops.cut(img, x1=24, y1=24, x2=40, y2=40, color=(0, 0, 255))
    print(f"After cut: region color={cut_result[32, 32].tolist()}")

    # ── Flood fill ───────────────────────────────────────────────────
    filled = ops.flood_fill(img, x=32, y=32, color=(0, 255, 0), tolerance=50)
    print(f"After flood_fill: seed pixel={filled[32, 32].tolist()}")

    # ── Draw line ────────────────────────────────────────────────────
    lined = ops.draw_line(img, pt1=(0, 0), pt2=(63, 63), color=(255, 0, 0), width=2)
    print(f"After draw_line: diagonal pixels marked={np.any(lined[:, :, 0] == 255)}")

    # ── History stack ────────────────────────────────────────────────
    hs = HistoryStack(max_size=10)
    hs.push(img)
    hs.push(blurred)
    hs.push(high_contrast)
    print(f"\nHistory: can_undo={hs.can_undo}  can_redo={hs.can_redo}")
    hs.undo()
    print(f"After undo: current mean={hs.current().mean():.1f}  (blurred)")
    hs.reset()
    print(f"After reset: current mean={hs.current().mean():.1f}  (original)")

    print("\nAll operations completed successfully.")


if __name__ == "__main__":
    main()

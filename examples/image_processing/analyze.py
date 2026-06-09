# SPDX-FileCopyrightText: 2026 bright-ideas-clan
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""CLI: binary image section area analysis and replica generation.

Usage:
    python examples/image_processing/analyze.py input.txt

See input.txt for configuration options.
"""

from __future__ import annotations

import configparser
import sys
from pathlib import Path

import numpy as np
from PIL import Image

from multibest.image_processing import analysis
from multibest.image_processing import replica as _replica_mod


def _load_config(path: Path) -> configparser.ConfigParser:
    cfg = configparser.ConfigParser(inline_comment_prefixes=("#", ";"))
    if not path.exists():
        raise FileNotFoundError(f"Input file not found: {path}")
    cfg.read(path, encoding="utf-8")
    if "INPUT" not in cfg:
        raise ValueError("Missing [INPUT] section in input file.")
    return cfg


def _bool(cfg, key: str, fallback: bool) -> bool:
    return cfg.getboolean("INPUT", key, fallback=fallback)


def _int(cfg, key: str, fallback: int) -> int:
    return cfg.getint("INPUT", key, fallback=fallback)


def _float(cfg, key: str, fallback: float) -> float:
    return cfg.getfloat("INPUT", key, fallback=fallback)


def main() -> None:
    if len(sys.argv) != 2:
        print("Usage: python analyze.py input.txt", file=sys.stderr)
        sys.exit(1)

    config_path = Path(sys.argv[1])
    cfg = _load_config(config_path)

    image_path_str = cfg.get("INPUT", "image_path", fallback="").strip()
    if not image_path_str:
        raise ValueError("Missing required parameter: [INPUT] image_path")
    image_path = Path(image_path_str)
    if not image_path.exists():
        raise FileNotFoundError(f"Image file not found: {image_path}")

    out_report_str = cfg.get("INPUT", "output_report", fallback="").strip()
    output_report = Path(out_report_str) if out_report_str else image_path.with_name(f"{image_path.stem}_analysis.txt")

    analyzed_str = cfg.get("INPUT", "analyzed_image", fallback="").strip()
    analyzed_path = Path(analyzed_str) if analyzed_str else image_path.with_name("analyzed.png")

    threshold = _int(cfg, "threshold", 127)
    if not 0 <= threshold <= 255:
        raise ValueError("threshold must be between 0 and 255.")
    connectivity = _int(cfg, "connectivity", 2)
    if connectivity not in (1, 2):
        raise ValueError("connectivity must be 1 or 2.")

    invert = _bool(cfg, "invert", False)
    include_white = _bool(cfg, "include_white", True)
    include_black = _bool(cfg, "include_black", True)
    save_analyzed = _bool(cfg, "save_analyzed_image", True)
    replica_count = _int(cfg, "replica_count", 0)
    random_seed = _int(cfg, "random_seed", 12345)
    min_region = _int(cfg, "min_black_region_size", 10)
    max_region = _int(cfg, "max_black_region_size", 200)
    sigma = _float(cfg, "boundary_smoothing_sigma", 1.2)
    cleanup_width = _int(cfg, "boundary_cleanup_width", 2)

    if not include_white and not include_black:
        raise ValueError("At least one of include_white or include_black must be true.")
    if min_region > max_region:
        raise ValueError("min_black_region_size cannot be larger than max_black_region_size.")

    with Image.open(image_path) as pil_img:
        rgb = np.asarray(pil_img.convert("RGB"))

    gray = analysis.to_grayscale(rgb)
    binary = analysis.to_binary(gray, threshold=threshold, invert=invert)

    _empty = ([], np.zeros_like(gray, dtype=np.int32))
    white_rows, white_labels = analysis.label_sections(binary, "white", connectivity) if include_white else _empty
    black_rows, black_labels = analysis.label_sections(~binary, "black", connectivity) if include_black else _empty

    report = analysis.build_report_text(
        image_label=str(image_path),
        gray=gray,
        threshold=threshold,
        connectivity=connectivity,
        invert=invert,
        white_rows=white_rows,
        black_rows=black_rows,
        replica_count=replica_count,
        min_black_region=min_region,
        max_black_region=max_region,
        boundary_smoothing_sigma=sigma,
        boundary_cleanup_width=cleanup_width,
    )
    output_report.write_text(report, encoding="utf-8")
    print(f"Analysis complete. Report saved to: {output_report}")

    if save_analyzed:
        import cv2

        overlay = analysis.render_overlay(
            gray,
            white_labels,
            black_labels,
            white_rows,
            black_rows,
            draw_white=include_white,
            draw_black=include_black,
        )
        cv2.imwrite(str(analyzed_path), overlay)
        print(f"Analyzed image saved to: {analyzed_path}")

    if replica_count > 0:
        rng = np.random.default_rng(random_seed)
        for i in range(1, replica_count + 1):
            mask = _replica_mod.generate_replica(
                binary,
                min_black_region=min_region,
                max_black_region=max_region,
                rng=rng,
                boundary_smoothing_sigma=sigma,
                boundary_cleanup_width=cleanup_width,
            )
            out = image_path.with_name(f"{image_path.stem}_replica_{i}.png")
            Image.fromarray(mask.astype(np.uint8) * 255).save(str(out))
            print(f"Replica {i} saved to: {out}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 bright-ideas-clan
#
# SPDX-License-Identifier: GPL-3.0-or-later

import argparse
import shutil
import sys
from pathlib import Path

# Force UTF-8 encoding for standard output and error
if sys.platform == "win32":
    for stream in (sys.stdout, sys.stderr):
        if stream is not None and hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)


def replicate_file(input_path: Path, n: int, start: int = 1, overwrite: bool = False) -> None:
    if not input_path.exists() or not input_path.is_file():
        raise FileNotFoundError(f"Input file not found: {input_path}")

    if n < 1:
        raise ValueError("--replicate must be >= 1")
    if start < 1:
        raise ValueError("--start must be >= 1")

    directory = input_path.parent
    stem = input_path.stem  # e.g. "ebsdmaps001"
    suffix = input_path.suffix  # e.g. ".ctf"

    created = 0
    skipped = 0

    for i in range(start, start + n):
        out_path = directory / f"{stem}_{i}{suffix}"

        if out_path.exists() and not overwrite:
            print(f"Skip (exists): {out_path.name}")
            skipped += 1
            continue

        shutil.copy2(input_path, out_path)  # copy2 preserves timestamps/metadata
        print(f"Created: {out_path.name}")
        created += 1

    print(f"\nDone. Created: {created}, Skipped: {skipped}, Target: {n}")


def main():
    parser = argparse.ArgumentParser(
        description="Replicate an EBSD file N times in the same directory, adding _1.._N suffix."
    )
    parser.add_argument("input_file", help="Path to the EBSD file to replicate (e.g. ebsdmaps001.ctf)")
    parser.add_argument("--replicate", "-r", type=int, required=True, help="Number of copies to create (e.g. 50)")
    parser.add_argument("--start", type=int, default=1, help="Starting index for suffix numbering (default: 1)")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite files if they already exist")

    args = parser.parse_args()
    replicate_file(Path(args.input_file), args.replicate, start=args.start, overwrite=args.overwrite)


if __name__ == "__main__":
    main()

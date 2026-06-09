# SPDX-FileCopyrightText: 2026 bright-ideas-clan
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Install a portable Blender build for MultiBEST mesh modification."""

from __future__ import annotations

import argparse
import sys

from multibest.utils.blender import BlenderError, get_download_info, install_blender, user_blender_dir


def _progress(downloaded: int, total: int) -> None:
    if total:
        percent = int(downloaded * 100 / total)
        print(f"\rDownloading Blender... {percent:3d}%", end="", flush=True)
    else:
        mib = downloaded / (1024 * 1024)
        print(f"\rDownloading Blender... {mib:.1f} MiB", end="", flush=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Download a portable Blender build for MultiBEST.")
    parser.add_argument("--destination", default="", help="Directory to install Blender into.")
    args = parser.parse_args(argv)

    try:
        info = get_download_info()
        destination = args.destination or str(user_blender_dir())
        print(f"Blender archive: {info.url}")
        print(f"Destination: {destination}")
        blender_exec = install_blender(destination=destination, progress=_progress)
    except BlenderError as exc:
        print(f"\nError: {exc}", file=sys.stderr)
        return 1

    print(f"\nBlender ready: {blender_exec}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

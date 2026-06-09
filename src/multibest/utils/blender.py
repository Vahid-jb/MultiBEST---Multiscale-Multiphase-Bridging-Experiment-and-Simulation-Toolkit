# SPDX-FileCopyrightText: 2026 bright-ideas-clan
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Detect, validate, and optionally download a local Blender executable."""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
import tarfile
import urllib.error
import urllib.request
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

BLENDER_VERSION = "5.1.1"
BLENDER_RELEASE = "Blender5.1"
BLENDER_BASE_URL = f"https://download.blender.org/release/{BLENDER_RELEASE}"
BLENDER_DOWNLOAD_HEADERS = {
    "User-Agent": "MultiBEST Blender downloader",
    "Accept": "application/octet-stream,*/*;q=0.8",
    "Referer": "https://www.blender.org/download/",
}
BLENDER_WINDOWS_EXECUTABLE = "blender.exe"
ENV_BLENDER_EXEC = "MULTIBEST_BLENDER"
ENV_BLENDER_DIR = "MULTIBEST_BLENDER_DIR"
BUNDLED_BLENDER_DIR = "blender"


class BlenderError(RuntimeError):
    """Raised when Blender cannot be located, downloaded, or validated."""


@dataclass(frozen=True)
class BlenderDownload:
    """Download metadata for one supported platform."""

    filename: str
    executable_parts: tuple[str, ...]
    archive_type: str

    @property
    def url(self) -> str:
        return f"{BLENDER_BASE_URL}/{self.filename}"


def _platform_key() -> str:
    machine = platform.machine().lower()
    if sys.platform.startswith("linux") and machine in {"x86_64", "amd64"}:
        return "linux-x64"
    if sys.platform == "win32" and machine in {"x86_64", "amd64"}:
        return "windows-x64"
    return ""


def get_download_info() -> BlenderDownload:
    """Return download metadata for the current platform."""
    downloads = {
        "linux-x64": BlenderDownload(
            filename=f"blender-{BLENDER_VERSION}-linux-x64.tar.xz",
            executable_parts=(f"blender-{BLENDER_VERSION}-linux-x64", "blender"),
            archive_type="tar.xz",
        ),
        "windows-x64": BlenderDownload(
            filename=f"blender-{BLENDER_VERSION}-windows-x64.zip",
            executable_parts=(f"blender-{BLENDER_VERSION}-windows-x64", BLENDER_WINDOWS_EXECUTABLE),
            archive_type="zip",
        ),
    }
    key = _platform_key()
    if key not in downloads:
        raise BlenderError(
            "Automatic Blender download is currently available for Linux x64 and Windows x64 only. "
            "Please install Blender manually and choose its executable."
        )
    return downloads[key]


def user_blender_dir() -> Path:
    """Return the user-owned directory where MultiBEST stores Blender."""
    override = os.environ.get(ENV_BLENDER_DIR)
    if override:
        return Path(override).expanduser()

    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
        return base / "MultiBEST" / "blender"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "MultiBEST" / "blender"

    base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    return base / "multibest" / "blender"


def _is_executable_file(path: Path) -> bool:
    if not path.is_file():
        return False
    if sys.platform == "win32":
        return True
    return os.access(path, os.X_OK)


def _candidate_common_paths() -> list[Path]:
    if sys.platform == "win32":
        roots = [os.environ.get("PROGRAMFILES"), os.environ.get("PROGRAMFILES(X86)")]
        return [
            Path(root) / "Blender Foundation" / "Blender 5.1" / BLENDER_WINDOWS_EXECUTABLE for root in roots if root
        ]
    if sys.platform == "darwin":
        return [Path("/Applications/Blender.app/Contents/MacOS/Blender")]
    return [
        Path("/usr/bin/blender"),
        Path("/usr/local/bin/blender"),
        Path("/snap/bin/blender"),
        Path("/var/lib/flatpak/exports/bin/org.blender.Blender"),
        Path.home() / ".local" / "bin" / "blender",
    ]


def _cached_executable() -> Path | None:
    try:
        info = get_download_info()
    except BlenderError:
        return None
    candidate = user_blender_dir() / info.executable_parts[-2] / info.executable_parts[-1]
    if _is_executable_file(candidate):
        return candidate
    return find_blender_executable(user_blender_dir())


def _bundled_executable() -> Path | None:
    """Return a Blender executable shipped inside a PyInstaller bundle."""
    if not getattr(sys, "frozen", False):
        return None

    bundle_internal = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    bundle_root = Path(sys.executable).parent
    for root in (
        bundle_internal / BUNDLED_BLENDER_DIR,
        bundle_root / BUNDLED_BLENDER_DIR,
    ):
        blender_exec = find_blender_executable(root)
        if blender_exec:
            return blender_exec
    return None


def bundled_blender() -> Path | None:
    """Return the Blender executable shipped with a packaged binary, if any.

    Packaged builds (``just release`` / ``just release conda``) install Blender
    into the PyInstaller bundle. When running from such a bundle this returns
    that executable so the application uses it exclusively; otherwise ``None``.
    """
    return _bundled_executable()


def find_blender_executable(search_root: str | os.PathLike[str] | None = None) -> Path | None:
    """Search *search_root* recursively for a Blender executable."""
    if not search_root:
        return None
    root = Path(search_root).expanduser()
    if _is_executable_file(root):
        return root
    if not root.is_dir():
        return None

    executable_names = (BLENDER_WINDOWS_EXECUTABLE, "blender") if sys.platform == "win32" else ("blender",)
    for executable_name in executable_names:
        for candidate in root.rglob(executable_name):
            if _is_executable_file(candidate):
                return candidate
    return None


def discover_blender(saved_path: str = "") -> Path | None:
    """Return the best available Blender executable, or None if none is found."""
    candidates: list[Path] = []
    env_path = os.environ.get(ENV_BLENDER_EXEC)
    if env_path:
        candidates.append(Path(env_path).expanduser())
    if saved_path:
        candidates.append(Path(saved_path).expanduser())

    bundled = _bundled_executable()
    if bundled:
        candidates.append(bundled)

    cached = _cached_executable()
    if cached:
        candidates.append(cached)

    which_blender = shutil.which("blender")
    if which_blender:
        candidates.append(Path(which_blender))
    candidates.extend(_candidate_common_paths())

    for candidate in candidates:
        if _is_executable_file(candidate):
            return candidate
    return None


def blender_version(blender_exec: str | os.PathLike[str], timeout: int = 20) -> str:
    """Run Blender in background mode and return its version output."""
    proc = subprocess.run(
        [str(blender_exec), "--background", "--version"],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    output = "\n".join(part.strip() for part in (proc.stdout, proc.stderr) if part.strip())
    if proc.returncode != 0:
        raise BlenderError(output or f"Blender exited with code {proc.returncode}.")
    return output


def validate_blender(blender_exec: str | os.PathLike[str]) -> bool:
    """Return True if *blender_exec* starts successfully."""
    try:
        blender_version(blender_exec)
    except (OSError, subprocess.SubprocessError, BlenderError):
        return False
    return True


def _download_file(url: str, destination: Path, progress: Callable[[int, int], None] | None = None) -> None:
    request = urllib.request.Request(url, headers=BLENDER_DOWNLOAD_HEADERS)
    try:
        with urllib.request.urlopen(request) as response, destination.open("wb") as file:
            total = int(response.headers.get("Content-Length") or 0)
            downloaded = 0
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                file.write(chunk)
                downloaded += len(chunk)
                if progress:
                    progress(downloaded, total)
    except urllib.error.HTTPError as exc:
        raise BlenderError(f"Blender download failed from {url}: HTTP {exc.code} {exc.reason}") from exc
    except urllib.error.URLError as exc:
        raise BlenderError(f"Blender download failed from {url}: {exc.reason}") from exc


def _extract_archive(archive_path: Path, destination: Path, archive_type: str) -> None:
    if archive_type == "zip":
        with zipfile.ZipFile(archive_path) as archive:
            _safe_extract_zip(archive, destination)
        return
    if archive_type == "tar.xz":
        with tarfile.open(archive_path, mode="r:xz") as archive:
            _safe_extract_tar(archive, destination)
        return
    raise BlenderError(f"Unsupported Blender archive type: {archive_type}")


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def _safe_extract_zip(archive: zipfile.ZipFile, destination: Path) -> None:
    root = destination.resolve()
    for member in archive.infolist():
        target = (destination / member.filename).resolve()
        if not _is_relative_to(target, root):
            raise BlenderError(f"Refusing to extract unsafe archive member: {member.filename}")
    archive.extractall(destination)


def _safe_extract_tar(archive: tarfile.TarFile, destination: Path) -> None:
    root = destination.resolve()
    for member in archive.getmembers():
        target = (destination / member.name).resolve()
        if not _is_relative_to(target, root):
            raise BlenderError(f"Refusing to extract unsafe archive member: {member.name}")
    extract_filter = getattr(tarfile, "data_filter", None)
    if extract_filter is None:
        archive.extractall(destination)
    else:
        archive.extraction_filter = extract_filter
        archive.extractall(destination)


def install_blender(
    destination: str | os.PathLike[str] | None = None,
    progress: Callable[[int, int], None] | None = None,
) -> Path:
    """Download Blender into a user cache and return the executable path."""
    info = get_download_info()
    install_dir = Path(destination).expanduser() if destination else user_blender_dir()
    install_dir.mkdir(parents=True, exist_ok=True)

    existing = find_blender_executable(install_dir)
    if existing and validate_blender(existing):
        return existing

    archive_path = install_dir / info.filename
    _download_file(info.url, archive_path, progress)
    _extract_archive(archive_path, install_dir, info.archive_type)
    archive_path.unlink(missing_ok=True)

    blender_exec = install_dir.joinpath(*info.executable_parts)
    if sys.platform != "win32":
        blender_exec.chmod(blender_exec.stat().st_mode | 0o755)
    if not validate_blender(blender_exec):
        raise BlenderError(f"Downloaded Blender did not start correctly: {blender_exec}")
    return blender_exec

# SPDX-FileCopyrightText: 2026 bright-ideas-clan
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Locate or provision an external DREAM3D-NX Python environment.

MultiBEST's EBSD preparation step depends on the ``simplnx`` and
``orientationanalysis`` Python modules shipped with DREAM3D-NX. Those binaries
are **not redistributable** with MultiBEST (the conda packages from the
``bluequartzsoftware`` channel carry a proprietary EULA, and the simplnx
sources are dual-licensed AGPL-3.0/commercial), so the packaged application
never bundles them. Instead, the EBSD backend runs in a *separate* Python
environment on the user's machine — either one the user already has, or a
managed environment this module can create on demand by downloading
micromamba (BSD-3-Clause) and installing ``dream3dnx`` from BlueQuartz's own
channel at the user's request.
"""

from __future__ import annotations

import os
import platform
import subprocess
import sys
import tarfile
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

ENV_DREAM3D_PYTHON = "MULTIBEST_DREAM3D_PYTHON"
ENV_DREAM3D_DIR = "MULTIBEST_DREAM3D_DIR"

MICROMAMBA_BASE_URL = "https://micro.mamba.pm/api/micromamba"
DOWNLOAD_HEADERS = {
    "User-Agent": "MultiBEST DREAM3D-NX environment installer",
    "Accept": "application/octet-stream,*/*;q=0.8",
}

# Conda specs for the managed environment. ``dream3dnx`` provides simplnx and
# orientationanalysis; matplotlib/numpy/h5py are required by EBSD_Atomistic.py
# and EBSD_visualization.py at runtime inside this environment.
DREAM3D_ENV_SPECS = ("python=3.12", "dream3dnx", "matplotlib", "numpy", "h5py")
DREAM3D_ENV_CHANNELS = ("bluequartzsoftware", "conda-forge")

PROBE_STATEMENT = "import simplnx; import orientationanalysis"
PROBE_TIMEOUT_SECONDS = 180


class Dream3DError(RuntimeError):
    """Raised when a DREAM3D-NX environment cannot be located or provisioned."""


@dataclass(frozen=True)
class MicromambaDownload:
    """Download metadata for the micromamba bootstrap binary."""

    url: str
    executable_parts: tuple[str, ...]


def user_dream3d_dir() -> Path:
    """Return the user-owned directory where MultiBEST stores the managed env."""
    override = os.environ.get(ENV_DREAM3D_DIR)
    if override:
        return Path(override).expanduser()

    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
        return base / "MultiBEST" / "dream3dnx"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "MultiBEST" / "dream3dnx"

    base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    return base / "multibest" / "dream3dnx"


def managed_env_python() -> Path:
    """Return the Python interpreter path inside the managed environment."""
    env_prefix = user_dream3d_dir() / "env"
    if sys.platform == "win32":
        return env_prefix / "python.exe"
    return env_prefix / "bin" / "python"


def probe_python(python_exec: str | os.PathLike[str], timeout: int = PROBE_TIMEOUT_SECONDS) -> bool:
    """Return True if *python_exec* can import simplnx and orientationanalysis."""
    try:
        proc = subprocess.run(
            [str(python_exec), "-c", PROBE_STATEMENT],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return proc.returncode == 0


def _is_executable_file(path: Path) -> bool:
    if not path.is_file():
        return False
    if sys.platform == "win32":
        return True
    return os.access(path, os.X_OK)


def _env_prefix_python(prefix: Path) -> Path:
    if sys.platform == "win32":
        return prefix / "python.exe"
    return prefix / "bin" / "python"


def _conda_env_pythons() -> list[Path]:
    """Return Python interpreters of conda-style environments on this machine.

    Reads ``~/.conda/environments.txt`` (written by conda/mamba for every
    created environment) and falls back to well-known env root directories.
    """
    prefixes: list[Path] = []

    environments_txt = Path.home() / ".conda" / "environments.txt"
    if environments_txt.is_file():
        for line in environments_txt.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                prefixes.append(Path(line))

    for root_name in ("miniconda3", "anaconda3", "mambaforge", "miniforge3", "micromamba"):
        envs_dir = Path.home() / root_name / "envs"
        if envs_dir.is_dir():
            prefixes.extend(sorted(p for p in envs_dir.iterdir() if p.is_dir()))

    pythons: list[Path] = []
    seen: set[Path] = set()
    for prefix in prefixes:
        python = _env_prefix_python(prefix)
        if python not in seen and _is_executable_file(python):
            seen.add(python)
            pythons.append(python)
    return pythons


def discover_dream3d_python(saved_path: str = "", *, run_probe: bool = True) -> Path | None:
    """Return the best available DREAM3D-NX Python interpreter, or None.

    Candidates are checked in order: the ``MULTIBEST_DREAM3D_PYTHON``
    environment variable, *saved_path* (a previously saved GUI setting), the
    managed environment, then any conda-style environments found on the
    machine. Each candidate must exist and — unless *run_probe* is False —
    pass :func:`probe_python`. Skipping the probe keeps the check cheap for
    UI status refreshes; runs should always probe.
    """
    candidates: list[Path] = []
    env_path = os.environ.get(ENV_DREAM3D_PYTHON)
    if env_path:
        candidates.append(Path(env_path).expanduser())
    if saved_path:
        candidates.append(Path(saved_path).expanduser())
    candidates.append(managed_env_python())
    candidates.extend(_conda_env_pythons())

    for candidate in candidates:
        if _is_executable_file(candidate) and (not run_probe or probe_python(candidate)):
            return candidate
    return None


def get_micromamba_download_info() -> MicromambaDownload:
    """Return the micromamba download metadata for the current platform."""
    machine = platform.machine().lower()
    if sys.platform.startswith("linux"):
        subdir = {"x86_64": "linux-64", "amd64": "linux-64", "aarch64": "linux-aarch64"}.get(machine)
        executable_parts: tuple[str, ...] = ("bin", "micromamba")
    elif sys.platform == "darwin":
        subdir = {"x86_64": "osx-64", "arm64": "osx-arm64"}.get(machine)
        executable_parts = ("bin", "micromamba")
    elif sys.platform == "win32":
        subdir = {"x86_64": "win-64", "amd64": "win-64"}.get(machine)
        executable_parts = ("Library", "bin", "micromamba.exe")
    else:
        subdir = None
        executable_parts = ()

    if not subdir:
        raise Dream3DError(
            f"Automatic DREAM3D-NX environment setup is not supported on {sys.platform}/{machine}. "
            "Please install DREAM3D-NX manually and select its Python interpreter."
        )
    return MicromambaDownload(url=f"{MICROMAMBA_BASE_URL}/{subdir}/latest", executable_parts=executable_parts)


def _download_file(url: str, destination: Path, progress: Callable[[int, int], None] | None = None) -> None:
    request = urllib.request.Request(url, headers=DOWNLOAD_HEADERS)
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
        raise Dream3DError(f"Download failed from {url}: HTTP {exc.code} {exc.reason}") from exc
    except urllib.error.URLError as exc:
        raise Dream3DError(f"Download failed from {url}: {exc.reason}") from exc


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def _extract_tar(archive_path: Path, destination: Path) -> None:
    with tarfile.open(archive_path, mode="r:bz2") as archive:
        root = destination.resolve()
        for member in archive.getmembers():
            target = (destination / member.name).resolve()
            if not _is_relative_to(target, root):
                raise Dream3DError(f"Refusing to extract unsafe archive member: {member.name}")
        extract_filter = getattr(tarfile, "data_filter", None)
        if extract_filter is not None:
            archive.extraction_filter = extract_filter
        archive.extractall(destination)


def _ensure_micromamba(root: Path) -> Path:
    """Return a micromamba executable below *root*, downloading it if needed."""
    info = get_micromamba_download_info()
    micromamba_dir = root / "micromamba"
    micromamba = micromamba_dir.joinpath(*info.executable_parts)
    if _is_executable_file(micromamba):
        return micromamba

    micromamba_dir.mkdir(parents=True, exist_ok=True)
    archive_path = micromamba_dir / "micromamba.tar.bz2"
    _download_file(info.url, archive_path)
    _extract_tar(archive_path, micromamba_dir)
    archive_path.unlink(missing_ok=True)

    if sys.platform != "win32" and micromamba.is_file():
        micromamba.chmod(micromamba.stat().st_mode | 0o755)
    if not _is_executable_file(micromamba):
        raise Dream3DError(f"micromamba was not found after extraction: {micromamba}")
    return micromamba


def _env_create_command(micromamba: Path, root: Path, env_prefix: Path) -> list[str]:
    command = [
        str(micromamba),
        "create",
        "--yes",
        "--root-prefix",
        str(root / "mamba-root"),
        "--prefix",
        str(env_prefix),
    ]
    for channel in DREAM3D_ENV_CHANNELS:
        command.extend(["-c", channel])
    command.extend(DREAM3D_ENV_SPECS)
    return command


def _stream_command(command: list[str], log: Callable[[str], None] | None) -> int:
    """Run *command*, forwarding each output line to *log*; return the exit code."""
    proc = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    assert proc.stdout is not None
    for line in proc.stdout:
        if log:
            log(line.rstrip("\n"))
    return proc.wait()


def install_dream3d_env(
    progress: Callable[[int, int], None] | None = None,
    log: Callable[[str], None] | None = None,
) -> Path:
    """Create the managed DREAM3D-NX environment and return its interpreter.

    Downloads micromamba (BSD-3-Clause) into the MultiBEST user data
    directory, then installs ``dream3dnx`` from BlueQuartz Software's own
    conda channel. The DREAM3D-NX binaries land on the user's machine at the
    user's request and are never redistributed with MultiBEST.

    Parameters
    ----------
    progress:
        Optional ``(downloaded_bytes, total_bytes)`` callback for the
        micromamba download.
    log:
        Optional callback receiving each line of micromamba's output.
    """
    root = user_dream3d_dir()
    root.mkdir(parents=True, exist_ok=True)

    python = managed_env_python()
    if _is_executable_file(python) and probe_python(python):
        return python

    micromamba = _ensure_micromamba(root)
    if progress:
        progress(1, 1)

    env_prefix = root / "env"
    command = _env_create_command(micromamba, root, env_prefix)
    if log:
        log(f"Creating DREAM3D-NX environment: {' '.join(command)}")
    exit_code = _stream_command(command, log)
    if exit_code != 0:
        raise Dream3DError(f"micromamba create exited with code {exit_code}.")

    if not _is_executable_file(python) or not probe_python(python):
        raise Dream3DError(f"The created environment did not provide working simplnx modules: {python}")
    return python

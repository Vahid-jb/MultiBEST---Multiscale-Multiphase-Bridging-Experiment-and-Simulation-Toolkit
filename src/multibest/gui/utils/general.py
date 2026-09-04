# SPDX-FileCopyrightText: 2026 bright-ideas-clan
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
multibest.gui.utils/general.py
==========================

Shared runtime utilities for all MultiBEST GUI sub-modules.

Provides:
- Path resolution for frozen (PyInstaller) and development builds.
- ``Runner``: an async Qt sub-process wrapper that streams stdout/stderr
  to a caller-supplied callback.
- ``MultiBESTLogger``: thin adapter between ``Runner`` and a PySide6 ``Signal``.
- File-dialog helpers (``browse_file``, ``create_file``, ``browse_directory``).
"""

from __future__ import annotations

import os
import shutil
import sys
from collections.abc import Callable

from PySide6.QtCore import QObject, QProcess, QProcessEnvironment
from PySide6.QtWidgets import QFileDialog, QLineEdit, QWidget


def is_pyinstaller() -> bool:
    """Return True if the process is running inside a PyInstaller frozen bundle."""
    return getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS")


def get_base_dir() -> str:
    """Return the project root / data directory.

    In a PyInstaller frozen app the bundled data lives in the
    ``_internal/`` directory pointed to by ``sys._MEIPASS``.
    In normal development the base dir is the directory containing
    the main script.
    """
    if getattr(sys, "frozen", False):
        # PyInstaller stores bundled data files here
        return sys._MEIPASS  # type: ignore[attr-defined]
    return os.path.dirname(os.path.abspath(sys.argv[0]))


def get_script_path(*parts: str) -> str:
    """Build an absolute path to a bundled script or binary.

    Usage::

        get_script_path("TEM", "lammps", "compute_saed.py")
        get_script_path("XRD", "XRD-Kinematical.py")

    In development mode returns the .py path relative to the project root.

    In frozen (PyInstaller) mode the compute scripts are built as separate
    PyInstaller binaries that land **next to** ``sys.executable`` in the
    dist folder (not inside ``_MEIPASS``).  The function strips the ``.py``
    extension and, on Windows, appends ``.exe`` to find the binary.
    """
    if not getattr(sys, "frozen", False):
        # Development: point at the .py source file as usual
        return os.path.join(get_base_dir(), *parts)

    # Frozen: look for the sibling binary next to the main executable.
    # Only the last part (the filename) is relevant – all binaries are
    # collected into the same flat dist folder by the merged spec.
    stem = os.path.splitext(parts[-1])[0]  # e.g. "compute_saed"
    exe_dir = os.path.dirname(sys.executable)
    if sys.platform == "win32":
        return os.path.join(exe_dir, stem + ".exe")
    return os.path.join(exe_dir, stem)


def get_source_script_path(*parts: str) -> str:
    """Build an absolute path to a script shipped as plain ``.py`` source.

    Unlike :func:`get_script_path`, scripts resolved here are *not* frozen
    into sibling binaries — they are bundled as data files and executed by an
    external Python interpreter (e.g. the DREAM3D-NX environment, whose
    dependencies must not be redistributed inside the bundle).

    In development mode this is identical to :func:`get_script_path`. In
    frozen mode the relative ``..`` segments are dropped and the path is
    resolved inside the bundle's data directory (``sys._MEIPASS``).
    """
    if not getattr(sys, "frozen", False):
        return os.path.join(get_base_dir(), *parts)

    clean_parts = [part for part in parts if part not in ("..", ".")]
    return os.path.join(sys._MEIPASS, *clean_parts)  # type: ignore[attr-defined]


def _get_python_interpreter() -> str:
    """Return the path to a Python interpreter for running scripts.

    * **Normal mode** – returns ``sys.executable`` (the current interpreter).
    * **Frozen mode** – checks (in order):
      1. ``MULTIBEST_PYTHON`` environment variable
      2. A bundled ``python/bin/python3`` directory next to the executable
      3. ``python3`` / ``python`` on ``PATH``
    """
    if not getattr(sys, "frozen", False):
        return sys.executable

    # 1) Honour an explicit override
    env = os.environ.get("MULTIBEST_PYTHON")
    if env and (os.path.isfile(env) or shutil.which(env)):
        return env

    # 2) Check for a bundled python/ directory (conda-pack layout)
    exe_dir = os.path.dirname(sys.executable)
    for candidate in (
        os.path.join(exe_dir, "python", "bin", "python3"),
        os.path.join(exe_dir, "python", "bin", "python"),
        os.path.join(exe_dir, "python", "python.exe"),  # Windows
    ):
        if os.path.isfile(candidate):
            return candidate

    # 3) Probe common names on PATH
    for name in ("python3", "python"):
        found = shutil.which(name)
        if found:
            return found

    # 4) Last resort – the user will see an informative error from QProcess
    return "python3"


class Runner(QObject):
    """Launches a compute script as a ``QProcess`` and streams its output.

    Each line from stdout is forwarded to *on_line* as ``("STDOUT", line)``
    and each line from stderr as ``("STDERR", line)``. Terminal progress bars
    such as tqdm still arrive through stderr, but are classified later by the
    logger so they do not appear as errors in the GUI.
    An optional *on_finished* callback is invoked when the process exits.
    """

    def __init__(
        self,
        on_line: Callable[[str, str], None],
        on_finished: Callable[[int, object], None] | None = None,
    ) -> None:
        super().__init__()
        self.on_line = on_line
        self.on_finished_cb = on_finished
        self.proc = QProcess()

        self.proc.readyReadStandardOutput.connect(self._on_stdout)
        self.proc.readyReadStandardError.connect(self._on_stderr)
        self.proc.finished.connect(self._on_finished)

    def _on_finished(self, exit_code: int, exit_status: object) -> None:
        self.on_line("INFO", f"[Process finished] exit_code={exit_code}")
        if self.on_finished_cb:
            self.on_finished_cb(exit_code, exit_status)

    def kill(self) -> None:
        """Terminate the running sub-process if one is active."""
        if self.proc.state() != QProcess.ProcessState.NotRunning:
            self.proc.kill()

    @property
    def is_running(self) -> bool:
        """True while the sub-process has not yet exited."""
        return self.proc.state() != QProcess.ProcessState.NotRunning

    def start(
        self,
        script_path: str,
        args: list[str] | None = None,
        cwd: str | None = None,
    ) -> None:
        """Launch *script_path* via a Python interpreter.

        In frozen (PyInstaller) mode the interpreter is resolved via
        ``_get_python_interpreter()`` so that the binary does **not**
        re-launch itself.
        """
        args = args or []
        if cwd:
            self.proc.setWorkingDirectory(cwd)

        # Unbuffered output ensures lines arrive at the GUI in real time.
        env = QProcessEnvironment.systemEnvironment()
        env.insert("PYTHONUNBUFFERED", "1")

        if is_pyinstaller() and not sys.platform.startswith("win"):
            # PyInstaller's bootloader on Linux/macOS replaces LD_LIBRARY_PATH
            # with its own MEIPASS paths and saves the original value in
            # LD_LIBRARY_PATH_ORIG.  Child PyInstaller binaries must receive a
            # clean LD_LIBRARY_PATH so their own bootloaders can initialise
            # correctly; otherwise the parent's libraries leak into the child.
            if env.contains("LD_LIBRARY_PATH_ORIG"):
                env.insert("LD_LIBRARY_PATH", env.value("LD_LIBRARY_PATH_ORIG"))
            else:
                env.remove("LD_LIBRARY_PATH")

        self.proc.setProcessEnvironment(env)

        if is_pyinstaller():
            # In frozen mode, script_path is a sibling binary resolved by
            # get_script_path; execute it directly without a Python interpreter.
            self.proc.start(script_path, [*args])
        else:
            self.proc.start(_get_python_interpreter(), ["-u", script_path, *args])

    def start_program(
        self,
        program: str,
        args: list[str] | None = None,
        cwd: str | None = None,
    ) -> None:
        """Launch an external executable directly and stream its output."""
        args = args or []
        if cwd:
            self.proc.setWorkingDirectory(cwd)

        env = QProcessEnvironment.systemEnvironment()
        env.insert("PYTHONUNBUFFERED", "1")

        if is_pyinstaller() and not sys.platform.startswith("win"):
            if env.contains("LD_LIBRARY_PATH_ORIG"):
                env.insert("LD_LIBRARY_PATH", env.value("LD_LIBRARY_PATH_ORIG"))
            else:
                env.remove("LD_LIBRARY_PATH")

        self.proc.setProcessEnvironment(env)
        self.proc.start(program, args)

    def _emit_chunks(self, stream_name: str, data: bytes) -> None:
        text = data.decode("utf-8", errors="replace")
        for line in text.splitlines():
            if line.strip():
                self.on_line(stream_name, line)

    def _on_stdout(self) -> None:
        self._emit_chunks("STDOUT", bytes(self.proc.readAllStandardOutput()))

    def _on_stderr(self) -> None:
        self._emit_chunks("STDERR", bytes(self.proc.readAllStandardError()))


class MultiBESTLogger:
    """Adapts structured log calls to a PySide6 ``Signal(str)``.

    Each message is emitted as ``"LEVEL: text"`` so the receiver can
    colour-code by prefix without additional parsing.
    """

    def __init__(self, log_signal) -> None:
        self.log_signal = log_signal

    def log_message(self, level: str, msg: str) -> None:
        """Emit *msg* prefixed with *level* (e.g. 'INFO', 'ERROR')."""
        self.log_signal.emit(f"{level}: {msg}")

    def handle_process_line(self, stream: str, line: str) -> None:
        """Route a sub-process output line to the log signal."""
        if stream == "STDERR":
            if _looks_like_terminal_progress(line):
                self.log_message("PROGRESS", line)
            else:
                self.log_message("ERROR", line)
        else:
            self.log_message("INFO", line)


def _looks_like_terminal_progress(line: str) -> bool:
    """Return True for carriage-return progress output, especially tqdm."""
    stripped = line.strip()
    return "%|" in stripped and ("it/s" in stripped or "/s]" in stripped or "[" in stripped)


# ---------------------------------------------------------------------------
# File-dialog helpers shared across all sub-module GUIs
# ---------------------------------------------------------------------------


def browse_file(parent: QWidget, line_edit: QLineEdit, filter: str = "All files (*)") -> None:
    """Open an 'Open File' dialog and set the chosen path on *line_edit*."""
    filename, _ = QFileDialog.getOpenFileName(parent, "Select File", "", filter)
    if filename:
        line_edit.setText(filename)


def create_file(parent: QWidget, line_edit: QLineEdit, filter: str = "All files (*)") -> None:
    """Open a 'Save File' dialog and set the chosen path on *line_edit*."""
    filename, _ = QFileDialog.getSaveFileName(parent, "Output File", "", filter)
    if filename:
        line_edit.setText(filename)


def browse_directory(parent: QWidget, line_edit: QLineEdit) -> None:
    """Open a directory selection dialog and set the chosen path on *line_edit*."""
    dirname = QFileDialog.getExistingDirectory(parent, "Select Directory", "")
    if dirname:
        line_edit.setText(dirname)

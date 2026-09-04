# SPDX-FileCopyrightText: 2026 bright-ideas-clan
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Shared DREAM3D-NX environment control helpers for GUI modules.

DREAM3D-NX is not redistributable with MultiBEST (proprietary conda binaries;
AGPL-3.0/commercial sources), so the EBSD backend runs in an external Python
environment. These controls let the user select, validate, or install one.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit

from multibest.gui.utils.theme import make_action_button

PathFinder = Callable[..., Path | None]

INSTALL_QUESTION = (
    "Set up a managed DREAM3D-NX Python environment now?\n\n"
    "MultiBEST will download micromamba (BSD-3-Clause licensed) and install the "
    "free dream3dnx package from BlueQuartz Software's own conda channel into "
    "your user MultiBEST data directory (roughly 2 GB of disk space).\n\n"
    "DREAM3D-NX is provided by BlueQuartz Software under its own license terms; "
    "it is downloaded to your machine at your request and is not part of MultiBEST."
)


def build_dream3d_group(owner: Any, settings_key: str) -> QGroupBox:
    """Build the standard DREAM3D-NX Python interpreter selector group."""
    group = QGroupBox("DREAM3D-NX environment")
    owner._dream3d_group = group
    layout = QFormLayout(group)

    owner.dream3d_python = QLineEdit()
    owner.dream3d_python.setPlaceholderText("Auto-detect DREAM3D-NX Python")
    owner.dream3d_python.editingFinished.connect(owner._save_dream3d_path)
    owner.dream3d_status = QLabel("")
    owner.dream3d_status.setWordWrap(True)

    saved_path = owner._settings().value(settings_key, "", str)
    if saved_path:
        owner.dream3d_python.setText(saved_path)

    browse_btn = make_action_button("Browse", "browse")
    browse_btn.clicked.connect(owner._browse_dream3d_python)
    test_btn = make_action_button("Test", "test")
    test_btn.clicked.connect(owner._test_dream3d_python)
    install_btn = make_action_button("Install", "download")
    install_btn.clicked.connect(owner._install_dream3d_env)

    path_row = QHBoxLayout()
    path_row.addWidget(owner.dream3d_python)
    path_row.addWidget(browse_btn)
    path_row.addWidget(test_btn)
    path_row.addWidget(install_btn)
    layout.addRow("Python:", path_row)
    layout.addRow("Status:", owner.dream3d_status)
    return group


def save_dream3d_path(owner: Any, settings_key: str) -> None:
    path = owner.dream3d_python.text().strip()
    owner._settings().setValue(settings_key, path)
    owner._refresh_dream3d_status()


def browse_dream3d_python(owner: Any, get_open_file_name: Callable[..., tuple[str, str]]) -> None:
    filename, _ = get_open_file_name(owner, "Select DREAM3D-NX Python Interpreter", "", "Python (*)")
    if filename:
        owner.dream3d_python.setText(filename)
        owner._save_dream3d_path()


def refresh_dream3d_status(owner: Any, missing_message: str, discover_func: PathFinder) -> None:
    """Update the status label with a cheap (no-probe) discovery result."""
    python_exec = discover_func(owner.dream3d_python.text().strip(), run_probe=False)
    if python_exec:
        owner.dream3d_status.setText(f"Candidate: {python_exec} (use Test to verify)")
    else:
        owner.dream3d_status.setText(missing_message)


def test_dream3d_python(owner: Any, discover_func: PathFinder) -> None:
    """Fully probe the selected/discovered interpreter and report the result."""
    python_exec = discover_func(owner.dream3d_python.text().strip())
    if not python_exec:
        owner.logger.log_message(
            "ERROR",
            "No working DREAM3D-NX Python found. Use Install to create a managed "
            "environment, or Browse to select an interpreter that can import "
            "'simplnx' and 'orientationanalysis'.",
        )
        return
    owner.dream3d_python.setText(str(python_exec))
    owner._save_dream3d_path()
    owner.dream3d_status.setText(f"Available: {python_exec}")
    owner.logger.log_message("INFO", f"DREAM3D-NX environment OK: {python_exec}")


def install_dream3d_env(
    owner: Any,
    install_func: Callable[..., Path],
    error_type: type[Exception],
    message_box: Any,
    progress_dialog_type: Any,
    process_events: Callable[[], None],
) -> None:
    """Confirm with the user, then create the managed environment.

    The micromamba transaction can take several minutes; its output is
    streamed to the module logger while a busy dialog keeps the UI alive.
    """
    if message_box.question(owner, "Install DREAM3D-NX environment", INSTALL_QUESTION) != (
        message_box.StandardButton.Yes
    ):
        return

    progress = progress_dialog_type("Installing DREAM3D-NX environment...", "Cancel", 0, 0, owner)
    progress.setWindowModality(Qt.WindowModality.WindowModal)
    progress.setMinimumDuration(0)

    def _log(line: str) -> None:
        if progress.wasCanceled():
            raise error_type("DREAM3D-NX environment installation canceled.")
        owner.logger.log_message("INFO", line)
        process_events()

    try:
        python_exec = install_func(log=_log)
    except Exception as exc:
        progress.close()
        owner.logger.log_message("ERROR", f"DREAM3D-NX environment installation failed:\n{exc}")
        return

    progress.close()
    owner.dream3d_python.setText(str(python_exec))
    owner._save_dream3d_path()
    owner.logger.log_message("INFO", f"DREAM3D-NX environment ready: {python_exec}")

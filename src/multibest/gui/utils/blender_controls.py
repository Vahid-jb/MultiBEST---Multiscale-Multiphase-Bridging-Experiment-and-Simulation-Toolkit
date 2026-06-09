# SPDX-FileCopyrightText: 2026 bright-ideas-clan
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Shared Blender control helpers for GUI modules."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit

from multibest.gui.utils.theme import make_action_button

PathFinder = Callable[[str], Path | str | None]
VersionReader = Callable[[Path | str], str]


def build_blender_group(
    owner: Any,
    settings_key: str,
    bundled_blender_func: Callable[[], Path | None],
) -> QGroupBox:
    """Build the standard Blender executable selector group."""
    group = QGroupBox("Blender")
    owner._blender_group = group
    layout = QFormLayout(group)

    owner.blender_exec = QLineEdit()
    owner.blender_exec.setPlaceholderText("Auto-detect Blender")
    owner.blender_exec.editingFinished.connect(owner._save_blender_path)
    owner.blender_status = QLabel("")
    owner.blender_status.setWordWrap(True)

    bundled = bundled_blender_func()
    owner._blender_bundled = bundled is not None
    if bundled is not None:
        owner.blender_exec.setText(str(bundled))
        owner.blender_exec.setReadOnly(True)
        group.hide()
        return group

    saved_path = owner._settings().value(settings_key, "", str)
    if saved_path:
        owner.blender_exec.setText(saved_path)

    browse_btn = make_action_button("Browse", "browse")
    browse_btn.clicked.connect(owner._browse_blender_exec)
    test_btn = make_action_button("Test", "test")
    test_btn.clicked.connect(owner._test_blender_exec)
    download_btn = make_action_button("Download", "download")
    download_btn.clicked.connect(owner._download_blender)

    path_row = QHBoxLayout()
    path_row.addWidget(owner.blender_exec)
    path_row.addWidget(browse_btn)
    path_row.addWidget(test_btn)
    path_row.addWidget(download_btn)
    layout.addRow("Executable:", path_row)
    layout.addRow("Status:", owner.blender_status)
    return group


def save_blender_path(owner: Any, settings_key: str) -> None:
    path = owner.blender_exec.text().strip()
    owner._settings().setValue(settings_key, path)
    owner._refresh_blender_status()


def browse_blender_exec(owner: Any, get_open_file_name: Callable[..., tuple[str, str]]) -> None:
    filename, _ = get_open_file_name(owner, "Select Blender Executable", "", "Blender (*)")
    if filename:
        owner.blender_exec.setText(filename)
        owner._save_blender_path()


def refresh_blender_status(
    owner: Any,
    missing_message: str,
    bundled_blender_func: Callable[[], Path | None],
    discover_blender_func: PathFinder,
) -> None:
    blender_exec = bundled_blender_func() or discover_blender_func(owner.blender_exec.text().strip())
    if blender_exec:
        owner.blender_status.setText(f"Available: {blender_exec}")
    else:
        owner.blender_status.setText(missing_message)


def test_blender_exec(
    owner: Any,
    discover_blender_func: PathFinder,
    blender_version_func: VersionReader,
    blender_error_type: type[Exception],
) -> None:
    blender_exec = discover_blender_func(owner.blender_exec.text().strip())
    if not blender_exec:
        owner.logger.log_message("ERROR", "Blender executable not found.")
        return
    try:
        version = blender_version_func(blender_exec)
    except (OSError, blender_error_type) as exc:
        owner.logger.log_message("ERROR", f"Blender test failed:\n{exc}")
        return
    first_line = version.splitlines()[0] if version else str(blender_exec)
    owner.blender_exec.setText(str(blender_exec))
    owner._save_blender_path()
    owner.logger.log_message("INFO", f"Blender test succeeded: {first_line}")


def download_blender(
    owner: Any,
    get_download_info_func: Callable[[], Any],
    install_blender_func: Callable[..., Path | str],
    blender_error_type: type[Exception],
    message_box: Any,
    progress_dialog_type: Any,
    process_events: Callable[[], None],
) -> None:
    try:
        info = get_download_info_func()
    except blender_error_type as exc:
        message_box.warning(owner, "Blender download unavailable", str(exc))
        return

    question = (
        f"Download Blender {info.filename} from blender.org?\n\n"
        "The archive is large and will be stored in your user MultiBEST data directory."
    )
    if message_box.question(owner, "Download Blender", question) != message_box.StandardButton.Yes:
        return

    progress = progress_dialog_type("Downloading Blender...", "Cancel", 0, 100, owner)
    progress.setWindowModality(Qt.WindowModality.WindowModal)
    progress.setMinimumDuration(0)
    progress.setValue(0)

    def _progress(downloaded: int, total: int) -> None:
        if progress.wasCanceled():
            raise blender_error_type("Blender download canceled.")
        if total:
            progress.setValue(min(100, int(downloaded * 100 / total)))
        process_events()

    try:
        blender_exec = install_blender_func(progress=_progress)
    except Exception as exc:
        progress.close()
        owner.logger.log_message("ERROR", f"Blender download failed:\n{exc}")
        return

    progress.setValue(100)
    owner.blender_exec.setText(str(blender_exec))
    owner._save_blender_path()
    owner.logger.log_message("INFO", f"Blender ready: {blender_exec}")

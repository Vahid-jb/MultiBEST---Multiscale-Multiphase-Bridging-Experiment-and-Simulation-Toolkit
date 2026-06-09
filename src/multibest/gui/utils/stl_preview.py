# SPDX-FileCopyrightText: 2026 bright-ideas-clan
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Shared STL preview widgets and behavior."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PySide6.QtWidgets import QApplication, QFrame, QHBoxLayout, QLabel

from multibest.gui.utils.theme import NoWheelComboBox, apply_subtle_text, make_action_button


def build_mesh_preview_toolbar(owner: Any) -> QFrame:
    toolbar = QFrame()
    owner.mesh_preview_toolbar = toolbar
    layout = QHBoxLayout(toolbar)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(10)
    layout.addWidget(QLabel("Preview STL"))

    owner.mesh_preview_selector = NoWheelComboBox()
    owner.mesh_preview_selector.setMinimumWidth(180)
    owner.mesh_preview_selector.currentIndexChanged.connect(lambda index: on_mesh_preview_selected(owner, index))
    layout.addWidget(owner.mesh_preview_selector, 1)

    owner.mesh_preview_count = QLabel("")
    apply_subtle_text(owner.mesh_preview_count)
    layout.addWidget(owner.mesh_preview_count)

    reset_view_btn = make_action_button("Reset View", "reset")
    reset_view_btn.clicked.connect(lambda: reset_mesh_preview_camera(owner))
    layout.addWidget(reset_view_btn)
    toolbar.hide()
    return toolbar


def set_mesh_choices(
    owner: Any,
    paths: list[str],
    label_for_path: Callable[[str], str],
    singular_label: str,
    plural_label: str,
) -> None:
    owner._mesh_preview_paths = paths
    owner.mesh_preview_selector.blockSignals(True)
    owner.mesh_preview_selector.clear()
    for path in paths:
        owner.mesh_preview_selector.addItem(label_for_path(path), path)
    owner.mesh_preview_selector.blockSignals(False)

    count = len(paths)
    owner.mesh_preview_count.setText(f"{count} {singular_label if count == 1 else plural_label}")
    owner.mesh_preview_toolbar.setVisible(count > 0)


def on_mesh_preview_selected(owner: Any, index: int) -> None:
    if index < 0:
        return
    path = owner.mesh_preview_selector.itemData(index)
    if path:
        owner._load_mesh_preview(str(path))


def reset_mesh_preview_camera(owner: Any) -> None:
    owner.mesh_viewer.reset_camera()


def load_mesh_preview(
    owner: Any,
    path: str,
    process_events: Callable[[], None] = QApplication.processEvents,
) -> None:
    try:
        owner.mesh_viz_label.hide()
        owner.mesh_viewer.show()
        process_events()
        owner.mesh_viewer.load_mesh(path)
    except (OSError, ValueError, RuntimeError) as exc:
        owner.mesh_viewer.hide()
        owner.mesh_viz_label.setText(f"STL preview unavailable:\n{exc}")
        owner.mesh_viz_label.show()
        owner.logger.log_message("ERROR", f"Failed to visualize STL mesh:\n{exc}")
        return
    owner._last_mesh_preview_path = path

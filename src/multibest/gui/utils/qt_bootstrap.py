# SPDX-FileCopyrightText: 2026 bright-ideas-clan
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Process-wide Qt platform setup helpers.

These helpers must run BEFORE ``QApplication`` is constructed — Qt only reads
``QT_QPA_PLATFORM`` when it picks its platform plugin during ``QApplication``
construction.
"""

from __future__ import annotations

import os
import sys


def force_x11_if_wayland() -> None:
    """Prefer the stable XCB backend for frozen Qt apps on Wayland sessions.

    OVITO's embedded Qt viewport can crash under the Wayland backend in frozen
    builds. Development runs keep the native Wayland backend with XCB fallback,
    while PyInstaller bundles use XCB directly when an X display is available.
    """
    if os.environ.get("XDG_SESSION_TYPE") != "wayland":
        return
    if "QT_QPA_PLATFORM" in os.environ:
        return
    if getattr(sys, "frozen", False) and os.environ.get("DISPLAY"):
        os.environ["QT_QPA_PLATFORM"] = "xcb"
        return
    os.environ["QT_QPA_PLATFORM"] = "wayland;xcb"

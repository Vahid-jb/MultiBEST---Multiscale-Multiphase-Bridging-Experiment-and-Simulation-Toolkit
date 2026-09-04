# SPDX-FileCopyrightText: 2026 bright-ideas-clan
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Configure Qt platform variables before GUI libraries are imported."""

from __future__ import annotations

import os
import subprocess
import sys

from multibest.gui.utils.qt_bootstrap import force_x11_if_wayland


def _inherit_xcursor_settings_for_xcb() -> None:
    """Propagate cursor settings so the XCB backend uses the correct system cursor.

    When the frozen binary forces XCB (via XWayland) on a Wayland session the
    cursor-rendering library (libXcursor) reads ``XCURSOR_SIZE``,
    ``XCURSOR_THEME``, and ``XCURSOR_PATH`` from the environment.  If those
    variables are absent it falls back to tiny default cursors (typically 16 px)
    even though the system has large HiDPI cursors configured.

    Three things are needed:
    1. ``XCURSOR_PATH`` — ensures the bundled libXcursor can find cursor themes
       installed in the system icon directories rather than only looking inside
       the frozen bundle.
    2. ``XCURSOR_THEME`` — the cursor theme name (e.g. ``Adwaita``), sourced
       from xrdb or left unset so libXcursor uses its own default.
    3. ``XCURSOR_SIZE`` — cursor size in physical pixels (e.g. ``48`` for a
       24-pt cursor on a 2× HiDPI display), sourced from xrdb.

    All settings are only applied when they are not already present in the
    environment so a caller can always override them.
    """
    if not getattr(sys, "frozen", False):
        return
    if sys.platform.startswith("win") or sys.platform == "darwin":
        return
    # Only matters when we are about to force the XCB backend.
    if os.environ.get("XDG_SESSION_TYPE") != "wayland":
        return

    # 1. Ensure libXcursor can find system cursor themes.
    if not os.environ.get("XCURSOR_PATH"):
        xcursor_paths = [
            os.path.expanduser("~/.local/share/icons"),
            os.path.expanduser("~/.icons"),
            "/usr/share/icons",
            "/usr/share/pixmaps",
        ]
        existing_paths = [p for p in xcursor_paths if os.path.isdir(p)]
        if existing_paths:
            os.environ["XCURSOR_PATH"] = ":".join(existing_paths)

    # 2 & 3. Read XCURSOR_THEME and XCURSOR_SIZE from xrdb when not already set.
    if not os.environ.get("XCURSOR_SIZE") or not os.environ.get("XCURSOR_THEME"):
        try:
            result = subprocess.run(
                ["xrdb", "-query"],
                capture_output=True,
                text=True,
                check=False,
                timeout=2,
            )
            for line in result.stdout.splitlines():
                if ":" not in line:
                    continue
                key, _, value = line.partition(":")
                key = key.strip()
                value = value.strip()
                if key == "Xcursor.size" and not os.environ.get("XCURSOR_SIZE"):
                    if value.isdigit():
                        os.environ["XCURSOR_SIZE"] = value
                elif key == "Xcursor.theme" and not os.environ.get("XCURSOR_THEME"):
                    if value:
                        os.environ["XCURSOR_THEME"] = value
        except Exception:
            # Cursor metadata is optional; missing xrdb or malformed output should
            # not prevent the GUI from starting.
            pass

    # Fallback: if xrdb provided nothing, try gsettings (common on GNOME/KDE).
    if not os.environ.get("XCURSOR_SIZE"):
        try:
            result = subprocess.run(
                ["gsettings", "get", "org.gnome.desktop.interface", "cursor-size"],
                capture_output=True,
                text=True,
                check=False,
                timeout=2,
            )
            size_str = result.stdout.strip()
            if size_str.isdigit():
                os.environ["XCURSOR_SIZE"] = size_str
        except Exception:
            # gsettings is only a best-effort fallback for cursor size.
            pass

    if not os.environ.get("XCURSOR_THEME"):
        try:
            result = subprocess.run(
                ["gsettings", "get", "org.gnome.desktop.interface", "cursor-theme"],
                capture_output=True,
                text=True,
                check=False,
                timeout=2,
            )
            theme = result.stdout.strip().strip("'\"")
            if theme:
                os.environ["XCURSOR_THEME"] = theme
        except Exception:
            # gsettings is only a best-effort fallback for cursor theme.
            pass


_inherit_xcursor_settings_for_xcb()
force_x11_if_wayland()

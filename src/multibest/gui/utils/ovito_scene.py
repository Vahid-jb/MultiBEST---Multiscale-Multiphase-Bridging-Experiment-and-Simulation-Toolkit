# SPDX-FileCopyrightText: 2026 bright-ideas-clan
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Helpers for managing OVITO's process-wide scene in GUI modules."""

from __future__ import annotations

from collections.abc import Callable

ATOM_STYLE_RETRY_MESSAGE = "OVITO did not accept the explicit LAMMPS atom style; retrying with auto-detection."


def clear_ovito_scene(log_error: Callable[[str], None] | None = None) -> int:
    """Remove all pipelines from OVITO's global scene.

    OVITO keeps scene pipelines process-wide. MultiBEST embeds several OVITO
    viewport widgets in different modules, so module-local pipeline cleanup is
    not enough when users switch between those modules.
    """
    try:
        from ovito import scene
    except Exception as exc:
        if log_error is not None:
            log_error(f"Could not access OVITO scene: {exc}")
        return 0

    removed = 0
    for pipeline in getattr(scene, "pipelines", ()):
        try:
            pipeline.remove_from_scene()
            removed += 1
        except Exception as exc:
            if log_error is not None:
                log_error(f"Could not remove OVITO pipeline from scene: {exc}")

    return removed


def import_atomistic_file(
    path: str,
    kwargs: dict[str, str],
    import_file_func: Callable[..., object],
    log_info: Callable[[str], None] | None = None,
) -> object:
    """Import an atomistic file, retrying LAMMPS data files with auto-detection if needed."""
    try:
        return import_file_func(path, **kwargs)
    except Exception as exc:
        if "atom_style" not in kwargs or "atom_style" not in str(exc):
            raise
        if log_info is not None:
            log_info(ATOM_STYLE_RETRY_MESSAGE)
        return import_file_func(path)

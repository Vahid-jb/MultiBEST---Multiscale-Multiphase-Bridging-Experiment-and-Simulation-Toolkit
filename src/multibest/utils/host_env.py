# SPDX-FileCopyrightText: 2026 bright-ideas-clan
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Hand host programs an environment that is not polluted by the bundle.

The PyInstaller bootloader prepends the bundle's ``_internal/`` directory to
``LD_LIBRARY_PATH`` (saving the user's value in ``LD_LIBRARY_PATH_ORIG``), and
``rthook_release_paths`` prepends the bundle directories to ``PATH``.  Both are
right for the helper executables MultiBEST ships, and wrong for programs that
belong to the user's desktop: they inherit the environment and load the
bundle's conda libraries instead of their own.

The failure this was written for is the ``Docs`` button.  ``webbrowser.open()``
spawns ``xdg-open``/``gio``, which then loads the bundled
``libgio-2.0.so.0``.  That library has the build container's prefix compiled in,
so it looks for its helper where the container kept it and the browser never
opens::

    gio: http://localhost:8000/index.html: Failed to execute child process
    "gio-launch-desktop" (No such file or directory)

Restoring the host environment for the duration of the launch fixes that, and
keeps the browser itself from running against the bundle's libraries.
"""

from __future__ import annotations

import os
import sys
import webbrowser
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path

# Variables the PyInstaller bootloader overwrites; it saves what the user had in
# ``<name>_ORIG``, or leaves that unset when the variable was not set at all.
BOOTLOADER_VARS: tuple[str, ...] = ("LD_LIBRARY_PATH", "DYLD_LIBRARY_PATH", "DYLD_FRAMEWORK_PATH")

ORIG_SUFFIX = "_ORIG"

# ``PATH``-style variables that must not point into the bundle for host programs.
SEARCH_PATH_VARS: tuple[str, ...] = ("PATH", "PYTHONPATH", *BOOTLOADER_VARS)


def is_frozen() -> bool:
    """Return True while running inside a PyInstaller bundle."""
    return getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS")


def bundle_directories() -> tuple[Path, ...]:
    """Return the directories that make up the running bundle.

    Returns
    -------
    tuple of Path
        The data directory (``sys._MEIPASS``) and the directory holding the
        executable, resolved and de-duplicated.  Empty when not frozen.
    """
    if not is_frozen():
        return ()

    directories: list[Path] = []
    for candidate in (Path(getattr(sys, "_MEIPASS", "")), Path(sys.executable).parent):
        try:
            resolved = candidate.resolve()
        except OSError:
            continue
        if resolved not in directories:
            directories.append(resolved)
    return tuple(directories)


def _is_inside_bundle(entry: str, directories: tuple[Path, ...]) -> bool:
    if not entry:
        return False
    try:
        candidate = Path(entry).resolve()
    except OSError:
        return False
    return any(candidate == directory or directory in candidate.parents for directory in directories)


def _without_bundle_entries(value: str, directories: tuple[Path, ...]) -> str:
    kept = [entry for entry in value.split(os.pathsep) if entry and not _is_inside_bundle(entry, directories)]
    return os.pathsep.join(kept)


def host_environment(environ: Mapping[str, str] | None = None) -> dict[str, str]:
    """Return *environ* as the user's desktop had it before the bundle started.

    Parameters
    ----------
    environ
        Mapping to derive from; defaults to :data:`os.environ`.  It is never
        modified — the result is always a new dictionary.

    Returns
    -------
    dict
        A copy with the bootloader's library paths restored from their
        ``_ORIG`` backups and every bundle directory removed from the
        search-path variables.  Outside a bundle it is a plain copy.
    """
    env = dict(os.environ if environ is None else environ)

    directories = bundle_directories()
    if not directories:
        return env

    for name in BOOTLOADER_VARS:
        original = env.pop(f"{name}{ORIG_SUFFIX}", None)
        if original is not None:
            env[name] = original

    for name in SEARCH_PATH_VARS:
        value = env.get(name)
        if value is None:
            continue
        cleaned = _without_bundle_entries(value, directories)
        if cleaned:
            env[name] = cleaned
        else:
            # Nothing outside the bundle was left; an empty value would still be
            # honoured by the child, so drop the variable instead.
            del env[name]

    return env


@contextmanager
def host_environment_applied() -> Iterator[None]:
    """Put :func:`host_environment` into :data:`os.environ` for the block.

    Child processes started inside the block inherit the host environment.  The
    previous environment is restored on the way out, including after an error.
    Outside a bundle the environment is left untouched.
    """
    if not is_frozen():
        yield
        return

    previous = dict(os.environ)
    os.environ.clear()
    os.environ.update(host_environment(previous))
    try:
        yield
    finally:
        os.environ.clear()
        os.environ.update(previous)


def open_url(url: str) -> bool:
    """Open *url* in the user's browser, launched with the host environment.

    Parameters
    ----------
    url
        The address to open.

    Returns
    -------
    bool
        True when a browser could be launched, as reported by
        :func:`webbrowser.open`.
    """
    with host_environment_applied():
        return webbrowser.open(url)

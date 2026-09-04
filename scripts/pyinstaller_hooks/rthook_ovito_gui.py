# SPDX-FileCopyrightText: 2026 bright-ideas-clan
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Initialize OVITO GUI helper functions in frozen applications."""

import importlib
import importlib.machinery
import sys
import types
from pathlib import Path

import ovito  # noqa: F401


def _ensure_linux_conda_ovito_plugins_package() -> None:
    """Expose bundled conda OVITO plugins before extension modules import them."""
    if not (getattr(sys, "frozen", False) and sys.platform.startswith("linux")):
        return

    meipass = getattr(sys, "_MEIPASS", None)
    if not meipass:
        return

    plugin_dir = Path(meipass) / "ovito" / "plugins"
    if not plugin_dir.is_dir():
        return

    package = sys.modules.get("ovito.plugins")
    if package is None:
        package = types.ModuleType("ovito.plugins")
        package.__file__ = str(plugin_dir / "__init__.py")
        package.__package__ = "ovito.plugins"
        package.__path__ = [str(plugin_dir)]
        package.__spec__ = importlib.machinery.ModuleSpec("ovito.plugins", loader=None, is_package=True)
        package.__spec__.submodule_search_locations = package.__path__
        sys.modules["ovito.plugins"] = package
        setattr(ovito, "plugins", package)
        return

    package_path = getattr(package, "__path__", None)
    if package_path is not None and str(plugin_dir) not in package_path:
        package_path.append(str(plugin_dir))


_ensure_linux_conda_ovito_plugins_package()

for module_name in (
    "ovito.plugins.ovito_bindings",
    "ovito._extensions.particles",
    "ovito._extensions.pyscript",
    "ovito.gui._create_qwidget",
    "ovito.gui._create_window",
    "ovito.gui._utility_interface",
    "ovito.nonpublic._lammps_data_io",
):
    importlib.import_module(module_name)

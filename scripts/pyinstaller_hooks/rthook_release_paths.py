# SPDX-FileCopyrightText: 2026 bright-ideas-clan
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Runtime environment fixes for bundled helper executables."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from multibest.utils.certificates import configure_ssl_cert_env


def _prepend_path(path: Path) -> None:
    if path.is_dir():
        os.environ["PATH"] = f"{path}{os.pathsep}{os.environ.get('PATH', '')}"


def _prepend_xtb_path(path: Path) -> None:
    if path.is_dir():
        os.environ["XTBPATH"] = f"{path}{os.pathsep}{os.environ.get('XTBPATH', '')}"


bundle_internal = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
bundle_root = Path(sys.executable).parent

for candidate in (bundle_internal, bundle_internal / "bin", bundle_root, bundle_root / "bin"):
    _prepend_path(candidate)

for candidate in (bundle_internal / "share" / "xtb", bundle_root / "share" / "xtb"):
    _prepend_xtb_path(candidate)

# The bundled conda OpenSSL looks for its CA store under the build environment's
# prefix, which does not exist on a user's machine, so every HTTPS request fails
# with CERTIFICATE_VERIFY_FAILED until SSL_CERT_FILE points somewhere real.
configure_ssl_cert_env()

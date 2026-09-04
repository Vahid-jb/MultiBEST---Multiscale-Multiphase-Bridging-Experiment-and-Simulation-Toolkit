# SPDX-FileCopyrightText: 2026 bright-ideas-clan
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Point the bundled OpenSSL at a CA store that exists on the user's machine.

The release bundle ships conda's OpenSSL, and conda compiles ``OPENSSLDIR`` to
the path of the environment it was built in — ``/opt/conda/envs/<name>/ssl``.
That directory exists only inside the build container, so on a user's machine
OpenSSL has no CA store at all and every HTTPS request from the frozen
application fails with::

    [SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed:
    unable to get local issuer certificate

That breaks the DREAM3D-NX environment installer (which fetches micromamba) and
the Blender downloader, both of which use :mod:`urllib.request`.

The system store is preferred over the bundled :mod:`certifi` one so that
machines with custom or corporate CAs keep working; certifi is the fallback for
distributions that keep their store somewhere unusual.
"""

from __future__ import annotations

import os
from collections.abc import MutableMapping
from pathlib import Path

# Single-file CA bundles, in the order distributions are most likely to use.
CA_BUNDLE_CANDIDATES: tuple[str, ...] = (
    "/etc/ssl/certs/ca-certificates.crt",  # Debian, Ubuntu, Arch, Alpine
    "/etc/pki/tls/certs/ca-bundle.crt",  # Fedora, RHEL, CentOS
    "/etc/ssl/ca-bundle.pem",  # openSUSE
    "/etc/pki/tls/cacert.pem",  # older RHEL
    "/etc/ssl/cert.pem",  # BSD, macOS, Alpine
)

# Hashed CA directories, used by OpenSSL alongside the single-file bundle.
CA_DIRECTORY_CANDIDATES: tuple[str, ...] = (
    "/etc/ssl/certs",
    "/etc/pki/tls/certs",
)


def system_ca_bundle() -> Path | None:
    """Return the first CA bundle the host provides, if any."""
    for candidate in CA_BUNDLE_CANDIDATES:
        path = Path(candidate)
        if path.is_file():
            return path
    return None


def system_ca_directory() -> Path | None:
    """Return the first hashed CA directory the host provides, if any."""
    for candidate in CA_DIRECTORY_CANDIDATES:
        path = Path(candidate)
        if path.is_dir():
            return path
    return None


def bundled_ca_bundle() -> Path | None:
    """Return the ``certifi`` CA bundle shipped inside the application."""
    try:
        import certifi
    except ImportError:
        return None

    path = Path(certifi.where())
    return path if path.is_file() else None


def configure_ssl_cert_env(environ: MutableMapping[str, str] | None = None) -> Path | None:
    """Export ``SSL_CERT_FILE`` (and friends) so certificate verification works.

    Parameters
    ----------
    environ
        Mapping to update; defaults to :data:`os.environ`.

    Returns
    -------
    Path or None
        The CA bundle in effect, or ``None`` when no store could be found.
        A pre-existing ``SSL_CERT_FILE`` is always left untouched so a user or
        site override wins.
    """
    env = os.environ if environ is None else environ

    existing = env.get("SSL_CERT_FILE")
    if existing:
        return Path(existing)

    bundle = system_ca_bundle() or bundled_ca_bundle()
    if bundle is None:
        return None

    env["SSL_CERT_FILE"] = str(bundle)
    env.setdefault("REQUESTS_CA_BUNDLE", str(bundle))

    directory = system_ca_directory()
    if directory is not None:
        env.setdefault("SSL_CERT_DIR", str(directory))

    return bundle

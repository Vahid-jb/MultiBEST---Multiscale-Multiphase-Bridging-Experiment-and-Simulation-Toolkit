# SPDX-FileCopyrightText: 2026 bright-ideas-clan
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
PyInstaller hook for torch_geometric.

torch_geometric uses torch.jit.script() in several of its scatter/gather
utility functions.  sevenn relies on these at model-load time, so the source
.py files must be present on disk alongside the PYZ archive entries.
"""

module_collection_mode = "pyz+py"

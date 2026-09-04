# Third-Party Notices

MultiBEST is licensed under **GPL-3.0-or-later** (see [`LICENSE`](LICENSE)).

The distributed application **binaries** (the PyInstaller bundle published as
release assets) embed third-party components that remain under **their own
licenses**. Those licenses and their attribution/notice requirements are listed
below. This file is shipped inside the binary bundle to satisfy those
obligations. Full license texts for each component are available from the
component's own project (linked below) and, where present, in the corresponding
package directory inside the bundle.

> This is an engineering-maintained notice, not formal legal advice.

## Bundled components

| Component | License | Notes |
|-----------|---------|-------|
| PyInstaller bootloader | GPL-2.0 **with bootloader exception** | Exception permits distributing the frozen app under any license. |
| OVITO (PyPI `ovito`) | MIT | The MIT PyPI module — **not** the proprietary `conda.ovito.org` OVITO Pro build. Bundles `libcudart.so.12` (see the CUDA / NVIDIA note). |
| PySide6 (Qt for Python) | LGPL-3.0 | Dynamically linked. |
| xtb / xtb-python | LGPL-3.0-or-later | Includes GFN parameter data files. |
| VTK | BSD-3-Clause | |
| gmsh | GPL-2.0-or-later | |
| pymeshlab / MeshLab | GPL-3.0 | |
| Open3D | MIT | Bundles the Roboto font (Apache-2.0). |
| qtawesome | MIT | Bundles Font Awesome Free — icons CC-BY-4.0, fonts SIL OFL-1.1. |
| oneTBB | Apache-2.0 | See Apache-2.0 NOTICE requirements. |
| PyTorch (if present, via SevenNet) | BSD-3-Clause | CPU build only; see CUDA note below. |
| ASE (Atomic Simulation Environment) | LGPL-2.1-or-later | Dynamically linked as a Python dependency. |
| pymeshfix | AGPL-3.0 | Wraps MeshFix (IMATI-GE/CNR), dual-licensed GPL-3.0-or-later/commercial. Taken under the GPL path here; combines with GPL-3.0-or-later per GPLv3 §13. |
| NumPy, SciPy, Matplotlib, Pillow, pandas, h5py, trimesh, rtree, periodictable, scikit-image, opencv-python-headless, and other Python dependencies | BSD-3-Clause / MIT / PSF / HPND (permissive) | Reproduced under their permissive terms. |

## Blender (bundled executable)

The bundle includes an unmodified **Blender** executable (downloaded from
blender.org), used as a **separate program** invoked via subprocess. This is a
*mere aggregation* under the GPL and does not affect MultiBEST's own licensing.

Blender is licensed **GPL-2.0-or-later** (some components GPL-3.0). In accordance
with the GPL, the **complete corresponding source code** for the bundled Blender
version is available from the Blender Foundation:

- Binaries: <https://download.blender.org/release/Blender5.1/>
- Source:   <https://download.blender.org/source/> and
  <https://projects.blender.org/blender/blender>

A copy of the GNU General Public License is provided with this distribution and
at <https://www.gnu.org/licenses/>.

## Font attributions

- **Font Awesome Free** (via qtawesome): icons under CC-BY-4.0, fonts under SIL
  OFL-1.1. <https://fontawesome.com/license/free>
- **Roboto** (via Open3D): Apache-2.0.
  <https://github.com/googlefonts/roboto>

## CUDA / NVIDIA note

The redistributable bundle ships **CPU-only** PyTorch. NVIDIA CUDA libraries
(`libcudnn*`, `libcublas*`, `nvidia-*` wheels) carry the proprietary NVIDIA
Software License and are **not** included, with one disclosed exception:

- **`libcudart.so.12` (NVIDIA CUDA Runtime)** is redistributed, at
  `_internal/ovito/plugins/libcudart.so.12` (and a symlink to it at
  `_internal/`). It ships inside the MIT-licensed OVITO PyPI wheel and is a
  hard `NEEDED` dependency of `ovito_bindings.so` — it is not `dlopen`'d, so it
  cannot be removed without removing OVITO. NVIDIA's CUDA EULA permits
  redistributing the CUDA runtime as part of an application. The license gate
  (`scripts/check_licenses.py`) exempts this one path and continues to fail on
  every other CUDA library anywhere in the bundle.

## Components intentionally excluded from the redistributable binary

The following are **not** redistributable under GPL-3.0-or-later and must not be
bundled in published release binaries:

- **Intel MKL** (`libmkl_*`, `libiomp5`) — Intel Simplified Software License
  (non-free). MultiBEST uses an open BLAS/LAPACK (OpenBLAS) instead.
- **DREAM.3D-NX / simplnx** (`dream3dnx` / `DREAM3DNX` / `nxrunner` / `libNX*` /
  `libsimplnx*` / `*.simplnx` / `libEbsdLib*`) — the conda binaries from the
  `bluequartzsoftware` channel carry a proprietary EULA, and the simplnx
  sources are dual-licensed AGPL-3.0/commercial. See the next section for how
  the EBSD workflow uses DREAM3D-NX without bundling it.

## DREAM3D-NX (external, user-installed environment)

The EBSD preparation step requires the `simplnx` and `orientationanalysis`
Python modules from **DREAM3D-NX** (BlueQuartz Software). These are **never
bundled**. Instead, MultiBEST runs the EBSD scripts as a **separate process**
in an external Python environment on the user's machine — either one the user
already has, or a managed environment that MultiBEST can create **at the
user's explicit request**: it downloads **micromamba** (BSD-3-Clause,
<https://github.com/mamba-org/mamba>) and installs the free `dream3dnx`
package directly from BlueQuartz Software's own conda channel into the user's
MultiBEST data directory. DREAM3D-NX remains governed by BlueQuartz Software's
own license terms; it is obtained by the user from BlueQuartz and is not part
of, nor redistributed with, MultiBEST. Running it as a separate program is
*mere aggregation* under the GPL.

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
| OVITO (PyPI `ovito`) | MIT | The MIT PyPI module — **not** the proprietary `conda.ovito.org` OVITO Pro build. |
| PySide6 (Qt for Python) | LGPL-3.0 | Dynamically linked. |
| xtb / xtb-python | LGPL-3.0-or-later | Includes GFN parameter data files. |
| VTK | BSD-3-Clause | |
| gmsh | GPL-2.0-or-later | |
| pymeshlab / MeshLab | GPL-3.0 | |
| Open3D | MIT | Bundles the Roboto font (Apache-2.0). |
| qtawesome | MIT | Bundles Font Awesome Free — icons CC-BY-4.0, fonts SIL OFL-1.1. |
| oneTBB | Apache-2.0 | See Apache-2.0 NOTICE requirements. |
| PyTorch (if present, via SevenNet) | BSD-3-Clause | CPU build only; see CUDA note below. |
| NumPy, SciPy, Matplotlib, Pillow, ASE, pandas, h5py, trimesh, rtree, periodictable, pymeshfix, scikit-image, opencv-python-headless, and other Python dependencies | BSD-3-Clause / MIT / PSF / HPND (permissive) | Reproduced under their permissive terms. |

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

The redistributable bundle must ship **CPU-only** PyTorch. NVIDIA CUDA runtime
libraries (`libcudnn*`, `libcu*`, `nvidia-*` wheels) carry the proprietary NVIDIA
Software License and are **not** included in / redistributed with this binary.

## Components intentionally excluded from the redistributable binary

The following are **not** redistributable under GPL-3.0-or-later and must not be
bundled in published release binaries:

- **Intel MKL** (`libmkl_*`, `libiomp5`) — Intel Simplified Software License
  (non-free). MultiBEST uses an open BLAS/LAPACK (OpenBLAS) instead.
- **DREAM.3D-NX** proprietary binaries (`dream3dnx` / `DREAM3DNX` / `nxrunner` /
  `libNX*`) from the `bluequartzsoftware` channel — proprietary EULA.

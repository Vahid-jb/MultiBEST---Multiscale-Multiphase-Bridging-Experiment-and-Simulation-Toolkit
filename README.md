<p align="center">
  <img src="docs/assets/multibest-banner.png" alt="MultiBEST" width="100%">
</p>

# MultiBEST – Multiscale/Multiphase Bridging Experiment and Simulation Toolkit

[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)

MultiBEST is a GUI-based, end-to-end framework for constructing
experiment-identical microstructures for atomistic, continuum, and multiscale
simulations. Instead of relying on idealized or implicit microstructures,
MultiBEST starts directly from experimental or user-defined inputs and preserves
microstructural detail across all modelling stages:

- 2D micrographs (optical/SEM)
- 2D / 3D EBSD datasets
- Simple user sketches of microstructures

From these inputs, MultiBEST builds:

- Atomistic models with grain-resolved crystallography and phase identity
- Continuum meshes in which grain boundaries are explicit volumetric interphases
  with their own material properties (diffusivity, elasticity, transport tensors,
  etc.), not just invisible voxel transitions or weightless surfaces

Moreover, users can provide the morphology of a microstructure or object as a
mesh and construct an atomistic model with desired atomic compositions and
crystallographic orientations.

<p align="center">
  <img src="docs/assets/multibest-overview.png" alt="MultiBEST workflow overview" width="100%">
</p>

## Modules

Each module runs independently from the command line or through the central GUI.
Per-module guides live under [docs/modules](docs/modules/index.md).

| Module | Purpose |
|--------|---------|
| **Image Processing** | Edit, threshold, and annotate experimental images; analyse binary section areas; generate area-preserving random binary replicas. |
| **Image to Mesh** | Convert binary microstructure images into 3D phase-region meshes. |
| **Mesh Modification** | Refine, smooth, clean, repair, and transform mesh files. |
| **Mesh to Atomistic** | Fill mesh volumes with atomistic structures, merge phases, export simulation-ready files. |
| **Relaxation** | Relax atomistic structures with GFN2-xTB or SevenNet workflows. |
| **EBSD to Atomistic / Mesh** | Process EBSD data into grain-resolved meshes and fill grains with oriented atoms. |
| **Atomistic to Continuum** | Identify grains/phases in atomistic microstructures and build continuum meshes. |
| **Input Convertor** | Convert atomistic structures between formats; generate LAMMPS data/dump files. |

## Getting Started

Pre-built application binaries will be published on the
[Releases](../../releases) page. Download the archive for your platform, extract
it, and launch the `MultiBEST` executable. Each computational module can also be
run standalone from a terminal with an input file.

To run from source (Python 3.12+):

```sh
pip install .
python -m multibest.gui.main_ui
```

Several modules rely on external scientific packages (OVITO, DREAM.3D-NX, xTB,
Blender); a conda-based environment is the simplest way to provide them.

## Documentation

Open the in-app help (the **?** button in any module) for the bundled module
guides, or browse [docs/modules](docs/modules/index.md).

## Example data

The [`examples/`](examples/) directory contains sample inputs for the modules.
See [`examples/DATA_SOURCES.md`](examples/DATA_SOURCES.md) for provenance and
licensing.

## License

MultiBEST is free software, licensed under the **GNU General Public License
v3.0 or later (GPL-3.0-or-later)** — see [`LICENSE`](LICENSE). Bundled
third-party components retain their own licenses; see
[`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md).

Copyright © 2026 bright-ideas-clan

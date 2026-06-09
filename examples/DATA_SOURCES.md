# Example Data Sources & Attribution

The example **datasets** in this directory are sample inputs for the MultiBEST
modules. Unlike the source code (which is GPL-3.0-or-later), these data files
retain the licenses and attribution of their original sources, listed below.

Large binary assets (`*.stl`, `*.lmp`, `*.jpg`) are stored via
[Git LFS](https://git-lfs.com/). After cloning, run `git lfs pull` to fetch
them (or `git lfs install` once, then a normal `git pull`).

## Mesh-to-Atomistic (`mesh_to_atomistic/`)

| File | Source | License |
|------|--------|---------|
| `Cr2O3_mp-776873_computed.cif` | [Materials Project](https://materialsproject.org/) entry `mp-776873`, exported via pymatgen | CC-BY-4.0 |
| `TiN_mp-998908_primitive.cif` | [Materials Project](https://materialsproject.org/) entry `mp-998908`, exported via pymatgen | CC-BY-4.0 |
| `scaled_Base.stl`, `scaled_Bulk.stl`, `scaled_Guest.stl` | Example surface meshes (Git LFS) | See repository owner |

> **Materials Project attribution:** A. Jain *et al.*, "Commentary: The
> Materials Project: A materials genome approach to accelerating materials
> innovation," *APL Materials* **1**, 011002 (2013).
> Materials Project data is licensed under
> [CC-BY-4.0](https://creativecommons.org/licenses/by/4.0/).

## Atomistic-to-Continuum (`atomistic_to_continuum/`)

| File | Source | License |
|------|--------|---------|
| `FeCr.lmp` | Example Fe–Cr LAMMPS data file (Git LFS) | See repository owner |

## EBSD (`ebsd/`)

| File | Source | License |
|------|--------|---------|
| `EBSD-source.txt` | Pointer to the **SmallIN100** EBSD dataset distributed by [DREAM.3D](https://dream3d.bluequartz.net/Help/2_Tutorials/EBSDReconstruction/) | See DREAM.3D / BlueQuartz |

The raw SmallIN100 EBSD files are **not** bundled here (large, externally
hosted). Download them from the DREAM.3D tutorial link in `EBSD-source.txt`.

## Image Processing (`image_processing/`)

| File | Source | License |
|------|--------|---------|
| `test.jpg`, `ech_robinet_2_brut_008_scale.jpg` | Example micrographs (Git LFS) | See repository owner |

## Provenance

These example datasets were imported from
[Vahid-jb/MultiBEST](https://github.com/Vahid-jb/MultiBEST---Multiscale-Multiphase-Bridging-Experiment-and-Simulation-Toolkit)
(MIT-licensed). The Materials Project CIF files retain CC-BY-4.0 as noted above.

If you are the author of any asset marked "See repository owner" and wish to add
a specific license or attribution, please open an issue or PR.

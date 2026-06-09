# Atomistic to Continuum

## Overview
The **Atomistic to Continuum** module is a specialized package designed to bridge the gap between atomistic simulations and continuum mechanics in multiscale modeling. It takes an atomistic model and converts it into a continuum model in such a way that extended defects (such as grain boundaries) are treated as distinct regions.

This approach enables users to specify distinct physical characteristics—such as **Diffusion Coefficient**, **Young's Modulus**, **Poisson Ratio**, etc.—explicitly for different microstructural features. By considering the morphology of defects while preserving atomistic details, this module makes physically realistic and accurate multiscale modeling possible.

Key capabilities include:
1.  **Morphological Description:** Provides a detailed morphological description of extended defects, including grain boundaries, preserving atomistic details.
2.  **Grain Boundary Handling:** Considers parts of grain boundaries that follow the crystallography of adjacent grains as part of those grains, based on adjustable criteria (`RMSD`, `Grain Size`).
3.  **Amorphous/Disordered Regions:** Identifies remaining atoms that deviate considerably from adjacent grains and lack long-range order as generally **amorphous**. These regions are treated as a distinct material phase.
4.  **Distinct Mesh Generation:** Generates separate meshes for crystalline grains and amorphous/boundary regions.

This methodology enables a feasible, adaptive, and dynamical description of grain boundaries. Specifically, as the system evolves under external parameters—resulting in grain boundary migration, extension, and annihilation—the atomic arrangement shifts accordingly. This evolution is precisely tracked by the generated mesh at each stage, ensuring the resulting morphological description is a direct consequence of the underlying atomic arrangement.

---

## Workflow
The workflow consists of two main steps, executed sequentially:

### Step 1: Microstructure Analysis

**Input:** Atomistic structure file (e.g., `.lmp`, `.xyz`)

This step analyzes the atomistic structure to identify and segment crystalline grains and disordered regions.
1.  **[Polyhedral Template Matching (PTM)](https://iopscience.iop.org/article/10.1088/0965-0393/24/5/055007):** Identifies the local crystalline structure (FCC, BCC, HCP, etc.) of every atom.
2.  **[Graph clustering algorithm](https://arxiv.org/abs/1806.01664):** Clusters atoms with the same crystal structure and orientation into distinct grains.
3.  **Phase Separation:**
    -   **Grains:** Atoms belonging to identified crystalline grains.
    -   **Non-Grains (Amorphous):** Atoms at grain boundaries or defects that do not match the crystal template or are too small to form a grain ("orphan atoms").
4.  **Export:** Saves separate XYZ files for each phase (e.g., `parent_phase_bcc.xyz`, `parent_phase_other.xyz`) for meshing.

### Step 2: Mesh Generation
**Input:** Output XYZ files from Step 1

This step generates continuum surface meshes from the segmented atomistic data.
1.  **Combination:** Reads the grain and non-grain XYZ files specified in the config.
2.  **Surface Reconstruction:** Uses one of two methods to wrap a surface mesh around the atoms:
    -   **[Alpha Shape](https://link.springer.com/article/10.1007/s11837-013-0827-5):** Best for capturing precise, sharp geometric details of the atomistic cloud.
    -   **[Gaussian Density](https://diglib.eg.org/items/d34c2b92-60b4-489b-8801-9b8cad2d8ba2):** Best for creating smooth, watertight isosurfaces suitable for FEM.
3.  **Output:** Produces VTK and STL files for:
    -   **Grains Mesh:** The crystalline regions.
    -   **Non-Grains Mesh:** The amorphous/boundary regions.
    -   **Microstructure Mesh:** The combined system.

These meshes serve as the geometric domain for finite element modeling where distinct properties can be assigned to the "Grain" and "Non-Grain" definitions.

---

## Detailed Parameter Guide

### 1. Micro Analysis Configuration

| Parameter | Default | Description |
| :--- | :--- | :--- |
| `input file` | *(Required)* | Path to the input atomistic structure (Lammps dump, XYZ, etc.). |
| `rmsd cutoff` | `0.1` | **Root Mean Square Deviation.** Controls the strictness of crystal structure identification. Lower values (`<0.1`) are stricter; higher values (`>0.15`) are more tolerant of thermal noise or distortion at boundaries. |
| `min grain size` | `100` | **Minimum Grain Size.** Grains with fewer atoms than this threshold are considered "orphan" or amorphous atoms and grouped into the non-grain phase. |

### 2. Mesh Generation Configuration

#### General Settings
| Parameter | Default | Description |
| :--- | :--- | :--- |
| `method` | `alpha_shape` | **Meshing Algorithm.** `alpha_shape` (geometric) or `gaussian` (density-based). |
| `input file grains_X` | *(Required)* | Path to grain XYZ file(s) from Step 1. Can specify multiple. |
| `input file nongrains_X`| *(Required)* | Path to non-grain XYZ file(s) from Step 1. |
| `rep_x`, `rep_y`, `rep_z`| `1` | **Replication.** Replicates the domain in X/Y/Z directions before meshing to create a larger representative volume element. |

#### Alpha Shape Parameters (Structure-Preserving)
| Parameter | Default | Description |
| :--- | :--- | :--- |
| `radius` | `2.5` | **Probe Radius.** Determines the level of detail. Smaller radius = tighter fit to atoms; Larger radius = smoother, more convex shape. If too small, holes appear. |
| `smoothing level` | `1` | **Mesh Smoothing.** Iterations of Laplacian smoothing applied to the final mesh. |

#### Gaussian Density Parameters (Smooth/Watertight)
| Parameter | Default | Description |
| :--- | :--- | :--- |
| `grid resolution` | `200` | **Voxel Grid Size.** Higher values (e.g., 600) give finer mesh resolution but increase memory usage. |
| `radius scaling` | `100` | **Atom Radius %**. Percentage of atomic radius to use for density calculation. |
| `isolevel` | `0.6` | **Density Threshold.** Cutoff value for the isosurface. Lower values make the mesh "fatter"; higher values make it "thinner". |

---

## Note
The input atomistic file must include the lattice dimensions.<br>
The quality of the final mesh is a direct consequence of the input atomistic configuration and the parameters defined by the user. To ensure a watertight and intact mesh, these parameters must be carefully adjusted. For further post-processing, users can utilize the 'Mesh Modification' module. In cases where the resulting meshes are overly defective, one can isolate the defects or crystalline domains and subtract them from a reference volume to achieve a watertight result.<br>

The following libraries and specific modules are leveraged in this package:<br>
-   [**ASE (Atomic Simulation Environment):**](https://ase-lib.org/) Used for file I/O.
-   [**NumPy:**](https://numpy.org/) Core numerical operations.
-   [**Gmsh:**](https://gmsh.info/) Used for post-processing and STL conversion.

---

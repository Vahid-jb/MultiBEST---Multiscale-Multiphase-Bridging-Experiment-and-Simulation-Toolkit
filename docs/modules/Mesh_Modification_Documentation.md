# Mesh Modification

## Overview
The **Mesh Modification** module is a robust toolkit designed for the post-processing of 3D meshes. It provides a comprehensive pipeline for **refinement**, **smoothing**, and **repair**, ensuring that the final meshes are watertight, manifold, and suitable for high-fidelity simulations.

The module orchestrates two key processes:
1.  **Iterative Voxel Refinement:** Increases mesh resolution and uniformity using a voxel-based approach.
2.  **Iterative Cleaning & Smoothing:** Repairs topological errors (holes, non-manifold edges) and applies advanced smoothing algorithms.

## Workflow

The processing pipeline follows this logical flow:

1.  **Input:** A raw 3D mesh (STL, OBJ, etc.).
2.  **Refinement (Optional):** If requested, the mesh undergoes voxel remeshing to standardize the topology and increase resolution.
3.  **Repair & Smoothing Loop:** The mesh enters a quality assurance loop:
    -   **Smooth:** Apply selected smoothing algorithm.
    -   **Repair:** Fix holes, degenerate faces, and non-manifold edges using PyMeshFix or Blender.
    -   **Check:** Analyze mesh quality. If strict criteria are met, the loop finishes early.
4.  **Output:** A clean, optimized 3D mesh.

## Methodologies

### A. Mesh Refinement Methodology

-   **Method:** **Iterative Voxel Remeshing**
-   **Description:** This method converts the mesh into a volume (voxels) and reconstructs it. It is "dynamic" because it calculates a target voxel size based on a starting value and a step reduction factor (`start_voxel - step * level`). It is best for fixing extremely messy topology or ensuring uniform mesh density.

### B. Smoothing Methodologies


This module implements three distinct methodologies for dynamic iterative refinement and smoothing:

#### 1. Taubin (Default)

-   **Method:** **Volume-Preserving Smoothing (PyVista)**
-   **Description:** Uses the Taubin algorithm via the PyVista library. Taubin smoothing alternates between shrinking and expanding steps to filter out high-frequency noise without shrinking the object's overall volume. It is often mathematically analogous to iterative diffusion processes (like Runge-Kutta integration) for surface smoothing.

#### 2. PyMeshLab
-   **Method:** **Volume-Preserving Smoothing (PyMeshLab)**
-   **Description:** Uses the Taubin smoothing filter provided by the PyMeshLab library. This is an alternative implementation of the volume-preserving algorithm.

#### 3. Blender

-   **Method:** **Laplacian Smoothing (Blender)**
-   **Description:** Uses Blender's native `smooth_laplacian` operator. This method moves each vertex toward the average position of its neighbors. It is very effective for aggressive smoothing. This implementation enables the "Volume Preservation" flag in Blender to mitigate the shrinkage effect common with simple Laplacian smoothing.

## Parameters

| Argument | Description | Default |
| :--- | :--- | :--- |
| `refinement` | Integeger level of refinement. If `0`, refinement is skipped. Higher values = smaller voxels. | `0` |
| `start-voxel` | Starting voxel size for refinement calculation. | `0.8` |
| `step` | Step size reduction per refinement level. | `0.2` |
| `apply-refine` | Directly apply the remesh modifier before passing to the cleaning stage. | `False` |
| `iterations` | Maximum number of Repair-Smooth-Check loops. | `3` |
| `smoothing` | Number of smoothing iterations per loop. `0` disables smoothing. | `0` |
| `smoothing-method` | Algorithm to use: `taubin`, `pymeshlab`, `blender`, `open3d`. | `taubin` |
| `fill hole threshold` | Maximum size of holes (boundary edges) to fill automatically. | `120` |
| `output` | Path for the final processed mesh file. | - |

Every run writes these parameters to `input_mesh_modification.txt` in the output directory and the backend reads them from there, so a run can be repeated or edited outside the GUI with `Mesh_Modification.py --input-file input_mesh_modification.txt`.

---
## Notes
The following libraries and specific modules are leveraged in this package:<br>
[Blender Python API](https://docs.blender.org/api/current/index.html): Used for Voxel Refinement, Laplacian Smoothing.<br>
[PyVista](https://pyvista.org/): Used for efficient Taubin smoothing and mesh data structures.<br>
[Open3D](https://www.open3d.org/): Used for alternative Laplacian smoothing.<br>
[PyMeshLab](https://pymeshlab.readthedocs.io/en/latest/): Used for advanced filter applications (an interface to MeshLab). <br>
[PyMeshFix](https://pymeshfix.pyvista.org/): Used for robust hole filling and boundary repair.<br>
[Trimesh](https://trimesh.org/): Used as the core library for I/O, mesh analysis, and data handling. <br>
[NumPy](https://numpy.org/) & [SciPy](https://scipy.org/): Used for numerical operations and k-d tree spatial queries (for vertex duplication checks). <br>

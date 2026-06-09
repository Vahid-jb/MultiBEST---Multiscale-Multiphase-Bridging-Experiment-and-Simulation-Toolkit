# Mesh to Atomistic

## Overview
The **Mesh to Atomistic** module is a sophisticated toolchain designed to convert 3D mesh geometries (STL, OBJ, etc.) into atomistic structures. It allows users to "fill" complex 3D shapes with atoms arranged in specific structure (defined by CIF files or standard structures), supporting multi-phase systems with intricate internal boundaries.

This module is particularly powerful for generating:
-   **Nanoparticles and Nanostructures** with complex shapes.
-   **Multi-phase Composites** (e.g., a precipitate inside a matrix).
-   **Porous Materials** (by defining "void" phases).

## Workflow
The process is orchestrated by calling specialized sub-modules for specific tasks.

1.  **Voxelization & Initial Filling:**
    -   Reads the input mesh.
    -   Converts the mesh volume into a voxel grid ("voxelization").
    -   **Considers Orientation:** Applies user-defined crystallographic orientation (Euler angles) to the **unit cell/lattice** *before* filling.
    -   **Fills Interior:** Fills the interior volume with atoms generated from the *oriented* structure.
    -   Applies voxel-based filtering to shape the atomic block.

2.  **Phase Merging & Cleanup:**
    -   Handles the interaction between different "phases" (e.g., a guest particle inside a base matrix).
    -   **Hierarchical Processing:** Strictly follows the order **Base → Guest → Void**. This ensures proper nesting: Guests cut into the Base, and Voids cut into everything.
    -   **Guest Integration:** Generates a new, clean mesh from the Guest atoms to perform precise boolean cuts on the Base.
    -   Performs boolean-like operations to ensure atoms from different phases do not overlap unphysically.

3.  **Final Manipulation & Formatting:**
    -   Applies global geometric transformations (rotation, displacement) to the entire assembly.
    -   Sets Periodic Boundary Conditions (PBC).
    -   Formats the output for simulation software (specifically LAMMPS), adding necessary columns like Charge and Spin.

---

## Methodologies & Strategies

### 1. Atom Filling Strategy (Voxelization)

The core challenge is to determine which lattice points lie *inside* an arbitrary 3D mesh. This module uses a two-step approach:

#### A. Voxelization and Fallback Strategy
The continuous mesh surface is discretized into a boolean 3D grid (voxels). The system intelligently chooses the method:

1.  **Intelligent Selection:** The script first checks if the mesh is **watertight** (closed, no holes).
    -   If **Watertight:** It attempts to use the `trimesh` library's optimized voxelizer, which is significantly faster.
    -   If **Not Watertight** (or if `trimesh` fails): It automatically falls back to the **Triangle Voxelization** method.
2.  **Triangle Voxelization (Robust Fallback):** Iterates over every triangle in the mesh and marks the voxels it intersects. This method is extremely robust against geometric errors (like self-intersections) but is slower.
3.  **Force Triangle (`force-tri`):** User can manually override the intelligent check and force the robust Triangle method.

#### B. Interior Extraction
Once the surface is marked, the interior must be filled.
-   **Flood Fill (Default):** Starts from the outside and floods the "empty" space. Anything not reached is considered "interior". Requires a watertight (closed) surface.
-   **Parity (Scanline) Fill (Fallback):** If Flood Fill fails, the system switches to Parity Fill. This method casts rays through the grid and counts how many surface voxels the ray passes through. An **odd number** of intersections implies the ray has entered the shape, while an **even number** implies it has exited. This allows filling of shapes that might have small holes where flood fill would leak.

#### C. Supercell Tiling
The script applies crystallographic orientation to the unit cell *first*. Then, it builds a massive "Supercell" of these rotated atoms that encompasses the entire mesh bounding box (plus padding). Finally, it overlays the Voxel Mask on this Supercell and keeps only the atoms whose centers fall inside a "True" interior voxel.




### 2. Multi-Phase Merging Strategy (Boolean Logic)

When integrating a "Guest" phase into a "Base" phase, the system must resolve spatial overlaps to prevent unphysical atomic collisions. Two distinct strategies for this, which can be toggled via the `method` are provided:

#### A. Distance-Based Overlap Deletion (`merge_method overlap`)
This approach identifies atoms in the **Base** phase that are within a specific cutoff distance of any atom in the **Guest** phase and removes them.
-   **Mechanism:** Uses a neighbor search (KD-Tree) to find collisions based on atomic radii.
-   **Best for:** Sparse guest phases or simple interfaces where a geometric volume is hard to define.
-   **User Control:** The sensitivity is controlled by the `overlap_distance` parameter.

#### B. Mesh-Based Robust Deletion (`merge_method mesh` / Default)
This is the more advanced strategy that treats the Guest phase as a solid geometric entity.
1.  **Surface Reconstruction:** The script generates a surface mesh [(Alpha-Shape)](https://link.springer.com/article/10.1007/s11837-013-0827-5) around the Guest atoms to define their occupied volume.
2.  **Volumetric Deletion:** It uses the voxelization logic (described in Section 1) to identify the "Interior" of the Guest phase. Any Base atoms falling within this interior volume are deleted.
-   **Best for:** Complex geometries and ensuring a perfectly flush interface between phases.
-   **Advantage:** It prevents "jagged" interfaces often caused by distance-based deletion in mismatched lattices.

Based on The mesh-based startegy when adding a "Guest" phase (e.g., a sphere) into a "Base" phase (e.g., a cube), simply placing atoms would cause collisions. The module uses a hierarchy-based deletion strategy:

1.  **Base Layer:** The Base atoms serve as the initial canvas.
2.  **Guest Integration:**
    -   **Step 1 (Model Generation):** The script generates the atomistic model for the Guest phase.
    -   **Step 2 (Mesh Reconstruction):** It takes these Guest *atoms* and generate a *new*, clean isosurface mesh that tightly wraps these atoms. This is often more reliable and "physical" than the original input mesh file.
    -   **Step 3 (Deletion/Boolean Cut):** The script identifies all Base atoms that fall *inside* this *newly generated* Guest mesh and deletes them.
    -   **Step 4 (Insertion):** The Guest atoms are then inserted into the empty space created in the Base.
3.  **Void Processing:**
    -   For "Void" phases, the script simply defines a region (via a mesh) and deletes all atoms inside it, leaving empty space.

#### The "Shrink Distance" Parameter
A critical parameter for perfect interfaces is the `shrink_distance`.
-   **Positive Value (e.g., 0.5 Å):** The deletion zone is slightly *smaller* than the mesh. This allows Base and Guest atoms to coexist closer to the boundary, preventing large gaps.
-   **Negative Value:** Expands the deletion zone, creating a gap between phases.

### 3. Output Formatting Strategy


Final files for molecular dynamics often require specific headers and columns.
-   **LAMMPS Data Format:** The module can convert standard XYZ coordinates into LAMMPS data files.
-   **Charge & Spin:** It can inject `Charge` and `Spin` columns (initialized to 0) if the simulation potential requires them (e.g., ReaxFF or magnetic simulations).

---

## Detailed Parameter Guide

### A. Voxelization & Filling Parameters (Per Phase)

| Parameter | Default | Description |
| :--- | :--- | :--- |
| `pitch` | `a/4` | **Voxel Size (Å).** Determines the resolution of the voxel grid. Smaller = higher fidelity but more memory. Default is 1/4 of lattice constant. |
| `padding-angstrom` | `0.0` | **Boundary Padding.** Adds extra space around the mesh bounding box before tiling atoms. Essential to ensure the mesh is fully covered by the atom supercell. |
| `mask-dilate` | `0` | **Interior Erosion.** Number of iterations to erode (shrink) the voxel mask. Useful if atoms are spawning too close to the surface. |
| `dilate` | `1` | **Surface Thickening.** Dilates the surface voxels before filling. Helps close small gaps in non-watertight meshes. |
| `close` | `3` | **Hole Closing.** Size of the kernel for binary closing. Fills small holes in the voxel surface. |
| `force-tri` | `False` | **Force Triangle Method.** Forces the use of the robust triangle-box intersection voxelizer instead of Trimesh. Slower but safer. |
| `euler` | `None` | **Euler angles (phi1, Phi, phi2) (deg).** Applies a crystallographic orientation to the lattice unit cell prior to filling. This is defined by three Euler angles (ϕ1​,Φ,ϕ2​) in degrees. |
| `cif` | `None` | **Structure File.** Path to a CIF file defining the crystal structure. |
| `voxel-method` | `triangle`| **Algorithm.** `triangle` (robust) or `trimesh` (fast). Falls back to `triangle` if not watertight. |

### B. Merging & Surface Parameters (Per Phase / Global)

These parameters control how the "Guest" mesh is reconstructed for the boolean cut operation.

| Parameter | Default | Description |
| :--- | :--- | :--- |
| `merge` | `False` | **Enable Merging.** Must be set to `True` to trigger the phase merging and cleanup process. |
| `merge_method` | `mesh` | **Strategy.** `mesh` (Robust volumetric cut) or `overlap` (Simple distance check). |
| `resolution` | `300` | **Grid Resolution.** Resolution of the Gaussian Density grid. **High:** Accurate shape, slow. **Low:** Pixelated shape, fast. |
| `particle_radius` | `100` | **Atom Size (%).** Scaling factor for atom radius in density calculation. **High:** Smoother surface, blobs merge. **Low:** Individual atoms visible, rough surface. |
| `iso value` | `0.6` | **Iso-Level.** Threshold for the surface generation. Controls how "fat" the mesh is. Lower = fatter/larger volume. |
| `shrink distance` | `0.5` | **Interface Control (Å).** Distance from surface to delete Base atoms. **Positive:** Interface atoms overlap slightly (good binding). **Negative:** Creates a vacuum gap. |
| `overlap threshold`| `0.5` | **Atom Overlap (Å).** Final check to remove atoms that are physically too close after merging. |

### C. Post-Processing Parameters (Global)

| Parameter | Description |
| :--- | :--- |
| `rotate` | Rotates the *entire final assembly* about its centroid (x, y, z) in degrees. |
| `displace` | Translates the entire assembly (dx, dy, dz) in Å. |
| `pbc` | **Periodic Boundary Conditions.** Sets the simulation cell to the bounding box and enables PBC. |
| `charge` | Adds a `Charge` column (0.0) to output. Required for potentials like ReaxFF/Comb. |
| `spin` | Adds spin columns to output. Required for magnetic simulations. |
| `out` | Final output filename (supports `.xyz`, `.lmp`, `.lammps`). |


---
## Notes
To perform multiscale modeling of a microstructure, you can combine this module with the Image Processing and Image to Mesh modules as follows:
1. Image Processing & Image to Mesh Modules:<br>
- Sub-region Partitioning: You can manipulate the "guest" phases of an image by dividing the primary phase into several sub-regions—similar to pieces of a puzzle—and generate individual meshes for each using the Image to Mesh module.<br>
- Manual Region Definition: Alternatively, you can manually introduce arbitrarily shaped regions within the matrix to be converted into meshes (acting as guest phases) in the Image to Mesh module.
2. Mesh to Atomistic Module:
- Base Phase Selection: Use the "Bulk phase" generated in the Image to Mesh module as your Base phase.
- Material Assignment: The generated meshes for each sub-region can be filled with different materials or varying alloy compositions. For example, this allows you to analyze the effects of alloying element concentration gradients by avoiding the assumption that the entire guest phase is uniform and homogeneous.
- Multi-Phase Definition: You can define multiple distinct guest phases within a single microstructure. Furthermore, any generated mesh can be designated as a void rather than a solid material.<br>

Summary: Any arbitrary shape created in the Image Processing module can be converted into a mesh using Image to Mesh and finally integrated into your atomistic microstructure within the Mesh to Atomistic module.

**Initialization**: All `charge` and `spin` values are initially set to **zero** for convenience. Users can assign specific charge and spin values in their LAMMPS input script using the `set` command. <br>

A validation figure (PNG) is automatically generated for each guest and base phase, displaying both the initial and the Euler-rotated unit cells. <br>

The following libraries and specific modules are leveraged in this package:<br>
[ASE (Atomic Simulation Environment)](https://ase-lib.org/): Used for lattice generation and file I/O.<br>
[OVITO Python module](https://www.ovito.org/manual/python/index.html): Used for boolean operations. <br>
[Trimesh](https://trimesh.org/): Used for mesh I/O and ray-casting. <br>
[NumPy](https://numpy.org/) & [SciPy](https://scipy.org/): Core numerical methods (KDTree, ndimage). <br>

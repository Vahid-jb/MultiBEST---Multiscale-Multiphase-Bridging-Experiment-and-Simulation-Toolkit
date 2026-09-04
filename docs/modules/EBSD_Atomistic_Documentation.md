# EBSD to Atomistic/Mesh

## Overview
The **EBSD to Atomistic/Mesh** is a sophisticated, full-featured pipeline designed to convert Electron Backscatter Diffraction (EBSD) data into high-quality 3D meshes. These meshes are subsequently populated with atomistic structures that retain the crystallographic orientation of each corresponding grain, allowing for arbitrary atom types, phases and crystal structures. This enables physically accurate multiscale modeling of polycrystalline materials, starting from either experimental or synthetic microstructures.
The pipeline bridges the gap between mesoscale microstructural characterization (EBSD/SEM) and atomistic simulation (Molecular Dynamics, Molecular Statics), preserving grain morphology, crystallographic orientation (Euler angles), and phase identity throughout every transformation.

Key capabilities include:
1.  **Flexible Data Import:**
    -   **2D to 3D:** rapid replication of 2D slices to form 3D volumes.
    -   **3D Stacks:** Direct import of serial-section EBSD stacks (.ang, .ctf, or pre-assembled .h5ebsd).
2.  **Advanced Filtering Pipeline:** Uses the **[simplnx](https://www.dream3d.io/python_docs/simplnx.html)** library ([DREAM3D](https://www.dream3d.io/)) to clean data, align sections, group grains, and remove bad data points.
3.  **Comprehensive Visualization:** Generates detailed slice-by-slice visualizations of phase distribution, crystallographic orientation (IPF maps), and image quality.
4.  **Rescaling:** Allows uniform rescaling of the generated STL mesh assembly to fit the simulation scale or memory constraints of the target atomistic/continuum simulation.
5.  **Atomistic Filling:** Robustly fills each grain mesh with atoms oriented according to the grain's Euler angles and phase-specific CIF structure, then optionally assembles all grains into a single output file.

---

## Workflow
The standard workflow involves five sequential steps (Steps 0 and 2 are optional):

### Step 0: Data Preparation (Optional)
If starting with a single 2D EBSD scan (e.g., .ctf), replicate it to create a pseudo-3D volume.

| Argument | Description |
| :--- | :--- |
| `input file` | Path to the EBSD file to replicate (positional). |
| `Replicate` | Number of copies to create. |

### Step 1: EBSD Processing & Meshing

> **DREAM3D-NX environment required.** The cleaning pipeline runs in a separate
> Python environment providing the `simplnx` and `orientationanalysis` modules
> (DREAM3D-NX by BlueQuartz Software). DREAM3D-NX is not redistributable with
> MultiBEST, so it is not part of the installed application. Use the
> **DREAM3D-NX environment** controls at the top of the *Stage 1* tab:
>
> - **Install** — one-time managed setup: MultiBEST downloads micromamba
>   (BSD-3-Clause) and installs the free `dream3dnx` package from BlueQuartz
>   Software's own conda channel into your user data directory (~2 GB,
>   network access required).
> - **Browse / Test** — alternatively, select the Python interpreter of an
>   existing DREAM3D-NX/conda environment and verify it works.
>
> The selection is saved and auto-detected on the next start. The
> `MULTIBEST_DREAM3D_PYTHON` environment variable overrides it.

This is the core processing step. It:
1.  Imports EBSD data (ANG/CTF/H5EBSD).
2.  Runs a 12-filter cleaning pipeline (detailed below) including thresholding, alignment, segmentation, twin merging, and morphological cleaning.
3.  Calculates statistics (phase, average Euler angles, equivalent diameter, volume, centroid) and visualizes data.
4.  Generates STL files for each grain.
5. Saves the full data structure as a .dream3d file for later inspection in DREAM3D.



### Step 1b: Grain Data Conversion & Diagnostic Plots

Converts the **Euler angles** in `grain_data.csv` from **radians** (as output by simplnx) to **degrees**, adds a zero-indexed `grain_ID` column, and produces a diagnostic two-panel plot:

-   **Upper panel:** Euler angles (φ₁, Φ, φ₂) vs. Grain ID — useful for spotting anomalous grains.
-   **Lower panel:** Equivalent dimensionless Diameter and Volume vs. Grain ID — helps decide a suitable rescaling factor for **Step 2**. <br>
- **Output Statistics:** The ranges for Euler Angles (degrees), Equivalent Diameter, and Volume are also printed.


| Argument | Description |
| :--- | :--- |
| `input` | Path to the CSV file produced by Step 1 (`grain_data.csv`). Required. |
| `output` | Output filename for the processed tab-separated text file. Default: `processed_<input_stem>.txt`. |

**Output files:**
-   `processed_data.txt` — Tab-separated grain data with degree-based Euler angles.
-   `grain_analysis_plots_processed_data.png` — Diagnostic scatter plots.


### Step 2: Rescaling (Optional)

If the physical dimensions of the EBSD scan are too large for atomistic simulation, rescale the entire STL assembly uniformly. In this step the spatial relationships between grains are perfectly preserved.


| Argument | Description |
| :--- | :--- |
| `scale factor` | Uniform scale factor for all axes (e.g., `5.0` to upscale, `0.2` to downscale). Required. |
| `input dir` | Directory containing the original STL files. Required. |
| `input prefix` | Prefix of input filenames (e.g., `TriangleFeature_`). Required. |
| `output dir` | Directory for rescaled STLs (created automatically). Required. |


### Step 3: Atomistic Filling

Reads the processed grain data and, for each valid grain, invokes to fill the corresponding (rescaled) STL mesh with atoms. The filling process:

1.  Loads the STL mesh and voxelizes it at the specified pitch.
2.  Extracts the interior volume via flood-fill.
3.  Reads the CIF file for the grain's phase to obtain the unit cell.
4.  For each grain, the corresponding Euler rotation (ϕ1​,Φ,ϕ2​)—obtained from the data file generated in Step 1b—is applied to the unit cell before the tiling process.
5.  Creates a supercell covering the mesh bounding box.
6.  Filters atoms to keep only those inside the interior voxel mask.
7.  Deduplicates atoms within physical tolerance.
8.  Saves the grain as a `.xyz` file.

If `assembly on` is set, all per-grain `.xyz` files are automatically concatenated into a single `Final_Microstructure.xyz`.


## Detailed Parameter Guide

### 1. EBSD Atomistic Configuration

This file controls the `simplnx` pipeline. For detailed filter algorithm descriptions, refer to the [simplnx documentation](https://www.dream3d.io/python_docs/simplnx.html).

#### Data Import Mode
Choose **Mode A** (existing `.h5ebsd`) or **Mode B** (convert raw files).

| Parameter | Description |
| :--- | :--- |
| `has h5ebsd` | `yes` or `no`. Selects Mode A or Mode B. |

**Mode A — Existing H5EBSD:**

| Parameter | Description |
| :--- | :--- |
| `h5ebsd file` | Path to an existing `.h5ebsd` file. |
| `start slice` | First slice index to read (default: `1`). |
| `end slice` | Last slice index to read (default: `117`). |

**Mode B — Convert Raw ANG/CTF Stack:**

| Parameter | Description | Default |
| :--- | :--- | :--- |
| `input dir` | Directory containing `.ang` / `.ctf` files. | — |
| `file prefix` | Common prefix of filenames (e.g., `Slice_`). | `Slice_` |
| `start index` | Start index. | `1` |
| `end index` | End index. | `117` |
| `padding digits` | Number of zero-padded digits in the filename index. | `1` |
| `file extension` | `.ang` or `.ctf`. | `.ang` |
| `file suffix` | Optional suffix between the index and extension. | (empty) |
| `increment index` | Step between slice indices. | `1` |
| `z spacing` | Physical spacing between slices (µm). | `0.25` |
| `reference frame index` | `0` = EDAX (.ang), `1` = Oxford (.ctf). | `0` |
| `stacking order index` | `0` = LowToHigh, `1` = HighToLow. | `1` |
| `output h5ebsd file` | Name for the generated `.h5ebsd` file. | — |

#### Common Output Parameters

| Parameter | Description | Default |
| :--- | :--- | :--- |
| `output dream3d` | Name for the output `.dream3d` file. | — |
| `stl output dir` | Directory to save generated grain STLs. | Current dir |
| `grain data file` | Filename for the grain data CSV export. | `grain_data.csv` |

#### Visualization & Output

| Parameter | Description | Default |
| :--- | :--- | :--- |
| `ebsd visualization` | `True` to enable slice visualization (IPF, Phase, Quality maps). | `False` |
| `generate all slices` | `True` for all slices, `False` for just start/middle/end. | `False` |
| `visualization output dir` | Directory to save plots. | Same as `stl_output_dir` |

#### Simplnx Filtering Parameters

These parameters tune the segmentation and cleaning algorithms. The filter pipeline runs in the exact order listed below.

| Parameter | Default | Description & Simplnx Reference |
| :--- | :---: | :--- |
| **Filter 1: Thresholding** | | [MultiThresholdObjectsFilter](https://www.dream3d.io/python_docs/simplnx.html#simplnx.filters.multi_threshold_objects_filter) |
| `image quality threshold` | `120.0` | Min Image Quality (ANG format only). Voxels below are masked as bad data. |
| `confidence index threshold` | `0.1` | Min Confidence Index (ANG format only). |
| `band contrast threshold` | `50.0` | Min Band Contrast (CTF format only). |
| `mad threshold` | `1.0` | Max Mean Angular Deviation (CTF format only). Voxels **above** this are masked. |
| **Filter 2: Section Alignment** | | [AlignSectionsMisorientationFilter](https://www.dream3d.io/python_docs/OrientationAnalysis.html#OrientationAnalysis.AlignSectionsMisorientationFilter) |
| `align misorientation tolerance` | `5.0` | Misorientation tolerance (degrees) for aligning adjacent slices. |
| **Filter 3: Bad Data Neighbor Check** | | [BadDataNeighborOrientationCheckFilter](https://www.dream3d.io/python_docs/OrientationAnalysis.html#OrientationAnalysis.BadDataNeighborOrientationCheckFilter) |
| `bad data misorientation tolerance` | `5.0` | Misorientation tolerance (degrees) for re-classifying bad voxels. |
| `bad data number of neighbors` | `4` | Number of correct neighbors required to recover a bad voxel. |
| **Filter 4: Neighbor Correlation** | | [NeighborOrientationCorrelationFilter](https://www.dream3d.io/python_docs/OrientationAnalysis.html#OrientationAnalysis.NeighborOrientationCorrelationFilter) |
| `neighbor correlation min confidence` | `0.2` | Min confidence for neighbor correlation re-indexing. |
| `neighbor correlation level` | `2` | Correlation level (number of neighbor rings). |
| `neighbor correlation misorientation tolerance` | `5.0` | Misorientation tolerance (degrees) for correlation filter. |
| **Filter 5: Grain Segmentation** | | [EBSDSegmentFeaturesFilter](https://www.dream3d.io/python_docs/OrientationAnalysis.html#OrientationAnalysis.EBSDSegmentFeaturesFilter) |
| `segment misorientation tolerance` | `5.0` | Tolerance (degrees) to group voxels into grains. |
| **Filter 6: Twin Merging** | | [MergeTwinsFilter](https://www.dream3d.io/python_docs/OrientationAnalysis.html#OrientationAnalysis.MergeTwinsFilter) |
| `merge twins angle tolerance` | `2.0` | Angle tolerance (degrees) for Σ3 twin detection. |
| `merge twins axis tolerance` | `3.0` | Axis tolerance (degrees) for twin detection. |
| **Filter 7: Minimum Feature Size** | | [RequireMinimumSizeFeaturesFilter](https://www.dream3d.io/python_docs/simplnx.html#simplnx.RequireMinimumSizeFeaturesFilter) |
| `min allowed features size` | `16` | Minimum number of voxels to define a grain. Smaller grains are dissolved. |
| `min feature phase number` | `0` | Phase to apply minimum size to (`0` = all). |
| **Filter 8: Minimum Neighbor Count** | | [RequireMinNumNeighborsFilter](https://www.dream3d.io/python_docs/simplnx.html#simplnx.RequireMinNumNeighborsFilter) |
| `min num neighbors` | `2` | Minimum number of neighbors required for a grain to survive. |
| `min num neighbors phase` | `0` | Phase to apply minimum neighbor constraint to (`0` = all). |
| **Filter 9: Fill Bad Data** | | [FillBadDataFilter](https://www.dream3d.io/python_docs/simplnx.html#simplnx.FillBadDataFilter) |
| `min allowed defect size` | `1000` | Minimum size (voxels) of "bad data" regions to fill. |
| **Filter 10: Morphological Cleaning** | | [ErodeDilateBadDataFilter](https://www.dream3d.io/python_docs/simplnx.html#simplnx.ErodeDilateBadDataFilter) |
| `dilate iterations` | `2` | Number of dilation iterations applied to bad data masks. |
| `erode iterations` | `2` | Number of erosion iterations applied to bad data masks. |
| **Filter 11: IPF Coloring** | | [ComputeIPFColorsFilter](https://www.dream3d.io/python_docs/OrientationAnalysis.html#OrientationAnalysis.ComputeIPFColorsFilter) |
| `reference direction` | `0.0,0.0,1.0` | Reference direction for IPF coloring (comma-separated, typically the sample normal direction). |
| **Filter 12: Surface Mesh** | | [SurfaceNetsFilter](https://www.dream3d.io/python_docs/simplnx.html#simplnx.SurfaceNetsFilter) |
| `smoothing iterations` | `25` | Number of Laplacian smoothing iterations applied to the extracted surface mesh. |

---

### 2. Euler Angle Conversion & Grain Analysis

This script requires no input configuration file. It reads the CSV produced by Step 1 and is controlled entirely via command-line arguments.

| Argument | Description | Default |
| :--- | :--- | :--- |
| `input` | Path to `grain_data.csv` (required). | — |
| `output` | Output filename (tab-separated text). | `processed_<input_stem>.txt` |

**What it does:**
-   Converts `AvgEulerAngles_Export_0/1/2` from **radians to degrees**.
-   Replaces `NaN` values with `0.0`.
-   Inserts a zero-indexed `grain_ID` column.
-   Exports columns: `grain_ID`, `Phases_Export`, φ₁, Φ, φ₂, `EquivalentDiameters_Export`, `Volumes_Export`.
-   Generates `grain_analysis_plots_<stem>.png` with diagnostic scatter plots.

---

### 3. Atomistic Filling Configuration

It populates the meshes with atoms for each grain.

| Parameter | Description |
| :--- | :--- |
| `grain data` | Path to the processed grain data file (output of `euler_to_angle.py`). |
| `stl dir` | Directory containing (rescaled) STL files. |
| `output dir` | Directory to save individual grain XYZ files. |
| `stl prefix` | Prefix of STL filenames (default: `TriangleFeature_`). |
| `verification fig` | `on` / `off`. Generate a validation PNG per grain showing initial and Euler-rotated unit cell. |
| `assembly` | `on` / `off`. Automatically combine all grain XYZ files into one assembled file. |
| `assembly output` | Custom path for the assembled output (default: `<output_dir>/assembled_final.xyz`). |
| `phase X cif path` | Define phase `X` with its CIF file. `X` must match the `Phases_Export` column in the grain data. Multiple phases can be defined. |

#### Setup Parameters

These options configure the voxelization and atom-placement engine:

| Flag | Description | Default |
| :--- | :--- | :--- |
| `pitch` | Voxel pitch in Ångström. Smaller pitch → higher resolution → more atoms → slower. | Auto (from lattice constant) |
| `padding angstrom` | Padding in Å around the mesh bounding box for supercell tiling. | `0.0` |
| `mask dilate` | Number of binary dilation iterations applied to the interior mask. Increases the filled volume slightly beyond the mesh surface. | `0` |
| `dilate` | Number of binary dilation iterations applied to the surface voxel shell **before** interior extraction. | `1` |
| `close` | Size of the morphological closing kernel (must be odd). Fills small gaps in the voxelized surface. | `3` |

---

## Visualization Module

It produces a **4-panel figure per slice** saved as `ebsd_slice_zXXX.png`:

| Panel | Content |
| :--- | :--- |
| **Top-Left** | IPF Orientation Map (RGB color from Euler angles + crystal symmetry). |
| **Top-Right** | Data Quality Map (Image Quality for ANG, Band Contrast for CTF). |
| **Bottom-Left** | Phase Map (color-coded by phase ID, with legend). |
| **Bottom-Right** | Phase Distribution Pie Chart (percentage of each phase, background excluded). |

**Slice selection:** By default, only the first, middle, and last slices are visualized. Set `generate_all_slices True` to process every slice.

---

## Atomistic Engine

This is the **low-level atomistic filling engine**. It is typically not invoked directly by the user. Its key functions include:

| Capability | Description |
| :--- | :--- |
| **Mesh Loading** | Loads STL/OBJ meshes via `trimesh`. |
| **Voxelization** | Triangle-box intersection (Möller algorithm) to convert the mesh surface into a 3D voxel grid. |
| **Interior Extraction** | Flood-fill from exterior + complement, with parity (scanline) fallback for non-watertight meshes. |
| **Lattice Construction** | Reads unit cell from CIF files (via ASE `ase.io.read`) or builds standard bulk structures (`ase.build.bulk`). |
| **Euler Rotation** | Applies Bunge convention Euler rotation (φ₁, Φ, φ₂) to the unit cell **before** supercell tiling, so atoms are correctly oriented. |
| **Supercell Tiling** | Builds a supercell covering the mesh bounding box + padding, using fractional coordinate algebra for arbitrary (including triclinic) cells. |
| **Atom Filtering** | Maps candidate atoms to voxel centers and keeps only those inside the interior mask. |
| **Deduplication** | Removes duplicate atoms within a configurable tolerance (default: 0.001 Å). |
| **Validation PNG** | Generates side-by-side 3D scatter plots of the initial and Euler-rotated unit cells with crystallographic metadata. |
| **XYZ Output** | Writes standard XYZ format (atom_count, comment, element x y z). |

---

## Notes
By leveraging the simplnx library and its robust I/O capabilities, the module seamlessly integrates with DREAM3D. This allows users to perform initial EBSD processing in DREAM3D—useful for handling specialized file formats or applying custom filters not currently available in this module—and save the output as an .h5ebsd file for direct import into the workflow. Furthermore, results can be verified by importing and analyzing the generated .dream3d files within the DREAM3D software, or by reviewing the visualization files, statistical reports, and verification figures automatically produced by the workflow. <br>

The following libraries and specific modules are leveraged in this package:<br>

[ASE (Atomic Simulation Environment)](https://ase-lib.org/): Used for lattice generation and file I/O.<br>
[OVITO Python module](https://www.ovito.org/manual/python/index.html): Used for boolean operations. <br>
[Trimesh](https://trimesh.org/): Mesh I/O and watertight checks. <br>
[NumPy](https://numpy.org/): Numerical operations throughout the pipeline. <br>
[scipy](https://scipy.org/): Morphological operations (dilation, closing, flood-fill) and KDTree for deduplication. <br>
[matplotlib](https://matplotlib.org/):Visualization (IPF maps, phase maps, grain plots, validation PNGs). <br>
[pandas](https://dataanalysispython.readthedocs.io/en/latest/pandas.html): Grain data processing. <br>
[pymeshlab](https://pymeshlab.readthedocs.io/en/latest/): STL rescaling. <br>
[simplnx](https://www.dream3d.io/python_docs/simplnx.html): EBSD processing. <br>

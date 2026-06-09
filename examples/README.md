# MultiBEST Examples

This directory contains runnable example scripts and sample datasets for the
MultiBEST modules. Scripts demonstrate the pure-Python backends without launching
the GUI; the datasets are ready-to-use inputs for the GUI modules.

## Structure

Examples are organized by module:

```
examples/
├── image_processing/            # Image processing backend (no Qt)
│   ├── basic.py                 # ops + HistoryStack usage
│   ├── analyze.py               # CLI: binary section analysis + replica generation
│   ├── input.txt                # Configuration file for analyze.py
│   ├── test.jpg                 # Sample micrograph (Git LFS)
│   └── ech_robinet_2_brut_008_scale.jpg  # Sample micrograph (Git LFS)
├── mesh_to_atomistic/           # Sample meshes + CIF structures for mesh-filling
│   ├── *.stl                    # Surface meshes (Git LFS)
│   └── *.cif                    # Crystal structures (Materials Project)
├── atomistic_to_continuum/      # Sample LAMMPS data file
│   └── FeCr.lmp                 # Fe–Cr atomistic structure (Git LFS)
├── ebsd/                        # Pointer to external EBSD dataset
│   └── EBSD-source.txt
└── DATA_SOURCES.md              # Attribution + licenses for all sample data
```

> Large binary assets (`*.stl`, `*.lmp`, `*.jpg`) are stored via
> [Git LFS](https://git-lfs.com/). After cloning run `git lfs pull` to fetch them.
> See [DATA_SOURCES.md](DATA_SOURCES.md) for provenance and licensing.

## Prerequisites

Install the dependency group for the module you want to exercise:

```bash
uv sync --group image_processing   # for the image_processing scripts
uv sync --all-groups               # everything
```

## Running the Scripts

### Image Processing — `basic.py`

Demonstrates the core image operations (`threshold`, `gaussian_blur`, `contrast`,
`crop`, `cut`, `flood_fill`, `draw_line`) and the `HistoryStack` undo/redo buffer
on a synthetic image — no files or GUI required.

```bash
python examples/image_processing/basic.py
```

### Image Processing — `analyze.py`

A small command-line tool that thresholds a binary microstructure image, labels
connected sections (per-section area / centroid / bounding box), and optionally
generates area-preserving random binary replicas. It is driven by an `.ini`-style
configuration file.

```bash
python examples/image_processing/analyze.py examples/image_processing/input.txt
```

Edit [`input.txt`](image_processing/input.txt) to point at your own image and to
tune thresholding, connectivity, and replica-generation settings.

### GUI Datasets

The `mesh_to_atomistic/`, `atomistic_to_continuum/`, and `ebsd/` folders hold
sample inputs you can load directly in the corresponding GUI modules
(launch with `just run`). They are not standalone scripts.

## Adding New Module Examples

1. Create a module directory: `mkdir examples/your_module/`
2. Add runnable scripts and/or sample data.
3. Start every `*.py` file with the SPDX header (see existing scripts).
4. Update this README and, for data files, [DATA_SOURCES.md](DATA_SOURCES.md).

## See Also

- [Module documentation](../docs/modules/index.md) — per-module guides
- [DATA_SOURCES.md](DATA_SOURCES.md) — example data attribution and licenses

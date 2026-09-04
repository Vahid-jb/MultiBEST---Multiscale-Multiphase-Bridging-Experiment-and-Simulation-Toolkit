# MultiBEST Examples

This directory contains sample datasets, ready to load directly into the
corresponding MultiBEST GUI modules (launch with `just run`).

## Structure

Examples are organized by module:

```
examples/
├── image_processing/            # Sample micrographs for the Image Processing module
│   ├── raw_micrograph.jpg               # Raw, unprocessed micrograph (Git LFS)
│   └── processed_micrograph.jpg         # Thresholded/processed micrograph (Git LFS)
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

## Using the Datasets

Every folder here holds sample inputs you load directly in the corresponding
GUI module (launch with `just run`) — none of them are standalone scripts:

- **`image_processing/`** — open `raw_micrograph.jpg` in the Image Processing
  module's Edit tab to try thresholding, blur, contrast, crop/cut, flood fill,
  and section analysis yourself; `processed_micrograph.jpg` shows an example
  of the thresholded output for comparison.
- **`mesh_to_atomistic/`, `atomistic_to_continuum/`, `ebsd/`** — load directly
  in the corresponding GUI module.

## Adding New Module Examples

1. Create a module directory: `mkdir examples/your_module/`
2. Add sample data files.
3. Update this README and [DATA_SOURCES.md](DATA_SOURCES.md) with the new files.

## See Also

- [Module documentation](../docs/modules/index.md) — per-module guides
- [DATA_SOURCES.md](DATA_SOURCES.md) — example data attribution and licenses

# MultiBEST Toolkit

The **MultiBEST Toolkit** is a GUI-driven environment for building multiscale
materials workflows from experimental images, meshes, EBSD data, and atomistic
structures. Its modules can be used independently or chained together to move
between image processing, mesh preparation, atomistic model generation,
relaxation, and continuum model construction.

This documentation site is built for the help button in the MultiBEST GUI. When
opened from a module, the help page jumps directly to the corresponding module
documentation.

---

## Module Guide

- **[Image Processing](Image_Processing_Documentation.md)**
  Edit, threshold, and annotate experimental images; analyse binary section
  areas; and generate area-preserving random binary replicas.

- **[Image to Mesh](Image_to_Mesh_Documentation.md)**
  Prepare binary microstructure images and convert image-derived phase regions
  into three-dimensional meshes for downstream modeling.

- **[Mesh Modification](Mesh_Modification_Documentation.md)**
  Refine, smooth, clean, repair, and transform mesh files before atomistic or
  continuum conversion.

- **[Mesh To Atomistic](Mesh_to_Atomistic_Documentation.md)**
  Fill mesh volumes with atomistic structures, merge multiple phases, and export
  simulation-ready files.

- **[Relaxation](Relaxation_Module_Documentation.md)**
  Relax atomistic structures with GFN2-xTB or SevenNet-based workflows.

- **[EBSD To Atomistic / Mesh](EBSD_Atomistic_Documentation.md)**
  Process EBSD data, build grain-resolved meshes, rescale geometry, and fill
  grains with oriented atomistic structures.

- **[Atomistic To Continuum](Atomistic_to_Continuum_Documentation.md)**
  Analyze atomistic microstructures, identify grains and phases, and generate
  continuum-ready mesh representations.

- **[Input Convertor](Input_Convertor_Docs.md)**
  Convert atomistic structures between common file formats and generate LAMMPS
  data or dump files for classic, charge, and spin simulations.

---

## Typical Workflow

1. Process experimental images or EBSD data into clean phase or grain geometry.
2. Modify and validate meshes for the intended downstream method.
3. Convert meshes to atomistic structures or atomistic data to continuum meshes.
4. Relax atomistic systems and export structures for simulation or analysis.

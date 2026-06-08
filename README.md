<img width="1162" height="200" alt="grafik" src="https://github.com/user-attachments/assets/c0e1f91b-52be-47d7-aad2-e20cafa27347" />


<img width="2494" height="1621" alt="Figure_1" src="https://github.com/user-attachments/assets/3f45ed76-b4a8-4318-b333-cc406c074b51" />


# MultiBEST – Multiscale/Multiphase Bridging Experiment and Simulation Toolkit

MultiBEST is a GUI‑based, end‑to‑end framework for constructing experiment‑identical microstructures for atomistic, continuum, and multiscale simulations. Instead of relying on idealized or implicit microstructures, MultiBEST starts directly from experimental or user‑defined inputs and preserves microstructural detail across all modelling stages:

- 2D micrographs (optical/SEM)
- 2D / 3D EBSD datasets
- Simple user sketches of microstructures

From these inputs, MultiBEST builds:

- Atomistic models with grain‑resolved crystallography and phase identity
- Continuum meshes in which grain boundaries are explicit volumetric interphases with their own material properties (diffusivity, elasticity, transport tensors, etc.), not just invisible voxel transitions or weightless surfaces

Moreover, users can provide the morphology of a microstructure or object as a mesh and construct an atomistic model with desired atomic compositions and crystallographic orientations.

This architecture allows users to:

- Perform experiment‑matched simulations, microstructure and alloying‑element optimization, and conduct experiment‑matched multiscale modelling
- Seamlessly move between atomistic and continuum scales within a single, consistent workflow

MultiBEST integrates all required stages into one toolkit, from image processing to the final atomistic model in a suitable format for atomistic simulations, including reactive and classical molecular dynamics as well as spin‑lattice dynamics, and to representative continuum models with explicit grain‑boundary regions. The software is designed to run efficiently on both standard workstations and HPC systems, enabling anything from rapid prototyping to large‑scale, high‑fidelity simulations. The architecture allows each computational module to run either independently from the command line or through the central GUI, and includes a local HTTP server that delivers static HTML documentation to the browser for convenient offline use.

## 🚀 Getting Started

Download the current release for your platform from the [GitHub Releases](https://github.com/Vahid-jb/MultiBEST---Multiscale-Multiphase-Bridging-Experiment-and-Simulation-Toolkit/releases) page and extract the archive to a folder of your choice.

The GUI can be launched by running the MultiBEST executable. The compute scripts can also be used standalone by invoking them directly from a terminal with an input file.

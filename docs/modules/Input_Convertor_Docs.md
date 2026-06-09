# Input Converter and Format Manager

## 1. Introduction
The **Input Converter** is a versatile tool designed to bridge the gap between various computational materials science software packages. Its primary function is to convert atomic structure files into formats compatible with LAMMPS (Large-scale Atomic/Molecular Massively Parallel Simulator) and visualization tools like Ovito.

It automatically handles tasks such as:
*   **Orthogonalization** of triclinic simulation cells.
*   Assignment of **Charge** and **Spin** degrees of freedom for **reactive MD or spin-lattice dynamics**.

## 2. Particle Definitions and LAMMPS Formats
The tool supports three distinct "modes" corresponding to different physical models in Molecular Dynamics (MD).

| Mode | Description | LAMMPS Format | Columns in `.lmp` |
| :--- | :--- | :--- | :--- |
| **Classic** | Classical MD with neutral point particles. | `atom_style atomic` | `ID type x y z` |
| **Charge** | MD with explicit Coulombic interactions (ions). | `atom_style charge` | `ID type charge x y z` |
| **Spin** | Magnetic MD with atomic spin moments. | `atom_style spin` | `ID type x y z sx sy sz scalar_spin` |

*   **Atomic Spin**: In `spin` mode, the script adds 4 extra columns. `sx, sy, sz` represent the direction of the spin vector, and `scalar_spin` represents the magnitude (in Bohr magnetons).
*   **Initialization**: All `charge` and `spin` values are initially set to **zero** for convenience. Users can assign specific charge and spin values in their LAMMPS input script using the `set` command.

## 3. Output Files
The script generates different outputs based on the requested filename extension. By leveraging the **Atomic Simulation Environment (ASE)** backend, it supports conversion between a vast array of formats including **CIF (`.cif`)**, **XCrysDen (`.xsf`)**, **VASP (`POSCAR`/`CONTCAR`)**, and many others. For a full list of supported formats, refer to the [ASE IO documentation](https://wiki.fysik.dtu.dk/ase/ase/io/io.html).

Specific details for key formats:

1.  **LAMMPS Data (`.lmp`, `.data`)**:
    *   Header containing `N atoms`, `N atom types`.
    *   Box bounds: `xlo xhi`, `ylo yhi`, `zlo zhi` (and `xy xz yz` for triclinic).
    *   `Masses` section: Inferred from periodic table based on element symbols.
    *   `Atoms` section: The coordinate data in the selected format (Classic/Charge/Spin).

2.  **LAMMPS Dump (`.dump`)**:
    *   Created if the input contains multiple timeframes (a trajectory).
    *   Standard LAMMPS dump format with `ITEM: TIMESTEP`, `ITEM: NUMBER OF ATOMS`, `ITEM: BOX BOUNDS`, `ITEM: ATOMS ...`.

3.  **Extended XYZ (`.xyz`, `.extxyz`)**:
    *   Compatible with **Ovito**.
    *   Includes Lattice string and Properties line (e.g., `Properties=species:S:1:pos:R:3`).

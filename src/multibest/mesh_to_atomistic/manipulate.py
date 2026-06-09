#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 bright-ideas-clan
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
manipulate.py

Enhanced tool to manipulate a single XYZ file with LAMMPS conversion options:
- Apply rotation about centroid
- Apply displacement
- Apply periodic boundary conditions (set cell to bounding box and translate to origin)
- Replicate structure
- Convert to LAMMPS data format with charge/spin support

Usage:
  python manipulate.py input.xyz --displace 20 10 80 --rotate 20 30 12.5 --charge --spin \
    --replicate 2 2 2 --pbc --output LAMMPSDATFILE.lmp
"""

import argparse
import math
import os
import sys
from pathlib import Path

import numpy as np
from ase import io as ase_io

# Force UTF-8 encoding for standard output and error
if sys.platform == "win32":
    for stream in (sys.stdout, sys.stderr):
        if stream is not None and hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

# Import functions from the packaged Input Convertor module.
try:
    from multibest.input_convertor.input_convertor import (
        detect_charge_spin,
        is_triclinic,
        orthogonalize_and_wrap_atoms,
        write_lammps_data_from_ase,
    )

    INPUT_CONVERTOR_AVAILABLE = True
except ImportError:
    try:
        src_dir = Path(__file__).resolve().parents[2]
        if str(src_dir) not in sys.path:
            sys.path.insert(0, str(src_dir))
        from multibest.input_convertor.input_convertor import (
            detect_charge_spin,
            is_triclinic,
            orthogonalize_and_wrap_atoms,
            write_lammps_data_from_ase,
        )

        INPUT_CONVERTOR_AVAILABLE = True
    except ImportError:
        try:
            from Input_Convertor import (
                detect_charge_spin,
                is_triclinic,
                orthogonalize_and_wrap_atoms,
                write_lammps_data_from_ase,
            )

            INPUT_CONVERTOR_AVAILABLE = True
        except ImportError:
            INPUT_CONVERTOR_AVAILABLE = False
            print("Warning: Input Convertor not available. LAMMPS conversion features disabled.")


# -------------------------
# Rotation utilities
# -------------------------
def _rotation_matrix_for_axis(axis, angle_deg):
    a = math.radians(float(angle_deg))
    c = math.cos(a)
    s = math.sin(a)
    if axis.lower() == "x":
        R = np.array([[1.0, 0.0, 0.0], [0.0, c, -s], [0.0, s, c]])
    elif axis.lower() == "y":
        R = np.array([[c, 0.0, s], [0.0, 1.0, 0.0], [-s, 0.0, c]])
    elif axis.lower() == "z":
        R = np.array([[c, -s, 0.0], [s, c, 0.0], [0.0, 0.0, 1.0]])
    else:
        raise ValueError("Unknown axis for rotation: " + str(axis))
    return R


def rotate_atoms_about_centroid(atoms, rot_x=0.0, rot_y=0.0, rot_z=0.0):
    """
    Rotate ASE Atoms object about its centroid by given angles in degrees.
    The object position (centroid) is preserved: rotation done around centroid.
    Returns rotation matrix for logging.
    """
    pos = atoms.get_positions()
    if len(pos) == 0:
        return np.eye(3)

    centroid = pos.mean(axis=0)
    # translate to origin
    pos0 = pos - centroid
    R = np.eye(3)
    if rot_x:
        R = _rotation_matrix_for_axis("x", rot_x) @ R
    if rot_y:
        R = _rotation_matrix_for_axis("y", rot_y) @ R
    if rot_z:
        R = _rotation_matrix_for_axis("z", rot_z) @ R
    pos_rot = (R @ pos0.T).T + centroid
    atoms.set_positions(pos_rot)
    return R


def apply_pbc(atoms):
    """
    Apply periodic boundary conditions:
    - Set cell to bounding box of atoms
    - Translate atoms so minimum is at origin
    - Set PBC to True in all directions
    """
    pos = atoms.get_positions()
    if len(pos) == 0:
        return atoms

    mins = pos.min(axis=0)
    maxs = pos.max(axis=0)
    size = maxs - mins

    # Avoid zero-size cell vectors
    size = np.maximum(size, 1e-8)

    # Translate positions to put them in [0, L]
    atoms.set_positions(pos - mins)

    # Set orthogonal cell equal to bounding box extents
    atoms.set_cell(np.diag(size))
    atoms.set_pbc([True, True, True])

    print(f"Applied PBC: Lx={size[0]:.6f}, Ly={size[1]:.6f}, Lz={size[2]:.6f}")
    return atoms


def replicate_atoms(atoms, replication_factors):
    """
    Replicate atoms in x, y, z directions
    """
    nx, ny, nz = replication_factors
    if nx <= 0 or ny <= 0 or nz <= 0:
        raise ValueError("Replication factors must be positive integers")

    print(f"Replicating structure: {nx}x{ny}x{nz}")
    replicated = atoms.repeat((nx, ny, nz))
    print(f"Replicated from {len(atoms)} to {len(replicated)} atoms")
    return replicated


def _ensure_valid_cell(atoms):  # pragma: no cover
    cell = np.array(atoms.get_cell(), dtype=float)
    try:
        vol = np.linalg.det(cell)
    except Exception:
        vol = 0.0

    if abs(vol) >= 1e-12:
        return
    pos = atoms.get_positions()
    if len(pos) == 0:
        return
    mins = pos.min(axis=0)
    maxs = pos.max(axis=0)
    size = np.maximum(maxs - mins, 1.0)
    atoms.set_cell(np.diag(size))
    atoms.set_pbc([True, True, True])
    atoms.set_positions(pos - mins + 0.5 * (size - (maxs - mins)))


def _ensure_charge_spin_arrays(atoms, charge=False, spin=False):  # pragma: no cover
    if charge:
        has_charge, _, _ = detect_charge_spin(atoms)
        if not has_charge:
            atoms.set_array("charge", np.zeros(len(atoms), dtype=float))
            print("Added zero-initialized charge array")

    if spin:
        _, _, has_spin_components = detect_charge_spin(atoms)
        if not has_spin_components:
            for spin_idx in range(4):
                atoms.set_array(f"Spin{spin_idx}", np.zeros(len(atoms), dtype=float))
            print("Added zero-initialized spin arrays")


def _orthogonalize_if_triclinic(atoms):  # pragma: no cover
    cell = np.array(atoms.get_cell(), dtype=float)
    if not is_triclinic(cell):
        return atoms
    print("Orthogonalizing triclinic cell for LAMMPS compatibility")
    try:
        return orthogonalize_and_wrap_atoms(atoms)
    except Exception as e:
        print(f"Warning: Orthogonalization failed: {e}. Using original cell.")
        return atoms


def prepare_for_lammps(atoms, charge=False, spin=False):  # pragma: no cover
    """
    Prepare atoms for LAMMPS output by adding charge/spin arrays as needed
    """
    if not INPUT_CONVERTOR_AVAILABLE:
        raise RuntimeError("Input_Convertor not available for LAMMPS preparation")

    _ensure_valid_cell(atoms)
    _ensure_charge_spin_arrays(atoms, charge=charge, spin=spin)
    return _orthogonalize_if_triclinic(atoms)


def write_lammps_output(filename, atoms, charge=False, spin=False):
    """
    Write atoms to LAMMPS format with appropriate mode
    """
    if not INPUT_CONVERTOR_AVAILABLE:
        raise RuntimeError("Input_Convertor not available for LAMMPS writing")

    # Determine write mode
    if spin:
        mode = 3  # Spin format
    elif charge:
        mode = 2  # Charge format
    else:
        mode = 1  # Classic format

    # Ensure output has .lmp extension for LAMMPS data files
    if not filename.lower().endswith(".lmp"):
        filename = os.path.splitext(filename)[0] + ".lmp"

    write_lammps_data_from_ase(filename, atoms, mode=mode)
    return filename


def main():  # pragma: no cover  # NOSONAR - legacy CLI workflow kept intact for behavior parity
    parser = argparse.ArgumentParser(
        description="Manipulate XYZ file with rotation, displacement, PBC, replication, and LAMMPS conversion",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python manipulate.py input.xyz --displace 20 10 80 --rotate 20 30 12.5 --charge --spin \
    --replicate 2 2 2 --pbc --output LAMMPSDATFILE.lmp
  python manipulate.py input.xyz --rotate 0 90 0 --pbc --output rotated.xyz
  python manipulate.py input.xyz --displace 50 0 0 --replicate 2 1 1 --charge --output charged.lmp
        """,
    )

    parser.add_argument("input", help="Input XYZ file")
    parser.add_argument(
        "--displace", nargs=3, type=float, metavar=("DX", "DY", "DZ"), help="Displacement vector in Ångstroms"
    )
    parser.add_argument(
        "--rotate",
        nargs=3,
        type=float,
        metavar=("RX", "RY", "RZ"),
        help="Rotation angles in degrees about X, Y, Z axes",
    )
    parser.add_argument(
        "--pbc", action="store_true", help="Apply periodic boundary conditions (set cell to bounding box)"
    )
    parser.add_argument(
        "--replicate", nargs=3, type=int, metavar=("NX", "NY", "NZ"), help="Replication factors in x, y, z directions"
    )
    parser.add_argument("--charge", action="store_true", help="Add charge arrays and output LAMMPS data format")
    parser.add_argument("--spin", action="store_true", help="Add spin arrays and output LAMMPS data format")
    parser.add_argument("--output", required=True, help="Output file")

    args = parser.parse_args()

    # Check LAMMPS feature dependencies
    if (args.charge or args.spin) and not INPUT_CONVERTOR_AVAILABLE:
        print("Error: LAMMPS conversion features require Input_Convertor.py")
        print("Make sure Input_Convertor.py is in the same directory or PYTHONPATH")
        sys.exit(1)

    # Validate input file exists
    if not os.path.exists(args.input):
        print(f"Error: Input file not found: {args.input}")
        sys.exit(1)

    # Read input file
    print(f"Reading input file: {args.input}")
    try:
        atoms = ase_io.read(args.input)
        print(f"  Atoms: {len(atoms)}")
        print(f"  Chemical symbols: {set(atoms.get_chemical_symbols())}")
    except Exception as e:
        print(f"Failed to read {args.input}: {e}")
        sys.exit(1)

    # Apply rotation if requested
    if args.rotate:
        rx, ry, rz = args.rotate
        print(f"Applying rotation: RX={rx}°, RY={ry}°, RZ={rz}°")
        R = rotate_atoms_about_centroid(atoms, rx, ry, rz)
        print("Rotation matrix:")
        for row in R:
            print(f"  [{row[0]:8.4f} {row[1]:8.4f} {row[2]:8.4f}]")

    # Apply displacement if requested
    if args.displace:
        dx, dy, dz = args.displace
        print(f"Applying displacement: DX={dx}, DY={dy}, DZ={dz} Å")
        pos = atoms.get_positions()
        atoms.set_positions(pos + np.array([dx, dy, dz]))

    # Apply PBC if requested
    if args.pbc:
        print("Applying periodic boundary conditions...")
        atoms = apply_pbc(atoms)

    # Determine output format and write
    output_is_lammps = args.output.lower().endswith((".lmp", ".lammps")) or args.charge or args.spin

    if output_is_lammps:
        print("Preparing structure for LAMMPS output...")
        try:
            atoms = prepare_for_lammps(atoms, charge=args.charge, spin=args.spin)

            # Apply replication AFTER preparing for LAMMPS (so we have a proper cell)
            if args.replicate:
                try:
                    atoms = replicate_atoms(atoms, args.replicate)
                except Exception as e:
                    print(f"Replication failed: {e}")
                    sys.exit(1)

            output_file = write_lammps_output(args.output, atoms, charge=args.charge, spin=args.spin)
            print(f"Success! LAMMPS data written to {output_file}")
            print(f"Final atom count: {len(atoms)}")

            # Report format used
            if args.spin:
                format_type = "spin"
            elif args.charge:
                format_type = "charge"
            else:
                format_type = "classic"
            print(f"LAMMPS format: {format_type}")

        except Exception as e:
            print(f"Failed to write LAMMPS output: {e}")
            sys.exit(1)
    else:
        # For non-LAMMPS output, apply replication before writing
        if args.replicate:
            try:
                atoms = replicate_atoms(atoms, args.replicate)
            except Exception as e:
                print(f"Replication failed: {e}")
                sys.exit(1)

        # Write standard XYZ format
        print(f"Writing output to: {args.output}")
        try:
            ase_io.write(args.output, atoms, format="xyz")
            print(f"Success! Output written to {args.output}")
            print(f"Final atom count: {len(atoms)}")
        except Exception as e:
            print(f"Failed to write output: {e}")
            sys.exit(1)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 bright-ideas-clan
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
ASE-based LAMMPS input converter with bidirectional conversion support.
Automatically detects conversion direction based on file extensions.

CLI mode: python input_convertor.py input.txt
Input file format (simple and consistent):
input_file ./FeCr.xyz
output_file ./FeCr.lmp
charge/spin classic/charge/spin
unskew_and_align yes/no

or
input_file ./FeCr.lmp
output_file ./FeCr.cif

The script automatically detects:
- If output file has .lmp/.data extension -> Convert TO LAMMPS format
- If output file has other extension (.cif/.xyz/.cfg/.xsf) -> Convert FROM input to that format
"""

from __future__ import annotations

import os
import re
import sys

import numpy as np

try:
    from ase import Atoms
    from ase import io as aseio
    from ase.io import write
except ImportError:
    io = None
    Atoms = None
    write = None


# Force UTF-8 encoding for standard output and error
if sys.platform == "win32":
    for stream in (sys.stdout, sys.stderr):
        if stream is not None and hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

GENERATED_HEADER = "# This file is generated using MultiBEST\n"
LAMMPS_DUMP_EXT = ".dump"
LAMMPS_TRAJ_EXT = ".lammpstrj"
LAMMPS_DUMP_EXTENSIONS = (LAMMPS_DUMP_EXT, LAMMPS_TRAJ_EXT, ".lammpstrj.gz", ".traj")
LAMMPS_FILE_EXTENSIONS = (".lmp", ".data", ".lammps", LAMMPS_DUMP_EXT, LAMMPS_TRAJ_EXT)
SPIN_KEYS = ("Spin0", "Spin1", "Spin2", "Spin3")

# Periodic masses for mass->element guessing
PERIODIC_MASSES = {
    "H": 1.00794,
    "He": 4.002602,
    "Li": 6.941,
    "Be": 9.012182,
    "B": 10.811,
    "C": 12.0107,
    "N": 14.0067,
    "O": 15.9994,
    "F": 18.9984032,
    "Ne": 20.1797,
    "Na": 22.98976928,
    "Mg": 24.3050,
    "Al": 26.9815386,
    "Si": 28.0855,
    "P": 30.973762,
    "S": 32.065,
    "Cl": 35.453,
    "Ar": 39.948,
    "K": 39.0983,
    "Ca": 40.078,
    "Sc": 44.955912,
    "Ti": 47.867,
    "V": 50.9415,
    "Cr": 51.9961,
    "Mn": 54.938045,
    "Fe": 55.845,
    "Co": 58.933195,
    "Ni": 58.6934,
    "Cu": 63.546,
    "Zn": 65.38,
    "Ga": 69.723,
    "Ge": 72.64,
    "As": 74.92160,
    "Se": 78.96,
    "Br": 79.904,
    "Kr": 83.798,
    "Rb": 85.4678,
    "Sr": 87.62,
    "Y": 88.90585,
    "Zr": 91.224,
    "Nb": 92.90638,
    "Mo": 95.96,
    "Tc": 98.0,
    "Ru": 101.07,
    "Rh": 102.90550,
    "Pd": 106.42,
    "Ag": 107.8682,
    "Cd": 112.411,
    "In": 114.818,
    "Sn": 118.710,
    "Sb": 121.760,
    "Te": 127.60,
    "I": 126.90447,
    "Xe": 131.293,
    "Cs": 132.9054519,
    "Ba": 137.327,
    "La": 138.90547,
    "Ce": 140.116,
    "Pr": 140.90765,
    "Nd": 144.242,
    "Pm": 145.0,
    "Sm": 150.36,
    "Eu": 151.964,
    "Gd": 157.25,
    "Tb": 158.92535,
    "Dy": 162.500,
    "Ho": 164.93032,
    "Er": 167.259,
    "Tm": 168.93421,
    "Yb": 173.04,
    "Lu": 174.967,
    "Hf": 178.49,
    "Ta": 180.94788,
    "W": 183.84,
    "Re": 186.207,
    "Os": 190.23,
    "Ir": 192.217,
    "Pt": 195.084,
    "Au": 196.966569,
    "Hg": 200.59,
    "Tl": 204.3833,
    "Pb": 207.2,
    "Bi": 208.98040,
    "Po": 209.0,
    "At": 210.0,
    "Rn": 222.0,
    "Fr": 223.0,
    "Ra": 226.0,
    "Ac": 227.0,
    "Th": 232.03806,
    "Pa": 231.03588,
    "U": 238.02891,
    "Np": 237.0,
    "Pu": 244.0,
    "Am": 243.0,
    "Cm": 247.0,
    "Bk": 247.0,
    "Cf": 251.0,
    "Es": 252.0,
    "Fm": 257.0,
    "Md": 258.0,
    "No": 259.0,
    "Lr": 262.0,
    "Rf": 261.0,
    "Db": 262.0,
    "Sg": 266.0,
    "Bh": 264.0,
    "Hs": 277.0,
    "Mt": 268.0,
    "Ds": 271.0,
    "Rg": 272.0,
    "Cn": 285.0,
    "Nh": 284.0,
    "Fl": 289.0,
    "Mc": 288.0,
    "Lv": 293.0,
    "Ts": 294.0,
    "Og": 294.0,
}


# ---------------- Utility ----------------
def prepend_vcl_header(filename: str):
    """Prepend the VCL toolkit header to a file."""
    try:
        with open(filename, encoding="utf-8", errors="ignore") as f:
            content = f.read()
        with open(filename, "w", encoding="utf-8") as f:
            f.write(GENERATED_HEADER + content)
    except (OSError, UnicodeError) as e:
        print(f"Warning: Could not prepend header to {filename}: {e}")


def normalize_path_for_os(path: str) -> str:
    if not path:
        return path
    if os.name == "nt":
        if path.startswith("/mnt/") and len(path) > 7:
            drive = path[5]
            rest = path[7:].replace("/", "\\")
            return drive.upper() + ":\\" + rest
        return path
    if len(path) >= 3 and path[1] == ":":
        drive = path[0].lower()
        rest = path[3:].replace("\\", "/")
        return f"/mnt/{drive}/{rest}"
    return path


def ask(prompt: str, default: str | None = None) -> str:
    if default is not None:
        s = input(f"{prompt} [{default}]: ").strip()
        return s if s else default
    while True:
        s = input(f"{prompt}: ").strip()
        if s:
            return s
        print("This field is required.")


def build_type_mapping(symbols: list[str]) -> dict:
    mapping = {}
    for s in symbols:
        if s not in mapping:
            mapping[s] = len(mapping) + 1
    return mapping


def triangular_cell_components(cell: np.ndarray) -> tuple[float, float, float, float, float, float]:
    a = np.array(cell[0], dtype=float)
    b = np.array(cell[1], dtype=float)
    c = np.array(cell[2], dtype=float)
    ax = np.linalg.norm(a)
    if ax == 0:
        raise RuntimeError("Cell vector a has zero length.")
    e1 = a / ax
    bx = np.dot(b, e1)
    b_perp = b - bx * e1
    by = np.linalg.norm(b_perp)
    if by > 1e-12:
        e2 = b_perp / by
    else:
        e2 = np.array([0.0, 1.0, 0.0])
        if abs(np.dot(e2, e1)) > 0.9:
            e2 = np.array([0.0, 0.0, 1.0])
        e2 = e2 - np.dot(e2, e1) * e1
        e2 = e2 / np.linalg.norm(e2)
    cx = np.dot(c, e1)
    cy = np.dot(c, e2)
    c_perp = c - cx * e1 - cy * e2
    cz = np.linalg.norm(c_perp)
    return ax, bx, cx, by, cy, cz


def guess_masses_for_symbols(symbols: list[str]) -> dict:
    return {s: PERIODIC_MASSES.get(s, 1.0) for s in symbols}


def nearest_element_by_mass(mass: float) -> str:
    best = None
    best_diff = float("inf")
    for sym, m in PERIODIC_MASSES.items():
        d = abs(m - mass)
        if d < best_diff:
            best_diff = d
            best = sym
    return best or "X"


# ---------------- ASE geometry helpers ----------------
def wrap_positions_in_place(atoms: Atoms):
    if Atoms is None:
        raise RuntimeError("ASE required.")
    try:
        scaled = atoms.get_scaled_positions(wrap=False)
    except TypeError:
        pos = atoms.get_positions()
        cell = np.array(atoms.get_cell(), dtype=float)
        inv_c = np.linalg.inv(cell)
        scaled = pos.dot(inv_c)
    scaled_wrapped = np.mod(scaled, 1.0)
    cell = np.array(atoms.get_cell(), dtype=float)
    atoms.set_positions(scaled_wrapped.dot(cell))


def orthogonalize_and_wrap_atoms(atoms: Atoms) -> Atoms:
    if Atoms is None:
        raise RuntimeError("ASE required.")
    pos = atoms.get_positions()
    cell = np.array(atoms.get_cell(), dtype=float)
    vol = np.linalg.det(cell)
    if abs(vol) < 1e-12:
        raise RuntimeError("Input cell has near-zero volume or invalid cell.")
    inv_c = np.linalg.inv(cell)
    frac = pos.dot(inv_c)
    frac_wrapped = np.mod(frac, 1.0)
    lengths = np.linalg.norm(cell, axis=1)
    new_cell = np.diag(lengths)
    new_pos = frac_wrapped.dot(new_cell)
    new_atoms = Atoms(symbols=atoms.get_chemical_symbols(), positions=new_pos, cell=new_cell, pbc=True)
    for name, arr in getattr(atoms, "arrays", {}).items():
        if name in ("positions",):
            continue
        try:
            new_atoms.set_array(name, np.array(arr))
        except (TypeError, ValueError) as exc:
            print(f"Warning: Could not copy array '{name}' during orthogonalization: {exc}")
    return new_atoms


def is_triclinic(cell: np.ndarray, tol=1e-8) -> bool:
    cm = np.array(cell, dtype=float)
    off = cm.copy()
    np.fill_diagonal(off, 0.0)
    return np.any(np.abs(off) > tol)


def detect_charge_spin(atoms: Atoms) -> tuple[bool, bool, bool]:
    arrs = getattr(atoms, "arrays", {})
    keys = set(arrs.keys())
    has_charge = any(k.lower() == "charge" for k in keys)
    has_spin_any = any(k.lower().startswith("spin") for k in keys)
    has_spin_components = all(k in keys for k in SPIN_KEYS)
    return has_charge, has_spin_any, has_spin_components


def _set_array_if_present(atoms: Atoms, name: str, index: int, default: float = 0.0) -> float:
    arrs = getattr(atoms, "arrays", {})
    return float(arrs[name][index]) if name in arrs else default


def _lammps_data_atom_line(atom_id: int, atom_type: int, position, atoms: Atoms, index: int, mode: int) -> str:
    x, y, z = position
    if mode == 1:
        return f"{atom_id} {atom_type} {x:.12g} {y:.12g} {z:.12g}\n"
    if mode == 2:
        charge = _set_array_if_present(atoms, "charge", index)
        return f"{atom_id} {atom_type} {charge:.6f} {x:.12g} {y:.12g} {z:.12g}\n"
    spin_values = [_set_array_if_present(atoms, key, index) for key in SPIN_KEYS]
    return (
        f"{atom_id} {atom_type} {x:.12g} {y:.12g} {z:.12g} "
        f"{spin_values[0]:.6f} {spin_values[1]:.6f} {spin_values[2]:.6f} {spin_values[3]:.6f}\n"
    )


# ---------------- Writers ----------------
def write_lammps_data_from_ase(filename: str, atoms: Atoms, mode: int = 1):
    natoms = len(atoms)
    symbols = atoms.get_chemical_symbols()
    positions = atoms.get_positions()
    cell = np.array(atoms.get_cell(), dtype=float)
    typemap = build_type_mapping(symbols)
    types = [typemap[s] for s in symbols]
    mass_map_symbol = guess_masses_for_symbols(typemap.keys())
    masses_map = {typemap[sym]: mass_map_symbol[sym] for sym in typemap.keys()}
    ax, bx, cx, by, cy, cz = triangular_cell_components(cell)

    xlo, xhi = 0.0, ax
    ylo, yhi = 0.0, by
    zlo, zhi = 0.0, cz
    xy, xz, yz = bx, cx, cy

    with open(filename, "w", encoding="utf-8") as fh:
        fh.write(f"{GENERATED_HEADER}\n")
        # fh.write("LAMMPS data file (generated by VCL-toolkit)\n\n")
        fh.write(f"{natoms} atoms\n")
        fh.write(f"{len(typemap)} atom types\n\n")
        fh.write(f"{xlo:.12g} {xhi:.12g} xlo xhi\n")
        fh.write(f"{ylo:.12g} {yhi:.12g} ylo yhi\n")
        fh.write(f"{zlo:.12g} {zhi:.12g} zlo zhi\n")
        fh.write(f"{xy:.12g} {xz:.12g} {yz:.12g} xy xz yz\n\n")
        fh.write("Masses\n\n")
        for tid in sorted(masses_map.keys()):
            fh.write(f"{tid} {masses_map[tid]:.6f}\n")
        fh.write("\nAtoms\n\n")
        for i in range(natoms):
            aid = i + 1
            typ = types[i]
            x, y, z = positions[i]
            fh.write(_lammps_data_atom_line(aid, typ, (x, y, z), atoms, i, mode))
    print(f"Wrote LAMMPS data: {filename}")


def _write_lammps_dump_bounds(fh, atoms: Atoms) -> None:
    cell = np.array(atoms.get_cell(), dtype=float)
    ax, bx, cx, by, cy, cz = triangular_cell_components(cell)
    fh.write("ITEM: BOX BOUNDS pp pp pp\n")
    fh.write(f"0 {ax:.12g}\n")
    fh.write(f"0 {by:.12g}\n")
    fh.write(f"0 {cz:.12g}\n")
    fh.write(f"{bx:.12g} {cx:.12g} {cy:.12g}\n")


def _write_lammps_dump_atoms(fh, atoms: Atoms, mode: int) -> None:
    positions = atoms.get_positions()
    symbols = atoms.get_chemical_symbols()
    typemap = build_type_mapping(symbols)
    types = [typemap[symbol] for symbol in symbols]

    if mode == 1:
        fh.write("ITEM: ATOMS id type x y z\n")
    elif mode == 2:
        fh.write("ITEM: ATOMS id type charge x y z\n")
    else:
        fh.write("ITEM: ATOMS id type x y z Spin0 Spin1 Spin2 Spin3\n")

    for index, position in enumerate(positions):
        fh.write(_lammps_data_atom_line(index + 1, types[index], position, atoms, index, mode))


def write_lammps_dump(filename: str, frames: list[Atoms], mode: int = 1):
    if len(frames) == 0:
        raise RuntimeError("No frames to write.")
    with open(filename, "w", encoding="utf-8") as fh:
        fh.write(GENERATED_HEADER)
        for tstep, atoms in enumerate(frames):
            fh.write("ITEM: TIMESTEP\n")
            fh.write(f"{tstep}\n")
            fh.write("ITEM: NUMBER OF ATOMS\n")
            fh.write(f"{len(atoms)}\n")
            _write_lammps_dump_bounds(fh, atoms)
            _write_lammps_dump_atoms(fh, atoms, mode)
    print(f"Wrote LAMMPS dump: {filename}")


# ---------------- Custom Extended XYZ Writer for Ovito ----------------
def write_extxyz_for_ovito(filename: str, frames: list[Atoms]):
    """
    Write extended XYZ format compatible with Ovito.
    This produces the exact format that Ovito expects.
    """
    if len(frames) == 0:
        raise RuntimeError("No frames to write.")

    with open(filename, "w", encoding="utf-8") as fh:
        for atoms in frames:
            natoms = len(atoms)
            symbols = atoms.get_chemical_symbols()
            positions = atoms.get_positions()
            cell = atoms.get_cell()

            # Write number of atoms
            fh.write(f"{natoms}\n")

            # Write lattice information if available
            if cell is not None and np.any(cell):
                cell_matrix = cell.reshape(9)
                fh.write(f'Lattice="{cell_matrix[0]:.6f} {cell_matrix[1]:.6f} {cell_matrix[2]:.6f} ')
                fh.write(f"{cell_matrix[3]:.6f} {cell_matrix[4]:.6f} {cell_matrix[5]:.6f} ")
                fh.write(f'{cell_matrix[6]:.6f} {cell_matrix[7]:.6f} {cell_matrix[8]:.6f}" ')

            # Write properties line
            fh.write("Properties=species:S:1:pos:R:3\n")

            # Write atoms (without element prefix, just space-separated)
            for i in range(natoms):
                symbol = symbols[i]
                x, y, z = positions[i]
                fh.write(f"{symbol} {x:.6f} {y:.6f} {z:.6f}\n")

    print(f"Wrote extended XYZ: {filename}")


# ---------------- LAMMPS-data parser using column counting ----------------
_float_re = r"[-+]?(?:\d+\.\d*|\.\d+|\d+)(?:[eE][-+]?\d+)?"
_float_field_re = f"({_float_re})"
_two_float_fields_re = rf"{_float_field_re}\s+{_float_field_re}"
_three_float_fields_re = rf"{_two_float_fields_re}\s+{_float_field_re}"


def _is_number_token(tok: str) -> bool:
    try:
        float(tok)
        return True
    except ValueError:
        return False


def _parse_atom_count(line: str, current_count: int | None) -> int | None:
    if current_count is not None:
        return current_count
    match = re.match(r"^\s*(\d+)\s+atoms\b", line, re.IGNORECASE)
    return int(match.group(1)) if match else None


def _section_header(line: str) -> str | None:
    line_lower = line.lower()
    if line_lower.startswith("masses"):
        return "masses"
    if line_lower.startswith("atoms"):
        return "atoms"
    return None


def _parse_mass_line(line: str) -> tuple[int, float] | None:
    match = re.match(rf"^\s*(\d+)\s+{_float_field_re}", line)
    return (int(match.group(1)), float(match.group(2))) if match else None


def _parse_bounds_line(line: str) -> tuple[float, float] | None:
    match = re.match(
        rf"^\s*{_two_float_fields_re}\s+(xlo|ylo|zlo)\s+(xhi|yhi|zhi)\s*$",
        line,
        re.IGNORECASE,
    )
    return (float(match.group(1)), float(match.group(2))) if match else None


def _parse_tilt_line(line: str) -> tuple[float, float, float] | None:
    match = re.match(
        rf"^\s*{_three_float_fields_re}\s+xy\s+xz\s+yz\s*$",
        line,
        re.IGNORECASE,
    )
    return (float(match.group(1)), float(match.group(2)), float(match.group(3))) if match else None


def _is_atom_data_line(line: str) -> bool:
    return bool(re.match(r"^\s*\d+", line))


def _is_new_text_section(line: str) -> bool:
    return bool(re.match(r"^[A-Za-z]", line) and not re.match(r"^\d", line))


def _start_lammps_section(line: str, natoms: int | None, section: str | None) -> tuple[int | None, str | None, bool]:
    parsed_natoms = _parse_atom_count(line, natoms)
    if parsed_natoms != natoms:
        return parsed_natoms, section, True

    next_section = _section_header(line)
    if next_section:
        return natoms, next_section, True

    return natoms, section, False


def _collect_lammps_mass(line: str, section: str | None, masses_section: dict[int, float]) -> tuple[str | None, bool]:
    if section != "masses":
        return section, False

    mass_entry = _parse_mass_line(line)
    if mass_entry:
        mass_id, mass = mass_entry
        masses_section[mass_id] = mass
        return section, True

    return None, False


def _collect_lammps_bounds(
    line: str,
    bounds_temp: list[tuple[float, float]],
    bounds: dict[str, tuple[float, float]],
) -> None:
    bounds_entry = _parse_bounds_line(line)
    if bounds_entry:
        bounds_temp.append(bounds_entry)
        if len(bounds_temp) == 3:
            bounds["x"], bounds["y"], bounds["z"] = bounds_temp[:3]


def _collect_lammps_atom_line(line: str, section: str | None, atom_lines: list[str]) -> str | None:
    if section != "atoms":
        return section
    if _is_atom_data_line(line):
        atom_lines.append(line)
        return section
    if _is_new_text_section(line):
        return None
    return section


def _extract_lammps_sections(
    lines: list[str],
) -> tuple[int | None, dict[int, float], dict[str, tuple[float, float]], tuple[float, float, float] | None, list[str]]:
    natoms: int | None = None
    masses_section = {}
    bounds_temp = []
    bounds = {}
    tilt = None
    section = None
    atom_lines = []

    for s in filter(None, lines):
        natoms, section, handled = _start_lammps_section(s, natoms, section)
        if handled:
            continue

        section, handled = _collect_lammps_mass(s, section, masses_section)
        if handled:
            continue

        _collect_lammps_bounds(s, bounds_temp, bounds)
        tilt = _parse_tilt_line(s) or tilt
        section = _collect_lammps_atom_line(s, section, atom_lines)

    return natoms, masses_section, bounds, tilt, atom_lines


def _atom_record(atom_id: int, atom_type: int, x: float, y: float, z: float, charge=None, spin=None) -> dict:
    spin = spin or (0.0, 0.0, 0.0, 0.0)
    return {
        "id": atom_id,
        "type": atom_type,
        "position": (x, y, z),
        "charge": charge,
        "spin": spin,
    }


def _parse_standard_atom_tokens(tokens: list[str]) -> tuple[str, dict] | None:
    token_count = len(tokens)
    last3_numeric = token_count >= 3 and all(_is_number_token(token) for token in tokens[-3:])
    last4_numeric = token_count >= 4 and all(_is_number_token(token) for token in tokens[-4:])

    if token_count == 9 and last4_numeric and all(_is_number_token(tokens[index]) for index in range(2, 5)):
        return "spin", _atom_record(
            int(tokens[0]),
            int(tokens[1]),
            float(tokens[2]),
            float(tokens[3]),
            float(tokens[4]),
            spin=tuple(float(tokens[index]) for index in range(5, 9)),
        )

    if token_count == 6 and _is_number_token(tokens[2]) and last3_numeric:
        return "charge", _atom_record(
            int(tokens[0]),
            int(tokens[1]),
            float(tokens[3]),
            float(tokens[4]),
            float(tokens[5]),
            charge=float(tokens[2]),
        )

    if token_count == 5 and last3_numeric:
        return "classic", _atom_record(
            int(tokens[0]),
            int(tokens[1]),
            float(tokens[2]),
            float(tokens[3]),
            float(tokens[4]),
        )

    return None


def _first_integer_token(tokens: list[str], default: int) -> int:
    for token in tokens:
        if re.match(r"^\d+$", token):
            return int(token)
    return default


def _parse_fallback_atom_tokens(tokens: list[str], line: str, next_atom_id: int) -> tuple[str, dict]:
    for coord_idx in range(len(tokens) - 3, -1, -1):
        coord_tokens = tokens[coord_idx : coord_idx + 3]
        if all(_is_number_token(token) for token in coord_tokens):
            atom_id = _first_integer_token(tokens[: min(4, coord_idx)], next_atom_id)
            atom_type = _first_integer_token(tokens[1:coord_idx], 1)
            x, y, z = (float(token) for token in coord_tokens)
            return "unknown", _atom_record(atom_id, atom_type, x, y, z)

    raise RuntimeError(f"Unable to parse coordinates from atom line: '{line}'")


def _parse_atom_lines(atom_lines: list[str]) -> tuple[list[dict], str | None]:
    records = []
    format_detected = None
    for line in atom_lines:
        tokens = line.split("#")[0].strip().split()
        parsed = _parse_standard_atom_tokens(tokens)
        if parsed is None:
            parsed = _parse_fallback_atom_tokens(tokens, line, len(records) + 1)
        line_format, record = parsed
        records.append(record)
        format_detected = format_detected or line_format

    return records, format_detected


def _symbols_from_types(types: list[int], masses_section: dict[int, float]) -> list[str]:
    if masses_section:
        type_to_symbol = {tid: nearest_element_by_mass(mass) for tid, mass in masses_section.items()}
    else:
        type_to_symbol = dict.fromkeys(sorted(set(types)), "X")
    return [type_to_symbol.get(atom_type, "X") for atom_type in types]


def _apply_lammps_cell(
    atoms: Atoms,
    bounds: dict[str, tuple[float, float]],
    tilt: tuple[float, float, float] | None,
) -> None:
    if not {"x", "y", "z"}.issubset(bounds):
        return

    xlo, xhi = bounds["x"]
    ylo, yhi = bounds["y"]
    zlo, zhi = bounds["z"]
    bx, cx, cy = tilt or (0.0, 0.0, 0.0)
    cell = np.array(
        [
            [xhi - xlo, 0.0, 0.0],
            [bx, yhi - ylo, 0.0],
            [cx, cy, zhi - zlo],
        ]
    )
    atoms.set_cell(cell)
    atoms.set_pbc(True)
    atoms.set_positions(atoms.get_positions() - np.array([xlo, ylo, zlo]))


def parse_lammps_data(path: str) -> Atoms:
    """
    Parse a LAMMPS data file, using column counting to identify format.

    Supported atom rows are classic (id type x y z), charge
    (id type charge x y z), and spin (id type x y z Spin0 Spin1 Spin2 Spin3).
    Non-standard rows fall back to a rightmost-coordinate heuristic.
    """
    with open(path) as fh:
        stripped = [line.strip() for line in fh]

    natoms, masses_section, bounds, tilt, atom_lines = _extract_lammps_sections(stripped)
    if not atom_lines:
        raise RuntimeError(f"No atom lines parsed from '{path}'. (checked {len(stripped)} lines)")

    if natoms is None:
        natoms = len(atom_lines)
        print(f"Warning: Could not find 'atoms' count in header, using {natoms} from atom lines.")

    records, format_detected = _parse_atom_lines(atom_lines)
    ids = [record["id"] for record in records]
    types = [record["type"] for record in records]
    positions = np.array([record["position"] for record in records], dtype=float)

    print(f"Detected format: {format_detected}")
    print(f"Parsed {len(ids)} atoms from {len(atom_lines)} atom lines")

    atoms = Atoms(symbols=_symbols_from_types(types, masses_section), positions=positions, pbc=True)
    _apply_lammps_cell(atoms, bounds, tilt)

    if format_detected == "spin":
        spins = np.array([record["spin"] for record in records], dtype=float)
        for index, spin_key in enumerate(SPIN_KEYS):
            atoms.set_array(spin_key, spins[:, index])

    charges = [record["charge"] for record in records]
    if format_detected == "charge" or any(charge is not None for charge in charges):
        atoms.set_array("charge", np.array([0.0 if charge is None else charge for charge in charges], dtype=float))

    return atoms


# ---------------- Read frames with ASE and fallback to parser ----------------
def _as_frame_list(frames) -> list[Atoms]:
    return [frames] if isinstance(frames, Atoms) else frames


def _read_lammps_data_with_custom_parser(path: str, ext: str) -> list[Atoms] | None:
    if ext not in (".lmp", ".data"):
        return None
    try:
        return [parse_lammps_data(path)]
    except Exception as e_parse:
        print(f"Custom parser failed: {e_parse}, trying ASE...")
        return None


def _fallback_lammps_formats(ext: str) -> list[str]:
    return ["lammps-dump"] if ext in LAMMPS_DUMP_EXTENSIONS else []


def _read_with_specific_formats(path: str, formats: list[str]) -> list[Atoms] | None:
    for fmt in formats:
        try:
            return _as_frame_list(aseio.read(path, format=fmt, index=":"))
        except Exception as exc:
            print(f"Warning: ASE could not read '{path}' as {fmt}: {exc}")
    return None


def read_frames_with_ase(path: str) -> list[Atoms]:
    if aseio is None:
        raise RuntimeError("ASE not installed.")

    ext = os.path.splitext(path)[1].lower()
    custom_frames = _read_lammps_data_with_custom_parser(path, ext)
    if custom_frames is not None:
        return custom_frames

    tried = _fallback_lammps_formats(ext)
    try:
        return _as_frame_list(aseio.read(path, index=":"))
    except Exception as e_auto:
        format_frames = _read_with_specific_formats(path, tried)
        if format_frames is not None:
            return format_frames

        try:
            return [aseio.read(path, index=0)]
        except Exception as e_final:
            raise RuntimeError(
                f"ASE failed to read '{path}'. Autodetect error: {e_auto}. "
                f"Attempted formats: {tried}. Last error: {e_final}"
            ) from e_final


def _copy_optional_arrays(source: Atoms, target: Atoms) -> None:
    for name, arr in getattr(source, "arrays", {}).items():
        if name in ("positions",):
            continue
        try:
            target.set_array(name, np.array(arr))
        except (TypeError, ValueError) as exc:
            print(f"Warning: Could not copy array '{name}': {exc}")


def infer_box_from_frames(frames: list[Atoms]) -> tuple[np.ndarray, list[Atoms]]:
    all_mins = np.array([np.min(f.get_positions(axis=0), axis=0) for f in frames])
    all_maxs = np.array([np.max(f.get_positions(axis=0), axis=0) for f in frames])
    global_min = np.min(all_mins, axis=0)
    global_max = np.max(all_maxs, axis=0)
    lengths = global_max - global_min
    tiny = 1.0
    lengths = np.where(lengths < 1e-8, tiny, lengths)
    new_cell = np.diag(lengths)
    new_frames = []
    for f in frames:
        pos = f.get_positions()
        pos_shifted = pos - global_min
        new_at = Atoms(symbols=f.get_chemical_symbols(), positions=pos_shifted, cell=new_cell, pbc=True)
        _copy_optional_arrays(f, new_at)
        new_frames.append(new_at)
    return new_cell, new_frames


def _cell_volume(cell: np.ndarray) -> float:
    try:
        return float(np.linalg.det(cell))
    except np.linalg.LinAlgError:
        return 0.0


def _wrap_frame_with_fallback(frame: Atoms) -> None:
    try:
        wrap_positions_in_place(frame)
        return
    except (TypeError, ValueError, np.linalg.LinAlgError) as exc:
        print(f"Warning: Standard position wrapping failed: {exc}. Trying direct fractional wrap.")

    try:
        pos = frame.get_positions()
        cell = np.array(frame.get_cell(), dtype=float)
        frac = pos.dot(np.linalg.inv(cell))
        frame.set_positions(np.mod(frac, 1.0).dot(cell))
    except (TypeError, ValueError, np.linalg.LinAlgError) as exc:
        print(f"Warning: Could not wrap positions for frame: {exc}")


def _orthogonalize_frames(frames: list[Atoms]) -> list[Atoms]:
    new_frames = []
    for frame in frames:
        try:
            new_frames.append(orthogonalize_and_wrap_atoms(frame))
        except (RuntimeError, ValueError, np.linalg.LinAlgError) as exc:
            print(f"Orthogonalize failed: {exc}. Wrapping only.")
            _wrap_frame_with_fallback(frame)
            new_frames.append(frame)
    return new_frames


def maybe_orthogonalize_and_apply(frames: list[Atoms], orthogonalize: bool = True) -> list[Atoms]:
    """Apply orthogonalization if requested, otherwise just wrap positions."""
    if not frames:
        return frames

    first = frames[0]
    cell = np.array(first.get_cell(), dtype=float)
    vol = _cell_volume(cell)

    if abs(vol) < 1e-12:
        # If cell is invalid (e.g., zero volume), do not try to orthogonalize, just return
        return frames

    if orthogonalize:
        if is_triclinic(cell):
            _, bx, cx, _, cy, _ = triangular_cell_components(cell)
            print(f"Your cell appears triclinic with tilt-values: xy={bx:.6g}, xz={cx:.6g}, yz={cy:.6g}")
            print("Making it orthogonal as requested.")
            return _orthogonalize_frames(frames)
        else:
            print("Your cell is orthogonal. Unskewing and aligning as requested.")
            return _orthogonalize_frames(frames)

    print("Keeping original cell geometry (no orthogonalization).")
    for frame in frames:
        _wrap_frame_with_fallback(frame)
    return frames


# ---------------- Format Detection ----------------
def is_lammps_format(filename: str) -> bool:
    """Check if filename extension indicates LAMMPS format."""
    ext = os.path.splitext(filename)[1].lower()
    return ext in LAMMPS_FILE_EXTENSIONS


def get_output_format_from_extension(filename: str) -> str:
    """Get format string from file extension."""
    ext = os.path.splitext(filename)[1].lower().lstrip(".")
    extension_map = {
        "lmp": "lammps_data",
        "data": "lammps_data",
        "lammps": "lammps_data",
        LAMMPS_DUMP_EXT.lstrip("."): "lammps_dump",
        LAMMPS_TRAJ_EXT.lstrip("."): "lammps_dump",
        "cif": "cif",
        "xyz": "extxyz",
        "cfg": "cfg",
        "xsf": "xsf",
        "vasp": "vasp",
        "poscar": "vasp",
        "contcar": "vasp",
        "pdb": "pdb",
        "ent": "pdb",
        "extxyz": "extxyz",
    }
    return extension_map.get(ext, "extxyz")


def _prepare_frames_for_output(frames: list[Atoms], orthogonalize: bool) -> list[Atoms]:
    first_cell = np.array(frames[0].get_cell(), dtype=float)
    if abs(_cell_volume(first_cell)) < 1e-12:
        _, frames = infer_box_from_frames(frames)
        print("Inferred orthogonal cell (no cell present in input).")
        return frames
    return maybe_orthogonalize_and_apply(frames, orthogonalize)


def _remove_arrays_by_predicate(frame: Atoms, should_remove) -> None:
    for name in tuple(getattr(frame, "arrays", {})):
        if should_remove(name):
            frame.arrays.pop(name, None)


def _apply_classic_lammps_mode(frame: Atoms) -> None:
    _remove_arrays_by_predicate(
        frame,
        lambda name: name.lower() == "charge" or name.lower().startswith("spin"),
    )


def _apply_charge_lammps_mode(frame: Atoms) -> None:
    _remove_arrays_by_predicate(frame, lambda name: name.lower().startswith("spin"))
    if "charge" not in getattr(frame, "arrays", {}):
        frame.set_array("charge", np.zeros(len(frame)), dtype=float)


def _apply_spin_lammps_mode(frame: Atoms) -> None:
    _remove_arrays_by_predicate(frame, lambda name: name.lower() == "charge")
    for spin_key in SPIN_KEYS:
        if spin_key not in getattr(frame, "arrays", {}):
            frame.set_array(spin_key, np.zeros(len(frame)), dtype=float)


def _configure_lammps_mode(frames: list[Atoms], target_mode: str) -> int:
    mode_config = {
        "classic": (1, "Using LAMMPS classic format (mode 1)", _apply_classic_lammps_mode),
        "charge": (2, "Using LAMMPS charge format (mode 2)", _apply_charge_lammps_mode),
        "spin": (3, "Using LAMMPS spin format (mode 3)", _apply_spin_lammps_mode),
    }
    try:
        mode, message, apply_mode = mode_config[target_mode]
    except KeyError as exc:
        raise ValueError(f"Unknown target_mode: {target_mode}") from exc

    for frame in frames:
        apply_mode(frame)
    print(message)
    return mode


def _write_lammps_output(output_file: str, frames: list[Atoms], target_mode: str) -> str:
    mode = _configure_lammps_mode(frames, target_mode)
    if len(frames) == 1:
        write_lammps_data_from_ase(output_file, frames[0], mode=mode)
        return output_file

    base, ext = os.path.splitext(output_file)
    dump_file = output_file if ext.lower() in (LAMMPS_DUMP_EXT, LAMMPS_TRAJ_EXT) else base + LAMMPS_DUMP_EXT
    write_lammps_dump(dump_file, frames, mode=mode)
    return dump_file


def _write_single_ase_frame(output_file: str, frame: Atoms, output_format: str) -> None:
    try:
        write(output_file, frame, format=output_format)
        prepend_vcl_header(output_file)
        print(f"Converted to {output_format.upper()}: {output_file}")
    except Exception as exc:
        print(f"Error writing to {output_format}: {exc}")
        try:
            write(output_file, frame)
            prepend_vcl_header(output_file)
            print(f"Converted (using ASE default): {output_file}")
        except Exception as fallback_exc:
            print(f"Failed to write file: {fallback_exc}")


def _write_individual_frames(base: str, ext: str, frames: list[Atoms], output_format: str) -> None:
    for index, frame in enumerate(frames):
        frame_file = f"{base}_frame{index}{ext}"
        if output_format == "extxyz":
            write_extxyz_for_ovito(frame_file, [frame])
        else:
            write(frame_file, frame, format=output_format)
            prepend_vcl_header(frame_file)
        print(f"  Wrote frame {index}: {frame_file}")


def _write_multiple_ase_frames(output_file: str, frames: list[Atoms], output_format: str) -> None:
    base, ext = os.path.splitext(output_file)
    if output_format in ("xyz", "xsf", "extxyz"):
        try:
            if output_format == "extxyz":
                write_extxyz_for_ovito(output_file, frames)
            else:
                write(output_file, frames, format=output_format)
                prepend_vcl_header(output_file)
            print(f"Converted {len(frames)} frames to {output_format.upper()}: {output_file}")
            return
        except Exception as exc:
            print(f"Warning: Could not write multiple frames to single {output_format} file: {exc}")

    _write_individual_frames(base, ext, frames, output_format)


def _write_non_lammps_output(output_file: str, frames: list[Atoms], output_format: str) -> bool:
    if write is None:
        print("ERROR: ASE write module not available")
        return False

    if output_format == "extxyz":
        write_extxyz_for_ovito(output_file, frames)
        print(f"Converted to extended XYZ: {output_file}")
        return False

    if len(frames) == 1:
        _write_single_ase_frame(output_file, frames[0], output_format)
    else:
        _write_multiple_ase_frames(output_file, frames, output_format)
    return True


# ---------------- Main Conversion Function ----------------
def convert_file(input_file: str, output_file: str, target_mode: str = "classic", orthogonalize: bool = True):
    """Main conversion function that handles all formats automatically."""
    if aseio is None:
        print("ERROR: ASE not installed. pip install ase")
        return

    # Normalize paths
    input_file = normalize_path_for_os(input_file)
    output_file = normalize_path_for_os(output_file)

    if not os.path.exists(input_file):
        print(f"Error: Input file not found: {input_file}")
        return

    print(f"Converting: {input_file} -> {output_file}")
    print(f"Target mode: {target_mode}")
    print(f"Orthogonalize: {'yes' if orthogonalize else 'no'}")

    frames = read_frames_with_ase(input_file)
    print(f"Read {len(frames)} frame(s).")

    output_format = get_output_format_from_extension(output_file)
    print(f"Output format: {output_format}")

    frames = _prepare_frames_for_output(frames, orthogonalize)

    if output_format.startswith("lammps"):
        output_file = _write_lammps_output(output_file, frames, target_mode)
    elif not _write_non_lammps_output(output_file, frames, output_format):
        return

    # Print success message
    print("\n✓✓✓ SUCCESS! ✓✓✓")
    print(f"Converted: {input_file} -> {output_file}")


# ---------------- CLI Mode Functions ----------------
def _parse_config_line(line: str) -> tuple[str, str] | None:
    line = line.strip()
    if not line or line.startswith("#"):
        return None
    parts = line.split(maxsplit=1)
    if len(parts) < 2:
        return None
    return parts[0].strip(), parts[1].strip()


def _parse_target_mode(value: str) -> str:
    mode = value.lower()
    if mode in {"classic", "charge", "spin"}:
        return mode
    raise ValueError(f"Invalid charge/spin value: {value}. Must be 'classic', 'charge', or 'spin'")


def _parse_yes_no(value: str, key: str) -> bool:
    value_lower = value.lower()
    if value_lower in {"yes", "y", "true", "1"}:
        return True
    if value_lower in {"no", "n", "false", "0"}:
        return False
    raise ValueError(f"Invalid {key} value: {value}. Must be 'yes' or 'no'")


def _apply_input_param(params: dict, key: str, value: str) -> None:
    param_handlers = {
        "input_file": lambda raw_value: raw_value,
        "output_file": lambda raw_value: raw_value,
        "charge/spin": _parse_target_mode,
        "unskew_and_align": lambda raw_value: _parse_yes_no(raw_value, "unskew_and_align"),
    }
    param_names = {
        "input_file": "input_file",
        "output_file": "output_file",
        "charge/spin": "target_mode",
        "unskew_and_align": "orthogonalize",
    }
    if key in param_handlers:
        params[param_names[key]] = param_handlers[key](value)


def _validate_input_params(params: dict) -> None:
    if "input_file" not in params:
        raise ValueError("Missing 'input_file' in input file")
    if "output_file" not in params:
        raise ValueError("Missing 'output_file' in input file")


def parse_input_file(input_file_path: str) -> dict:
    """Parse the simple input file format:
    input_file ./FeCr.xyz
    output_file ./FeCr.lmp
    charge/spin classic/charge/spin
    unskew_and_align yes/no
    """
    params = {}
    with open(input_file_path) as f:
        for line in f:
            config_line = _parse_config_line(line)
            if config_line is None:
                continue
            _apply_input_param(params, *config_line)

    _validate_input_params(params)
    return {"target_mode": "classic", "orthogonalize": True, **params}


# ---------------- Interactive operations ----------------
def _ensure_ase_available() -> bool:
    if aseio is None:
        print("ERROR: ASE not installed. pip install ase")
        return False
    return True


def _ask_existing_file(prompt: str) -> str | None:
    infile = normalize_path_for_os(ask(prompt))
    if os.path.exists(infile):
        return infile
    print("File not found:", infile)
    return None


def _ask_orthogonalize() -> bool:
    return ask("Would you like to unskew and align it? (Y/n)", "Y").strip().lower() not in ("n", "no")


def convert_to_classic_md_interactive():
    if not _ensure_ase_available():
        return
    infile = _ask_existing_file("Please enter structure filename (in current directory)")
    if infile is None:
        return
    out_default = os.path.splitext(os.path.basename(infile))[0] + "_classic.data"
    outname = ask("Enter desired output filename for modified LAMMPS file", out_default)
    convert_file(infile, outname, target_mode="classic", orthogonalize=_ask_orthogonalize())


def add_charge_interactive():
    if not _ensure_ase_available():
        return
    infile = _ask_existing_file("Enter structure filename (current directory)")
    if infile is None:
        return
    orthogonalize = _ask_orthogonalize()
    out_default = os.path.splitext(os.path.basename(infile))[0] + "_charge.data"
    outname = ask("Output filename for charged LAMMPS file", out_default)
    convert_file(infile, outname, target_mode="charge", orthogonalize=orthogonalize)


def add_spin_interactive():
    if not _ensure_ase_available():
        return
    infile = _ask_existing_file("Enter structure filename (current directory)")
    if infile is None:
        return
    orthogonalize = _ask_orthogonalize()
    out_default = os.path.splitext(os.path.basename(infile))[0] + "_spin.data"
    outname = ask("Output filename for spin LAMMPS file", out_default)
    convert_file(infile, outname, target_mode="spin", orthogonalize=orthogonalize)


def convert_from_lammps_interactive():
    """Interactive mode for converting FROM LAMMPS to other formats."""
    if not _ensure_ase_available():
        return
    infile = _ask_existing_file("Enter input filename")
    if infile is None:
        return
    base_name = os.path.splitext(os.path.basename(infile))[0]
    out_default = base_name + ".cif"
    outname = ask("Enter output filename (extension determines format, e.g., .cif, .xyz, .cfg)", out_default)
    convert_file(infile, outname, target_mode="classic", orthogonalize=_ask_orthogonalize())


def _read_replication_factors() -> tuple[int, int, int] | None:
    rep_str = ask("Enter replication factors nx ny nz (e.g. '2 2 1')", "1 1 1")
    try:
        factors = tuple(int(value) for value in rep_str.split())
    except ValueError:
        print("Invalid replication factors.")
        return None
    if len(factors) != 3:
        print("Invalid replication factors.")
        return None
    return factors


def _replication_lammps_mode(frame: Atoms) -> int:
    has_charge, has_spin_any, _ = detect_charge_spin(frame)
    if has_charge:
        return 2
    if has_spin_any:
        return 3
    return 1


def _write_replicated_lammps(outname: str, rep_frames: list[Atoms], original_frames: list[Atoms]) -> str:
    mode = _replication_lammps_mode(original_frames[0])
    if len(rep_frames) == 1:
        write_lammps_data_from_ase(outname, rep_frames[0], mode=mode)
        return outname
    outdump = os.path.splitext(outname)[0] + LAMMPS_DUMP_EXT
    write_lammps_dump(outdump, rep_frames, mode=mode)
    return outdump


def _write_replicated_ase(outname: str, rep_frames: list[Atoms], output_format: str) -> str:
    if len(rep_frames) == 1:
        if output_format == "extxyz":
            write_extxyz_for_ovito(outname, rep_frames)
        else:
            aseio.write(outname, rep_frames[0])
            prepend_vcl_header(outname)
        return outname

    try:
        if output_format == "extxyz":
            write_extxyz_for_ovito(outname, rep_frames)
        else:
            aseio.write(outname, rep_frames)
            prepend_vcl_header(outname)
        return outname
    except Exception as exc:
        print(f"Warning: Could not write replicated frames as {output_format}: {exc}")
        outxyz = os.path.splitext(outname)[0] + ".xyz"
        write_extxyz_for_ovito(outxyz, rep_frames)
        return outxyz


def replicate_only_interactive():
    if not _ensure_ase_available():
        return
    infile = _ask_existing_file("Enter filename to replicate (current directory)")
    if infile is None:
        return
    factors = _read_replication_factors()
    if factors is None:
        return
    nx, ny, nz = factors
    frames = read_frames_with_ase(infile)
    rep_frames = [frame.repeat(factors) for frame in frames]

    base, ext = os.path.splitext(os.path.basename(infile))
    suggested = f"{base}_rep{nx}x{ny}x{nz}{ext}"
    orthogonalize = _ask_orthogonalize()
    outname = ask("Output filename for replicated file", suggested)
    rep_frames = maybe_orthogonalize_and_apply(rep_frames, orthogonalize) if orthogonalize else rep_frames
    output_format = get_output_format_from_extension(outname)

    try:
        if output_format.startswith("lammps"):
            outname = _write_replicated_lammps(outname, rep_frames, frames)
        else:
            outname = _write_replicated_ase(outname, rep_frames, output_format)
        print("\n✓✓✓ SUCCESS! ✓✓✓")
        print(f"Your replicated structure is ready: {outname}")
    except Exception as e:
        print("Failed to write replicated file:", e)


# ---------------- Main menu ----------------
def run_input_convertor_app():
    if aseio is None:
        print("ERROR: ASE required. pip install ase")
        return
    print("************************************************")
    print("Welcome to the LAMMPS Input File Converter! (:")
    print("************************************************")
    while True:
        print("\n--- LAMMPS Format Converter ---")
        print("0. Exit")
        print("1. Convert file (auto-detect format from extension)")
        print("2. Add charge to a file (for LAMMPS)")
        print("3. Add spin to a file (for LAMMPS)")
        print("4. Replicate a structure")
        choice = ask("Select an option (0-4)", "0")
        if choice == "0":
            print("Exiting converter.")
            return
        elif choice == "1":
            convert_to_classic_md_interactive()
        elif choice == "2":
            add_charge_interactive()
        elif choice == "3":
            add_spin_interactive()
        elif choice == "4":
            replicate_only_interactive()
        else:
            print("Invalid choice.")


# ---------------- Main function ----------------
def main():
    if aseio is None:
        print("ERROR: ASE required. Please install ASE: pip install ase")
        sys.exit(1)

    # Check if input file is provided as command line argument
    if len(sys.argv) > 1:
        input_file = sys.argv[1]
        try:
            params = parse_input_file(input_file)
            convert_file(params["input_file"], params["output_file"], params["target_mode"], params["orthogonalize"])
        except Exception as e:
            print(f"Error processing input file: {e}")
            print("\nInput file format should be:")
            print("input_file ./FeCr.xyz")
            print("output_file ./FeCr.lmp")
            print("charge/spin classic/charge/spin  # optional, default: classic")
            print("unskew_and_align yes/no          # optional, default: yes")
            print("\nOr:")
            print("input_file ./FeCr.lmp")
            print("output_file ./FeCr.cif")
            print("unskew_and_align yes/no          # optional, default: yes")
            print("\nThe script automatically detects conversion direction from file extensions.")
            print("\nNOTE: .xyz files will be written in extended XYZ format")
            sys.exit(1)
    else:
        # Run interactive mode
        run_input_convertor_app()


if __name__ == "__main__":
    main()

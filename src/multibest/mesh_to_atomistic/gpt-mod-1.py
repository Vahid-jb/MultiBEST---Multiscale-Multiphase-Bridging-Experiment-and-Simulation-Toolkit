#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 bright-ideas-clan
#
# SPDX-License-Identifier: GPL-3.0-or-later


"""
gpt-mesh.py

Single-file tool that:
 - builds atomistic "guest" phases by voxelizing an input mesh and filling with a lattice (CIF or ASE bulk),
 - allows "void" phases (do nothing),
 - builds "base" phases as bulk/slab using CIF or ASE bulk,
 - writes individual phase XYZ files,
 - integrates with Ovito_Delete_Robust.py for merging and manipulate.py for final processing.

Input: text file (see example in your message). Run:
    python gpt-mesh.py input.txt

Notes:
 - Per-phase options supported: --cif, --pitch, --padding-angstrom, --mask-dilate,
   --force-tri, --euler <3 floats>, --dilate, --close, --out <path>.
 - "guest" phases are voxel-filled (using CIF if given). "base" phases are generated as repeated bulk from CIF or ASE.
 - "void" phases are read but produce no atoms.
 - Global options: --merge, --pbc, --out, --charge, --spin for final processing.
"""

import argparse
import math
import os
import shlex
import subprocess
import sys
from collections import deque
from pathlib import Path

import numpy as np

# geometry / mesh / voxel libs
import trimesh

# ASE for lattice, I/O
from ase import Atoms
from ase import io as ase_io
from ase.build import bulk
from ase.data import atomic_numbers, covalent_radii
from scipy import ndimage
from scipy.spatial import KDTree
from skimage.morphology import closing
from tqdm import tqdm

# Force UTF-8 encoding for standard output and error
if sys.platform == "win32":
    for stream in (sys.stdout, sys.stderr):
        if stream is not None and hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

# Import pymeshlab for mesh rescaling

global_filling_method = "flood"
NEIGHBOR_OFFSETS = [(-1, 0, 0), (1, 0, 0), (0, -1, 0), (0, 1, 0), (0, 0, -1), (0, 0, 1)]
TEMP_MERGED_XYZ = "temp_merged.xyz"
TEMP_HIERARCHICAL_FINAL_XYZ = "temp_hierarchical_final.xyz"
SCRIPT_DIR = Path(__file__).resolve().parent
SUBPROCESS_TEXT_KWARGS = {"encoding": "utf-8", "errors": "replace"}
TRUTHY_VALUES = {"1", "true", "yes", "on"}

# -------------------------
# Small utilities
# -------------------------


def sibling_command(script_name, *args):
    if getattr(sys, "frozen", False):
        suffix = ".exe" if sys.platform == "win32" else ""
        executable = Path(sys.executable).resolve().parent / (Path(script_name).stem + suffix)
        return [str(executable), *args]

    return [sys.executable, str(SCRIPT_DIR / script_name), *args]


def _is_truthy(value):
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in TRUTHY_VALUES


def deg2rad(a):  # pragma: no cover
    return float(a) * np.pi / 180.0


def rotation_matrix_from_euler(phi1_deg, phi_deg, phi2_deg):  # pragma: no cover
    phi1 = deg2rad(phi1_deg)
    phi = deg2rad(phi_deg)
    phi2 = deg2rad(phi2_deg)

    def rz(t):  # pragma: no cover
        c = np.cos(t)
        s = np.sin(t)
        return np.array([[c, -s, 0.0], [s, c, 0.0], [0.0, 0.0, 1.0]])

    def rx(t):  # pragma: no cover
        c = np.cos(t)
        s = np.sin(t)
        return np.array([[1.0, 0.0, 0.0], [0.0, c, -s], [0.0, s, c]])

    return rz(phi1) @ rx(phi) @ rz(phi2)


def _seed_boundary_voxels(closed):  # pragma: no cover
    nx, ny, nz = closed.shape
    visited = np.zeros_like(closed, dtype=bool)
    q = deque()
    boundary_planes = (
        (range(nx), range(ny), (0, nz - 1)),
        (range(nx), (0, ny - 1), range(nz)),
        ((0, nx - 1), range(ny), range(nz)),
    )
    for xs, ys, zs in boundary_planes:
        _seed_boundary_plane(closed, visited, q, xs, ys, zs)
    return visited, q


def _seed_boundary_plane(closed, visited, q, xs, ys, zs):  # pragma: no cover
    for ix in xs:
        for iy in ys:
            for iz in zs:
                if not closed[ix, iy, iz] and not visited[ix, iy, iz]:
                    q.append((ix, iy, iz))
                visited[ix, iy, iz] = True


def _flood_outside_voxels(closed):  # pragma: no cover
    nx, ny, nz = closed.shape
    outside = np.zeros_like(closed, dtype=bool)
    visited, q = _seed_boundary_voxels(closed)
    while q:
        x, y, z = q.popleft()
        outside[x, y, z] = True
        for dx, dy, dz in NEIGHBOR_OFFSETS:
            nx0, ny0, nz0 = x + dx, y + dy, z + dz
            if 0 <= nx0 < nx and 0 <= ny0 < ny and 0 <= nz0 < nz:
                if not closed[nx0, ny0, nz0] and not visited[nx0, ny0, nz0]:
                    visited[nx0, ny0, nz0] = True
                    q.append((nx0, ny0, nz0))
    return outside


def _rotation_matrix_xyz(rotate):  # pragma: no cover
    rx_deg, ry_deg, rz_deg = rotate
    rx_rad = math.radians(rx_deg)
    ry_rad = math.radians(ry_deg)
    rz_rad = math.radians(rz_deg)
    rot_x = np.array([[1, 0, 0], [0, math.cos(rx_rad), -math.sin(rx_rad)], [0, math.sin(rx_rad), math.cos(rx_rad)]])
    rot_y = np.array([[math.cos(ry_rad), 0, math.sin(ry_rad)], [0, 1, 0], [-math.sin(ry_rad), 0, math.cos(ry_rad)]])
    rot_z = np.array([[math.cos(rz_rad), -math.sin(rz_rad), 0], [math.sin(rz_rad), math.cos(rz_rad), 0], [0, 0, 1]])
    return rot_z @ rot_y @ rot_x


# -------------------------
# Triangle-box intersection (Möller triBoxOverlap adapted)
# -------------------------


def tri_box_overlap(
    box_center, box_half_diag, triverts
):  # pragma: no cover  # NOSONAR - legacy CLI workflow kept intact for behavior parity

    v0 = triverts[0] - box_center
    v1 = triverts[1] - box_center
    v2 = triverts[2] - box_center
    e0 = v1 - v0
    e1 = v2 - v1
    e2 = v0 - v2
    boxhalf = box_half_diag

    def axis_test(a, b, fa, fb, v0, v1, v2, boxhalf):  # pragma: no cover

        p0 = a * v0[1] - b * v0[2]
        p1 = a * v1[1] - b * v1[2]
        p2 = a * v2[1] - b * v2[2]
        min_p = min(p0, p1, p2)
        max_p = max(p0, p1, p2)
        rad = fa * boxhalf[1] + fb * boxhalf[2]
        if min_p > rad or max_p < -rad:
            return False
        return True

    axis_tests = (
        (e0[2], e0[1], abs(e0[2]), abs(e0[1])),
        (e0[2], e0[0], abs(e0[2]), abs(e0[0])),
        (e0[1], e0[0], abs(e0[1]), abs(e0[0])),
        (e1[2], e1[1], abs(e1[2]), abs(e1[1])),
        (e1[2], e1[0], abs(e1[2]), abs(e1[0])),
        (e1[1], e1[0], abs(e1[1]), abs(e1[0])),
        (e2[2], e2[1], abs(e2[2]), abs(e2[1])),
        (e2[2], e2[0], abs(e2[2]), abs(e2[0])),
        (e2[1], e2[0], abs(e2[1]), abs(e2[0])),
    )
    if not all(axis_test(a, b, fa, fb, v0, v1, v2, boxhalf) for a, b, fa, fb in axis_tests):
        return False

    for i in range(3):
        min_v = min(v0[i], v1[i], v2[i])
        max_v = max(v0[i], v1[i], v2[i])
        if min_v > boxhalf[i] or max_v < -boxhalf[i]:
            return False

    normal = np.cross(e0, e1)
    d = -np.dot(normal, v0)
    r = boxhalf[0] * abs(normal[0]) + boxhalf[1] * abs(normal[1]) + boxhalf[2] * abs(normal[2])
    s = d

    if abs(s) > r:
        return False
    return True


def extract_interior_unified(
    surface_matrix, forced_method=None, verbose=True
):  # pragma: no cover  # NOSONAR - legacy CLI workflow kept intact for behavior parity
    """
    forced_method: 'flood', 'parity', or None (auto)
    """
    # Access the global variable directly instead of importing
    # Determine which method to use
    if forced_method == "parity" or global_filling_method == "parity":
        # Use parity fill
        if verbose:
            print("  Using parity fill (global setting)...")
        return parity_fill_all_axes(surface_matrix, verbose)
    if verbose:
        print("Unified interior extraction...")
        print("  Attempting flood-fill method...")

    closed = surface_matrix
    interior = ~_flood_outside_voxels(closed) & ~closed

    if np.count_nonzero(interior) == 0:
        if verbose:
            print("  Flood-fill failed, falling back to parity fill...")
        return parity_fill_all_axes(surface_matrix, verbose)

    if verbose:
        print(f"  Flood-fill succeeded: {np.count_nonzero(interior)} interior voxels")
    return interior


def parity_fill_all_axes(surface_matrix, verbose=True):  # pragma: no cover
    """
    Try parity fill along all three axes and return the best result.
    """
    if verbose:
        print("  Trying parity fill along all axes...")

    best_interior = None
    best_count = 0

    for axis in [2, 0, 1]:  # Try z, x, y axes
        interior = parity_fill_along_axis(surface_matrix, axis, verbose=False)
        count = interior.sum()

        if verbose:
            print(f"    Axis {axis}: {count} interior voxels")

        if count > best_count:
            best_count = count
            best_interior = interior

    if best_interior is None or best_count == 0:
        if verbose:
            print("  All parity attempts failed")
        return np.zeros_like(surface_matrix, dtype=bool)

    if verbose:
        print(f"  Selected axis with {best_count} interior voxels")
    return best_interior


# -------------------------
# Triangle voxelizer (extended)
# -------------------------


def voxelize_mesh_by_triangles_extended(mesh, pitch, mesh_min, mesh_max, verbose=True):  # pragma: no cover

    mins = np.array(mesh_min) - pitch
    maxs = np.array(mesh_max) + pitch
    dims = np.ceil((maxs - mins) / pitch).astype(int) + 1
    nx, ny, nz = dims.tolist()
    if verbose:
        print("Triangle voxelization with extended bounds: dims", dims, " pitch", pitch)

    matrix = np.zeros((nx, ny, nz), dtype=bool)
    faces = mesh.faces

    if faces.ndim == 1:
        faces = faces.reshape(-1, 3)
    verts = mesh.vertices

    for fi in tqdm(range(len(faces)), desc="Rasterizing triangles"):
        _rasterize_triangle_voxels(matrix, verts[faces[fi]], mins, dims, pitch)
    origin = mins
    return matrix, origin


def _rasterize_triangle_voxels(matrix, tri, mins, dims, pitch):  # pragma: no cover
    tri_min = np.min(tri, axis=0)
    tri_max = np.max(tri, axis=0)
    imin = np.floor((tri_min - mins) / pitch).astype(int)
    imax = np.floor((tri_max - mins) / pitch).astype(int)
    ix0, iy0, iz0 = np.maximum(imin, 0)
    ix1, iy1, iz1 = np.minimum(imax, dims - 1)
    box_half = np.array([pitch / 2.0, pitch / 2.0, pitch / 2.0])

    for ix in range(ix0, ix1 + 1):
        xcenter = mins[0] + (ix + 0.5) * pitch
        for iy in range(iy0, iy1 + 1):
            ycenter = mins[1] + (iy + 0.5) * pitch
            for iz in range(iz0, iz1 + 1):
                zcenter = mins[2] + (iz + 0.5) * pitch
                box_center = np.array([xcenter, ycenter, zcenter])
                if tri_box_overlap(box_center, box_half, tri):
                    matrix[ix, iy, iz] = True


# -------------------------
# Flood-fill interior extraction
# -------------------------


def fill_voxel_interior(
    surface_matrix, verbose=True
):  # pragma: no cover  # NOSONAR - legacy CLI workflow kept intact for behavior parity

    if verbose:
        print("Filling / closing voxel surface to compute interior mask ...")
    closed = closing(surface_matrix, footprint=np.ones((3, 3, 3)))
    outside = _flood_outside_voxels(closed)
    interior = ~outside & ~closed
    if np.count_nonzero(interior) == 0:
        print("Warning: flood-fill produced 0 interior voxels; falling back to binary_fill_holes")
        filled = ndimage.binary_fill_holes(closed)
        interior = filled & ~closed
    if verbose:
        print("Interior voxel count:", np.count_nonzero(interior))
    return interior


# -------------------------
# Parity (scanline) fill fallback
# -------------------------


def parity_fill_along_axis(surface_matrix, axis=2, verbose=True):  # pragma: no cover

    if verbose:
        print("Running parity (scanline) fill along axis", axis)

    interior = np.zeros_like(surface_matrix, dtype=bool)

    mat = np.moveaxis(surface_matrix, axis, -1)

    out = np.moveaxis(interior, axis, -1)

    nx, ny, _ = mat.shape

    for i in range(nx):
        for j in range(ny):
            _fill_scanline(out, i, j, mat[i, j, :])

    interior_filled = np.moveaxis(out, -1, axis)

    if verbose:
        print("Parity-filled interior voxels count:", int(interior_filled.sum()))

    return interior_filled


def _fill_scanline(out, i, j, col):  # pragma: no cover
    true_inds = np.nonzero(col)[0]
    if true_inds.size == 0:
        return
    if (true_inds.size % 2) == 1:
        true_inds = true_inds[:-1]
        if true_inds.size == 0:
            return
    for k in range(0, len(true_inds), 2):
        z0 = true_inds[k]
        z1 = true_inds[k + 1]
        if z1 >= z0:
            out[i, j, z0 : z1 + 1] = True


# -------------------------
# Build supercell positions from ASE atoms (handles triclinic)
# -------------------------


def build_supercell_positions_from_ase(atoms_uc, mesh_min, mesh_max, padding_cells=2):  # pragma: no cover

    cell = np.array(atoms_uc.get_cell())

    inv_cell = np.linalg.inv(cell)

    corners = np.array(
        [
            [mesh_min[0], mesh_min[1], mesh_min[2]],
            [mesh_min[0], mesh_min[1], mesh_max[2]],
            [mesh_min[0], mesh_max[1], mesh_min[2]],
            [mesh_min[0], mesh_max[1], mesh_max[2]],
            [mesh_max[0], mesh_min[1], mesh_min[2]],
            [mesh_max[0], mesh_min[1], mesh_max[2]],
            [mesh_max[0], mesh_max[1], mesh_min[2]],
            [mesh_max[0], mesh_max[1], mesh_max[2]],
        ]
    )

    frac = corners @ inv_cell

    frac_min = frac.min(axis=0)
    frac_max = frac.max(axis=0)

    nmin = np.floor(frac_min).astype(int) - padding_cells

    nmax = np.ceil(frac_max).astype(int) + padding_cells

    uc_pos = np.array(atoms_uc.get_positions())

    symbols = list(atoms_uc.get_chemical_symbols())

    out_positions = []

    out_symbols = []

    for i in range(nmin[0], nmax[0] + 1):
        for j in range(nmin[1], nmax[1] + 1):
            for k in range(nmin[2], nmax[2] + 1):
                translation = i * cell[0] + j * cell[1] + k * cell[2]

                for sidx, p in enumerate(uc_pos):
                    out_positions.append(p + translation)

                    out_symbols.append(symbols[sidx])

    out_positions = np.array(out_positions, dtype=float)

    return out_positions, out_symbols, cell


# -------------------------
# Filter atoms by interior mask (voxel coordinates)
# -------------------------
def filter_atoms_by_voxels(  # pragma: no cover
    atom_positions, atom_symbols, voxel_origin, voxel_pitch, interior_mask, verbose=True, eps=1e-8
):
    """
    Map atoms to the nearest voxel CENTER and keep those whose voxel center falls inside interior_mask.
    Returns kept_positions, kept_symbols
    """
    if len(atom_positions) == 0:
        return np.zeros((0, 3)), []

    nx, ny, nz = interior_mask.shape
    # compute first voxel center coordinates (center of voxel with index 0)
    center0 = np.array(
        [voxel_origin[0] + 0.5 * voxel_pitch, voxel_origin[1] + 0.5 * voxel_pitch, voxel_origin[2] + 0.5 * voxel_pitch]
    )

    # map to nearest center index using rounding
    idx = np.round((atom_positions - center0 + eps) / voxel_pitch).astype(int)

    # clip indices to valid range (avoid any out-of-bounds)
    idx[:, 0] = np.clip(idx[:, 0], 0, nx - 1)
    idx[:, 1] = np.clip(idx[:, 1], 0, ny - 1)
    idx[:, 2] = np.clip(idx[:, 2], 0, nz - 1)

    inside_mask_vals = interior_mask[idx[:, 0], idx[:, 1], idx[:, 2]]
    kept_idx = np.nonzero(inside_mask_vals)[0]

    if kept_idx.size == 0:
        if verbose:
            print("No atoms inside voxel interior.")
        return np.zeros((0, 3)), []

    kept_positions = atom_positions[kept_idx]
    kept_symbols = [atom_symbols[i] for i in kept_idx]

    if verbose:
        print(f"Atoms inside mesh: {len(kept_positions)} / {len(atom_positions)}")

    return kept_positions, kept_symbols


# -------------------------
# Deduplicate pos+symbol lists
# -------------------------


def deduplicate_positions_symbols(positions, symbols, tol=1e-3):
    """
    Remove duplicate atoms within physical tolerance.

    Parameters:
    -----------
    positions : np.ndarray (N,3)
        Atomic positions in Ångström
    symbols : list of str (N,)
        Element symbols
    tol : float (default: 1e-3 Å = 0.1 pm)
        Physical tolerance for duplicate detection

    Returns:
    --------
    unique_positions, unique_symbols
    """
    if len(positions) == 0:
        return np.zeros((0, 3)), []

    # Scale positions to integer grid
    scaled = np.round(positions / tol).astype(int)

    # Use dictionary to store first occurrence per unique position
    unique_dict = {}
    unique_indices = []

    for i, (scaled_pos, symbol) in enumerate(zip(scaled, symbols)):
        # Create key including symbol to prevent element mixing
        key = (*scaled_pos, symbol)

        if key not in unique_dict:
            unique_dict[key] = i
            unique_indices.append(i)

    # Extract unique atoms
    unique_positions = positions[unique_indices]
    unique_symbols = [symbols[i] for i in unique_indices]

    if len(unique_positions) < len(positions):
        print(f"  Removed {len(positions) - len(unique_positions)} duplicates within {tol:.1e} Å tolerance")

    return unique_positions, unique_symbols


# -------------------------
# Save as simple XYZ
# -------------------------


def write_xyz(path, positions, symbols, comment=None):  # pragma: no cover

    n = len(symbols)

    with open(path, "w") as f:
        f.write(f"{n}\n")

        f.write((comment if comment is not None else "") + "\n")

        for s, p in zip(symbols, positions):
            f.write(f"{s} {p[0]:.8f} {p[1]:.8f} {p[2]:.8f}\n")


def _guest_phase_grid_options(options):
    pitch = (
        float(options.get("pitch", None))
        if options.get("pitch", None) is not None
        else (float(options.get("a", 4.05)) / 4.0)
    )
    padding_angstrom = float(options.get("padding_angstrom", 0.0))
    if math.isclose(padding_angstrom, 0.0, abs_tol=1e-12):
        padding_angstrom = float(options.get("padding", 2)) * float(options.get("a", 4.05))

    padding_cells_for_tiling = int(max(1, int(options.get("padding", 2))))
    if options.get("extra_unit_cells", 0) and int(options.get("extra_unit_cells", 0)) > 0:
        padding_cells_for_tiling = max(padding_cells_for_tiling, int(options.get("extra_unit_cells", 0)))

    return pitch, max(padding_angstrom, pitch), padding_cells_for_tiling


def _selected_voxelization_method(options, voxel_method):
    if options.get("force_tri", False):
        print("  Using triangle voxelization (--force-tri specified)")
        return "triangle"
    return voxel_method


def _voxelize_guest_mesh(mesh, pitch, extended_min, extended_max, use_method, verbose):
    try:
        return voxelize_mesh_unified(mesh, pitch, extended_min, extended_max, method=use_method, verbose=verbose)
    except Exception as e:
        print(f"  Voxelization with method '{use_method}' failed: {e}")
        if use_method != "trimesh":
            raise
        print("  Falling back to triangle voxelization...")
        return voxelize_mesh_unified(mesh, pitch, extended_min, extended_max, method="triangle", verbose=verbose)


def _prepare_surface_matrix(surface_matrix, options):
    if int(options.get("dilate", 1)) > 0:
        from scipy.ndimage import binary_dilation

        surface_matrix = binary_dilation(surface_matrix, iterations=int(options.get("dilate", 1)))
        print(" Applied surface dilation -> surface voxels:", int(surface_matrix.sum()))
    close_size = int(options.get("close", 3))
    if close_size % 2 == 0:
        close_size += 1
    surface_closed = closing(surface_matrix, footprint=np.ones((close_size, close_size, close_size)))
    print(" Closed (closing) surface voxels:", int(surface_closed.sum()))
    return surface_closed


def _apply_mask_dilation(interior_mask, options):
    if int(options.get("mask_dilate", 0)) <= 0:
        return interior_mask

    from scipy.ndimage import binary_closing as _bc
    from scipy.ndimage import binary_dilation as _bd

    iter_mask_d = int(options.get("mask_dilate", 0))
    interior_mask = _bd(interior_mask, structure=np.ones((3, 3, 3), dtype=bool), iterations=iter_mask_d)
    interior_mask = _bc(interior_mask, structure=np.ones((3, 3, 3), dtype=bool))
    print(" Interior mask after dilation+closing:", int(interior_mask.sum()))
    return interior_mask


def _build_rotated_unit_cell(options):
    rotation_matrix = None
    if options.get("euler", None) is not None:
        rotation_matrix = rotation_matrix_from_euler(*options.get("euler"))

    if options.get("cif", None) is not None:
        atoms_uc = ase_io.read(options.get("cif"))
    else:
        atoms_uc = bulk(options.get("element", "Al"), options.get("structure", "fcc"), a=float(options.get("a", 4.05)))

    if rotation_matrix is not None:
        cell = np.array(atoms_uc.get_cell())
        atoms_uc.set_cell((rotation_matrix @ cell.T).T, scale_atoms=False)
        pos = np.array(atoms_uc.get_positions())
        atoms_uc.set_positions((rotation_matrix @ pos.T).T)

    return atoms_uc


# -------------------------
# Core: produce guest-phase atoms via voxelization & tiling
# -------------------------


def build_guest_phase(mesh_path, options, voxel_method="triangle", verbose=True):  # pragma: no cover
    """
    options: dict containing keys used: pitch, padding_angstrom, force_tri, dilate, close, mask_dilate,
             cif (path or None), euler (tuple or None), a, element, structure, extra_unit_cells, padding (int)
             returns positions (Nx3 array), symbols (list), and the rotated unit-cell atoms
    """
    print(f"build_guest_phase: loading mesh {mesh_path}, using {voxel_method} voxelization")

    mesh = trimesh.load(mesh_path, force="mesh")
    if mesh is None:
        raise RuntimeError("Failed to load mesh: " + mesh_path)

    print(f" Mesh vertices={len(mesh.vertices)}, faces={len(mesh.faces)}, watertight={mesh.is_watertight}")

    # bounds & padding
    bounds = mesh.bounds
    mesh_min = bounds[0]
    mesh_max = bounds[1]

    pitch, padding_angstrom, padding_cells_for_tiling = _guest_phase_grid_options(options)
    extended_min = mesh_min - padding_angstrom
    extended_max = mesh_max + padding_angstrom

    vox_count_est = np.prod(np.ceil((extended_max - extended_min) / pitch).astype(int) + 3)
    print(f" pitch={pitch:.4f} Å, extended bounds {extended_min}..{extended_max}, voxels ~ {int(vox_count_est):,}")

    # Choose voxelization method (respect force_tri override)
    use_method = _selected_voxelization_method(options, voxel_method)
    print(f"  Selected voxelization method: {use_method}")

    surface_matrix, origin = _voxelize_guest_mesh(mesh, pitch, extended_min, extended_max, use_method, verbose)

    print("Surface voxels:", int(surface_matrix.sum()), "matrix shape:", surface_matrix.shape)

    # surface dilation / closing
    surface_closed = _prepare_surface_matrix(surface_matrix, options)

    # Unified interior extraction using mesh quality assessment
    interior_mask = extract_interior_unified(surface_closed, forced_method=global_filling_method, verbose=verbose)

    # optional interior dilation
    interior_mask = _apply_mask_dilation(interior_mask, options)

    # Build supercell from the ROTATED unit cell
    atoms_uc = _build_rotated_unit_cell(options)
    atoms_uc_for_fill = atoms_uc.copy()  # Already rotated
    mesh_min_tiling = mesh_min - padding_angstrom
    mesh_max_tiling = mesh_max + padding_angstrom
    all_positions, all_symbols, _ = build_supercell_positions_from_ase(
        atoms_uc_for_fill, mesh_min_tiling, mesh_max_tiling, padding_cells=padding_cells_for_tiling
    )
    print(f" Generated {len(all_positions):,} lattice candidate positions by supercell tiling")

    # Filter by interior mask
    kept_positions, kept_symbols = filter_atoms_by_voxels(
        all_positions,
        all_symbols,
        voxel_origin=origin + 0.5 * pitch,
        voxel_pitch=pitch,
        interior_mask=interior_mask,
        verbose=True,
    )

    # deduplicate
    kept_positions, kept_symbols = deduplicate_positions_symbols(kept_positions, kept_symbols)
    print(" After deduplication guest atoms:", len(kept_positions))

    return kept_positions, kept_symbols, atoms_uc


# -------------------------
# Build base-phase atoms (bulk) - simpler: generate repeated bulk covering bounding box
# -------------------------


def build_base_phase(mesh_path, options, voxel_method="triangle"):  # pragma: no cover
    """
    Build base phase with specified voxelization method.
    """
    print(f"build_base_phase: Using {voxel_method} voxelization method")

    # Simply call build_guest_phase with the voxel_method parameter
    # global_filling_method is already available as module variable
    positions, symbols, _ = build_guest_phase(mesh_path, options, voxel_method=voxel_method, verbose=True)
    return positions, symbols


# -------------------------
# Input file parser (very permissive)
# -------------------------


def parse_input_file(path):  # NOSONAR - legacy CLI workflow kept intact for behavior parity
    """
    Expected simple file format (space-separated tokens) with lines:
    total_num_phases N
    --merge on --overlap-threshold 0.5 --pbc on --out ./Final_Collection.xyz
    phase_1 guest ./Guest_Phase_large.obj [phase options...]
    phase_2 void ./Guest_Phase.stl [phase options...]
    phase_3 base ./scaled_bulk.obj [phase options...]
    Per-phase options use same style as command-line, for example:
    --cif file --pitch 0.3 --padding-angstrom 5.0 --mask-dilate 1 --force-tri
    --euler 35 45 12 --dilate 1 --close 3 --rotate 0 0 0 --displace 0 0 0
    --out ./path.xyz
    Returns a dict with global options and a list of phase dicts.
    """

    with open(path) as f:
        lines = [ln.strip() for ln in f.readlines() if ln.strip() and not ln.strip().startswith("#")]

    global_opts = {}
    phases = []

    # treat tokens
    i = 0
    while i < len(lines):
        line = lines[i]
        toks = shlex.split(line)

        if toks[0].lower() == "total_num_phases":
            global_opts["total_num_phases"] = int(toks[1])
            i += 1
            continue

        if toks[0].startswith("--"):
            # global options line (single line)
            # parse --key value or flags
            j = 0
            while j < len(toks):
                tk = toks[j]
                if tk.startswith("--"):
                    key = tk[2:].replace("-", "_")

                    # Add iso_value parsing (for mesh method)
                    if key == "iso_value":
                        if j + 1 < len(toks) and not toks[j + 1].startswith("--"):
                            global_opts[key] = float(toks[j + 1])
                            j += 2
                        else:
                            global_opts[key] = 0.7  # default
                            j += 1
                        continue

                    # Add overlap_distance parsing (for atom-atom checking)
                    if key == "overlap_distance":
                        if j + 1 < len(toks) and not toks[j + 1].startswith("--"):
                            global_opts[key] = float(toks[j + 1])
                            j += 2
                        else:
                            global_opts[key] = 0.5  # default
                            j += 1
                        continue

                    # Keep existing overlap_threshold for backward compatibility
                    if key == "overlap_threshold":
                        if j + 1 < len(toks) and not toks[j + 1].startswith("--"):
                            global_opts[key] = float(toks[j + 1])
                            j += 2
                        else:
                            global_opts[key] = 0.5  # default
                            j += 1
                        continue

                    # Add merge_method option
                    if key == "merge_method":
                        if j + 1 < len(toks) and not toks[j + 1].startswith("--"):
                            global_opts[key] = toks[j + 1]
                            j += 2
                        else:
                            global_opts[key] = "mesh"  # default
                            j += 1
                        continue

                    # ADD VOXEL-METHOD PARSING HERE
                    if key == "voxel_method":
                        if j + 1 < len(toks) and not toks[j + 1].startswith("--"):
                            global_opts[key] = toks[j + 1]
                            j += 2
                        else:
                            global_opts[key] = "triangle"  # default
                            j += 1
                        continue

                    if j + 1 < len(toks) and not toks[j + 1].startswith("--"):
                        val = toks[j + 1]
                        j += 2
                        global_opts[key] = val
                    else:
                        global_opts[key] = "on"
                        j += 1
                else:
                    j += 1
            i += 1
            continue

        # phase line: starts with "phase_"
        if toks[0].lower().startswith("phase_"):
            # expected: phase_i role mesh_path [options ...]
            phase_name = toks[0]
            role = toks[1].lower() if len(toks) > 1 else None
            mesh_path = toks[2] if len(toks) > 2 else None
            # collect the rest of tokens as options (we allow them on the same line)
            opt_toks = toks[3:]
            # parse options in opt_toks into dict
            opts = {}
            k = 0
            while k < len(opt_toks):
                t = opt_toks[k]
                if t.startswith("--"):
                    key = t[2:].replace("-", "_")
                    # special case: --euler expects 3 floats, --rotate 3 floats, --displace 3 floats
                    if key in ("euler", "rotate", "displace"):
                        vals = []
                        # read next 3
                        for kk in range(1, 4):
                            if k + kk < len(opt_toks):
                                vals.append(float(opt_toks[k + kk]))
                            else:
                                vals.append(0.0)
                        opts[key] = tuple(vals)
                        k += 4
                    elif key in ("force_tri",):  # boolean style flag
                        opts[key] = True
                        k += 1
                    elif key == "shrink_distance":  # Replace mesh_scale with shrink_distance
                        if k + 1 < len(opt_toks) and not opt_toks[k + 1].startswith("--"):
                            try:
                                opts[key] = float(opt_toks[k + 1])
                                k += 2
                            except ValueError:
                                opts[key] = 0.5  # Default shrink distance
                                k += 1
                        else:
                            opts[key] = 0.5  # Default shrink distance
                            k += 1
                    else:
                        # next token value (if not provided treat as flag on)
                        if k + 1 < len(opt_toks) and not opt_toks[k + 1].startswith("--"):
                            opts[key] = opt_toks[k + 1]
                            k += 2
                        else:
                            opts[key] = "on"
                            k += 1
                else:
                    k += 1
            phases.append({"name": phase_name, "role": role, "mesh": mesh_path, "opts": opts})
            i += 1
            continue
        # unknown -> skip
        i += 1
    return global_opts, phases


# -------------------------
# Validation PNG generator (fixed formatting & tick control)
# -------------------------
def save_validation_png(  # pragma: no cover  # NOSONAR - legacy CLI workflow kept intact for behavior parity
    initial_atoms,
    initial_symbols,
    rotated_atoms,
    rotated_symbols,
    cif_metadata,
    euler_angles,
    rotation_matrix,
    out_png,
    dpi=500,
):
    """
    Draw side-by-side 3D scatter of initial (left) and rotated (right) unit-cell visualization,
    and print formatted informational boxes below each plot.

    - initial_atoms, rotated_atoms: (N,3) arrays
    - initial_symbols, rotated_symbols: lists of element symbols
    - cif_metadata: dict with keys like 'elements','formula','cell_lengths','cell_angles','spacegroup'
    - euler_angles: tuple (phi1, Phi, phi2) or None (angles in degrees)
    - rotation_matrix: 3x3 numpy array or None
    """
    import matplotlib.pyplot as plt

    # High-contrast palette
    high_contrast_colors = ["red", "blue", "green", "yellow", "magenta", "cyan", "orange", "purple", "brown", "black"]
    elems = sorted(set(initial_symbols) | set(rotated_symbols))
    color_map = {el: high_contrast_colors[i % len(high_contrast_colors)] for i, el in enumerate(elems)}

    # Covalent radii lookup (safe fallback)
    radii_map = {}
    for el in elems:
        r = 1.0
        try:
            # ase.data.covalent_radii is indexed by atomic number
            Z = None
            try:
                Z = atomic_numbers.get(el) if isinstance(atomic_numbers, dict) else atomic_numbers[el]
            except Exception:
                # try capitalized key
                try:
                    Z = atomic_numbers.get(el.capitalize())
                except Exception:
                    Z = None
            if Z:
                rr = float(covalent_radii[int(Z)])
                if rr > 0 and not np.isnan(rr):
                    r = rr
        except Exception:
            r = 1.0
        radii_map[el] = r

    # Normalize and scale marker size (area)
    max_r = max(radii_map.values()) if len(radii_map) > 0 else 1.0
    base_marker = 40.0  # baseline area; final area = base_marker * (r/max_r) * 2

    # Create figure with top row plots and bottom row text boxes (separate axes to avoid overlap)
    fig = plt.figure(figsize=(12, 7), dpi=dpi)
    gs = fig.add_gridspec(2, 2, height_ratios=[4, 1.2], hspace=0.25, wspace=0.25)
    ax1 = fig.add_subplot(gs[0, 0], projection="3d")
    ax2 = fig.add_subplot(gs[0, 1], projection="3d")

    # Plot initial (left)
    for el in elems:
        mask = [s == el for s in initial_symbols]
        if any(mask):
            pts = np.array([p for p, m in zip(initial_atoms, mask) if m])
            if pts.size:
                marker_size = base_marker * (radii_map[el] / max_r) * 2.0
                ax1.scatter(
                    pts[:, 0], pts[:, 1], pts[:, 2], label=el, s=marker_size, color=color_map[el], depthshade=True
                )

    ax1.set_title("Initial (unrotated) unit-cell", fontsize=14)
    ax1.set_xlabel("X (Å)")
    ax1.set_ylabel("Y (Å)")
    ax1.set_zlabel("Z (Å)")

    # Plot rotated (right)
    for el in elems:
        mask = [s == el for s in rotated_symbols]
        if any(mask):
            pts = np.array([p for p, m in zip(rotated_atoms, mask) if m])
            if pts.size:
                marker_size = base_marker * (radii_map[el] / max_r) * 2.0
                ax2.scatter(
                    pts[:, 0], pts[:, 1], pts[:, 2], label=el, s=marker_size, color=color_map[el], depthshade=True
                )

    ax2.set_title("Rotated unit-cell", fontsize=14)
    ax2.set_xlabel("X (Å)")
    ax2.set_ylabel("Y (Å)")
    ax2.set_zlabel("Z (Å)")

    # Shared legend under the main title
    handles = []
    labels = []
    for el in elems:
        handles.append(
            plt.Line2D([0], [0], marker="o", color="w", markerfacecolor=color_map[el], markersize=8, label=el)
        )
        labels.append(el)
    if handles:
        fig.legend(
            handles, labels, loc="upper center", ncol=min(len(labels), 8), fontsize=14, bbox_to_anchor=(0.5, 0.955)
        )

    # ----- Prepare formatted bottom text (Header: newline Values) -----
    # LEFT: crystallographic info in requested format
    left_lines = []
    # Element Type:
    left_lines.append("Element Type:")
    if cif_metadata and "elements" in cif_metadata:
        left_lines.append(", ".join(cif_metadata["elements"]))
    else:
        left_lines.append(", ".join(sorted(set(initial_symbols))))

    # Formula:
    left_lines.append("")  # blank line as separator
    left_lines.append("Formula:")
    if cif_metadata and "formula" in cif_metadata:
        left_lines.append(str(cif_metadata["formula"]))
    else:
        # produce simple concatenation of counts if possible
        try:
            # build simple formula from initial_symbols
            from collections import Counter

            cnt = Counter(initial_symbols)
            formula = "".join(f"{el}{cnt[el] if cnt[el] > 1 else ''}" for el in sorted(cnt.keys()))
            left_lines.append(formula)
        except Exception:
            left_lines.append("N/A")

    # Crystallographic Information:
    left_lines.append("")  # separator
    left_lines.append("Crystallographic Information:")
    if cif_metadata and "cell_lengths" in cif_metadata:
        a, b, c = cif_metadata["cell_lengths"]
        left_lines.append(f"a = {a:.8f} Å, b = {b:.8f} Å, c = {c:.8f} Å")
    else:
        left_lines.append("a = N/A, b = N/A, c = N/A")

    if cif_metadata and "cell_angles" in cif_metadata:
        alpha, beta, gamma = cif_metadata["cell_angles"]
        # use roman words alpha,beta,gamma
        left_lines.append(f"alpha = {alpha:.6f}°, beta = {beta:.6f}°, gamma = {gamma:.6f}°")
    else:
        left_lines.append("alpha = N/A, beta = N/A, gamma = N/A")

    left_text = "\n".join(left_lines)

    # RIGHT: rotation info in requested format
    right_lines = []
    right_lines.append("Rotation angle:")
    right_lines.append("")  # blank line
    if euler_angles is not None:
        # keep the phi names (phi1, Phi, phi2) but use 'phi' roman
        right_lines.append(f"(phi1 = {euler_angles[0]:.6f}, Phi = {euler_angles[1]:.6f}, phi2 = {euler_angles[2]:.6f})")
    else:
        right_lines.append("(none)")

    right_lines.append("")  # separator
    right_lines.append("Rotation matrix:")
    # Format matrix as three rows of three numbers each (comma-separated)
    if rotation_matrix is not None:
        for row in rotation_matrix:
            right_lines.append("[ " + ", ".join(f"{val: .6f}" for val in row) + " ]")
    else:
        right_lines.append("None")

    right_text = "\n".join(right_lines)

    # Create two small axes at bottom for text; purely to avoid overlap with 3D plots.
    ax_text_left = fig.add_subplot(gs[1, 0])
    ax_text_right = fig.add_subplot(gs[1, 1])
    ax_text_left.axis("off")
    ax_text_right.axis("off")

    # Draw text (monospace) with boxed background; this will stay strictly below the plots
    ax_text_left.text(
        0.01,
        0.98,
        left_text,
        va="top",
        ha="left",
        fontsize=9,
        family="monospace",
        bbox={"boxstyle": "round", "facecolor": "wheat", "alpha": 0.9},
    )
    ax_text_right.text(
        0.01,
        0.98,
        right_text,
        va="top",
        ha="left",
        fontsize=9,
        family="monospace",
        bbox={"boxstyle": "round", "facecolor": "lightcyan", "alpha": 0.9},
    )

    # ----- Set axis ticks spacing exactly as requested -----
    def set_ticks_and_equalize(ax, pts, step):  # pragma: no cover
        # pts: Nx3 array; step: float tick spacing
        if pts is None or len(pts) == 0:
            return
        pts = np.array(pts)
        mins = pts.min(axis=0)
        maxs = pts.max(axis=0)
        # center and radius as before
        mx = 0.5 * (mins[0] + maxs[0])
        my = 0.5 * (mins[1] + maxs[1])
        mz = 0.5 * (mins[2] + maxs[2])
        r = max(maxs[0] - mins[0], maxs[1] - mins[1], maxs[2] - mins[2]) * 0.6 + 1e-8
        ax.set_xlim(mx - r, mx + r)
        ax.set_ylim(my - r, my + r)
        ax.set_zlim(mz - r, mz + r)

        # build ticks using floor/ceil to include full visible range
        def ticks_for_axis(low, high, s):  # pragma: no cover
            t0 = math.floor(low / s) * s
            t1 = math.ceil(high / s) * s
            if t1 <= t0:
                return [0.0]
            # create numpy array of ticks
            return np.arange(t0, t1 + 0.5 * s, s)

        xt = ticks_for_axis(mx - r, mx + r, step)
        yt = ticks_for_axis(my - r, my + r, step)
        zt = ticks_for_axis(mz - r, mz + r, step)
        ax.set_xticks(xt)
        ax.set_yticks(yt)
        ax.set_zticks(zt)
        # Format tick labels with reasonable decimals
        ax.xaxis.set_major_formatter(plt.FuncFormatter(lambda v, pos: f"{v:.1f}"))
        ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, pos: f"{v:.1f}"))
        ax.zaxis.set_major_formatter(plt.FuncFormatter(lambda v, pos: f"{v:.1f}"))

    # ticks every 2.5 Å for initial and 5.0 Å for rotated (as in attached file)
    try:
        set_ticks_and_equalize(ax1, initial_atoms, step=5.0)
        set_ticks_and_equalize(ax2, rotated_atoms, step=5.0)
    except Exception:
        # fallback: just set equal axes without custom ticks
        try:

            def set_equal_axis(ax, pts):  # pragma: no cover
                if pts is None or len(pts) == 0:
                    return
                pts = np.array(pts)
                mins = pts.min(axis=0)
                maxs = pts.max(axis=0)
                mx = 0.5 * (mins[0] + maxs[0])
                my = 0.5 * (mins[1] + maxs[1])
                mz = 0.5 * (mins[2] + maxs[2])
                r = max(maxs[0] - mins[0], maxs[1] - mins[1], maxs[2] - mins[2]) * 0.6 + 1e-8
                ax.set_xlim(mx - r, mx + r)
                ax.set_ylim(my - r, my + r)
                ax.set_zlim(mz - r, mz + r)

            set_equal_axis(ax1, initial_atoms)
            set_equal_axis(ax2, rotated_atoms)
        except Exception:
            # Tick/equal-axis fallback is best effort; plotting can proceed without it.
            pass

    fig.subplots_adjust(left=0, bottom=0.03, right=1, top=0.95)
    os.makedirs(os.path.dirname(out_png) or ".", exist_ok=True)
    fig.savefig(out_png, dpi=dpi)
    plt.close(fig)
    print(f"Saved validation PNG: {out_png} (dpi={dpi})")


# -------------------------
# Auxiliary script integration - CORRECTED VERSION
# -------------------------


def run_ovito_merge(  # pragma: no cover  # NOSONAR - legacy CLI workflow kept intact for behavior parity
    base_file,
    guest_files,
    void_files,
    output_file,
    resolution=300,
    particle_radius=100,
    iso_value=0.7,
    overlap_distance=0.5,
    shrink_distance=0.5,
):  # ADD shrink_distance parameter
    """
    Run Ovito merge with isosurface generation AND atom-atom distance checking.
    """
    print("\n=== Running Mesh Merge with Overlap Checking ===")
    print(f"Base: {base_file}")
    print(f"Guests: {guest_files}")
    print(f"Voids: {void_files}")
    print(f"Output: {output_file}")
    print(f"Iso-surface parameters: resolution={resolution}, particle_radius={particle_radius}, iso_value={iso_value}")
    print(f"Atom-atom overlap distance: {overlap_distance} Å")
    print(f"Shrink distance: {shrink_distance} Å")  # ADD this print

    # First run the Ovito mesh-based merge
    cmd = sibling_command(
        "Ovito_Delete_Robust.py",
        "--base",
        base_file,
        "--output",
        output_file,
        "--resolution",
        str(resolution),
        "--particle_radius",
        str(particle_radius),
        "--iso_value",
        str(iso_value),
        "--overlap_threshold",
        str(overlap_distance),
        "--shrink_distance",
        str(shrink_distance),  # ADD this parameter
    )

    for guest in guest_files:
        cmd.extend(["--guest", guest])

    for void in void_files:
        cmd.extend(["--void", void])

    print("Running merge ...")
    result = subprocess.run(cmd, capture_output=True, text=True, **SUBPROCESS_TEXT_KWARGS)

    print(f"merge stdout: {result.stdout}")
    if result.stderr:
        print(f"merge stderr: {result.stderr}")

    if result.returncode != 0:
        print(f"merge failed with return code: {result.returncode}")
        return False

    print("✓ mesh-based merge completed")

    # Now apply atom-atom distance checking if overlap_distance > 0
    if overlap_distance > 0:
        print(f"\nApplying atom-atom distance check with threshold {overlap_distance} Å...")
        try:
            atoms = ase_io.read(output_file)
            positions = atoms.get_positions()
            symbols = atoms.get_chemical_symbols()

            if len(positions) == 0:
                print("  No atoms to check for overlap")
                return True

            # Use KDTree for efficient distance checking
            tree = KDTree(positions)

            # Find all pairs closer than overlap_distance
            # Use query_ball_tree for efficiency with large systems
            indices = tree.query_ball_tree(tree, r=overlap_distance)

            # Build set of atoms to remove (keep first in each overlapping pair)
            to_remove = set()
            for i, neighbors in enumerate(indices):
                if i in to_remove:
                    continue  # Already marked for removal

                # Remove all neighbors except self
                for j in neighbors:
                    if j != i and j not in to_remove:
                        # Keep atom with lower index (i), remove higher index (j)
                        if j > i:
                            to_remove.add(j)

            if to_remove:
                # Create new arrays without removed atoms
                keep_indices = [i for i in range(len(positions)) if i not in to_remove]
                new_positions = positions[keep_indices]
                new_symbols = [symbols[i] for i in keep_indices]

                print(f"  Removed {len(to_remove)} overlapping atoms (distance < {overlap_distance} Å)")

                # Save the cleaned structure
                final_atoms = Atoms(positions=new_positions, symbols=new_symbols)
                ase_io.write(output_file, final_atoms, format="xyz")
                print(f"  Final atom count: {len(new_positions)}")
            else:
                print("  No overlapping atoms found")

        except Exception as e:
            print(f"  Error during atom-atom distance check: {e}")
            import traceback

            traceback.print_exc()
            return False

    return True


def run_hierarchical_overlap_strategy(  # pragma: no cover
    base_file, guest_files, void_files_info, output_file, phase_ids, overlap_distance=0.5
):
    """Hierarchical overlap strategy with phase ID-based deletion"""
    print("\n=== Running Hierarchical Overlap Strategy ===")
    print(f"Atom-atom overlap distance: {overlap_distance} Å")
    print(f"Phase hierarchy (higher ID wins): {phase_ids}")

    try:
        # Load base atoms
        base_atoms = ase_io.read(base_file)
        positions = base_atoms.get_positions()
        symbols = base_atoms.get_chemical_symbols()

        print(f"Initial base atoms: {len(positions)}")

        # Save base as temporary file for hierarchical processing
        temp_base = "temp_base_phase.xyz"
        write_xyz(temp_base, positions, symbols, comment="Base phase")

        # Create list of all phase files in order
        all_phase_files = [temp_base] + guest_files
        all_phase_ids = [1] + phase_ids  # Base is ID 1

        # Apply hierarchical overlap deletion
        final_positions, final_symbols = hierarchical_overlap_deletion(
            all_phase_files, all_phase_ids, overlap_distance, verbose=True
        )

        # Apply void deletions AFTER hierarchical merging (voids affect ALL phases)
        if void_files_info:
            print("\n=== Applying Void Deletions to All Phases ===")
            for void_info in void_files_info:
                print(f"Processing void: {void_info['file']}")

                void_mesh = trimesh.load(void_info["file"])

                if void_info.get("rotate"):
                    rotation_matrix = _rotation_matrix_xyz(void_info["rotate"])
                    centroid = void_mesh.vertices.mean(axis=0)
                    vertices_centered = void_mesh.vertices - centroid
                    vertices_rotated = (rotation_matrix @ vertices_centered.T).T
                    void_mesh.vertices = vertices_rotated + centroid

                if void_info.get("displace"):
                    void_mesh.vertices += np.array(void_info["displace"])

                inside = void_mesh.contains(final_positions)
                outside_mask = ~inside

                final_positions = final_positions[outside_mask]
                final_symbols = [final_symbols[i] for i in np.nonzero(outside_mask)[0]]
                print(f"  After void deletion: {len(final_positions)} atoms")

        # Create final atoms object
        final_atoms = Atoms(positions=final_positions, symbols=final_symbols)

        # Write output
        ase_io.write(output_file, final_atoms, format="xyz")
        print(f"✓ Final merged structure saved to: {output_file}")
        print(f"  Total atoms: {len(final_positions)}")

        # Clean up temp file
        if os.path.exists(temp_base):
            os.remove(temp_base)

        return True

    except Exception as e:
        print(f"✗ Error in hierarchical overlap strategy: {e}")
        import traceback

        traceback.print_exc()
        return False


def run_manipulate(
    input_file, output_file, displace=None, rotate=None, pbc=False, charge=False, spin=False
):  # pragma: no cover
    """Run manipulate.py for final processing"""
    print("\n=== Running Manipulate ===")
    print(f"Input: {input_file}")
    print(f"Output: {output_file}")
    print(f"PBC: {pbc}, Charge: {charge}, Spin: {spin}")

    cmd = sibling_command("manipulate.py", input_file, "--output", output_file)

    if displace and len(displace) == 3:
        cmd.extend(["--displace", str(displace[0]), str(displace[1]), str(displace[2])])

    if rotate and len(rotate) == 3:
        cmd.extend(["--rotate", str(rotate[0]), str(rotate[1]), str(rotate[2])])

    if pbc:
        cmd.append("--pbc")

    if charge:
        cmd.append("--charge")

    if spin:
        cmd.append("--spin")

    print(f"Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True, **SUBPROCESS_TEXT_KWARGS)

    print(f"Manipulate stdout: {result.stdout}")
    if result.stderr:
        print(f"Manipulate stderr: {result.stderr}")

    if result.returncode != 0:
        print(f"Manipulate failed with return code: {result.returncode}")
        return False
    else:
        print("Manipulate completed successfully")
        return True


def transform_void_mesh(void_mesh_file, rotate=None, displace=None):  # pragma: no cover
    """
    Apply rotation and displacement to void mesh using trimesh transformations.
    This uses axis rotations (like manipulate.py), NOT Euler angles.
    """
    if not rotate and not displace:
        return void_mesh_file  # No transformation needed

    print(f"Transforming void mesh: {void_mesh_file}")
    try:
        mesh = trimesh.load_mesh(void_mesh_file)

        if rotate and len(rotate) == 3:
            print(f"  Applying axis rotation: {rotate}")
            # Combined rotation: Z * Y * X (standard order)
            rotation_matrix = _rotation_matrix_xyz(rotate)

            # Apply rotation about centroid
            centroid = mesh.vertices.mean(axis=0)
            vertices_centered = mesh.vertices - centroid
            vertices_rotated = (rotation_matrix @ vertices_centered.T).T
            mesh.vertices = vertices_rotated + centroid

        if displace and len(displace) == 3:
            print(f"  Applying displacement: {displace}")
            mesh.vertices += np.array(displace)

        # Create temporary file for transformed mesh
        base_name = os.path.splitext(os.path.basename(void_mesh_file))[0]
        output_file = f"transformed_{base_name}.stl"

        mesh.export(output_file)
        print(f"  Transformed void mesh saved to: {output_file}")
        return output_file
    except Exception as e:
        print(f"  Error transforming void mesh: {e}")
        return void_mesh_file  # Return original if transformation fails


def voxelize_mesh_unified(mesh, pitch, mesh_min, mesh_max, method="triangle", verbose=True):  # pragma: no cover
    """
    Unified voxelization that handles both methods with automatic fallback.

    Args:
        mesh: trimesh object
        pitch: voxel size
        mesh_min, mesh_max: bounding box
        method: 'triangle' or 'trimesh'
        verbose: print progress

    Returns:
        surface_matrix, origin
    """
    if method == "trimesh":
        print("Attempting trimesh voxelization...")
        if not mesh.is_watertight:
            raise ValueError("Mesh is not watertight. Cannot use trimesh voxelization.")

        try:
            # Use trimesh's built-in voxelizer
            import trimesh.voxel.creation as vc

            voxel_grid = vc.voxelize(mesh, pitch)
            surface_matrix = voxel_grid.matrix
            transform = voxel_grid.transform
            # Calculate origin from transform matrix
            origin = transform[:3, 3] - np.array([pitch / 2, pitch / 2, pitch / 2])

            if verbose:
                print(f"  Trimesh voxelization succeeded: matrix shape {surface_matrix.shape}")
            return surface_matrix, origin

        except Exception as e:
            print(f"  Trimesh voxelization failed: {e}")
            raise ValueError(f"Trimesh voxelization failed: {e}")

    else:  # triangle method (default)
        return voxelize_mesh_by_triangles_extended(mesh, pitch, mesh_min, mesh_max, verbose)


def test_flood_fill_on_mesh(
    mesh_path, pitch, padding_angstrom, dilate=1, close=3
):  # pragma: no cover  # NOSONAR - legacy CLI workflow kept intact for behavior parity
    """Test if flood-fill works on a mesh sample"""
    try:
        # Load mesh
        mesh = trimesh.load(mesh_path, force="mesh")
        bounds = mesh.bounds
        mesh_min = bounds[0]
        mesh_max = bounds[1]

        # Calculate extended bounds
        extended_min = mesh_min - padding_angstrom
        extended_max = mesh_max + padding_angstrom

        # Voxelize
        surface_matrix, _ = voxelize_mesh_by_triangles_extended(mesh, pitch, extended_min, extended_max, verbose=False)

        # Apply dilation and closing (same as in build_guest_phase)
        from scipy.ndimage import binary_dilation

        if dilate > 0:
            surface_matrix = binary_dilation(surface_matrix, iterations=dilate)

        close_size = close
        if close_size % 2 == 0:
            close_size += 1
        surface_closed = closing(surface_matrix, footprint=np.ones((close_size, close_size, close_size)))

        interior = ~_flood_outside_voxels(surface_closed) & ~surface_closed
        return interior.sum() > 0  # True if flood-fill worked

    except Exception as e:
        print(f"  Flood-fill test failed: {e}")
        return False


def _read_phase_file(phase_file):  # pragma: no cover
    atoms = ase_io.read(phase_file)
    return atoms.get_positions(), atoms.get_chemical_symbols()


def _find_overlap_indices(current_positions, new_positions, overlap_distance):  # pragma: no cover
    if len(current_positions) == 0:
        return set()
    current_tree = KDTree(current_positions)
    neighbor_lists = current_tree.query_ball_point(new_positions, overlap_distance)
    return {idx for sublist in neighbor_lists for idx in sublist}


def _remove_atoms_by_index(current_positions, current_symbols, phase_trackers, indices_to_remove):  # pragma: no cover
    rem_list = sorted(indices_to_remove, reverse=True)
    current_positions = np.delete(current_positions, rem_list, axis=0)
    for idx in rem_list:
        current_symbols.pop(idx)
        phase_trackers.pop(idx)
    return current_positions, current_symbols, phase_trackers, rem_list


def _append_phase_atoms(
    current_positions, current_symbols, phase_trackers, phase_id, new_positions, new_symbols
):  # pragma: no cover
    current_positions = np.vstack([current_positions, new_positions])
    current_symbols.extend(new_symbols)
    phase_trackers.extend([phase_id] * len(new_positions))
    return current_positions, current_symbols, phase_trackers


def _log_phase_counts(phase_trackers):  # pragma: no cover
    for pid in set(phase_trackers):
        count = phase_trackers.count(pid)
        print(f"    Phase {pid}: {count} atoms")


def _process_overlap_phase(
    current_positions,
    current_symbols,
    phase_trackers,
    phase_file,
    phase_id,
    overlap_distance,
    verbose,
):  # pragma: no cover
    if verbose:
        print(f"\nAdding Phase {phase_id}...")

    new_positions, new_symbols = _read_phase_file(phase_file)
    if len(new_positions) == 0:
        if verbose:
            print(f"  Phase {phase_id} has no atoms, skipping")
        return current_positions, current_symbols, phase_trackers

    indices_to_remove = _find_overlap_indices(current_positions, new_positions, overlap_distance)
    if indices_to_remove:
        current_positions, current_symbols, phase_trackers, rem_list = _remove_atoms_by_index(
            current_positions, current_symbols, phase_trackers, indices_to_remove
        )
        if verbose:
            print(f"  Removing {len(rem_list)} existing atoms that overlap with Phase {phase_id}")

    current_positions, current_symbols, phase_trackers = _append_phase_atoms(
        current_positions, current_symbols, phase_trackers, phase_id, new_positions, new_symbols
    )
    if verbose:
        print(f"  Added {len(new_positions)} atoms from Phase {phase_id}")
        print(f"  Total atoms after Phase {phase_id}: {len(current_positions)}")
        _log_phase_counts(phase_trackers)
    return current_positions, current_symbols, phase_trackers


def hierarchical_overlap_deletion(
    phase_files, phase_ids, overlap_distance=0.5, verbose=True
):  # pragma: no cover  # NOSONAR - legacy CLI workflow kept intact for behavior parity
    """
    Delete overlap atoms based on phase hierarchy.

    Parameters:
    -----------
    phase_files : list of str
        Paths to phase XYZ files in order of processing
    phase_ids : list of int
        Phase IDs (should correspond to phase numbers in input file)
    overlap_distance : float
        Minimum allowed distance between atoms (Å)

    Returns:
    --------
    final_positions, final_symbols : combined atoms after hierarchical deletion
    """
    if verbose:
        print("\n=== Hierarchical Overlap Deletion ===")
        print(f"Processing phases in order: {phase_ids}")

    # Initialize with first phase
    if not phase_files:
        return np.zeros((0, 3)), []

    # Load first phase
    current_positions, current_symbols = _read_phase_file(phase_files[0])
    phase_trackers = [0] * len(current_positions)  # Track which phase each atom belongs to

    if verbose:
        print(f"Phase {phase_ids[0]}: {len(current_positions)} atoms")

    for i, phase_file in enumerate(phase_files[1:], 1):
        current_positions, current_symbols, phase_trackers = _process_overlap_phase(
            current_positions,
            current_symbols,
            phase_trackers,
            phase_file,
            phase_ids[i],
            overlap_distance,
            verbose,
        )

    return current_positions, current_symbols


# -------------------------
# Main driver with integration - CORRECTED VERSION
# -------------------------


def main():  # pragma: no cover  # NOSONAR - legacy CLI workflow kept intact for behavior parity
    parser = argparse.ArgumentParser(description="Build phases from input.txt (guest/void/base/bulk).")
    parser.add_argument("input_file", help="Path to input text file describing phases.")
    args = parser.parse_args()

    global_opts, phases = parse_input_file(args.input_file)

    # Extract global voxel method from input file
    voxel_method = global_opts.get("voxel_method", "triangle")
    print(f"Initial voxelization method from input: {voxel_method}")

    # =========== EXTRACT UNIFIED OVERLAP PARAMETERS ===========
    # 1. iso_value for mesh method (default 0.7)
    iso_value = float(global_opts.get("iso_value", 0.7))

    # 2. overlap_distance for atom-atom checking (prefer new param, fallback to old)
    if "overlap_distance" in global_opts:
        overlap_distance = float(global_opts.get("overlap_distance", 0.5))
    else:
        overlap_distance = float(global_opts.get("overlap_threshold", 0.5))

    print("\n=== Unified Overlap Parameters ===")
    print(f"Iso-value (mesh method): {iso_value}")
    print(f"Atom-atom distance threshold (both methods): {overlap_distance} Å")
    # =========== END UNIFIED PARAMETERS ===========

    # =========== DETERMINE GLOBAL FILLING METHOD ===========
    global global_filling_method  # Declare we're using the module-level variable

    # Default is 'flood', we'll test and potentially change it
    global_filling_method = "flood"

    # Find first guest/base phase to test
    first_test_mesh = None
    first_test_opts = None

    for ph in phases:
        if ph["role"] in ["guest", "base"]:
            first_test_mesh = ph["mesh"]
            first_test_opts = ph["opts"].copy()
            break

    if first_test_mesh:
        print(f"\n=== Testing flood-fill on first mesh: {first_test_mesh} ===")

        # Get pitch from options
        test_pitch = float(first_test_opts.get("pitch", float(first_test_opts.get("a", 4.05)) / 4.0))
        test_padding = float(first_test_opts.get("padding_angstrom", 0.0))
        if math.isclose(test_padding, 0.0, abs_tol=1e-12):
            test_padding = float(first_test_opts.get("padding", 2)) * float(first_test_opts.get("a", 4.05))

        test_dilate = int(first_test_opts.get("dilate", 1))
        test_close = int(first_test_opts.get("close", 3))

        print(f"  Test parameters: pitch={test_pitch:.3f}Å, padding={test_padding:.2f}Å")
        print(f"  dilate={test_dilate}, close={test_close}")

        flood_works = test_flood_fill_on_mesh(first_test_mesh, test_pitch, test_padding, test_dilate, test_close)

        if not flood_works:
            global_filling_method = "parity"
            print("❌ Flood-fill test FAILED → Using PARITY fill for ALL phases")
        else:
            print("✅ Flood-fill test PASSED → Using FLOOD fill for ALL phases")
    else:
        print("No guest/base phases found, using default flood-fill")

    print(f"Global filling method set to: {global_filling_method}")
    # =========== END OF ADDITION ===========

    # ADD THESE DEFAULT VALUES FOR OVITO PARAMETERS:
    ovito_resolution = 300
    ovito_particle_radius = 100

    # Track if we need to switch methods
    switch_to_triangle = False
    fallback_reason = ""

    # Track if we need to switch methods
    switch_to_triangle = False
    fallback_reason = ""

    # Rest of your existing main() function continues...
    # First pass: Try to use specified method for all phases
    if voxel_method == "trimesh":
        print("\nChecking if all meshes can use trimesh voxelization...")
        for ph in phases:
            role = ph["role"]
            mesh_path = ph["mesh"]

            if role in ["guest", "base"]:
                try:
                    mesh = trimesh.load(mesh_path, force="mesh")
                    if not mesh.is_watertight:
                        switch_to_triangle = True
                        fallback_reason = f"Mesh '{mesh_path}' is not watertight"
                        print(f"  ✗ {fallback_reason}")
                        break
                    else:
                        print(f"  ✓ Mesh '{os.path.basename(mesh_path)}' is watertight")
                except Exception as e:
                    switch_to_triangle = True
                    fallback_reason = f"Failed to load/check mesh '{mesh_path}': {e}"
                    print(f"  ✗ {fallback_reason}")
                    break

    # Update method if needed
    if switch_to_triangle:
        print(f"\n⚠️ Switching to triangle voxelization for all phases: {fallback_reason}")
        voxel_method = "triangle"

    print(f"\nFinal voxelization method for all phases: {voxel_method}")

    # Track generated files for post-processing
    base_files = []
    guest_files = []
    void_files_info = []

    # Process each phase with the FINAL method
    for ph in phases:
        role = ph["role"]
        mesh = ph["mesh"]
        opts = ph["opts"].copy()

        # normalize and convert options
        opts["force_tri"] = (
            opts.get("force_tri", False) or opts.get("force-tri", False) or (opts.get("force_tri", "False") == "True")
        )
        mask_dilate_value = opts.get("mask_dilate", opts.get("mask-dilate", 0))
        if not mask_dilate_value:
            mask_dilate_value = opts.get("mask-dilate", 0) or 0
        opts["mask_dilate"] = int(mask_dilate_value)
        for key in ("pitch", "padding_angstrom"):
            if key in opts:
                try:
                    opts[key] = float(opts[key])
                except (TypeError, ValueError):
                    # Invalid optional numeric values fall back to backend defaults.
                    pass
        for key in ("dilate", "close", "extra_unit_cells"):
            if key in opts:
                try:
                    opts[key] = int(opts[key])
                except (TypeError, ValueError):
                    # Invalid optional numeric values fall back to backend defaults.
                    pass
        for key in ("euler", "rotate", "displace"):
            if isinstance(opts.get(key, None), str):
                try:
                    parts = opts[key].split()
                    opts[key] = tuple(float(x) for x in parts[:3])
                except Exception:
                    opts[key] = (0.0, 0.0, 0.0)

        opts.setdefault("a", 4.05)
        opts.setdefault("element", "Al")
        opts.setdefault("structure", "fcc")
        opts.setdefault("padding", 2)

        # Extract Ovito parameters from guest phase
        if role == "guest":
            if "resolution" in opts:
                ovito_resolution = int(opts["resolution"])
            if "particle_radius" in opts:
                ovito_particle_radius = float(opts["particle_radius"])

        # Process based on role
        if role == "void":
            print(f"Phase {ph['name']} is VOID -> no atoms created.")
            positions = np.zeros((0, 3))
            symbols = []

            # Store void mesh info
            void_files_info.append({"file": mesh, "rotate": opts.get("rotate"), "displace": opts.get("displace")})

        elif role == "guest":
            # Pass the FINAL voxel_method AND global filling method
            positions, symbols, atoms_uc = build_guest_phase(mesh, opts, voxel_method=voxel_method, verbose=True)
        elif role == "base":
            # Pass the FINAL voxel_method AND global filling method
            positions, symbols = build_base_phase(mesh, opts, voxel_method=voxel_method)
        else:
            print(f"Unknown role '{role}', treating as void.")
            positions = np.zeros((0, 3))
            symbols = []

        # Save per-phase XYZ (for guest and base phases)
        if role in ["guest", "base"] and opts.get("out", None):
            try:
                write_xyz(opts["out"], positions, symbols, comment=f"phase {ph['name']} {role}")
                print(f" wrote {role} phase output to", opts["out"])

                # Track for post-processing
                if role == "base":
                    base_files.append(opts["out"])
                elif role == "guest":
                    guest_files.append(opts["out"])

            except Exception as e:
                print(f" failed to write {role} phase output:", e)

        # Generate validation PNG (for guest and base phases with CIF)
        if role in ["guest", "base"] and opts.get("cif", None) and global_opts.get("validation", "on").lower() != "off":
            try:
                # For base phases, we need to get the rotated atoms_uc
                if role == "base":
                    # Get rotated unit cell for base phase
                    _, _, atoms_uc = build_guest_phase(mesh, opts, voxel_method=voxel_method, verbose=False)

                # atoms_uc is already rotated, so get the unrotated version for comparison
                atoms_uc_unrotated = ase_io.read(opts["cif"])  # Original unrotated

                rot_angles = opts.get("euler", None)
                rot_mat = rotation_matrix_from_euler(*rot_angles) if rot_angles else None

                png_path = os.path.splitext(opts.get("out", f"{ph['name']}.xyz"))[0] + "_validation.png"

                # Extract CIF metadata
                cif_metadata = {
                    "elements": list(set(atoms_uc_unrotated.get_chemical_symbols())),
                    "formula": atoms_uc_unrotated.get_chemical_formula(),
                    "cell_lengths": atoms_uc_unrotated.cell.cellpar()[:3],
                    "cell_angles": atoms_uc_unrotated.cell.cellpar()[3:],
                }

                # Initial positions: unrotated unit cell
                init_positions = np.array(atoms_uc_unrotated.get_positions())
                init_symbols = list(atoms_uc_unrotated.get_chemical_symbols())

                # Rotated positions: already rotated unit cell (atoms_uc)
                rot_positions = np.array(atoms_uc.get_positions())
                rot_symbols = list(atoms_uc.get_chemical_symbols())

                save_validation_png(
                    initial_atoms=init_positions,
                    initial_symbols=init_symbols,
                    rotated_atoms=rot_positions,
                    rotated_symbols=rot_symbols,
                    cif_metadata=cif_metadata,
                    euler_angles=rot_angles,
                    rotation_matrix=rot_mat,
                    out_png=png_path,
                    dpi=500,
                )
            except Exception as e:
                print(f" ⚠️ Failed to generate validation PNG for {ph['name']}: {e}")

    print("\n=== Phase building completed ===")
    print(f"Generated: {len(base_files)} base, {len(guest_files)} guest, {len(void_files_info)} void phases")
    print(f"parameters: resolution={ovito_resolution}, particle_radius={ovito_particle_radius}")
    print(f"Iso-value (mesh method): {iso_value}")
    print(f"Atom-atom distance threshold: {overlap_distance} Å")

    # Post-processing: Merge and convert if requested
    if _is_truthy(global_opts.get("merge", False)):
        print("\n=== Starting Post-Processing ===")

        # Get merge method (default to "mesh" for backward compatibility)
        merge_method = global_opts.get("merge_method", "mesh")
        print(f"Using merge method: {merge_method}")

        # Check if we have the required phases
        if not base_files:
            print("❌ Error: No base phase found for merging")
            return
        if len(base_files) > 1:
            print("⚠️ Warning: Multiple base phases found, using first one")

        base_file = base_files[0]

        # =========== ALWAYS EXTRACT PHASE IDs FOR HIERARCHICAL OVERLAP ===========
        # Build proper role-aware mappings
        guest_id_to_file = {}  # {phase_num: output_file}
        base_actual_id = None

        guest_file_idx = 0
        for ph in phases:
            try:
                phase_num = int(ph["name"].lower().replace("phase_", ""))
            except (AttributeError, ValueError):
                print(f"⚠️ Warning: Could not parse phase number from '{ph['name']}'")
                phase_num = 999 + guest_file_idx

            if ph["role"] == "base":
                base_actual_id = phase_num
            elif ph["role"] == "guest" and guest_file_idx < len(guest_files):
                guest_id_to_file[phase_num] = guest_files[guest_file_idx]
                guest_file_idx += 1

        if base_actual_id is None:
            print("❌ Error: No base phase role found for merging")
            return

        # Guest phase IDs sorted ascending (processing order = priority order)
        guest_phase_ids = sorted(guest_id_to_file.keys())
        sorted_guest_files = [guest_id_to_file[pid] for pid in guest_phase_ids]

        print(f"Base phase ID: {base_actual_id} (file: {base_file})")
        print(f"Guest phase IDs: {guest_phase_ids}")
        print(f"Guest files: {sorted_guest_files}")
        # =========== END PHASE ID EXTRACTION ===========

        if merge_method == "overlap":
            print(f"Processing phases in order: Base (ID {base_actual_id}), Guests (IDs {guest_phase_ids})")

            overlap_success = run_hierarchical_overlap_strategy(
                base_file=base_file,
                guest_files=sorted_guest_files,
                void_files_info=void_files_info,
                output_file=TEMP_MERGED_XYZ,
                phase_ids=guest_phase_ids,
                overlap_distance=overlap_distance,
            )

            if overlap_success and os.path.exists(TEMP_MERGED_XYZ):
                # Run manipulate for final processing
                final_output = global_opts.get("out", "Final_Collection.lmp")
                manipulate_success = run_manipulate(
                    input_file=TEMP_MERGED_XYZ,
                    output_file=final_output,
                    pbc=global_opts.get("pbc", False),
                    charge=global_opts.get("charge", False),
                    spin=global_opts.get("spin", False),
                )

                if manipulate_success:
                    print(f"\n✅ Final structure saved to: {final_output}")
                    # Clean up
                    if os.path.exists(TEMP_MERGED_XYZ):
                        os.remove(TEMP_MERGED_XYZ)
                else:
                    print("❌ Final processing failed")
            else:
                print("❌ Overlap merge failed")

        else:  # Default to mesh method
            # Transform void meshes if needed (using AXIS rotation, not Euler)
            transformed_voids = []
            for void_info in void_files_info:
                transformed_file = transform_void_mesh(
                    void_info["file"],
                    rotate=void_info.get("rotate"),  # AXIS rotation
                    displace=void_info.get("displace"),
                )
                transformed_voids.append(transformed_file)

            # Pass original guest files - scaling will be handled by Ovito_Delete_Robust.py

            # Create temporary merged XYZ file
            temp_merged_xyz = TEMP_MERGED_XYZ

            # Run Ovito merge with parameters from guest phase
            shrink_distance = 0.5  # Default
            for ph in phases:
                if ph["role"] == "guest" and "shrink_distance" in ph["opts"]:
                    shrink_distance = float(ph["opts"]["shrink_distance"])
                    print(f"Using shrink distance from guest phase: {shrink_distance} Å")
                    break

            merge_success = run_ovito_merge(
                base_file=base_file,
                guest_files=guest_files,
                void_files=transformed_voids,
                output_file=temp_merged_xyz,
                resolution=ovito_resolution,
                particle_radius=ovito_particle_radius,
                iso_value=iso_value,
                overlap_distance=overlap_distance,
                shrink_distance=shrink_distance,  # ADD THIS LINE
            )

            if merge_success and os.path.exists(temp_merged_xyz):
                # =========== APPLY HIERARCHICAL OVERLAP FOR MESH METHOD TOO ===========
                print("\n=== Applying Hierarchical Overlap for Mesh Method ===")
                print(f"Applying hierarchical overlap: Base (ID {base_actual_id}), Guests (IDs {guest_phase_ids})")

                temp_base_for_hierarchical = "temp_mesh_merged_base.xyz"

                # The mesh merge already removed void atoms, so we pass empty void list
                hierarchical_success = run_hierarchical_overlap_strategy(
                    base_file=temp_merged_xyz,  # Use the mesh-merged result as base
                    guest_files=sorted_guest_files,
                    void_files_info=[],  # Voids already processed in mesh merge
                    output_file=TEMP_HIERARCHICAL_FINAL_XYZ,
                    phase_ids=guest_phase_ids,
                    overlap_distance=overlap_distance,
                )

                if hierarchical_success:
                    final_temp_file = TEMP_HIERARCHICAL_FINAL_XYZ
                else:
                    final_temp_file = temp_merged_xyz  # Fall back to original mesh merge

                # Clean up intermediate files
                if os.path.exists(temp_base_for_hierarchical):
                    os.remove(temp_base_for_hierarchical)
                # =========== END HIERARCHICAL OVERLAP FOR MESH METHOD ===========

                # Run manipulate for final processing
                final_output = global_opts.get("out", "Final_Collection.lmp")
                manipulate_success = run_manipulate(
                    input_file=final_temp_file,
                    output_file=final_output,
                    pbc=global_opts.get("pbc", False),
                    charge=global_opts.get("charge", False),
                    spin=global_opts.get("spin", False),
                )

                if manipulate_success:
                    print(f"\n✅ Final structure saved to: {final_output}")

                    # Clean up temporary files
                    cleanup_files = [temp_merged_xyz, TEMP_HIERARCHICAL_FINAL_XYZ, temp_base_for_hierarchical]
                    for temp_file in cleanup_files:
                        if temp_file and os.path.exists(temp_file):
                            os.remove(temp_file)
                            print(f"Cleaned up temporary file: {temp_file}")

                    # Clean up transformed void files
                    for void_file in transformed_voids:
                        if void_file.startswith("transformed_") and os.path.exists(void_file):
                            os.remove(void_file)
                            print(f"Cleaned up transformed void: {void_file}")
                else:
                    print("❌ Final processing failed")
            else:
                print("❌ Merge failed")
    else:
        print("Each phase has been built and written to its respective output file.")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 bright-ideas-clan
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
advanced_merge_delete.py

Advanced script to:
1. Handle multiple guest phases and voids
2. Automatically clean up temporary files after each phase
3. Process in hierarchy: base → guests → voids
4. Delete atoms from all previous phases when adding new phases
5. Scale mesh using rescale.py for better deletion
"""

import argparse
import glob
import os
import sys

import gmsh
import numpy as np

# Embedded Mesh_Ovito functionality
import trimesh
from ovito.io import export_file, import_file
from ovito.modifiers import ConstructSurfaceModifier, ReplicateModifier
from scipy.spatial import KDTree

# Force UTF-8 encoding for standard output and error
if sys.platform == "win32":
    for stream in (sys.stdout, sys.stderr):
        if stream is not None and hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)


def get_ray_direction(point):  # pragma: no cover
    """
    Get a robust ray direction that avoids degeneracy.
    """
    # Use a deterministic hash of the point to choose direction
    # This gives different directions for different points but is reproducible
    point_hash = hash(tuple(np.round(point, 6).tolist()))
    direction_idx = point_hash % 3

    # Three orthogonal directions
    directions = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]

    return directions[direction_idx]


def _read_replication_factors():  # pragma: no cover
    rep_input = input("Enter cell replication factors along X, Y, and Z (e.g., 2 2 1. Default: 1 1 1): ").strip()
    if not rep_input:
        return 1, 1, 1
    parts = rep_input.split()
    if len(parts) != 3:
        print("Error: Please provide exactly three space-separated integer replication factors.")
        return None
    try:
        return tuple(map(int, parts))
    except ValueError:
        print("Error: Replication factors must be valid integers. Exiting.")
        return None


def _read_surface_parameters():  # pragma: no cover
    try:
        res = input("Enter Resolution (grid_resolution, Default=600): ")
        grid_resolution = int(res) if res else 600
        rad_scale_percent = input("Enter Radius of the particles scaling (e.g., 100 for 100%, Default=100): ").strip()
        radius_scaling = float(rad_scale_percent) / 100.0 if rad_scale_percent else 1.0
        iso_val = input(
            "Enter Iso value, affecting how far away from particle centers the contour surface is "
            "located (Default: 0.6): "
        ).strip()
        isolevel = float(iso_val) if iso_val else 0.6
        return grid_resolution, radius_scaling, isolevel
    except ValueError:
        print("Error: Surface parameters must be valid numbers. Exiting.")
        return None


def _convert_vtk_to_stl(output_file_path, stl_output_path):  # pragma: no cover
    print("\n--- Converting VTK to STL using Gmsh ---")
    gmsh.initialize()
    gmsh.open(output_file_path)
    gmsh.model.mesh.generate(3)
    gmsh.write(stl_output_path)
    gmsh.finalize()
    print(f"✅ Converted to STL: {stl_output_path}")


def _apply_mesh_scaling_if_needed(stl_output_path, mesh_scale):  # pragma: no cover
    if not isinstance(mesh_scale, (tuple, list)) and np.isclose(float(mesh_scale), 1.0):
        return
    print(f"\n--- Applying mesh scaling factor: {mesh_scale} ---")
    if isinstance(mesh_scale, (tuple, list)):
        scale_factors = mesh_scale
        print(f"  Applying non-uniform scaling: X={scale_factors[0]}, Y={scale_factors[1]}, Z={scale_factors[2]}")
        result_file = rescale_mesh_with_pymeshlab(stl_output_path, scale_factors=scale_factors, output_mesh=None)
    else:
        scale_value = mesh_scale
        print(f"  Applying uniform scaling: {scale_value}")
        result_file = rescale_mesh_with_pymeshlab(stl_output_path, scale_factor=scale_value, output_mesh=None)
    if result_file != stl_output_path and os.path.exists(result_file):
        if os.path.exists(stl_output_path):
            os.remove(stl_output_path)
        os.rename(result_file, stl_output_path)
        print(f"✅ Applied mesh scaling factor: {mesh_scale}")
    else:
        print("⚠️ Scaling may have failed, using original mesh")


def rescale_mesh_with_pymeshlab(
    input_mesh, scale_factor=None, scale_factors=None, output_mesh=None
):  # pragma: no cover
    # (unchanged)
    if scale_factors is not None:
        sx, sy, sz = scale_factors
        print(f"Rescaling mesh using pymeshlab: {input_mesh}")
        print(f"  Non-uniform scaling factors: X={sx}, Y={sy}, Z={sz}")
    else:
        sx = sy = sz = scale_factor or 1.0
        print(f"Rescaling mesh using pymeshlab: {input_mesh}")
        print(f"  Uniform scaling factor: {scale_factor}")
    try:
        import pymeshlab as ml

        ms = ml.MeshSet()
        ms.load_new_mesh(input_mesh)
        original_mesh = ms.current_mesh()
        original_bb = original_mesh.bounding_box()
        original_center = original_bb.center()
        print(f"  Original mesh center: {original_center}")
        print(f"  Applying scaling: X={sx}, Y={sy}, Z={sz}")
        ms.apply_filter(
            "compute_matrix_from_scaling_or_normalization",
            axisx=sx,
            axisy=sy,
            axisz=sz,
            uniformflag=False,
            scalecenter=0,
            customcenter=np.array([0.0, 0.0, 0.0]),
            unitflag=False,
            freeze=True,
            alllayers=False,
        )
        if output_mesh is None:
            base_name = os.path.splitext(os.path.basename(input_mesh))[0]
            ext = os.path.splitext(input_mesh)[1]
            output_mesh = f"{base_name}_scaled{ext}"
        ms.save_current_mesh(output_mesh)
        final_mesh = ms.current_mesh()
        final_bb = final_mesh.bounding_box()
        original_dim = original_bb.max() - original_bb.min()
        final_dim = final_bb.max() - final_bb.min()
        final_center = final_bb.center()
        print(f"  Original dimensions: {original_dim}")
        print(f"  Final dimensions: {final_dim}")
        print(f"  Final mesh center: {final_center}")
        print(f"  Successfully saved rescaled mesh to: {output_mesh}")
        return output_mesh
    except Exception as e:
        print(f"  Error rescaling mesh with pymeshlab: {e}")
        print(f"  Returning original mesh: {input_mesh}")
        return input_mesh


def interactive_ovito_pipeline(
    input_file_path, mesh_scale=1.0
):  # pragma: no cover  # NOSONAR - legacy CLI workflow kept intact for behavior parity
    # (unchanged)
    print("--- Surface Mesh Generation Pipeline (Gaussian Density) ---")
    print("\n--- Step 1: Cell Replication ---")
    replication_factors = _read_replication_factors()
    if replication_factors is None:
        return
    rep_x, rep_y, rep_z = replication_factors

    print("\n--- Step 2: Gaussian Density Parameters (As per documentation) ---")
    surface_params = _read_surface_parameters()
    if surface_params is None:
        return
    grid_resolution, radius_scaling, isolevel = surface_params

    print("\nConfiguration Summary:")
    print(f"  Replication: ({rep_x}, {rep_y}, {rep_z})")
    print(
        "  Gaussian Density: "
        f"Resolution={grid_resolution}, Radius Scaling={radius_scaling} "
        f"(i.e., {radius_scaling * 100:.0f}%), Isolevel={isolevel}"
    )
    print(f"  Mesh scale factor: {mesh_scale}")

    try:
        pipeline = import_file(input_file_path)
        pipeline.modifiers.append(ReplicateModifier(num_x=rep_x, num_y=rep_y, num_z=rep_z))
        print(f"✅ Applied cell replication: ({rep_x}, {rep_y}, {rep_z}).")
        data = pipeline.compute()
        if data.cell is not None and any(data.cell.pbc):
            cell = data.cell_
            cell.pbc = [False, False, False]
            print("✅ Applied fixed boundary conditions (non-periodic in X, Y, Z).")
        else:
            print("✅ No PBC detected - using original boundary conditions.")
        surface_modifier = ConstructSurfaceModifier(
            method=ConstructSurfaceModifier.Method.GaussianDensity,
            grid_resolution=grid_resolution,
            radius_scaling=radius_scaling,
            isolevel=isolevel,
        )
        pipeline.modifiers.append(surface_modifier)
        print("✅ Added ConstructSurfaceModifier (Gaussian Density).")
        data = pipeline.compute()
        if "surface" not in data.surfaces:
            print("\n❌ Error: Surface Mesh was not generated. Check input data or parameters.")
            return
        surface_mesh = data.surfaces["surface"]
        base, _ = os.path.splitext(input_file_path)
        output_file_path = f"{base}_surface_R{rep_x}{rep_y}{rep_z}.vtk"
        export_file(surface_mesh, output_file_path, "vtk/trimesh")
        print("\n--- Pipeline Complete! ---")
        print(f"🎉 Surface mesh successfully exported to: {output_file_path}")
        print("  Note: The output file is a VTK Triangle Mesh, as requested.")
        stl_output_path = f"{base}_surface_R{rep_x}{rep_y}{rep_z}.stl"
        _convert_vtk_to_stl(output_file_path, stl_output_path)
        _apply_mesh_scaling_if_needed(stl_output_path, mesh_scale)
    except Exception as e:
        print(f"\nFATAL ERROR: {e}")
        return


def read_xyz(filename):
    """Read XYZ file and return atoms data"""
    atoms = []
    symbols = []
    with open(filename) as f:
        lines = f.readlines()
    for line in lines[2:]:
        parts = line.strip().split()
        if len(parts) >= 4:
            symbols.append(parts[0])
            atoms.append([float(parts[1]), float(parts[2]), float(parts[3])])
    # ensure numpy array shape (N,3)
    if len(atoms) == 0:
        return np.zeros((0, 3), dtype=float), symbols
    return np.array(atoms, dtype=float), symbols


def write_xyz(filename, atoms, symbols):
    """Write atoms data to XYZ file"""
    with open(filename, "w") as f:
        f.write(f"{len(atoms)}\n")
        f.write("Generated by advanced_merge_delete script\n")
        for i, atom in enumerate(atoms):
            f.write(f"{symbols[i]} {atom[0]:.8f} {atom[1]:.8f} {atom[2]:.8f}\n")


def generate_guest_mesh_stl(  # NOSONAR - legacy CLI workflow kept intact for behavior parity
    guest_xyz_file, resolution=300, particle_radius=100, iso_value=0.6, mesh_scale=1.0
):  # pragma: no cover
    """Generate STL mesh from guest XYZ using OVITO; robust: remove old files BEFORE generation and retry."""
    print("Generating STL mesh from guest atoms...")
    print(f"IMPORTANT: Mesh will be scaled by {mesh_scale} for deletion purposes")
    print("           Guest atoms remain at original positions")
    base_name = os.path.splitext(os.path.basename(guest_xyz_file))[0]
    stl_pattern = f"{base_name}_surface_R*.stl"
    vtk_pattern = f"{base_name}_surface_R*.vtk"
    for old in glob.glob(stl_pattern):
        try:
            os.remove(old)
            print(f"  Removed stale STL before generation: {old}")
        except Exception:
            # Stale debug files are best-effort cleanup and should not block generation.
            pass
    for old in glob.glob(vtk_pattern):
        try:
            os.remove(old)
            print(f"  Removed stale VTK before generation: {old}")
        except Exception:
            # Stale debug files are best-effort cleanup and should not block generation.
            pass
    import builtins

    original_input = builtins.input

    def mock_input(prompt):  # pragma: no cover
        pl = prompt.lower()
        if "resolution" in pl:
            return str(resolution)
        if "radius" in pl:
            return str(particle_radius)
        if "iso value" in pl or "isolevel" in pl:
            return str(iso_value)
        return ""

    builtins.input = mock_input
    try:
        stl_file = None
        tries = 3
        for attempt in range(1, tries + 1):
            print(f"  attempt {attempt}/{tries} ...")
            try:
                interactive_ovito_pipeline(guest_xyz_file, mesh_scale=mesh_scale)
            except Exception as e:
                print(f"  pipeline raised exception (attempt {attempt}): {e}")
            import time

            time.sleep(0.3 * attempt)
            matches = glob.glob(stl_pattern)
            if not matches:
                matches = glob.glob(f"{base_name}_surface*.stl")
            if matches:
                stl_file = max(matches, key=os.path.getmtime)
                print(f"✓ STL mesh generated: {stl_file} (found after attempt {attempt})")
                break
            else:
                print(f"  No STL found after attempt {attempt}. Retrying...")
    finally:
        builtins.input = original_input
    if stl_file is None:
        print("❌ No STL file generated after retries")
        return None
    return stl_file


def atoms_inside_mesh_simple(atoms_positions, mesh_file):  # pragma: no cover
    """
    Fast, robust parity-inside test:
      - Try trimesh.contains (vectorized C-level).
      - Fallback: batch ray intersections for all points at once, then parity via bincount.
    This preserves your parity logic but avoids per-point Python loops.
    """
    # quick shape guard
    atoms_positions = np.asarray(atoms_positions, dtype=float)
    if atoms_positions.size == 0:
        return np.zeros(0, dtype=bool)
    mesh = trimesh.load_mesh(mesh_file)
    # Try fast C-level contains
    try:
        contains = mesh.contains(atoms_positions)
        return np.array(contains, dtype=bool)
    except Exception:
        # Fallback: do a single batched ray-intersection call
        # Use a consistent direction; choosing +X avoids degeneracy if possible
        origins = atoms_positions
        directions = np.tile(np.array([1.0, 0.0, 0.0], dtype=float), (len(origins), 1))
        try:
            _, index_ray, _ = mesh.ray.intersects_location(ray_origins=origins, ray_directions=directions)
        except Exception:
            # Last fallback: do per-point ray but with early exit for very large sets if necessary
            inside_list = []
            for p in origins:
                loc, _, _ = mesh.ray.intersects_location(ray_origins=[p], ray_directions=[[1.0, 0.0, 0.0]])
                inside_list.append(len(loc) % 2 == 1)
            return np.array(inside_list, dtype=bool)
        # index_ray tells for each intersection which input ray it belonged to
        if index_ray.size == 0:
            return np.zeros(len(origins), dtype=bool)
        counts = np.bincount(index_ray, minlength=len(origins))
        inside = (counts % 2) == 1
        return inside


def clean_up_mesh_files(guest_xyz_file):  # pragma: no cover
    """Clean up VTK and STL files for a guest phase (both _surface.vtk and _surface_R*.vtk)"""
    base_name = os.path.splitext(os.path.basename(guest_xyz_file))[0]
    for vtk_file in glob.glob(f"{base_name}_surface*.vtk"):
        if os.path.exists(vtk_file):
            try:
                os.remove(vtk_file)
                print(f"  Removed VTK file: {vtk_file}")
            except Exception:
                # Cleanup is best-effort because these files may be locked by external tools.
                pass
    stl_pattern = f"{base_name}_surface_R*.stl"
    for stl_file in glob.glob(stl_pattern):
        if os.path.exists(stl_file):
            try:
                os.remove(stl_file)
                print(f"  Removed STL file: {stl_file}")
            except Exception:
                # Cleanup is best-effort because these files may be locked by external tools.
                pass


def process_guest_phase(  # pragma: no cover  # NOSONAR - legacy CLI workflow kept intact for behavior parity
    guest_file,
    current_atoms,
    current_symbols,
    resolution,
    particle_radius,
    iso_value,
    shrink_distance=0.5,
):
    """
    Process a single guest phase WITHOUT translation:
     - Read guest atoms (already in correct position from gpt-mod-1.py)
     - Generate guest mesh (OVITO) from guest atoms
     - Delete base atoms inside the guest mesh (or within shrink_distance of surface if > 0)
     - Append guest atoms at their original positions
    """
    print(f"\n=== Processing guest phase: {guest_file} ===")

    # Read guest atoms (already positioned correctly by gpt-mod-1.py)
    guest_atoms, guest_symbols = read_xyz(guest_file)
    if len(guest_atoms) == 0:
        print("  Warning: guest file contains no atoms.")
        return current_atoms, current_symbols

    print(f"Guest: {len(guest_atoms)} atoms")
    print(f"Base: {len(current_atoms)} atoms")

    # DEBUG: Show guest bounds
    print("Guest bounds:")
    print(f"  Min: {np.min(guest_atoms, axis=0)}")
    print(f"  Max: {np.max(guest_atoms, axis=0)}")
    print(f"  Center: {np.mean(guest_atoms, axis=0)}")

    # Generate mesh from guest atoms (OVITO) — this writes an STL; generate_guest_mesh_stl will try once
    mesh_file = generate_guest_mesh_stl(
        guest_file, resolution=resolution, particle_radius=particle_radius, iso_value=iso_value, mesh_scale=1.0
    )

    if not mesh_file:
        print(f"❌ Failed to generate mesh for {guest_file}")
        return current_atoms, current_symbols

    print(f"  Using mesh file: {mesh_file}")

    # Load mesh (already in correct position since it was generated from positioned guest atoms)
    mesh = trimesh.load_mesh(mesh_file)
    if mesh is None:
        print("❌ Failed to load generated mesh.")
        return current_atoms, current_symbols

    # DEBUG: Show mesh bounds
    print("Mesh bounds:")
    print(f"  Min: {mesh.bounds[0]}")
    print(f"  Max: {mesh.bounds[1]}")

    # Save mesh for debugging
    debug_mesh_file = "debug_guest_mesh.stl"
    mesh.export(debug_mesh_file)
    print(f"  Saved mesh to: {debug_mesh_file}")

    # Delete base atoms using shrink-distance
    print("Deleting base atoms inside guest mesh...")
    print(f"Shrink distance: {shrink_distance} Å")

    base_positions = current_atoms
    requested_shrink = float(shrink_distance)

    # Get atoms inside the mesh using vectorized contains (same parity ray-cast, but in C)
    print("  Using vectorized mesh.contains() to determine atoms inside mesh...")
    try:
        inside_mask = np.array(mesh.contains(base_positions), dtype=bool)
        print(f"  mesh.contains() succeeded: {inside_mask.sum()} atoms inside")
    except Exception as e:
        print(f"  mesh.contains() failed ({e}), falling back to per-atom ray-casting...")
        inside_mask = []
        for i, point in enumerate(base_positions):
            ray_direction = get_ray_direction(point)
            locations, _, _ = mesh.ray.intersects_location(ray_origins=[point], ray_directions=[ray_direction])
            is_inside = len(locations) % 2 == 1
            inside_mask.append(is_inside)
            if i % 5000 == 0 and i > 0:
                print(f"    Processed {i}/{len(base_positions)} atoms")
        inside_mask = np.array(inside_mask)

    print(f"  Atoms strictly inside mesh (before shrink): {inside_mask.sum()}")

    # If shrink_distance > 0, we need to exclude atoms that are too close to the surface

    # Apply shrink distance logic (works for both positive and negative)
    if abs(requested_shrink) > 1e-9:  # Non-zero shrink distance
        print(f"  Applying shrink distance: {requested_shrink} Å")

        if requested_shrink > 0:  # Positive: shrink inward
            print(f"  Excluding atoms within {requested_shrink} Å of mesh surface...")
            # For atoms marked as inside, compute distance to mesh surface
            inside_indices = np.nonzero(inside_mask)[0]
            if len(inside_indices) > 0:
                inside_points = base_positions[inside_indices]

                # Compute distance to surface for inside points
                try:
                    _, distances, _ = mesh.nearest.on_surface(inside_points)

                    # Atoms to keep are those WITHIN shrink_distance of surface
                    # Atoms to delete are DEEPER than shrink_distance
                    deep_inside_mask = distances > requested_shrink

                    # Update inside_mask to only include deep inside atoms
                    inside_mask_new = np.zeros(len(base_positions), dtype=bool)
                    inside_mask_new[inside_indices] = deep_inside_mask
                    inside_mask = inside_mask_new

                    print(f"  Atoms deep inside (>{requested_shrink} Å from surface): {inside_mask.sum()}")

                except Exception as e:
                    print(f"  Error computing distances: {e}")
                    print("  Using simple inside detection (no shrink distance)")

        else:  # Negative: expand outward
            shrink_abs = abs(requested_shrink)
            print(f"  Expanding deletion region by {shrink_abs} Å outside mesh...")

            # We need to check ALL base atoms (not just inside)
            # Compute distance to mesh for all base atoms
            try:
                _, distances, _ = mesh.nearest.on_surface(base_positions)

                # For NEGATIVE shrink_distance: delete atoms with distance < abs(shrink_distance)
                # This includes:
                # - Atoms inside mesh (distance = 0 or negative if trimesh returns signed distance)
                # - Atoms outside but within shrink_abs of surface
                expanded_mask = distances < shrink_abs

                inside_mask = expanded_mask
                print(f"  Atoms within {shrink_abs} Å of mesh surface: {inside_mask.sum()}")

            except Exception as e:
                print(f"  Error computing distances for expansion: {e}")
                print("  Using simple inside detection only")

    # Apply the deletion mask
    del_mask = inside_mask
    print("\nDeletion summary:")
    print(f"  Total base atoms: {len(current_atoms)}")
    print(f"  Atoms to delete: {del_mask.sum()}")
    print(f"  Atoms to keep: {(~del_mask).sum()}")

    # DEBUG: Show which atoms are being deleted
    if del_mask.sum() > 0:
        deleted_positions = current_atoms[del_mask]
        print("  Deleted atoms bounds:")
        print(f"    Min: {np.min(deleted_positions, axis=0)}")
        print(f"    Max: {np.max(deleted_positions, axis=0)}")

    # Remove those base atoms and corresponding symbols
    remaining_atoms = current_atoms[~del_mask]
    remaining_symbols = [current_symbols[i] for i in range(len(current_symbols)) if not del_mask[i]]

    print(f"Remaining base atoms: {len(remaining_atoms)}")

    # Add guest atoms at their original positions (NO TRANSLATION!)
    if len(guest_atoms) > 0:
        updated_atoms = np.vstack([remaining_atoms, guest_atoms])
    else:
        updated_atoms = remaining_atoms.copy()
    updated_symbols = remaining_symbols + guest_symbols

    print(f"After guest addition: {len(updated_atoms)} atoms total")
    print("  Guest atoms fill deleted interior")

    # DEBUG: Show final bounds
    print("Final structure bounds:")
    print(f"  Min: {np.min(updated_atoms, axis=0)}")
    print(f"  Max: {np.max(updated_atoms, axis=0)}")

    # Clean up mesh files
    clean_up_mesh_files(guest_file)

    # Clean up debug mesh
    if os.path.exists(debug_mesh_file):
        os.remove(debug_mesh_file)

    return updated_atoms, updated_symbols


def process_void_phase(void_file, current_atoms, current_symbols):  # pragma: no cover
    """Process a single void phase and return updated atoms and symbols"""
    print(f"\n=== Processing void phase: {void_file} ===")
    if not os.path.exists(void_file):
        print(f"❌ Void file {void_file} not found!")
        return current_atoms, current_symbols
    print("Deleting atoms inside void region...")
    inside_mask = atoms_inside_mesh_simple(current_atoms, void_file)
    remaining_atoms = current_atoms[~inside_mask]
    remaining_symbols = [current_symbols[i] for i in range(len(current_symbols)) if not inside_mask[i]]
    deleted_count = np.sum(inside_mask)
    print(f"Deleted {deleted_count} atoms inside void region")
    print(f"Remaining atoms: {len(remaining_atoms)}")
    return remaining_atoms, remaining_symbols


def remove_duplicate_atoms(atoms, symbols, tolerance=0.1):
    """Remove duplicate atoms within tolerance"""
    if len(atoms) == 0:
        return atoms, symbols
    print("Removing duplicate atoms...")
    tree = KDTree(atoms)
    pairs = tree.query_pairs(r=tolerance)
    keep_mask = np.ones(len(atoms), dtype=bool)
    for i, j in pairs:
        if i < j:
            keep_mask[j] = False
    unique_atoms = atoms[keep_mask]
    unique_symbols = [symbols[i] for i in range(len(symbols)) if keep_mask[i]]
    print(f"After duplicate removal: {len(unique_atoms)} atoms")
    return unique_atoms, unique_symbols


def atoms_inside_shrunk_mesh(atoms_positions, mesh_file, shrink_distance=0.5):  # pragma: no cover
    """
    Check which atoms are inside a 'shrunk' version of the mesh.
    """
    mesh = trimesh.load_mesh(mesh_file)
    if mesh is None:
        raise RuntimeError(f"Failed to load mesh {mesh_file}")
    if shrink_distance <= 0:
        print("  shrink_distance <= 0: deleting any atom strictly inside the mesh boundary.")
        try:
            inside = mesh.contains(atoms_positions)
            return np.array(inside, dtype=bool)
        except Exception:
            inside = []
            for p in atoms_positions:
                loc, _, _ = mesh.ray.intersects_location(ray_origins=[p], ray_directions=[[1.0, 0.0, 0.0]])
                inside.append(len(loc) % 2 == 1)
            return np.array(inside, dtype=bool)
    try:
        from trimesh.proximity import signed_distance

        sd = signed_distance(mesh, atoms_positions)
        inside_mask = sd < -float(shrink_distance)
        print(
            "  Used trimesh.proximity.signed_distance: "
            f"will delete {inside_mask.sum()} atoms (|sd| > {shrink_distance})"
        )
        return inside_mask
    except Exception:
        print("  signed_distance not available or failed; falling back to contains() + nearest surface distance.")
    try:
        contains = mesh.contains(atoms_positions)
    except Exception:
        contains = []
        for p in atoms_positions:
            loc, _, _ = mesh.ray.intersects_location(ray_origins=[p], ray_directions=[[1.0, 0.0, 0.0]])
            contains.append(len(loc) % 2 == 1)
        contains = np.array(contains, dtype=bool)
    try:
        _, distance = mesh.nearest.on_surface(atoms_positions)
        inside_mask = np.logical_and(contains, distance > float(shrink_distance))
        print(f"  Fallback nearest: will delete {inside_mask.sum()} atoms (inside & dist > {shrink_distance})")
        return inside_mask
    except Exception:
        print("  mesh.nearest.on_surface failed; using denser sampling + KDTree fallback (slower).")
        n_sample = max(100000, int(len(mesh.faces) * 2))
        surface_points = mesh.sample(n_sample)
        from scipy.spatial import KDTree as _KDTree

        surface_tree = _KDTree(surface_points)
        dists, _ = surface_tree.query(atoms_positions)
        inside_mask = np.logical_and(contains, dists > float(shrink_distance))
        print(f"  KDTree fallback: will delete {inside_mask.sum()} atoms (inside & sampled-dist > {shrink_distance})")
        return inside_mask


def parse_mesh_scale(value):
    try:
        parts = value.split(",")
        if len(parts) == 3:
            return tuple(float(x) for x in parts)
        return float(value)
    except (TypeError, ValueError):
        return 1.0


def _unique_ordered(paths):
    seen = set()
    unique_paths = []
    for path in paths:
        if path not in seen:
            seen.add(path)
            unique_paths.append(path)
    return unique_paths


def _process_guest_files(guest_files, current_atoms, current_symbols, args):  # pragma: no cover
    if not guest_files:
        print("\n=== Step 2: No guest phases to process ===")
        return current_atoms, current_symbols
    print(f"\n=== Step 2: Processing {len(guest_files)} guest phase(s) ===")
    for i, guest_file in enumerate(guest_files, 1):
        if not os.path.exists(guest_file):
            print(f"❌ Guest file {guest_file} not found!")
            continue
        print(f"\n--- Guest {i}/{len(guest_files)} ---")
        current_atoms, current_symbols = process_guest_phase(
            guest_file,
            current_atoms,
            current_symbols,
            args.resolution,
            args.particle_radius,
            args.iso_value,
            args.shrink_distance,
        )
    return current_atoms, current_symbols


def _process_void_files(void_files, current_atoms, current_symbols):  # pragma: no cover
    if not void_files:
        print("\n=== Step 3: No void phases to process ===")
        return current_atoms, current_symbols
    print(f"\n=== Step 3: Processing {len(void_files)} void phase(s) ===")
    for i, void_file in enumerate(void_files, 1):
        print(f"\n--- Void {i}/{len(void_files)} ---")
        current_atoms, current_symbols = process_void_phase(void_file, current_atoms, current_symbols)
    return current_atoms, current_symbols


def main():  # pragma: no cover
    parser = argparse.ArgumentParser(description="Merge guest phases and voids into base phase with proper hierarchy")
    parser.add_argument(
        "--shrink_distance",
        type=float,
        default=0.5,
        help="Shrink distance from mesh surface (Å) for deletion (default: 0.5)",
    )
    parser.add_argument("--base", required=True, help="Base structure XYZ file")
    parser.add_argument("--guest", action="append", help="Guest structure XYZ file (can be used multiple times)")
    parser.add_argument("--void", action="append", help="Void STL file (can be used multiple times)")
    parser.add_argument(
        "--output", default="final_structure.xyz", help="Output filename (default: final_structure.xyz)"
    )
    parser.add_argument(
        "--resolution", type=int, default=300, help="Grid resolution for mesh generation (default: 300)"
    )
    parser.add_argument(
        "--particle_radius", type=float, default=100.0, help="Particle radius scaling in percentage (default: 100)"
    )
    parser.add_argument(
        "--iso_value", type=float, default=0.6, help="Iso value for surface construction (default: 0.6)"
    )
    parser.add_argument(
        "--mesh_scale",
        type=parse_mesh_scale,
        default=1.0,
        help="Scale factor for guest mesh (default: 1.0, can be single value or x,y,z)",
    )
    parser.add_argument(
        "--overlap_threshold", type=float, default=0.5, help="Overlap threshold for deleting atoms (default: 0.5)"
    )
    args = parser.parse_args()
    if not os.path.exists(args.base):
        print(f"❌ Base file {args.base} not found!")
        return
    guest_files = _unique_ordered(args.guest or [])
    void_files = args.void if args.void else []
    print("=== Processing Hierarchy: Base → Guests → Voids ===")
    print(f"Shrink distance: {args.shrink_distance} Å")
    print("\n=== Step 1: Reading base structure ===")
    current_atoms, current_symbols = read_xyz(args.base)
    print(f"Base: {len(current_atoms)} atoms")
    current_atoms, current_symbols = _process_guest_files(guest_files, current_atoms, current_symbols, args)
    current_atoms, current_symbols = _process_void_files(void_files, current_atoms, current_symbols)
    print("\n=== Final Processing ===")
    final_atoms, final_symbols = remove_duplicate_atoms(current_atoms, current_symbols)
    write_xyz(args.output, final_atoms, final_symbols)
    print(f"\n✅ Success! Final structure saved to: {args.output}")
    print(f"   Total atoms: {len(final_atoms)}")
    print(f"   Guest phases processed: {len(guest_files)}")
    print(f"   Void phases processed: {len(void_files)}")
    print(f"   Mesh scale factor used: {args.mesh_scale}")
    print("\nDEBUG SUMMARY:")
    print("  Final number of atoms:", len(current_atoms))
    print("  Guest files considered:", guest_files)


if __name__ == "__main__":
    main()

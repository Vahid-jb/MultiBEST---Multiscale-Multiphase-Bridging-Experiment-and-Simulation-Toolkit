#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 bright-ideas-clan
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
ATOMISTIC FILE COMBINER AND MESH GENERATOR - USING OVITO-ASE BRIDGE
Correctly uses OVITO's ase_to_ovito() function per documentation
Now with both Alpha Shape and Gaussian Density methods
"""

import os
import shutil
import sys
import tempfile
import warnings

import numpy as np

# Force UTF-8 encoding for standard output and error
if sys.platform == "win32":
    for stream in (sys.stdout, sys.stderr):
        if stream is not None and hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

# Suppress OVITO warnings
warnings.filterwarnings("ignore", message=".*OVITO.*PyPI")

PARAM_DEFAULTS = {
    "method": "alpha_shape",
    "radius": 5.0,
    "smoothing_level": 1,
    "rep_x": 1,
    "rep_y": 1,
    "rep_z": 1,
    "grid_resolution": 600,
    "radius_scaling": 100.0,
    "isolevel": 0.6,
}

PARAM_CASTERS = {
    "method": lambda value: value.strip().lower(),
    "radius": float,
    "smoothing_level": int,
    "rep_x": int,
    "rep_y": int,
    "rep_z": int,
    "grid_resolution": int,
    "radius_scaling": float,
    "isolevel": float,
}

MESH_INPUTS = (
    ("Grains", "grains_mesh"),
    ("Non-grains", "nongrains_mesh"),
    ("Microstructure", "microstructure_mesh"),
)


def parse_input_file(input_file):
    """Parses parameters from an input text file."""
    params = {"grain_files": [], "nongrain_files": []}

    with open(input_file) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue

            key, value = (part.strip() for part in line.split("=", 1))
            if key.startswith("input_file_grains"):
                params["grain_files"].append(value)
            elif key.startswith("input_file_nongrains"):
                params["nongrain_files"].append(value)
            elif key in PARAM_CASTERS:
                params[key] = PARAM_CASTERS[key](value)

    for key, default in PARAM_DEFAULTS.items():
        params.setdefault(key, default)

    return params


def read_xyz_with_ase(filename):
    """Read XYZ file using ASE."""
    try:
        from ase.io import read

        atoms = read(filename, format="extxyz")
        return atoms
    except ImportError:
        print("❌ ASE is not installed. Please install with: pip install ase")
        return None
    except Exception as e:
        print(f"❌ Error reading {filename} with ASE: {e}")
        return None


def combine_atoms_files(files_list, output_file, description="combined"):
    """
    Combine multiple XYZ files into one using ASE.
    Returns the ASE atoms object.
    """
    print(f"\nCombining {len(files_list)} files for {description}...")

    all_atoms = []
    total_atoms = 0

    for i, filename in enumerate(files_list):
        if not os.path.exists(filename):
            print(f"❌ File not found: {filename}")
            return None

        atoms = read_xyz_with_ase(filename)
        if atoms is None:
            return None

        all_atoms.append(atoms)
        total_atoms += len(atoms)
        print(f"  {os.path.basename(filename)}: {len(atoms):,} atoms")

    # Combine all atoms
    from ase import Atoms

    combined_symbols = []
    combined_positions = []

    for atoms in all_atoms:
        combined_symbols.extend(atoms.get_chemical_symbols())
        combined_positions.extend(atoms.get_positions())

    combined_positions = np.array(combined_positions)

    # Use the cell from the first file
    if all_atoms[0].cell is not None and np.any(all_atoms[0].cell.lengths() > 0):
        cell = all_atoms[0].cell
        print("  Using cell from first file")
    else:
        # Create cell from bounds
        min_coords = combined_positions.min(axis=0)
        max_coords = combined_positions.max(axis=0)
        cell_lengths = max_coords - min_coords
        from ase.cell import Cell

        cell = Cell(np.diag(cell_lengths))
        print("  Created cell from bounds")

    # Create combined atoms
    combined_atoms = Atoms(symbols=combined_symbols, positions=combined_positions, cell=cell, pbc=(False, False, False))

    # Write to file
    from ase.io import write

    write(output_file, combined_atoms, format="extxyz")

    print(f"✅ Created {description} file: {os.path.basename(output_file)}")
    print(f"   Total atoms: {total_atoms:,}")

    return combined_atoms


def _write_temp_atoms_file(atoms):
    from ase.io import write

    with tempfile.NamedTemporaryFile(suffix=".xyz", delete=False, mode="w") as temp_file:
        temp_file_path = temp_file.name
    write(temp_file_path, atoms, format="extxyz")
    return temp_file_path


def _set_non_periodic_cell(data):
    if hasattr(data, "cell_") and data.cell_ is not None:
        data.cell_.pbc = (False, False, False)
        print(f"    Set PBC to: {data.cell.pbc}")


def _append_replication_modifier(pipeline, params, replicate_modifier):
    rep_x = params.get("rep_x", 1)
    rep_y = params.get("rep_y", 1)
    rep_z = params.get("rep_z", 1)

    if rep_x > 1 or rep_y > 1 or rep_z > 1:
        pipeline.modifiers.append(replicate_modifier(num_x=rep_x, num_y=rep_y, num_z=rep_z))


def _compute_alpha_surface(pipeline, surface_modifier, radius):
    data_with_surface = pipeline.compute()

    if "surface" in data_with_surface.surfaces:
        return data_with_surface

    print("❌ No surface generated. Trying larger radius...")
    for multiplier in [1.5, 2.0, 3.0, 5.0, 8.0, 10.0]:
        surface_modifier.radius = radius * multiplier
        data_with_surface = pipeline.compute()
        if "surface" in data_with_surface.surfaces:
            print(f"    Success with radius {radius * multiplier}")
            return data_with_surface

    return data_with_surface


def _write_stl_from_vtk(vtk_file, output_prefix, gmsh_module=None):
    try:
        gmsh = gmsh_module
        if gmsh is None:
            import gmsh
        gmsh.initialize()
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.open(vtk_file)
        gmsh.model.mesh.removeDuplicateNodes()
        gmsh.model.mesh.removeDuplicateElements()
        stl_file = f"{output_prefix}.stl"
        gmsh.write(stl_file)
        print(f"    STL: {stl_file}")
        return stl_file
    except Exception as e:
        print(f"⚠️  Could not create STL: {e}")
        return None
    finally:
        try:
            gmsh.finalize()
        except Exception:
            pass


def _export_surface_mesh(surface_mesh, output_prefix, export_file, gmsh_module=None):
    vtk_file = f"{output_prefix}.vtk"
    export_file(surface_mesh, vtk_file, "vtk/trimesh")

    num_vertices = len(surface_mesh.vertices)
    num_faces = len(surface_mesh.faces)
    print(f"✅ Created mesh: {num_vertices:,} vertices, {num_faces:,} faces")
    print(f"    VTK: {vtk_file}")

    return vtk_file, _write_stl_from_vtk(vtk_file, output_prefix, gmsh_module)


def create_mesh_from_ase_atoms_using_ovito_bridge(atoms, output_prefix, params, temp_file_path=None):
    """
    Create mesh from ASE atoms object by saving to file and using OVITO's import_file.
    This bypasses the problematic ase_to_ovito() function.
    """
    try:
        # Import OVITO modules
        from ovito.io import export_file, import_file
        from ovito.modifiers import ConstructSurfaceModifier, ReplicateModifier

        print("  Creating mesh using direct file import...")

        cleanup_temp = temp_file_path is None
        if cleanup_temp:
            temp_file_path = _write_temp_atoms_file(atoms)

        # Load the file directly with OVITO
        pipeline = import_file(temp_file_path)
        data = pipeline.compute()

        print(f"    Number of particles (direct load): {data.particles.count}")

        _set_non_periodic_cell(data)
        _append_replication_modifier(pipeline, params, ReplicateModifier)

        # Create Alpha Shape modifier
        radius = params.get("radius", 5.0)
        print(f"    Using Alpha Shape with radius={radius}")

        surface_modifier = ConstructSurfaceModifier(
            method=ConstructSurfaceModifier.Method.AlphaShape,
            radius=radius,
            smoothing_level=params.get("smoothing_level", 1),
        )

        pipeline.modifiers.append(surface_modifier)

        data_with_surface = _compute_alpha_surface(pipeline, surface_modifier, radius)

        if "surface" not in data_with_surface.surfaces:
            print("❌ Surface generation failed")
            if cleanup_temp:
                os.unlink(temp_file_path)
            return None, None

        surface_mesh = data_with_surface.surfaces["surface"]

        # Clean up temporary file
        if cleanup_temp:
            os.unlink(temp_file_path)

        return _export_surface_mesh(surface_mesh, output_prefix, export_file)

    except ImportError as e:
        print(f"❌ Import error: {e}")
        return None, None
    except Exception as e:
        print(f"❌ Error creating mesh: {e}")
        import traceback

        traceback.print_exc()
        return None, None


def create_mesh_gaussian(input_file_path, output_stem, params):
    """
    Generates surface mesh from XYZ file using Gaussian Density method.
    Returns paths to both VTK and STL files.
    """
    print(f"\n--- Creating mesh for: {os.path.basename(input_file_path)} ---")

    try:
        rep_x = int(params.get("rep_x", 1))
        rep_y = int(params.get("rep_y", 1))
        rep_z = int(params.get("rep_z", 1))
        grid_resolution = int(params.get("grid_resolution", 600))
        radius_scaling = float(params.get("radius_scaling", 100)) / 100.0
        isolevel = float(params.get("isolevel", 0.6))
    except ValueError as e:
        print(f"Error parsing mesh parameters: {e}. Using defaults.")
        rep_x, rep_y, rep_z = 1, 1, 1
        grid_resolution = 600
        radius_scaling = 1.0
        isolevel = 0.6

    try:
        # Import OVITO modules
        import gmsh
        from ovito.io import export_file, import_file
        from ovito.modifiers import ConstructSurfaceModifier, ReplicateModifier

        print("    Using Gaussian Density method")
        print(f"    Grid resolution: {grid_resolution}")
        print(f"    Radius scaling: {radius_scaling}")
        print(f"    Isolevel: {isolevel}")

        # Import file and create pipeline
        pipeline = import_file(input_file_path)

        _append_replication_modifier(pipeline, {"rep_x": rep_x, "rep_y": rep_y, "rep_z": rep_z}, ReplicateModifier)

        # Compute to get data and set PBC to False
        data = pipeline.compute()
        _set_non_periodic_cell(data)

        # Create Gaussian Density modifier
        surface_modifier = ConstructSurfaceModifier(
            method=ConstructSurfaceModifier.Method.GaussianDensity,
            grid_resolution=grid_resolution,
            radius_scaling=radius_scaling,
            isolevel=isolevel,
        )
        pipeline.modifiers.append(surface_modifier)

        # Compute surface
        data = pipeline.compute()
        if "surface" not in data.surfaces:
            print("❌ Surface mesh generation failed")
            return None, None

        return _export_surface_mesh(data.surfaces["surface"], output_stem, export_file, gmsh)

    except ImportError as e:
        print(f"❌ Import error: {e}")
        return None, None
    except Exception as e:
        print(f"\n❌ Error in mesh generation: {e}")
        import traceback

        traceback.print_exc()
        return None, None


def perform_boolean_operations():
    """
    Create a MeshLab script for Boolean operations.
    """
    print(f"\n{'=' * 70}")
    print("CREATING BOOLEAN OPERATION SCRIPTS")
    print(f"{'=' * 70}")

    # Script for subtracting grains from microstructure
    subtract_script = """<!DOCTYPE FilterScript>
<FilterScript>
 <filter name="Boolean Operation">
  <Param type="RichMesh" value="0" name="firstMesh"/>
  <Param type="RichMesh" value="1" name="secondMesh"/>
  <Param type="RichInt" value="0" name="BooleanOperation"/>
  <Param type="RichBool" value="true" name="DeleteFirstMesh"/>
  <Param type="RichBool" value="true" name="DeleteSecondMesh"/>
 </filter>
</FilterScript>"""

    with open("boolean_subtract.mlx", "w") as f:
        f.write(subtract_script)

    # Script for merging meshes
    merge_script = """<!DOCTYPE FilterScript>
<FilterScript>
 <filter name="Merge Visible Meshes">
  <Param type="RichBool" value="true" name="MergeVisible"/>
 </filter>
</FilterScript>"""

    with open("boolean_merge.mlx", "w") as f:
        f.write(merge_script)

    print("✅ Created MeshLab scripts:")
    print("   - boolean_subtract.mlx (for subtraction)")
    print("   - boolean_merge.mlx (for merging)")

    return "boolean_subtract.mlx", "boolean_merge.mlx"


def _print_step(title):
    print(f"\n{'=' * 70}")
    print(title)
    print(f"{'=' * 70}")


def _validate_config_file():
    if len(sys.argv) != 2:
        print("Usage: python alpha-mesh-generation.py <config_file.txt>")
        print("\nExample: python alpha-mesh-generation.py input-alpha-mesh-generation.txt")
        sys.exit(1)

    config_file = sys.argv[1]
    if not os.path.exists(config_file):
        print(f"❌ Config file not found: {config_file}")
        sys.exit(1)

    return config_file


def _validate_input_files(params):
    if not params["grain_files"]:
        print("❌ No grain files specified in config")
        sys.exit(1)

    if not params["nongrain_files"]:
        print("❌ No nongrain files specified in config")
        sys.exit(1)


def _print_input_configuration(params):
    print("\nInput configuration:")
    print(f"  Method: {params['method']}")
    print(f"  Grain files: {len(params['grain_files'])} file(s)")
    print(f"  Non-grain files: {len(params['nongrain_files'])} file(s)")

    if params["method"] == "alpha_shape":
        print(f"  Alpha Shape radius: {params.get('radius', 5.0)}")
        print(f"  Smoothing level: {params.get('smoothing_level', 1)}")
    else:
        print(f"  Grid resolution: {params.get('grid_resolution', 600)}")
        print(f"  Radius scaling: {params.get('radius_scaling', 100)}%")
        print(f"  Isolevel: {params.get('isolevel', 0.6)}")

    print(f"  Replication: {params.get('rep_x', 1)}x{params.get('rep_y', 1)}x{params.get('rep_z', 1)}")


def _combine_required_atoms(files_list, output_file, description, error_message):
    atoms = combine_atoms_files(files_list, output_file, description)
    if atoms is None:
        print(error_message)
        sys.exit(1)
    return atoms


def _create_input_atom_files(params):
    _print_step("STEP 1: COMBINING GRAIN FILES")
    grains_file = "grains.xyz"
    grains_atoms = _combine_required_atoms(
        params["grain_files"],
        grains_file,
        "grains",
        "❌ Failed to combine grain files",
    )

    _print_step("STEP 2: COMBINING NON-GRAIN FILES")
    nongrains_file = "nongrains.xyz"
    nongrains_atoms = _combine_required_atoms(
        params["nongrain_files"], nongrains_file, "nongrains", "❌ Failed to combine nongrain files"
    )

    _print_step("STEP 3: CREATING MICROSTRUCTURE FILE")
    microstructure_file = "microstructure.xyz"
    microstructure_atoms = _combine_required_atoms(
        [grains_file, nongrains_file],
        microstructure_file,
        "microstructure",
        "❌ Failed to create microstructure file",
    )

    return (
        ("Grains", grains_file, grains_atoms),
        ("Non-grains", nongrains_file, nongrains_atoms),
        ("Microstructure", microstructure_file, microstructure_atoms),
    )


def _append_mesh_result(all_meshes, name, vtk_file, stl_file):
    if vtk_file:
        all_meshes.append((name, vtk_file, stl_file))


def _create_alpha_meshes(mesh_sources, params):
    all_meshes = []
    for name, input_file, atoms in mesh_sources:
        print(f"\n--- Creating {name.lower()} mesh (Alpha Shape) ---")
        output_prefix = dict(MESH_INPUTS)[name]
        vtk_file, stl_file = create_mesh_from_ase_atoms_using_ovito_bridge(
            atoms, output_prefix, params, temp_file_path=input_file
        )
        _append_mesh_result(all_meshes, name, vtk_file, stl_file)
    return all_meshes


def _create_gaussian_meshes(mesh_sources, params):
    all_meshes = []
    for name, input_file, _atoms in mesh_sources:
        print(f"\n--- Creating {name.lower()} mesh (Gaussian Density) ---")
        output_prefix = dict(MESH_INPUTS)[name]
        vtk_file, stl_file = create_mesh_gaussian(input_file, output_prefix, params)
        _append_mesh_result(all_meshes, name, vtk_file, stl_file)
    return all_meshes


def _create_meshes(mesh_sources, params):
    _print_step(f"STEP 4: CREATING MESHES USING {params['method'].upper()} METHOD")
    if params["method"] == "alpha_shape":
        return _create_alpha_meshes(mesh_sources, params)
    return _create_gaussian_meshes(mesh_sources, params)


def _print_final_summary(all_meshes, params):
    _print_step("FINAL RESULTS")

    print("\n✅ Generated atomistic files:")
    print("   1. grains.xyz")
    print("   2. nongrains.xyz")
    print("   3. microstructure.xyz")

    if all_meshes:
        print(f"\n✅ Generated mesh files ({params['method']} method):")
        for name, vtk, stl in all_meshes:
            print(f"\n   {name}:")
            print(f"     - {vtk}")
            if stl:
                print(f"     - {stl}")
        return

    print("\n❌ No meshes were created")
    print("\nTroubleshooting:")
    if params["method"] == "alpha_shape":
        print("1. Try increasing the radius parameter (e.g., radius = 15)")
    else:
        print("1. Try adjusting Gaussian parameters: grid_resolution, radius_scaling, isolevel")
    print("2. Check that ASE is installed: pip install ase")
    print("3. The atoms may be too sparse for the current parameters")


def main():
    """Main workflow following the specified steps."""
    config_file = _validate_config_file()

    print("=" * 70)
    print("ATOMISTIC FILE COMBINER AND MESH GENERATOR")
    print("=" * 70)

    params = parse_input_file(config_file)
    _validate_input_files(params)
    _print_input_configuration(params)

    temp_dir = tempfile.mkdtemp()
    print(f"\nWorking in temporary directory: {temp_dir}")

    try:
        mesh_sources = _create_input_atom_files(params)
        all_meshes = _create_meshes(mesh_sources, params)
        _print_final_summary(all_meshes, params)

    finally:
        try:
            shutil.rmtree(temp_dir)
            print("\nCleaned up temporary directory")
        except OSError as exc:
            print(f"\n⚠️  Could not clean up temporary directory '{temp_dir}': {exc}")


if __name__ == "__main__":
    main()

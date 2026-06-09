# SPDX-FileCopyrightText: 2026 bright-ideas-clan
#
# SPDX-License-Identifier: GPL-3.0-or-later

import os
import sys

import numpy as np
from ovito.io import import_file
from ovito.modifiers import GrainSegmentationModifier, PolyhedralTemplateMatchingModifier

# Force UTF-8 encoding for standard output and error
if sys.platform == "win32":
    for stream in (sys.stdout, sys.stderr):
        if stream is not None and hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

STRUCTURE_TYPE = "Structure Type"
PARTICLE_TYPE = "Particle Type"
GRAIN_IDENTIFIER = "Grain Identifier"
GRAIN_SIZE = "Grain Size"
MEAN_ORIENTATION = "Mean Orientation"

DEFAULT_RMSD_CUTOFF = 0.1
DEFAULT_MIN_GRAIN_SIZE = 100


def parse_input_file(input_file):
    """Parses parameters from an input text file."""
    params = {}
    with open(input_file) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip()
                params[key] = value
    return params


def _read_numeric_parameter(params, key, caster, default, file_error, prompt, input_error):
    if key in params:
        try:
            return caster(params[key])
        except ValueError:
            print(file_error)
            return default

    user_input = input(prompt)
    try:
        return caster(user_input) if user_input else default
    except ValueError:
        print(input_error)
        return default


def get_user_input(params):
    """Gets parameters from input file or interactive input."""
    rmsd_cutoff = _read_numeric_parameter(
        params,
        "rmsd_cutoff",
        float,
        DEFAULT_RMSD_CUTOFF,
        "Invalid RMSD value in input file. Using default of 0.1.",
        "Enter RMSD cutoff value (default is 0.1): ",
        "Invalid RMSD value. Using default of 0.1.",
    )

    print(f"Using RMSD cutoff of: {rmsd_cutoff}")

    min_grain_size = _read_numeric_parameter(
        params,
        "min_grain_size",
        int,
        DEFAULT_MIN_GRAIN_SIZE,
        "Invalid min_grain_size in input file. Using default of 100.",
        "Please provide minimum grain size (# of atoms, default is 100): ",
        "Invalid input. Using default minimum grain size of 100.",
    )

    print(f"Using minimum grain size of: {min_grain_size}")

    return rmsd_cutoff, min_grain_size


def _phase_type_map():
    return {
        PolyhedralTemplateMatchingModifier.Type.OTHER.value: "Other",
        PolyhedralTemplateMatchingModifier.Type.FCC.value: "FCC",
        PolyhedralTemplateMatchingModifier.Type.HCP.value: "HCP",
        PolyhedralTemplateMatchingModifier.Type.BCC.value: "BCC",
        PolyhedralTemplateMatchingModifier.Type.ICO.value: "ICO",
        PolyhedralTemplateMatchingModifier.Type.SC.value: "SC",
        PolyhedralTemplateMatchingModifier.Type.CUBIC_DIAMOND.value: "Cubic diamond",
        PolyhedralTemplateMatchingModifier.Type.HEX_DIAMOND.value: "Hexagonal diamond",
        PolyhedralTemplateMatchingModifier.Type.GRAPHENE.value: "Graphene",
    }


def _detect_phases(struct_types):
    unique_types, counts = np.unique(struct_types, return_counts=True)
    total_atoms = len(struct_types)
    type_map = _phase_type_map()
    detected_phases = {}
    orphan_atoms_count = 0

    for i, (type_id, count) in enumerate(zip(unique_types, counts)):
        name = type_map.get(type_id, f"Unknown_{type_id}")
        percentage = (count / total_atoms) * 100
        detected_phases[i + 1] = {"id": type_id, "name": name, "count": count, "percentage": percentage}
        print(f"{i + 1}: {name:<20} Atoms: {count:<10} Percentage: {percentage:.2f}%")

        if type_id == PolyhedralTemplateMatchingModifier.Type.OTHER.value:
            orphan_atoms_count = count

    return detected_phases, orphan_atoms_count


def _filtered_grains(grain_table, min_grain_size):
    if grain_table is None or GRAIN_IDENTIFIER not in grain_table or GRAIN_SIZE not in grain_table:
        return None

    grain_ids = grain_table[GRAIN_IDENTIFIER][...]
    grain_sizes = grain_table[GRAIN_SIZE][...]
    filtered_indices = grain_sizes >= min_grain_size

    return {
        "indices": filtered_indices,
        "ids": grain_ids[filtered_indices],
        "sizes": grain_sizes[filtered_indices],
    }


def _format_orientation(orientation):
    return f"({orientation[0]:.4f}, {orientation[1]:.4f}, {orientation[2]:.4f}, {orientation[3]:.4f})"


def _print_grain_rows(grain_ids, grain_sizes):
    print("{:<10} {:<15}".format("ID", "Atoms"))
    for grain_id, num_atoms_in_grain in zip(grain_ids, grain_sizes):
        print(f"{int(grain_id):<10} {int(num_atoms_in_grain):<15}")


def _print_grain_orientation_rows(grain_ids, grain_sizes, grain_orientations):
    print("{:<10} {:<15} {:<50}".format("ID", "Atoms", "Mean Orientation (Quaternion)"))
    for grain_id, num_atoms_in_grain, orientation in zip(grain_ids, grain_sizes, grain_orientations, strict=True):
        print(f"{int(grain_id):<10} {int(num_atoms_in_grain):<15} {_format_orientation(orientation):<50}")


def _print_grain_details(grain_table, filtered_grains):
    num_grains = len(filtered_grains["ids"])
    print(f"\nNumber of grains found (>= {filtered_grains['min_size']} atoms): {num_grains}")

    if num_grains == 0:
        print("No grains were found that meet the specified minimum size.")
        return

    print("\nGrain Details:")
    if MEAN_ORIENTATION in grain_table:
        grain_orientations = grain_table[MEAN_ORIENTATION][...][filtered_grains["indices"]]
        _print_grain_orientation_rows(filtered_grains["ids"], filtered_grains["sizes"], grain_orientations)
    else:
        _print_grain_rows(filtered_grains["ids"], filtered_grains["sizes"])


def report_results(data, min_grain_size):
    """Prints a detailed report of the PTM and Grain Segmentation analysis."""

    # --- Report dynamically detected phases from PTM ---
    print("\n--- Phase Distribution Report ---")
    if STRUCTURE_TYPE not in data.particles.keys():
        print("Error: 'Structure Type' property not found. PTM analysis may have failed.")
        return None, None

    detected_phases, orphan_atoms_count = _detect_phases(data.particles[STRUCTURE_TYPE].array)

    # --- Grain Segmentation results ---
    grain_table = data.tables.get("grains")
    filtered_grains = _filtered_grains(grain_table, min_grain_size)
    if filtered_grains is None:
        print("No grains were found that meet the specified minimum size.")
    else:
        filtered_grains["min_size"] = min_grain_size
        _print_grain_details(grain_table, filtered_grains)

    # Orphan atoms are exactly the "Other" structure type count
    print(f"Total number of orphan atoms (non-crystalline): {orphan_atoms_count}")

    return detected_phases, orphan_atoms_count


def write_summary_file(filename, rmsd, min_grain_size, num_orphan, data, cell_size, num_atoms, detected_phases):
    """Writes a summary report to a text file."""
    with open(filename, "w") as f:
        f.write("--- Analysis Summary Report ---\n\n")
        f.write(f"RMSD Cutoff: {rmsd}\n")
        f.write(f"Minimum Grain Size: {min_grain_size} atoms\n")
        f.write(f"Total number of orphan atoms: {num_orphan}\n\n")

        f.write(f"Cell size (x, y, z): {cell_size[0]:.2f} x {cell_size[1]:.2f} x {cell_size[2]:.2f}\n")
        f.write(f"Number of atoms: {num_atoms}\n")
        f.write("--- Phase Distribution Report ---\n")

        for phase_num, phase_info in detected_phases.items():
            f.write(
                f"{phase_num}: {phase_info['name']:<20} "
                f"Atoms: {phase_info['count']:<10} "
                f"Percentage: {phase_info['percentage']:.2f}%\n"
            )

        f.write("\n--- Grain Details ---\n")
        grain_table = data.tables.get("grains")
        if grain_table is not None and GRAIN_IDENTIFIER in grain_table and GRAIN_SIZE in grain_table:
            grain_ids = grain_table[GRAIN_IDENTIFIER][...]
            grain_sizes = grain_table[GRAIN_SIZE][...]

            filtered_indices = grain_sizes >= min_grain_size
            filtered_grain_ids = grain_ids[filtered_indices]
            filtered_grain_sizes = grain_sizes[filtered_indices]

            if MEAN_ORIENTATION in grain_table:
                grain_orientations = grain_table[MEAN_ORIENTATION][...]
                filtered_grain_orientations = grain_orientations[filtered_indices]

                f.write("{:<10} {:<15} {:<50}\n".format("Grain ID", "Atoms", "Mean Orientation (Quaternion)"))
                for grain_id, num_atoms_in_grain, orientation in zip(
                    filtered_grain_ids,
                    filtered_grain_sizes,
                    filtered_grain_orientations,
                    strict=True,
                ):
                    orient_str = (
                        f"({orientation[0]:.4f}, {orientation[1]:.4f}, {orientation[2]:.4f}, {orientation[3]:.4f})"
                    )
                    f.write(f"{int(grain_id):<10} {int(num_atoms_in_grain):<15} {orient_str:<50}\n")
            else:
                f.write("{:<10} {:<15}\n".format("Grain ID", "Atoms"))
                for grain_id, num_atoms_in_grain in zip(filtered_grain_ids, filtered_grain_sizes):
                    f.write(f"{int(grain_id):<10} {int(num_atoms_in_grain):<15}\n")
        else:
            f.write("No grain data available for summary.\n")


def _load_params_from_args():
    params = {}
    if len(sys.argv) > 1:
        input_param_file = sys.argv[1]
        print(f"Reading parameters from: {input_param_file}")
        params = parse_input_file(input_param_file)
    return params


def _get_input_file(params):
    if "input_file" in params:
        return params["input_file"]
    return input("Please provide the path to your input structure file: ")


def _load_pipeline(input_file):
    try:
        return import_file(input_file)
    except FileNotFoundError:
        print(f"Error: The file '{input_file}' was not found.")
        sys.exit(1)


def _print_initial_data_info(pipeline, input_file):
    data = pipeline.compute()
    cell_size = data.cell.matrix.diagonal()[:3]
    num_atoms = data.particles.count
    print(f"\nSuccessfully loaded file: '{input_file}'")
    print(f"Cell size (x, y, z): {cell_size[0]:.2f} x {cell_size[1]:.2f} x {cell_size[2]:.2f}")
    print(f"Number of atoms: {num_atoms}\n")
    return cell_size, num_atoms


def _configure_pipeline_modifiers(pipeline, rmsd_cutoff):
    pipeline.modifiers.clear()

    ptm_modifier = PolyhedralTemplateMatchingModifier(rmsd_cutoff=rmsd_cutoff)
    if hasattr(ptm_modifier, "output_orientation"):
        ptm_modifier.output_orientation = True
    elif hasattr(ptm_modifier, "calculate_orientations"):
        ptm_modifier.calculate_orientations = True
    pipeline.modifiers.append(ptm_modifier)

    grain_modifier = GrainSegmentationModifier()
    if hasattr(grain_modifier, "adopt_orphan_atoms"):
        grain_modifier.adopt_orphan_atoms = False
    pipeline.modifiers.append(grain_modifier)


def _should_retry_after_failure(message, batch_mode):
    print(message)
    if batch_mode:
        sys.exit(1)
    choice = input("Do you want to try different parameters? (yes/no): ").strip().lower()
    return choice in ["yes", "y"]


def _run_analysis_once(pipeline, rmsd_cutoff, min_grain_size):
    _configure_pipeline_modifiers(pipeline, rmsd_cutoff)
    computed_data = pipeline.compute()
    detected_phases, num_orphan = report_results(computed_data, min_grain_size)
    return computed_data, detected_phases, num_orphan


def _retry_or_exit(message, batch_mode):
    should_retry = _should_retry_after_failure(message, batch_mode)
    if should_retry:
        return True
    sys.exit(1)
    return False


def _run_analysis_attempt(pipeline, rmsd_cutoff, min_grain_size, batch_mode):
    try:
        result = _run_analysis_once(pipeline, rmsd_cutoff, min_grain_size)
    except Exception as e:
        _retry_or_exit(f"Analysis failed: {e}", batch_mode)
        return None

    if result[1] is None:
        _retry_or_exit("Analysis failed. Please check your input file and installation.", batch_mode)
        return None

    return result


def _run_analysis_loop(pipeline, params):
    batch_mode = "rmsd_cutoff" in params and "min_grain_size" in params
    rmsd_cutoff = min_grain_size = None

    if batch_mode:
        rmsd_cutoff, min_grain_size = get_user_input(params)

    while True:
        if not batch_mode:
            rmsd_cutoff, min_grain_size = get_user_input(params)

        result = _run_analysis_attempt(pipeline, rmsd_cutoff, min_grain_size, batch_mode)
        if result is None:
            continue

        if batch_mode or _is_ready_to_export(pipeline):
            computed_data, detected_phases, num_orphan = result
            return computed_data, detected_phases, num_orphan, rmsd_cutoff, min_grain_size


def _is_ready_to_export(pipeline):
    print("\nDo you want to continue (export files) or modify parameters? (continue/modify):")
    choice = input("Enter your choice (default is 'continue'): ").strip().lower()
    if choice != "modify":
        return True

    pipeline.modifiers.clear()
    print("\nReturning to parameter selection...")
    return False


def _phase_info_for_type(type_id, detected_phases):
    for info in detected_phases.values():
        if info["id"] == type_id:
            return info
    return None


def _element_names_from_particle_types(particles):
    if not hasattr(particles, "particle_types"):
        return {}
    return {pt.id: pt.name if pt.name else f"Type{pt.id}" for pt in particles.particle_types.types}


def _write_lattice_header(f, cell):
    if cell is None:
        return

    matrix = cell.matrix
    f.write(f'Lattice="{matrix[0, 0]:.6f} {matrix[0, 1]:.6f} {matrix[0, 2]:.6f} ')
    f.write(f"{matrix[1, 0]:.6f} {matrix[1, 1]:.6f} {matrix[1, 2]:.6f} ")
    f.write(f'{matrix[2, 0]:.6f} {matrix[2, 1]:.6f} {matrix[2, 2]:.6f}" ')


def _write_position_rows(f, data_for_export, selection_mask, positions, phase_info):
    if PARTICLE_TYPE in data_for_export.particles.keys():
        type_ids = data_for_export.particles[PARTICLE_TYPE].array[selection_mask]
        element_names = _element_names_from_particle_types(data_for_export.particles)

        for i, pos in enumerate(positions):
            type_id_val = int(type_ids[i])
            element = element_names.get(type_id_val, "Fe")
            f.write(f"{element} {pos[0]:.6f} {pos[1]:.6f} {pos[2]:.6f}\n")
        return

    element = "Fe" if phase_info["name"] == "BCC" else "Cr"
    for pos in positions:
        f.write(f"{element} {pos[0]:.6f} {pos[1]:.6f} {pos[2]:.6f}\n")


def _write_phase_file(data_for_export, selection_mask, phase_info):
    safe_name = phase_info["name"].lower().replace(" ", "_").replace("-", "_")
    output_file = f"parent_phase_{safe_name}.xyz"
    positions = data_for_export.particles.position.array[selection_mask]

    with open(output_file, "w") as f:
        f.write(f"{len(positions)}\n")
        _write_lattice_header(f, data_for_export.cell)
        f.write("Properties=species:S:1:pos:R:3\n")
        _write_position_rows(f, data_for_export, selection_mask, positions, phase_info)

    print(f"Exported {len(positions)} atoms of phase '{phase_info['name']}' to '{output_file}'.")


def _export_detected_phases(data_for_export, detected_phases):
    print("\nExporting all detected phases...")

    if STRUCTURE_TYPE not in data_for_export.particles.keys():
        print("Error: 'Structure Type' property not found. Cannot export selected phases.")
        return

    struct_types = data_for_export.particles[STRUCTURE_TYPE].array
    for type_id in np.unique(struct_types):
        phase_info = _phase_info_for_type(type_id, detected_phases)
        selection_mask = struct_types == type_id
        if phase_info and np.any(selection_mask):
            _write_phase_file(data_for_export, selection_mask, phase_info)


def main():
    params = _load_params_from_args()
    input_file = _get_input_file(params)
    pipeline = _load_pipeline(input_file)
    cell_size, num_atoms = _print_initial_data_info(pipeline, input_file)
    data_for_export, detected_phases, num_orphan, rmsd_cutoff, min_grain_size = _run_analysis_loop(pipeline, params)

    _export_detected_phases(data_for_export, detected_phases)

    summary_filename = os.path.splitext(os.path.basename(input_file))[0] + "_summary.txt"
    write_summary_file(
        summary_filename,
        rmsd_cutoff,
        min_grain_size,
        num_orphan,
        data_for_export,
        cell_size,
        num_atoms,
        detected_phases,
    )
    print(f"\nAnalysis summary has been saved to '{summary_filename}'.")

    print("\nExport complete. You can now use these files for advanced meshing.")


if __name__ == "__main__":
    main()

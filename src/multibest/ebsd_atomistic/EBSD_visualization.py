# SPDX-FileCopyrightText: 2026 bright-ideas-clan
#
# SPDX-License-Identifier: GPL-3.0-or-later

# EBSD_visualization.py
import os
import sys

import matplotlib.pyplot as plt
import numpy as np
import simplnx as nx

# Force UTF-8 encoding for standard output and error
if sys.platform == "win32":
    for stream in (sys.stdout, sys.stderr):
        if stream is not None and hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

IMPORTED_DATA = "ImportedData"
IMAGE_GEOMETRY = "Image Geometry"
CELL_DATA = "Cell Data"
CELL_ENSEMBLE_DATA = "Cell Ensemble Data"

CRYSTAL_DICT = {
    0: "Hexagonal_High (6/mmm)",
    1: "Cubic_High (m3m)",
    2: "Hexagonal_Low (6/m)",
    3: "Cubic_Low (m3)",
    4: "Triclinic (-1)",
    5: "Monoclinic (2/m)",
    6: "Orthorhombic (mmm)",
    7: "Tetragonal_Low (4/m)",
    8: "Tetragonal_High (4/mmm)",
    9: "Trigonal_Low (-3)",
    10: "Trigonal_High (-3m)",
    999: "Unknown",
}


def _resolve_phase_path(data_structure):
    """Locate the phase array in the data structure, preferring 'Phases' over 'Phases_Export'."""
    primary = nx.DataPath([IMPORTED_DATA, IMAGE_GEOMETRY, CELL_DATA, "Phases"])
    if primary in data_structure:
        return primary
    print(f"Error: Phases array not found at {primary}")
    fallback = nx.DataPath([IMPORTED_DATA, IMAGE_GEOMETRY, CELL_DATA, "Phases_Export"])
    if fallback in data_structure:
        return fallback
    print("Error: Phases_Export also not found")
    return None


def _resolve_ipf_path(data_structure):
    ipf_path = nx.DataPath([IMPORTED_DATA, IMAGE_GEOMETRY, CELL_DATA, "IPFColors"])
    if ipf_path not in data_structure:
        print(f"Warning: IPFColors not found at {ipf_path}")
        return None
    print(f"Found IPFColors at: {ipf_path}")
    return ipf_path


def _resolve_quality_path(data_structure, data_format):
    if data_format == "ang":
        primary_name, fallback_name = "Image Quality", "Confidence Index"
    else:
        primary_name, fallback_name = "BC", "MAD"

    primary = nx.DataPath([IMPORTED_DATA, IMAGE_GEOMETRY, CELL_DATA, primary_name])
    if primary in data_structure:
        print(f"Found {primary_name} at: {primary}")
        return primary
    print(f"Warning: {primary_name} not found at {primary}")

    fallback = nx.DataPath([IMPORTED_DATA, IMAGE_GEOMETRY, CELL_DATA, fallback_name])
    if fallback in data_structure:
        print(f"Found {fallback_name} at: {fallback}")
        return fallback
    print(f"Warning: {fallback_name} also not found")
    return None


def _infer_dimensions(total_voxels):
    """Infer reasonable (x, y, z) dimensions from voxel count using common EBSD heuristics."""
    if total_voxels % 117 == 0:
        xy_pixels = total_voxels // 117
        side = int(np.sqrt(xy_pixels))
        if side * side == xy_pixels:
            print(f"Inferred dimensions: {[side, side, 117]}")
            return [side, side, 117]
        z_dim = 117
        x_dim = int(np.sqrt(xy_pixels))
        y_dim = xy_pixels // x_dim
        dims = [x_dim, y_dim, z_dim]
        print(f"Approximated dimensions: {dims}")
        return dims

    print(f"Total voxels: {total_voxels}")
    for z in [117, 100, 50, 25]:
        if total_voxels % z == 0:
            xy = total_voxels // z
            x = int(np.sqrt(xy))
            if xy % x == 0:
                y = xy // x
                dims = [x, y, z]
                print(f"Inferred from factor {z}: {dims}")
                return dims

    print("Using simple assumption for dimensions")
    xy_pixels = total_voxels // 117
    x_dim = int(np.sqrt(xy_pixels))
    y_dim = xy_pixels // x_dim
    dims = [x_dim, y_dim, 117]
    print(f"Assumed dimensions: {dims}")
    return dims


def _get_geometry_dims(geom, phase_array):
    if hasattr(geom, "dimensions"):
        dimensions = geom.dimensions
        print(f"Geometry dimensions: {dimensions}")
    else:
        print("Warning: Geometry doesn't have 'dimensions' attribute")
        dimensions = None

    if hasattr(geom, "spacing"):
        print(f"Geometry spacing: {geom.spacing}")

    if dimensions and len(dimensions) == 3:
        x_dim, y_dim, z_dim = dimensions
        print(f"Dimensions: X={x_dim}, Y={y_dim}, Z={z_dim}")
        return dimensions

    print("Inferring dimensions from phase array...")
    return _infer_dimensions(phase_array.size)


def _load_optional_array(data_structure, path, label):
    if path not in data_structure:
        return None
    try:
        arr = data_structure[path].npview()
        print(f"Found {label}: shape {arr.shape}")
        return arr
    except Exception as e:
        print(f"Error accessing {label}: {e}")
        return None


def _reshape_ipf_array(ipf_array, phase_array, z_dim, y_dim, x_dim):
    if ipf_array.size == phase_array.size * 3:
        reshaped = ipf_array.reshape(-1, 3).reshape(z_dim, y_dim, x_dim, 3)
        print(f"Reshaped IPF array to: {reshaped.shape}")
        return reshaped
    if ipf_array.size == phase_array.size:
        reshaped = ipf_array.reshape(z_dim, y_dim, x_dim)
        print(f"Reshaped single-channel IPF to: {reshaped.shape}")
        return reshaped
    print(f"Warning: IPF array size {ipf_array.size} doesn't match phase array size {phase_array.size}")
    return None


def _is_background_phase(phase, crystal_array):
    if crystal_array is None:
        return False
    try:
        if phase < len(crystal_array):
            return crystal_array[phase] == 999
    except Exception:
        return False
    return False


def _compute_phase_portions(phase_array, crystal_array):
    unique_phases = np.unique(phase_array)
    counts = {}
    total_valid = 0
    for phase in unique_phases:
        count = int(np.sum(phase_array == phase))
        counts[phase] = count
        if _is_background_phase(phase, crystal_array):
            print(f"Skipping background phase {phase} (count: {count}, {(count / phase_array.size) * 100:.2f}%)")
        else:
            total_valid += count

    portions = {}
    for phase in unique_phases:
        if counts.get(phase, 0) > 0 and not _is_background_phase(phase, crystal_array):
            portions[phase] = (counts[phase] / total_valid) * 100 if total_valid > 0 else 0
    return unique_phases, counts, portions, total_valid


def _phase_label(phase, phase_names_array):
    if phase_names_array is None:
        return "Unknown"
    try:
        if phase < len(phase_names_array):
            return phase_names_array[phase]
        if phase - 1 < len(phase_names_array):
            return phase_names_array[phase - 1]
    except Exception:
        # Invalid index or unexpected array type — fall through to "Unknown" sentinel.
        return "Unknown"
    return "Unknown"


def _crystal_info(phase, crystal_array):
    if crystal_array is None:
        return None, "Unknown"
    try:
        if phase < len(crystal_array):
            code = crystal_array[phase]
            return code, CRYSTAL_DICT.get(int(code.item()), "Unknown")
    except Exception:
        # Invalid index or non-numpy code value — fall through to "Unknown" sentinel.
        return None, "Unknown"
    return None, "Unknown"


def _print_stats(unique_phases, counts, portions, total_valid, phase_names_array, crystal_array):
    num_phases = len(unique_phases)
    total_cells = sum(counts.values()) if counts else 0
    sum_counts = total_cells
    print("\nPhase Statistics:")
    print(f"Number of phases (including background): {num_phases}")
    print(f"Number of valid phases: {len(portions)}")
    print(f"Total cells: {total_cells}")
    print(f"Sum of counts across all phases: {sum_counts}")
    pct = (total_valid / total_cells) * 100 if total_cells else 0
    print(f"Indexed cells: {total_valid} ({pct:.2f}% of total)")

    if not portions:
        return
    print("\nValid phase types and portions (% of indexed cells):")
    for phase in sorted(portions.keys()):
        name = _phase_label(phase, phase_names_array)
        struct_code, struct_name = _crystal_info(phase, crystal_array)
        print(f"Phase {phase} ({name}): {portions[phase]:.2f}% (raw count: {counts[phase]})")
        print(f"  Crystal structure: {struct_name} (code: {struct_code})")


def _render_ipf_panel(ax, ipf_array_3d, z, z_label):
    if ipf_array_3d is None:
        ax.text(0.5, 0.5, "IPF Colors not available", ha="center", va="center", fontsize=12)
        ax.axis("off")
        print(f"  Slice {z_label}: IPF not available")
        return
    try:
        ipf_2d = ipf_array_3d[z]
        if len(ipf_array_3d.shape) == 4:
            ax.imshow(ipf_2d)
        else:
            ax.imshow(ipf_2d, cmap="viridis")
        ax.set_title("IPF Orientation Map", fontsize=12)
        ax.axis("off")
        print(f"  Slice {z_label}: IPF map generated")
    except Exception as e:
        ax.text(0.5, 0.5, "IPF display error", ha="center", va="center", fontsize=10)
        ax.axis("off")
        print(f"  Slice {z_label}: IPF error - {e}")


def _render_quality_panel(fig, ax, quality_array_3d, z, data_format):
    if quality_array_3d is None:
        ax.text(0.5, 0.5, "Quality data not available", ha="center", va="center", fontsize=12)
        ax.axis("off")
        print(f"  Slice {z}: Quality not available")
        return
    try:
        im = ax.imshow(quality_array_3d[z], cmap="viridis")
        quality_title = "Image Quality" if data_format == "ang" else "Band Contrast"
        ax.set_title(f"{quality_title}", fontsize=12)
        ax.axis("off")
        fig.colorbar(im, ax=ax, label="Value", shrink=0.6)
        print(f"  Slice {z}: Quality map generated")
    except Exception as e:
        ax.text(0.5, 0.5, "Quality display error", ha="center", va="center", fontsize=10)
        ax.axis("off")
        print(f"  Slice {z}: Quality error - {e}")


def _render_phase_panel(ax, phase_array_3d, z, y_dim, x_dim):
    try:
        phase_2d = phase_array_3d[z]
        unique_phases_2d = np.unique(phase_2d)
        if len(unique_phases_2d) == 0:
            ax.text(0.5, 0.5, "No phase data", ha="center", va="center", fontsize=12)
            ax.axis("off")
            print(f"  Slice {z}: No phase data")
            return
        phase_map = np.zeros((y_dim, x_dim, 3), dtype=np.uint8)
        colors = plt.cm.tab20(np.linspace(0, 1, len(unique_phases_2d)))[:, :3] * 255
        for i, ph in enumerate(unique_phases_2d):
            phase_map[phase_2d == ph] = colors[i]
        ax.imshow(phase_map)
        ax.set_title("Phase Map", fontsize=12)
        ax.axis("off")
        from matplotlib.patches import Patch

        legend_elements = [
            Patch(facecolor=colors[i] / 255.0, edgecolor="black", label=f"Phase {ph}")
            for i, ph in enumerate(unique_phases_2d[:10])
        ]
        if len(unique_phases_2d) <= 10:
            ax.legend(handles=legend_elements, loc="upper right", bbox_to_anchor=(1.35, 1), fontsize=8)
        print(f"  Slice {z}: Phase map generated with {len(unique_phases_2d)} phases")
    except Exception as e:
        ax.text(0.5, 0.5, "Phase map error", ha="center", va="center", fontsize=10)
        ax.axis("off")
        print(f"  Slice {z}: Phase map error - {e}")


def _compute_slice_portions(phase_2d, crystal_array):
    unique_phases_2d = np.unique(phase_2d)
    slice_counts = {}
    slice_total_valid = 0
    for ph in unique_phases_2d:
        count = int(np.sum(phase_2d == ph))
        slice_counts[ph] = count
        if not _is_background_phase(ph, crystal_array):
            slice_total_valid += count
    slice_portions = {}
    for ph in unique_phases_2d:
        if slice_counts.get(ph, 0) > 0 and not _is_background_phase(ph, crystal_array):
            slice_portions[ph] = (slice_counts[ph] / slice_total_valid) * 100 if slice_total_valid > 0 else 0
    return slice_portions


def _render_pie_panel(ax, phase_array_3d, z, crystal_array, phase_names_array):
    try:
        phase_2d = phase_array_3d[z]
        slice_portions = _compute_slice_portions(phase_2d, crystal_array)

        if not slice_portions or sum(slice_portions.values()) == 0:
            ax.text(0.5, 0.5, "No valid phases\nfor distribution", ha="center", va="center", fontsize=12)
            print(f"  Slice {z}: No valid phases for pie chart")
            return

        labels, sizes, colors_pie = [], [], []
        cmap = plt.cm.tab20
        for i, ph in enumerate(sorted(slice_portions.keys())):
            name = _phase_label(ph, phase_names_array) or f"Phase {ph}"
            labels.append(f"{name}\n({slice_portions[ph]:.1f}%)")
            sizes.append(slice_portions[ph])
            colors_pie.append(cmap(i % 20))

        wedges, _, _ = ax.pie(
            sizes,
            colors=colors_pie,
            autopct="",
            startangle=90,
            wedgeprops={"linewidth": 1, "edgecolor": "black"},
            textprops={"fontsize": 8},
        )
        ax.set_title("Phase Distribution", fontsize=12)
        ax.legend(
            wedges,
            labels,
            loc="center left",
            bbox_to_anchor=(1, 0, 0.5, 1),
            fontsize=8,
            title="Phases (% of indexed)",
        )
        print(f"  Slice {z}: Pie chart generated with {len(slice_portions)} phases")
    except Exception as e:
        ax.text(0.5, 0.5, "Pie chart error", ha="center", va="center", fontsize=10)
        print(f"  Slice {z}: Pie chart error - {e}")


def _save_slice_figure(
    z,
    ipf_array_3d,
    quality_array_3d,
    phase_array_3d,
    crystal_array,
    phase_names_array,
    data_format,
    y_dim,
    x_dim,
    vis_output_dir,
):
    try:
        fig, axs = plt.subplots(2, 2, figsize=(14, 12), dpi=150)
        fig.suptitle(f"EBSD Analysis - Slice Z={z} (0-indexed)", fontsize=16)

        _render_ipf_panel(axs[0, 0], ipf_array_3d, z, z)
        _render_quality_panel(fig, axs[0, 1], quality_array_3d, z, data_format)
        _render_phase_panel(axs[1, 0], phase_array_3d, z, y_dim, x_dim)
        _render_pie_panel(axs[1, 1], phase_array_3d, z, crystal_array, phase_names_array)
        axs[1, 1].axis("off")

        plt.tight_layout(rect=[0, 0, 1, 0.96])
        output_path = os.path.join(vis_output_dir, f"ebsd_slice_z{z:03d}.png")
        fig.savefig(output_path, dpi=150, bbox_inches="tight")
        plt.close(fig)
        print(f"  Saved visualization for slice Z={z}: {output_path}")
    except Exception as e:
        print(f"  Error generating visualization for slice Z={z}: {e}")
        import traceback

        traceback.print_exc()


def _validate_base_paths(data_structure):
    """Validate the base and cell data paths exist; return (base_path, cell_ensemble_path) or None."""
    base_path = nx.DataPath([IMPORTED_DATA, IMAGE_GEOMETRY])
    if base_path not in data_structure:
        print(f"Error: Base path {base_path} not found in data structure")
        return None
    print(f"Found data structure at: {base_path}")

    cell_data_path = nx.DataPath([IMPORTED_DATA, IMAGE_GEOMETRY, CELL_DATA])
    cell_ensemble_path = nx.DataPath([IMPORTED_DATA, IMAGE_GEOMETRY, CELL_ENSEMBLE_DATA])
    print(f"\nLooking for Cell Data at: {cell_data_path}")
    print(f"Looking for Cell Ensemble Data at: {cell_ensemble_path}")
    if cell_data_path not in data_structure:
        print(f"Error: Cell Data not found at {cell_data_path}")
        return None
    print(f"Found Cell Data at: {cell_data_path}")
    return base_path, cell_ensemble_path


def _load_phase_array(data_structure, phase_path):
    try:
        phase_array = data_structure[phase_path].npview()
        print(f"Found phase array at: {phase_path}")
        print(f"Phase array shape: {phase_array.shape}")
        return phase_array
    except Exception as e:
        print(f"Error accessing phase array: {e}")
        return None


def _compute_geometry(data_structure, base_path, phase_array):
    """Return (x_dim, y_dim, z_dim, phase_array_3d) or None on failure."""
    try:
        geom = data_structure[base_path]
        dimensions = _get_geometry_dims(geom, phase_array)
    except Exception as e:
        print(f"Error getting geometry: {e}")
        return None
    if not dimensions:
        print("Error: Could not determine dimensions")
        return None
    x_dim, y_dim, z_dim = dimensions
    try:
        phase_array_3d = phase_array.reshape(z_dim, y_dim, x_dim)
    except Exception as e:
        print(f"Error reshaping phase array: {e}")
        return None
    print(f"Reshaped phase array to: {phase_array_3d.shape}")
    return x_dim, y_dim, z_dim, phase_array_3d


def _load_phase_meta_arrays(data_structure, cell_ensemble_path):
    if cell_ensemble_path not in data_structure:
        return None, None
    phase_names_array = _load_optional_array(
        data_structure,
        nx.DataPath([IMPORTED_DATA, IMAGE_GEOMETRY, CELL_ENSEMBLE_DATA, "PhaseNames"]),
        "PhaseNames",
    )
    crystal_array = _load_optional_array(
        data_structure,
        nx.DataPath([IMPORTED_DATA, IMAGE_GEOMETRY, CELL_ENSEMBLE_DATA, "CrystalStructures"]),
        "CrystalStructures",
    )
    return phase_names_array, crystal_array


def _load_ipf_3d(data_structure, ipf_path, phase_array, z_dim, y_dim, x_dim):
    if not (ipf_path and ipf_path in data_structure):
        return None
    try:
        ipf_array = data_structure[ipf_path].npview()
        print(f"IPF array shape: {ipf_array.shape}")
        return _reshape_ipf_array(ipf_array, phase_array, z_dim, y_dim, x_dim)
    except Exception as e:
        print(f"Error processing IPF array: {e}")
        return None


def _load_quality_3d(data_structure, quality_path, z_dim, y_dim, x_dim):
    if not (quality_path and quality_path in data_structure):
        return None
    try:
        quality_array = data_structure[quality_path].npview()
        print(f"Quality array shape: {quality_array.shape}")
        reshaped = quality_array.reshape(z_dim, y_dim, x_dim)
        print(f"Reshaped quality array to: {reshaped.shape}")
        return reshaped
    except Exception as e:
        print(f"Error processing quality array: {e}")
        return None


def _determine_slices_to_process(generate_all_slices, z_dim):
    if generate_all_slices:
        print(f"\nGenerating visualizations for ALL {z_dim} slices...")
        return list(range(z_dim))
    slices = [0]
    if z_dim > 1:
        slices.append(z_dim // 2)
    if z_dim > 2:
        slices.append(z_dim - 1)
    print(f"\nGenerating visualizations for representative slices: {slices}")
    return slices


def visualize_and_measure(data_structure, data_format, visualization_output_dir=".", generate_all_slices=False):
    """
    Visualization and measurement function for EBSD data
    Args:
        data_structure: simplnx data structure
        data_format: 'ang' or 'ctf' format
        visualization_output_dir: Directory to save visualization files
        generate_all_slices: If True, generate visualizations for all slices
    """

    print("\n=== Starting EBSD Visualization and Measurements ===")
    print("\n=== Direct Path Check ===")

    paths = _validate_base_paths(data_structure)
    if paths is None:
        return
    base_path, cell_ensemble_path = paths

    print("\n=== Looking for specific arrays ===")
    phase_path = _resolve_phase_path(data_structure)
    if phase_path is None:
        return

    phase_array = _load_phase_array(data_structure, phase_path)
    if phase_array is None:
        return

    ipf_path = _resolve_ipf_path(data_structure)
    quality_path = _resolve_quality_path(data_structure, data_format)

    print("\n=== Getting geometry information ===")
    geometry = _compute_geometry(data_structure, base_path, phase_array)
    if geometry is None:
        return
    x_dim, y_dim, z_dim, phase_array_3d = geometry

    phase_names_array, crystal_array = _load_phase_meta_arrays(data_structure, cell_ensemble_path)
    ipf_array_3d = _load_ipf_3d(data_structure, ipf_path, phase_array, z_dim, y_dim, x_dim)
    quality_array_3d = _load_quality_3d(data_structure, quality_path, z_dim, y_dim, x_dim)

    print("\n=== Calculating statistics ===")
    unique_phases, counts, portions, total_valid = _compute_phase_portions(phase_array, crystal_array)
    _print_stats(unique_phases, counts, portions, total_valid, phase_names_array, crystal_array)

    vis_output_dir = visualization_output_dir
    os.makedirs(vis_output_dir, exist_ok=True)
    print(f"\nVisualization output directory: {vis_output_dir}")

    slices_to_process = _determine_slices_to_process(generate_all_slices, z_dim)

    print("\n=== Generating visualizations ===")
    for z in slices_to_process:
        _save_slice_figure(
            z,
            ipf_array_3d,
            quality_array_3d,
            phase_array_3d,
            crystal_array,
            phase_names_array,
            data_format,
            y_dim,
            x_dim,
            vis_output_dir,
        )

    print(f"\nVisualization complete! Images saved to: {vis_output_dir}")
    print("=== EBSD Visualization and Measurements Complete ===\n")

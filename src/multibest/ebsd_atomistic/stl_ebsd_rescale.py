# SPDX-FileCopyrightText: 2026 bright-ideas-clan
#
# SPDX-License-Identifier: GPL-3.0-or-later

import argparse
import glob
import sys
from pathlib import Path

import numpy as np
import pymeshlab

# Force UTF-8 encoding for standard output and error
if sys.platform == "win32":
    for stream in (sys.stdout, sys.stderr):
        if stream is not None and hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)


def scale_assembly_together(input_files, output_dir, scale_factor, displace=None):
    """
    Load all STL files into a single MeshSet, scale them together around the assembly center,
    then save individually. Fixed so the assembly center stays in place after scaling.
    """
    print("Loading all meshes into a single MeshSet...")
    ms = pymeshlab.MeshSet()
    mesh_file_mapping = {}

    for i, input_file in enumerate(sorted(input_files)):
        print(f"  Loading: {input_file.name}")
        ms.load_new_mesh(str(input_file))
        mesh_file_mapping[i] = input_file.name

    print(f"Successfully loaded {len(input_files)} meshes")

    # Compute assembly bounds / center
    if len(input_files) > 0:
        overall_min = np.array([float("inf"), float("inf"), float("inf")])
        overall_max = np.array([-float("inf"), -float("inf"), -float("inf")])

        for i in range(len(input_files)):
            mesh = ms.mesh(i)
            bbox = mesh.bounding_box()
            overall_min = np.minimum(overall_min, bbox.min())
            overall_max = np.maximum(overall_max, bbox.max())

        assembly_center = (overall_min + overall_max) / 2.0
        assembly_dim = overall_max - overall_min

        print("\nAssembly before scaling:")
        print(f"  Bounds: {overall_min} to {overall_max}")
        print(f"  Center: {assembly_center}")
        print(f"  Dimensions: {assembly_dim}")
    else:
        print("No input files!")
        return 0

    # Move assembly center to origin (apply to all layers)
    print(f"\nTranslating assembly center to origin: -{assembly_center}")
    ms.apply_filter(
        "compute_matrix_from_translation",
        traslmethod=0,
        axisx=-assembly_center[0],
        axisy=-assembly_center[1],
        axisz=-assembly_center[2],
        freeze=True,
        alllayers=True,
    )

    # Scale around origin (now center is at origin)
    print(f"Applying uniform scaling factor {scale_factor} around origin")
    ms.apply_filter(
        "compute_matrix_from_scaling_or_normalization",
        axisx=scale_factor,
        axisy=scale_factor,
        axisz=scale_factor,
        uniformflag=True,  # uniform scaling
        scalecenter=0,  # scale around origin (we moved center there)
        customcenter=np.array([0.0, 0.0, 0.0]),
        unitflag=False,
        freeze=True,
        alllayers=True,
    )

    # Move back by the original assembly center (NOT scaled)
    print(f"Translating assembly back by +{assembly_center}")
    ms.apply_filter(
        "compute_matrix_from_translation",
        traslmethod=0,
        axisx=assembly_center[0],
        axisy=assembly_center[1],
        axisz=assembly_center[2],
        freeze=True,
        alllayers=True,
    )

    # Apply displacement if specified
    if displace and (displace[0] != 0 or displace[1] != 0 or displace[2] != 0):
        dx, dy, dz = displace
        print(f"Applying displacement: X={dx}, Y={dy}, Z={dz}")
        ms.apply_filter(
            "compute_matrix_from_translation", traslmethod=0, axisx=dx, axisy=dy, axisz=dz, freeze=True, alllayers=True
        )

    # Rest of your bounding-box checks and saving...
    # (unchanged from your original code)
    overall_min_scaled = np.array([float("inf"), float("inf"), float("inf")])
    overall_max_scaled = np.array([-float("inf"), -float("inf"), -float("inf")])

    for i in range(len(input_files)):
        mesh = ms.mesh(i)
        bbox = mesh.bounding_box()
        overall_min_scaled = np.minimum(overall_min_scaled, bbox.min())
        overall_max_scaled = np.maximum(overall_max_scaled, bbox.max())

    assembly_dim_scaled = overall_max_scaled - overall_min_scaled

    print("\nAssembly after scaling:")
    print(f"  Bounds: {overall_min_scaled} to {overall_max_scaled}")
    print(f"  Center (should be close to original center): {(overall_min_scaled + overall_max_scaled) / 2.0}")
    print(f"  Dimensions: {assembly_dim_scaled}")
    print(f"  Expected scaling: {assembly_dim * scale_factor}")
    print(f"  Actual scaling: {assembly_dim_scaled}")

    # Save each mesh individually
    print(f"\nSaving scaled meshes to: {output_dir}")
    successful = 0
    for i, original_filename in mesh_file_mapping.items():
        try:
            ms.set_current_mesh(i)
            output_path = output_dir / original_filename
            ms.save_current_mesh(str(output_path))
            print(f"  ✓ Saved: {original_filename}")
            successful += 1
        except Exception as e:
            print(f"  ✗ Failed to save {original_filename}: {str(e)}")
    return successful


def main():
    parser = argparse.ArgumentParser(description="Scale STL assembly by loading all meshes together")
    parser.add_argument(
        "--scale_factor", type=float, required=True, help="Uniform scale factor for all axes (e.g., 5.0)"
    )
    parser.add_argument("--input_dir", type=str, required=True, help="Input directory containing STL files")
    parser.add_argument(
        "--input_prefix", type=str, required=True, help="Prefix of input files (e.g., TriangleFeature_)"
    )
    parser.add_argument("--output_dir", type=str, required=True, help="Output directory for scaled STL files")
    parser.add_argument(
        "--displace", nargs=3, type=float, default=[0, 0, 0], help="Displacement along X, Y, Z axes (e.g., 0 0 10)"
    )

    args = parser.parse_args()

    # Convert to Path objects
    input_dir = Path(args.input_dir)
    output_dir = Path(args.output_dir)

    # Check if input directory exists
    if not input_dir.exists():
        print(f"Error: Input directory '{input_dir}' does not exist.")
        sys.exit(1)

    # Create output directory if it doesn't exist
    output_dir.mkdir(parents=True, exist_ok=True)
    print(f"Output directory created/verified: {output_dir}")

    # Find all STL files with the given prefix
    pattern = str(input_dir / f"{args.input_prefix}*.stl")
    stl_files = glob.glob(pattern)

    if not stl_files:
        print(f"No STL files found with pattern: {pattern}")
        sys.exit(1)

    stl_files = [Path(f) for f in stl_files]

    print(f"Found {len(stl_files)} STL files to process")
    print(f"Scale factor: {args.scale_factor}")
    print(f"Displacement: {args.displace}")
    print("USING SINGLE ASSEMBLY TRANSFORMATION METHOD")
    print("-" * 60)

    # Process all files together
    successful = scale_assembly_together(
        input_files=stl_files, output_dir=output_dir, scale_factor=args.scale_factor, displace=args.displace
    )

    # Summary
    print("\n" + "=" * 60)
    print("SINGLE ASSEMBLY TRANSFORMATION COMPLETED!")
    print(f"Successfully processed: {successful} files")
    print(f"Output directory: {output_dir}")
    print("\nMETHOD SUMMARY:")
    print("✓ All meshes loaded into single MeshSet")
    print("✓ Single transformation applied to entire assembly")
    print("✓ Perfect preservation of spatial relationships")
    print("✓ Equivalent to 'Apply to all visible meshes' in MeshLab")


if __name__ == "__main__":
    main()

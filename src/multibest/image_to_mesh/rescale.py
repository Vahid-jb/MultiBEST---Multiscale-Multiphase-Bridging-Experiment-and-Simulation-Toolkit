# SPDX-FileCopyrightText: 2026 bright-ideas-clan
#
# SPDX-License-Identifier: GPL-3.0-or-later

import argparse
import os
import sys

import numpy as np
import pymeshlab

# Force UTF-8 encoding for standard output and error
if sys.platform == "win32":
    for stream in (sys.stdout, sys.stderr):
        if stream is not None and hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)


def main():
    parser = argparse.ArgumentParser(
        description="Transform a mesh with scaling, rotation, and displacement using PyMeshLab."
    )
    parser.add_argument("--input_mesh", required=True, help="Input mesh file (e.g., .stl, .obj)")
    parser.add_argument(
        "--scale_value",
        nargs=3,
        type=float,
        required=True,
        help="Three scale factors for X, Y, Z axes (e.g., 50 50 300)",
    )
    parser.add_argument(
        "--displace", nargs=3, type=float, default=[0, 0, 0], help="Displacement along X, Y, Z axes (e.g., 20 2.2 1.6)"
    )
    parser.add_argument(
        "--rotate",
        nargs=6,
        type=str,
        default=None,
        help="Rotation angles: specify axis and angle pairs (e.g., --rotate x 25 y 36 z 69)",
    )
    parser.add_argument("--output", required=True, help="Output mesh file (e.g., .obj, .stl)")

    args = parser.parse_args()

    if not os.path.exists(args.input_mesh):
        raise FileNotFoundError(f"Input file {args.input_mesh} not found.")

    # Load the mesh
    ms = pymeshlab.MeshSet()
    ms.load_new_mesh(args.input_mesh)

    # Get original mesh center for rotation reference
    original_mesh = ms.current_mesh()
    original_bb = original_mesh.bounding_box()
    original_center = original_bb.center()

    print(f"Original mesh loaded. Center: {original_center}")

    # Step 1: Apply scaling
    sx, sy, sz = args.scale_value
    print(f"Applying non-uniform scaling: X={sx}, Y={sy}, Z={sz}")

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

    # Step 2: Apply rotations (if specified)
    if args.rotate:
        print("Applying rotations...")

        # Parse rotation arguments
        rotations = {}
        for i in range(0, len(args.rotate), 2):
            axis = args.rotate[i].lower()
            angle = float(args.rotate[i + 1])
            rotations[axis] = angle
            print(f"  Rotation around {axis}-axis: {angle}°")

        # Axis mapping: x=0, y=1, z=2, custom axis=3
        axis_mapping = {"x": 0, "y": 1, "z": 2}

        # Rotation center mapping: origin=0, barycenter=1, custom point=2
        rotcenter_mapping = 2  # custom point

        # Apply rotations in order: X, Y, Z
        axis_order = ["x", "y", "z"]
        for axis in axis_order:
            if axis in rotations:
                angle = rotations[axis]

                ms.apply_filter(
                    "compute_matrix_from_rotation",
                    rotaxis=axis_mapping[axis],
                    angle=angle,
                    rotcenter=rotcenter_mapping,
                    customcenter=original_center,
                    freeze=True,
                    alllayers=False,
                )

    # Step 3: Always apply recenter (Ctrl+H equivalent)
    print("Applying recenter (Ctrl+H equivalent)...")

    # Get current mesh center
    current_mesh = ms.current_mesh()
    current_bb = current_mesh.bounding_box()
    current_center = current_bb.center()

    # Translate to origin (this is what Ctrl+H does in MeshLab)
    ms.apply_filter(
        "compute_matrix_from_translation",
        traslmethod=0,
        axisx=-current_center[0],
        axisy=-current_center[1],
        axisz=-current_center[2],
        freeze=True,
        alllayers=False,
    )

    # Step 4: Apply displacement ONLY if specified (after recenter)
    dx, dy, dz = args.displace
    displacement_applied = False
    if dx != 0 or dy != 0 or dz != 0:
        print(f"Applying displacement: X={dx}, Y={dy}, Z={dz}")
        ms.apply_filter(
            "compute_matrix_from_translation", traslmethod=0, axisx=dx, axisy=dy, axisz=dz, freeze=True, alllayers=False
        )
        displacement_applied = True

    # Save the result
    ms.save_current_mesh(args.output)

    # Print transformation summary
    final_mesh = ms.current_mesh()
    final_bb = final_mesh.bounding_box()

    # Calculate dimensions manually
    original_dim = original_bb.max() - original_bb.min()
    final_dim = final_bb.max() - final_bb.min()
    final_center = final_bb.center()

    print("\nTransformation completed!")
    print(f"Original dimensions: {original_dim}")
    print(f"Final dimensions: {final_dim}")
    print(f"Final mesh center: {final_center}")

    if displacement_applied:
        print(f"Displacement applied: X={dx}, Y={dy}, Z={dz}")
        print(f"Final position after displacement: {final_center}")
    else:
        print("No displacement applied - mesh centered at origin")

    print(f"Successfully saved to: {args.output}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 bright-ideas-clan
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Image_to_Mesh (patched) - create Guest / Base / Bulk meshes from mask image in Blender,
align bottoms to Bulk, then export each object.

Usage (example):
blender --background --python ./Image_to_Mesh.py -- \
    --image ./micro-clean.png --vertices fine --depth 0.25 \
    --format STL --outdir . --guest --bulk --base

Every parameter can instead be read from a 'key = value' input file (the file the
GUI writes into the output directory):

blender --background --python ./Image_to_Mesh.py -- --input-file ./input_image_to_mesh.txt
"""

import argparse
import os
import sys
import tempfile

import bmesh
import bpy
from mathutils import Vector

# Force UTF-8 encoding for standard output and error
if sys.platform == "win32":
    for stream in (sys.stdout, sys.stderr):
        if stream is not None and hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

# Handle Blender passing all CLI args to sys.argv
if "--" in sys.argv:
    arg_start = sys.argv.index("--") + 1
    script_argv = sys.argv[arg_start:]
else:
    script_argv = []

# Input-file keys mapped onto the option of the same name.
VALUE_INPUT_KEYS = ("image", "vertices", "depth", "format", "outdir")
PHASE_INPUT_KEYS = ("guest", "base", "bulk")


def cleanup_scene():
    """Remove everything from the scene (use at start of run)."""
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)


def get_image_dimensions(image_path):
    try:
        img = bpy.data.images.load(image_path, check_existing=True)
        return img.size[0], img.size[1], img.name
    except Exception as e:
        print(f"Error loading image: {e}")
        return None, None, None


def set_image_data_colorspace(image):
    """Use a Blender-version-compatible color space for displacement masks."""
    enum_items = image.colorspace_settings.bl_rna.properties["name"].enum_items
    available_names = {value for item in enum_items for value in (item.identifier, item.name)}
    for colorspace in ("Non-Color", "scene_linear", "Linear Rec.709", "Linear CIE-XYZ D65"):
        if colorspace in available_names:
            image.colorspace_settings.name = colorspace
            return
    print(f"Warning: could not find a known linear/non-color colorspace. Using {image.colorspace_settings.name}.")


def create_inverted_image(original_image_path):
    """Create an inverted version of the image (black becomes white, white becomes black)"""
    try:
        original_img = bpy.data.images.load(original_image_path, check_existing=False)
        width, height = original_img.size
        inverted_img = bpy.data.images.new("inverted_mask", width=width, height=height, alpha=True)

        original_pixels = list(original_img.pixels)
        inverted_pixels = original_pixels[:]
        for index in range(0, len(original_pixels), 4):
            inverted_pixels[index] = 1.0 - original_pixels[index]
            inverted_pixels[index + 1] = 1.0 - original_pixels[index + 1]
            inverted_pixels[index + 2] = 1.0 - original_pixels[index + 2]
            inverted_pixels[index + 3] = original_pixels[index + 3]

        inverted_img.pixels.foreach_set(inverted_pixels)

        temp_dir = tempfile.gettempdir()
        inverted_path = os.path.join(temp_dir, "inverted_mask.png")
        inverted_img.filepath_raw = inverted_path
        inverted_img.file_format = "PNG"
        inverted_img.save()

        bpy.data.images.remove(original_img)
        bpy.data.images.remove(inverted_img)

        print(f"Created inverted image at: {inverted_path}")
        return inverted_path

    except Exception as e:
        print(f"Error creating inverted image: {e}")
        return None


def create_3d_mesh_from_image(image_path, extrusion_depth, phase_name, vertices="fine"):
    """
    Create a relief plane from image, extrude to given depth, and return the created Blender object.
    This function DOES NOT export; caller will align & export later.
    """
    if not os.path.exists(image_path):
        print(f"ERROR: Image not found at {image_path}")
        return None

    # Step 1: Create and scale plane
    width, height, img_name = get_image_dimensions(image_path)
    if not width or not height:
        return None

    scale_factor = 0.01
    plane_width = width * scale_factor
    plane_height = height * scale_factor

    print(f"Image dimensions: {width} x {height} pixels")
    print(f"Plane dimensions: {plane_width} x {plane_height} units")
    print(f"Processing phase: {phase_name}")

    bpy.ops.mesh.primitive_plane_add(size=2)
    plane = bpy.context.object
    plane.name = f"Image_Relief_Mesh_{phase_name.replace(' ', '_')}"
    plane.scale.x = plane_width / 2.0
    plane.scale.y = plane_height / 2.0
    # Bake transforms including location to standardize with Bulk branch
    bpy.ops.object.transform_apply(location=True, rotation=False, scale=True)
    print(f"  After scaling: width = {plane.dimensions.x:.6f}, height = {plane.dimensions.y:.6f}")

    # Step 2: Subdivide
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.subdivide(number_cuts=100)
    vertices_mapping = {"coarse": 2, "normal": 3, "fine": 5, "extra_fine": 10}
    subdivision_cuts = vertices_mapping.get(vertices, 5)
    bpy.ops.mesh.subdivide(number_cuts=subdivision_cuts)
    bpy.ops.object.mode_set(mode="OBJECT")

    # Step 3: Displace modifier
    tex_data = bpy.data.textures.new(name=f"ImageTexture_{phase_name.replace(' ', '_')}", type="IMAGE")
    tex_data.image = bpy.data.images[img_name]
    set_image_data_colorspace(tex_data.image)
    tex_data.extension = "CLIP"

    disp_mod = plane.modifiers.new(name=f"Displace_{phase_name.replace(' ', '_')}", type="DISPLACE")
    disp_mod.texture = tex_data
    disp_mod.strength = -0.25
    disp_mod.direction = "NORMAL"
    disp_mod.mid_level = 0.5
    disp_mod.texture_coords = "UV"
    bpy.ops.object.modifier_apply(modifier=disp_mod.name)

    # Step 4: Delete flat (higher Z) faces and flatten base
    bpy.ops.object.mode_set(mode="EDIT")
    bm = bmesh.from_edit_mesh(plane.data)
    z_threshold = 0.01

    # Delete vertices where Z <= -z_threshold (non-destructive alternative would be to clamp)
    verts_to_delete = [v for v in bm.verts if v.co.z <= -z_threshold]
    if verts_to_delete:
        bmesh.ops.delete(bm, geom=verts_to_delete, context="VERTS")

    # Clean up any loose vertices/edges
    loose_verts = [v for v in bm.verts if len(v.link_edges) == 0]
    loose_edges = [e for e in bm.edges if len(e.link_faces) == 0]
    if loose_verts:
        bmesh.ops.delete(bm, geom=loose_verts, context="VERTS")
    if loose_edges:
        bmesh.ops.delete(bm, geom=loose_edges, context="EDGES")

    # Update mesh and check for empty geometry
    bmesh.update_edit_mesh(plane.data)
    if not bm.verts:
        print(
            "Error: No geometry left after deleting flat faces."
            " Check image contrast/variation for effective displacement."
        )
        bpy.ops.object.mode_set(mode="OBJECT")
        return None

    # Select all and translate to min Z=0 (local coordinates)
    bpy.ops.mesh.select_all(action="SELECT")
    min_z = min(v.co.z for v in bm.verts)
    bmesh.ops.translate(bm, verts=bm.verts, vec=(0, 0, -min_z))

    # Flatten Z (base to single plane)
    bpy.ops.transform.resize(value=(1, 1, 0), orient_type="GLOBAL")
    bmesh.update_edit_mesh(plane.data)
    bpy.ops.object.mode_set(mode="OBJECT")

    # Step 5: Extrude up (positive Z) by full extrusion_depth
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    extrude_amount = extrusion_depth
    if extrude_amount > 0:
        bpy.ops.mesh.extrude_region_move(
            MESH_OT_extrude_region={"use_normal_flip": False}, TRANSFORM_OT_translate={"value": (0, 0, extrude_amount)}
        )
    else:
        print(f"Warning: extrusion_depth ({extrusion_depth}) is not positive; skipping extrusion.")
    bpy.ops.object.mode_set(mode="OBJECT")

    # Debug: Print final local dimensions
    print(
        f"  {phase_name} created: width = {plane.dimensions.x:.6f},"
        f" height = {plane.dimensions.y:.6f}, depth = {plane.dimensions.z:.6f}"
    )

    # Return the created object so caller can align & export later
    return plane


def align_phases_to_bulk(bulk_name="Bulk_Phase"):
    """
    Align all phase objects (Image_Relief_Mesh_* and *_Phase objects) so their bottom (min Z)
    matches the Bulk object's bottom (world space). This moves objects in world Z and bakes translation.
    """
    bulk_obj = bpy.data.objects.get(bulk_name)
    if bulk_obj is None:
        print("align_phases_to_bulk: Bulk object not found. Skipping alignment.")
        return

    # compute bulk world min z from its bounding box corners
    bulk_world_corners = [bulk_obj.matrix_world @ Vector(corner) for corner in bulk_obj.bound_box]
    bulk_min_z = min(v.z for v in bulk_world_corners)

    # candidate phase objects to align: ones we named with our convention
    candidates = [
        obj
        for obj in bpy.data.objects
        if (obj.name.startswith("Image_Relief_Mesh_") or obj.name.endswith("_Phase")) and obj != bulk_obj
    ]

    for obj in candidates:
        corners = [obj.matrix_world @ Vector(corner) for corner in obj.bound_box]
        obj_min_z = min(v.z for v in corners)
        delta = bulk_min_z - obj_min_z

        if abs(delta) > 1e-9:
            # move object in world Z
            obj.location.z += delta
            # bake the translation into mesh data (so exported file coordinates match world)
            bpy.context.view_layer.update()
            bpy.ops.object.select_all(action="DESELECT")
            obj.select_set(True)
            bpy.context.view_layer.objects.active = obj
            bpy.ops.object.transform_apply(location=True, rotation=False, scale=False)
            print(f"Aligned {obj.name} by delta Z = {delta:.6f}")
        else:
            print(f"{obj.name} already aligned (delta {delta:.6f})")


def build_parser():
    """Build the command-line parser for this script."""
    parser = argparse.ArgumentParser(description="Convert 2D image to 3D mesh in Blender")
    parser.add_argument(
        "--input-file",
        type=str,
        help="Parameter file with 'key = value' lines; overrides every other argument when given.",
    )
    parser.add_argument("--image", type=str, help="Full path to reference image (PNG/JPG)")
    parser.add_argument("--depth", type=float, default=0.25, help="Extrusion depth (default: 0.25)")
    parser.add_argument(
        "--vertices",
        type=str,
        default="fine",
        choices=["coarse", "normal", "fine", "extra_fine"],
        help="Mesh density (default: normal)",
    )
    parser.add_argument(
        "--format", type=str, default="STL", choices=["STL", "OBJ", "FBX"], help="Export format (default: STL)"
    )
    parser.add_argument("--outdir", type=str, help="Output directory (default: current dir)")
    parser.add_argument("--guest", action="store_true", help="Generate Guest Phase mesh")
    parser.add_argument("--base", action="store_true", help="Generate Base Phase mesh")
    parser.add_argument("--bulk", action="store_true", help="Generate Bulk Phase mesh")
    return parser


def parse_input_file(input_file):
    """Parse ``key = value`` parameters from an input text file."""
    params = {}
    with open(input_file, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, value = line.split("=", 1)
                params[key.strip()] = value.strip()
    return params


def argv_from_input_file(input_file):
    """Translate an input file written by the GUI into CLI arguments."""
    params = parse_input_file(input_file)
    argv = []
    for key in VALUE_INPUT_KEYS:
        value = params.get(key, "").strip()
        if value:
            argv.extend([f"--{key}", value])
    for key in PHASE_INPUT_KEYS:
        if params.get(key, "").strip().lower() in {"1", "true", "yes", "on"}:
            argv.append(f"--{key}")
    return argv


def parse_args(argv=None):
    """Parse arguments from *argv*, or from the input file it points at."""
    parser = build_parser()
    args = parser.parse_args(script_argv if argv is None else argv)
    if args.input_file:
        args = parser.parse_args(argv_from_input_file(args.input_file))
    return args


if __name__ == "__main__":
    args = parse_args()

    # If no phase flags are specified, generate all phases (backward compatibility)
    if not (args.guest or args.base or args.bulk):
        args.guest = True
        args.base = True
        args.bulk = True
        print("No phase flags specified. Generating all phases (Guest, Base, Bulk).")

    # Fallback to interactive if no CLI args provided (for GUI testing)
    image_path = args.image if args.image else input("Enter full path to reference image (PNG/JPG): ").strip()
    extrusion_depth = (
        args.depth if args.depth is not None else float(input("Enter extrusion depth (e.g., 0.25): ").strip())
    )
    export_format = args.format.upper()
    output_dir = args.outdir if args.outdir else input("Enter output directory: ").strip()
    # Ensure output_dir is absolute and exists
    if output_dir == ".":
        output_dir = os.getcwd()
    elif not os.path.isabs(output_dir):
        output_dir = os.path.abspath(output_dir)

    # Create directory if it doesn't exist
    os.makedirs(output_dir, exist_ok=True)
    print(f"Using absolute output directory: {output_dir}")

    # Make image path absolute if relative
    if image_path and not os.path.isabs(image_path):
        image_path = os.path.abspath(image_path)

    # Create inverted image (only needed if base phase is requested)
    inverted_image_path = None
    if args.base:
        print("Creating inverted version of the mask...")
        inverted_image_path = create_inverted_image(image_path)
        if not inverted_image_path:
            print("Failed to create inverted image. Skipping Base Phase.")
            args.base = False

    # --- START: run with a fresh scene and keep created objects ---
    cleanup_scene()
    created_objects = []  # list of tuples (phase_name, object)

    # Create Guest Phase(s)
    if args.guest:
        print("\n=== PROCESSING GUEST PHASE ===")
        obj = create_3d_mesh_from_image(image_path, extrusion_depth, "Guest_Phase", args.vertices)
        if obj:
            created_objects.append(("Guest_Phase", obj))
    else:
        print("\n=== SKIPPING GUEST PHASE ===")

    # Create Base Phase(s)
    if args.base:
        print("\n=== PROCESSING BASE PHASE ===")
        base_obj = create_3d_mesh_from_image(inverted_image_path, extrusion_depth, "Base_Phase", args.vertices)
        if base_obj:
            created_objects.append(("Base_Phase", base_obj))
    else:
        print("\n=== SKIPPING BASE PHASE ===")

    # Create Bulk Phase (keep it too)
    if args.bulk:
        print("\n=== PROCESSING BULK PHASE (plain block matching dimensions & subdivision) ===")
        width, height, _ = get_image_dimensions(image_path)
        if not width or not height:
            print("Failed to read image dimensions for bulk phase. Skipping Bulk_Phase creation.")
        else:
            scale_factor = 0.01
            block_w = width * scale_factor
            block_h = height * scale_factor
            block_d = extrusion_depth

            bpy.ops.mesh.primitive_cube_add(size=2)
            bulk_obj = bpy.context.object
            bulk_obj.name = "Bulk_Phase"
            bulk_obj.scale.x = block_w / 2.0
            bulk_obj.scale.y = block_h / 2.0
            bulk_obj.scale.z = block_d / 2.0
            bulk_obj.location.z = block_d / 2.0
            bpy.ops.object.transform_apply(location=True, rotation=False, scale=True)

            # Subdivide if requested (kept minimal for RAM)
            bpy.ops.object.mode_set(mode="EDIT")
            bpy.ops.mesh.subdivide(number_cuts=100)
            bpy.ops.object.mode_set(mode="OBJECT")

            # Ensure bottom face lies exactly at z=0 (translate if necessary)
            bpy.ops.object.mode_set(mode="EDIT")
            bm2 = bmesh.from_edit_mesh(bulk_obj.data)
            if bm2.verts:
                min_z = min(v.co.z for v in bm2.verts)
                if abs(min_z) > 1e-9:
                    bmesh.ops.translate(bm2, verts=bm2.verts, vec=(0, 0, -min_z))
            bmesh.update_edit_mesh(bulk_obj.data)
            bpy.ops.object.mode_set(mode="OBJECT")

            created_objects.append(("Bulk_Phase", bulk_obj))
            print(
                f"  Bulk_Phase created: width = {bulk_obj.dimensions.x:.6f},"
                f" height = {bulk_obj.dimensions.y:.6f}, depth = {bulk_obj.dimensions.z:.6f}"
            )
    else:
        print("\n=== SKIPPING BULK PHASE ===")

    # Align all created phases to bulk bottom (world Z) and then export them
    align_phases_to_bulk("Bulk_Phase")

    # Export created objects (one file per phase) — do this after alignment
    for phase_name, obj in created_objects:
        out_name = f"{phase_name}.{export_format.lower()}"
        out_path = os.path.join(output_dir, out_name)
        print(f"Exporting {phase_name} to absolute path: {out_path}")
        bpy.ops.object.select_all(action="DESELECT")
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj
        blender_4 = bpy.app.version >= (4, 0, 0)
        if export_format == "STL":
            if blender_4:
                bpy.ops.wm.stl_export(filepath=out_path, export_selected_objects=True)
            else:
                bpy.ops.export_mesh.stl(filepath=out_path, use_selection=True)
        elif export_format == "OBJ":
            if blender_4:
                bpy.ops.wm.obj_export(filepath=out_path, export_selected_objects=True)
            else:
                bpy.ops.export_scene.obj(filepath=out_path, use_selection=True)
        elif export_format == "FBX":
            bpy.ops.export_scene.fbx(filepath=out_path, use_selection=True)
        else:
            print(f"Invalid format for {phase_name}: {export_format}. Skipping export.")
            out_path = None

        if out_path:
            print(f"SUCCESS: {phase_name} exported to {out_path}")

        bpy.ops.object.select_all(action="DESELECT")
        obj.select_set(True)
        bpy.ops.object.delete(use_global=False)

    print("\n=== COMPLETED ===")

    # Clean up temporary inverted image
    if inverted_image_path and os.path.exists(inverted_image_path):
        try:
            os.remove(inverted_image_path)
            print(f"Cleaned up temporary file: {inverted_image_path}")
        except Exception:
            pass  # Ignore cleanup errors

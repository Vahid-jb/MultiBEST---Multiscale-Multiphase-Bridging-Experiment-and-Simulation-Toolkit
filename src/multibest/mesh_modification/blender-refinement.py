# SPDX-FileCopyrightText: 2026 bright-ideas-clan
#
# SPDX-License-Identifier: GPL-3.0-or-later

# blender_refine_single.py
import argparse
import os
import sys

import bpy

# Force UTF-8 encoding for standard output and error
if sys.platform == "win32":
    for stream in (sys.stdout, sys.stderr):
        if stream is not None and hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)


def parse_args():
    argv = sys.argv
    if "--" in argv:
        argv = argv[argv.index("--") + 1 :]
    else:
        argv = []
    p = argparse.ArgumentParser(
        description="Import (or use existing) mesh, compute a single target voxel size and run one Remesh (voxel)."
    )
    p.add_argument(
        "--refinement",
        type=int,
        default=0,
        help="Number of reductions to apply when computing final voxel: final = start_voxel - step * refinement",
    )
    p.add_argument(
        "--object",
        type=str,
        default=None,
        help=(
            "Object name in the scene or path to a mesh file to import (stl/obj/fbx/ply/gltf/glb). "
            "If omitted uses active object."
        ),
    )
    p.add_argument("--apply", action="store_true", help="Apply the Remesh modifier (modify the mesh) before exporting.")
    p.add_argument("--start_voxel", type=float, default=0.8, help="Starting voxel size (default 0.8).")
    p.add_argument("--step", type=float, default=0.2, help="Reduction per refinement (default 0.2).")
    p.add_argument("--min_voxel", type=float, default=0.001, help="Minimum voxel clamp (default 0.001).")
    p.add_argument(
        "--output",
        type=str,
        default=None,
        help="Export path (extension selects format: .stl .obj .fbx .ply .gltf .glb).",
    )
    return p.parse_args(argv)


def ensure_object_mode():
    if bpy.ops.object.mode_set.poll():
        try:
            bpy.ops.object.mode_set(mode="OBJECT")
        except Exception:
            # Blender can reject mode changes in some contexts; continue with the current mode.
            pass


def call_blender_operator(candidates, action):
    errors = []
    for operator_path, kwargs in candidates:
        try:
            operator = bpy.ops
            for part in operator_path.split("."):
                operator = getattr(operator, part)
            operator(**kwargs)
            return
        except AttributeError as e:
            errors.append(str(e))
        except Exception as e:
            errors.append(str(e))
    detail = "; ".join(error for error in errors if error) or "no compatible operator was available"
    raise RuntimeError(f"{action} failed: {detail}")


def import_mesh_file(path):
    ext = os.path.splitext(path)[1].lower()
    before = set(bpy.context.selected_objects)
    try:
        if ext == ".stl":
            call_blender_operator(
                (
                    ("wm.stl_import", {"filepath": path}),
                    ("import_mesh.stl", {"filepath": path}),
                ),
                "STL import",
            )
        elif ext == ".obj":
            call_blender_operator(
                (
                    ("wm.obj_import", {"filepath": path}),
                    ("import_scene.obj", {"filepath": path}),
                ),
                "OBJ import",
            )
        elif ext == ".fbx":
            bpy.ops.import_scene.fbx(filepath=path)
        elif ext == ".ply":
            call_blender_operator(
                (
                    ("wm.ply_import", {"filepath": path}),
                    ("import_mesh.ply", {"filepath": path}),
                ),
                "PLY import",
            )
        elif ext in (".gltf", ".glb"):
            bpy.ops.import_scene.gltf(filepath=path)
        else:
            raise RuntimeError(f"Unsupported import extension '{ext}'. Supported: stl, obj, fbx, ply, gltf, glb.")
    except Exception as e:
        raise RuntimeError(f"Import failed for '{path}': {e}")

    after = set(bpy.context.selected_objects)
    imported = list(after - before)
    if not imported:
        obj = bpy.context.view_layer.objects.active
        if obj and obj.type == "MESH":
            return obj
        raise RuntimeError(
            "Import succeeded but could not detect imported object. Please import manually or open a .blend."
        )
    for o in imported:
        if o.type == "MESH":
            return o
    return imported[0]


def get_target_object(arg):
    if not arg:
        obj = bpy.context.view_layer.objects.active
        if obj is None:
            raise RuntimeError("No active object: supply --object <name|path> or open a scene with an active object.")
        return obj

    if os.path.isfile(arg):
        print("Detected file path for --object; will import:", arg)
        return import_mesh_file(arg)

    obj = bpy.data.objects.get(arg)
    if obj is None:
        raise RuntimeError(f"Object named '{arg}' not found in the scene and it's not a valid file path.")
    return obj


def add_voxel_remesh(obj, voxel_size, name=None):
    ensure_object_mode()
    bpy.context.view_layer.objects.active = obj
    for o in bpy.context.view_layer.objects:
        o.select_set(False)
    obj.select_set(True)

    bpy.ops.object.modifier_add(type="REMESH")
    mod = obj.modifiers[-1]
    if name:
        mod.name = name
    try:
        mod.mode = "VOXEL"
    except Exception:
        # Older Blender builds may not expose voxel mode; keep the modifier defaults in that case.
        pass
    try:
        mod.voxel_size = float(voxel_size)
    except Exception as e:
        raise RuntimeError(f"Couldn't set voxel_size on remesh modifier: {e}")
    return mod


def export_object(obj, outpath):
    ensure_object_mode()
    bpy.context.view_layer.objects.active = obj
    for o in bpy.context.view_layer.objects:
        o.select_set(False)
    obj.select_set(True)

    ext = os.path.splitext(outpath)[1].lower()
    print("Exporting to:", outpath, " (format:", ext, ")")
    try:
        if ext == ".stl":
            call_blender_operator(
                (
                    ("wm.stl_export", {"filepath": outpath, "export_selected_objects": True, "apply_modifiers": True}),
                    ("export_mesh.stl", {"filepath": outpath, "use_selection": True}),
                ),
                "STL export",
            )
        elif ext == ".obj":
            call_blender_operator(
                (
                    (
                        "wm.obj_export",
                        {
                            "filepath": outpath,
                            "export_selected_objects": True,
                            "apply_modifiers": True,
                            "export_normals": True,
                        },
                    ),
                    (
                        "export_scene.obj",
                        {"filepath": outpath, "use_selection": True, "use_mesh_modifiers": True, "use_normals": True},
                    ),
                ),
                "OBJ export",
            )
        elif ext == ".fbx":
            bpy.ops.export_scene.fbx(
                filepath=outpath, use_selection=True, apply_unit_scale=True, bake_space_transform=False
            )
        elif ext == ".ply":
            call_blender_operator(
                (
                    ("wm.ply_export", {"filepath": outpath, "export_selected_objects": True, "apply_modifiers": True}),
                    ("export_mesh.ply", {"filepath": outpath, "use_selection": True}),
                ),
                "PLY export",
            )
        elif ext in (".gltf", ".glb"):
            bpy.ops.export_scene.gltf(filepath=outpath, export_selected=True)
        else:
            raise RuntimeError(f"Unsupported export extension '{ext}'. Supported: .stl .obj .fbx .ply .gltf .glb")
    except Exception as e:
        raise RuntimeError(f"Export failed: {e}")


def main():
    args = parse_args()

    try:
        obj = get_target_object(args.object)
    except Exception as e:
        print("Error:", e)
        return 1

    if obj.type != "MESH":
        print(f"Error: target object '{obj.name}' is type '{obj.type}', expected a mesh.")
        return 1

    # compute single final voxel -- NO ITERATIONS
    final_voxel = args.start_voxel - args.step * float(args.refinement)
    if final_voxel < args.min_voxel:
        print(f"Computed final_voxel {final_voxel:.6f} <= min_voxel {args.min_voxel:.6f}; clamping to min_voxel.")
        final_voxel = args.min_voxel

    print(f"Operating on object: {obj.name!r}")
    print(
        f"Computed final voxel size = {final_voxel:.6f} "
        f"(start={args.start_voxel}, step={args.step}, refinement={args.refinement})"
    )

    # add single remesh modifier
    ensure_object_mode()
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    mod = add_voxel_remesh(obj, voxel_size=final_voxel, name="Remesh_voxel_target")

    if args.apply:
        ensure_object_mode()
        bpy.context.view_layer.objects.active = obj
        try:
            bpy.ops.object.modifier_apply(modifier=mod.name)
            print(f"Applied modifier '{mod.name}'")
        except Exception as e:
            print(f"Could not apply modifier '{mod.name}': {e}")

    print("Remesh operation complete. Current modifiers on object:")
    for m in obj.modifiers:
        print(" -", m.name, "(type:", m.type, ")")

    if args.output:
        try:
            export_object(obj, args.output)
            print("Export succeeded:", args.output)
        except Exception as e:
            print("Export failed:", e)
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

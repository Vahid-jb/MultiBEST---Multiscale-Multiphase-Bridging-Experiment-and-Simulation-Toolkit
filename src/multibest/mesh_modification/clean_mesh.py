# SPDX-FileCopyrightText: 2026 bright-ideas-clan
#
# SPDX-License-Identifier: GPL-3.0-or-later

import argparse
import os
import subprocess
import sys
import tempfile

import numpy as np
import trimesh
from scipy import spatial

# Force UTF-8 encoding for standard output and error
if sys.platform == "win32":
    for stream in (sys.stdout, sys.stderr):
        if stream is not None and hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)


def _cleanup_temp_files(paths):
    for path in paths:
        if not path:
            continue
        if os.path.exists(path):
            try:
                os.remove(path)
            except OSError:
                # Best-effort cleanup: the operation already finished, so temp-file removal failure is non-fatal.
                pass


def _create_temp_paths():
    with tempfile.NamedTemporaryFile(mode="w+", suffix=".py", delete=False) as script_file:
        temp_script_path = script_file.name
    with tempfile.NamedTemporaryFile(suffix=".obj", delete=False) as input_file:
        input_path = input_file.name
    with tempfile.NamedTemporaryFile(suffix=".obj", delete=False) as output_file:
        output_path = output_file.name
    return temp_script_path, input_path, output_path


def _write_text_file(path, content):
    with open(path, "w") as f:
        f.write(content)


def _blender_unavailable_message(blender_exec):
    return (
        f"Blender executable not found: {blender_exec!r}. "
        "Install Blender and make sure it is available on your PATH, "
        "or pass the full executable path with --blender-exec."
    )


class MeshQualityInspector:
    def __init__(
        self, fill_hole_threshold=120, blender_exec="blender", smoothing_iterations=0, smoothing_method="taubin"
    ):
        self.mesh = None
        self.original_stats = {}
        self.current_stats = {}
        self.fill_hole_threshold = fill_hole_threshold
        self.blender_exec = blender_exec
        self.smoothing_iterations = smoothing_iterations
        self.smoothing_method = smoothing_method

    def load_mesh(self, filename):
        """Load mesh file with proper error handling"""
        try:
            self.mesh = trimesh.load(filename)

            # Handle different return types
            if isinstance(self.mesh, trimesh.Scene):
                self.mesh = trimesh.util.concatenate(list(self.mesh.geometry.values()))
            elif isinstance(self.mesh, list):
                self.mesh = trimesh.util.concatenate(self.mesh)

            print(f"Loaded: {len(self.mesh.vertices)} vertices, {len(self.mesh.faces)} faces")
            return True

        except Exception as e:
            print(f"Error loading mesh: {e}")
            return False

    def analyze_mesh_quality(self):
        """Practical mesh quality analysis for multiple components"""
        if self.mesh is None:
            return False

        stats = {"vertices": len(self.mesh.vertices), "faces": len(self.mesh.faces)}
        stats.update(self._component_quality_stats())
        stats["holes"] = self._count_holes_practical()
        stats["duplicate_faces"] = len(self.mesh.faces) - len(np.unique(self.mesh.faces, axis=0))
        stats["duplicate_vertices"] = self._count_duplicate_vertices()
        stats["boundary_edges"] = self._count_boundary_edges()

        self.current_stats = stats
        if not self.original_stats:
            self.original_stats = stats.copy()

        return True

    def _component_quality_stats(self):
        try:
            components = self.mesh.split()
            return self._summarize_components(components)
        except Exception as e:
            print(f"Component analysis error: {e}")
            return self._single_component_stats()

    def _summarize_components(self, components):
        component_details = [self._component_detail(comp) for comp in components]
        watertight_components = sum(detail["watertight"] for detail in component_details)
        manifold_components = sum(detail["manifold"] for detail in component_details)
        return {
            "components": len(components),
            "watertight_components": watertight_components,
            "manifold_components": manifold_components,
            "component_details": component_details,
            "manifold": manifold_components == len(components),
            "watertight": False,
        }

    def _component_detail(self, comp):
        return {
            "vertices": len(comp.vertices),
            "faces": len(comp.faces),
            "watertight": comp.is_watertight,
            "manifold": self._check_practical_manifold(comp),
        }

    def _single_component_stats(self):
        watertight = self.mesh.is_watertight
        manifold = self._check_practical_manifold(self.mesh)
        return {
            "components": 1,
            "watertight": watertight,
            "manifold": manifold,
            "watertight_components": 1 if watertight else 0,
            "manifold_components": 1 if manifold else 0,
        }

    def _count_boundary_edges(self):
        try:
            return len(self.mesh.faces_boundary)
        except Exception:
            return 0

    def _check_practical_manifold(self, mesh=None):
        """Check manifoldness in a practical way"""
        if mesh is None:
            mesh = self.mesh

        try:
            # Check for non-manifold edges (edges with >2 faces)
            non_manifold_edges = mesh.get_non_manifold()
            return len(non_manifold_edges) == 0
        except Exception:
            return True

    def _count_holes_practical(self):
        """Count holes in a practical way"""
        if not self.mesh.is_watertight:
            try:
                return len(self.mesh.faces_boundary)
            except Exception:
                return 0
        return 0

    def _count_duplicate_vertices(self, tolerance=1e-6):
        """Count duplicate vertices"""
        if len(self.mesh.vertices) == 0:
            return 0

        try:
            tree = spatial.cKDTree(self.mesh.vertices)
            pairs = tree.query_pairs(tolerance)
            return len(pairs)
        except Exception:
            return 0

    def print_quality_report(self):
        """Print practical quality report with component details"""
        if not self.current_stats:
            return

        print("\n" + "=" * 50)
        print("QUALITY INSPECTION")
        print("=" * 50)

        print(f"Vertices: {self.current_stats['vertices']:,}")
        print(f"Faces: {self.current_stats['faces']:,}")

        if self._has_component_report():
            self._print_component_report()
            return

        self._print_single_component_issues()

    def _has_component_report(self):
        return "components" in self.current_stats and self.current_stats["components"] > 0

    def _print_component_report(self):
        print(f"Components: {self.current_stats['components']}")
        if "manifold_components" not in self.current_stats or "watertight_components" not in self.current_stats:
            return

        print(f"Manifold components: {self.current_stats['manifold_components']}/{self.current_stats['components']}")
        print(
            f"Watertight components: {self.current_stats['watertight_components']}/{self.current_stats['components']}"
        )
        self._print_component_details()

    def _print_component_details(self):
        if "component_details" not in self.current_stats:
            return

        print("\nComponent details:")
        for i, comp in enumerate(self.current_stats["component_details"]):
            status_str = self._component_status_text(comp)
            print(f"  Component {i + 1}: {comp['vertices']:,} vert, {comp['faces']:,} faces - {status_str}")

    def _component_status_text(self, comp):
        status = []
        if comp.get("manifold", False):
            status.append("manifold")
        if comp.get("watertight", False):
            status.append("watertight")
        return ", ".join(status) if status else "issues"

    def _print_single_component_issues(self):
        issues = self._single_component_issues()
        if issues:
            print(f"Issues: {', '.join(issues)}")
            return
        print("No issues found")

    def _single_component_issues(self):
        issue_checks = [
            (not self.current_stats.get("manifold", True), "non-manifold"),
            (not self.current_stats.get("watertight", True), "not watertight"),
            (self.current_stats.get("holes", 0) > 0, f"holes ({self.current_stats.get('holes', 0)})"),
            (self.current_stats.get("duplicate_vertices", 0) > 0, "duplicate vertices"),
            (self.current_stats.get("duplicate_faces", 0) > 0, "duplicate faces"),
        ]
        return [issue for has_issue, issue in issue_checks if has_issue]

    def smooth_taubin(self):
        """Apply volume-preserving Taubin smoothing using PyVista with better parameters"""
        try:
            import pyvista as pv
        except ImportError:
            print("  PyVista not available for Taubin smoothing")
            print("  Install with: pip install pyvista")
            return False

        try:
            if self._mesh_is_empty():
                return False

            original_volume = self._calculate_total_volume()
            pv_mesh = pv.PolyData(self.mesh.vertices, self._pyvista_faces(self.mesh.faces))
            smoothed_mesh = pv_mesh.smooth_taubin(
                n_iter=self.smoothing_iterations,
                pass_band=0.05,  # More conservative (lower = less smoothing)
                feature_angle=30.0,  # More conservative
            )
            if not self._apply_taubin_mesh(smoothed_mesh):
                return False

            volume_info = self._check_volume_preservation(original_volume, "Taubin")
            print(f"  Taubin smoothing: {self.smoothing_iterations} iterations {volume_info}")
            return True

        except Exception as e:
            print(f"  Taubin smoothing error: {e}")
            return False

    def _mesh_is_empty(self):
        return self.mesh is None or len(self.mesh.vertices) == 0

    def _pyvista_faces(self, faces):
        return np.hstack([np.full((faces.shape[0], 1), 3), faces]).flatten()

    def _apply_taubin_mesh(self, smoothed_mesh):
        smoothed_faces = self._extract_pyvista_faces(smoothed_mesh)
        if smoothed_faces is None:
            print("  Taubin smoothing: No faces in smoothed mesh")
            return False

        self.mesh = trimesh.Trimesh(vertices=smoothed_mesh.points, faces=smoothed_faces, process=False)
        return True

    def _extract_pyvista_faces(self, smoothed_mesh):
        if smoothed_mesh.faces is None or len(smoothed_mesh.faces) == 0:
            return None

        faces_data = smoothed_mesh.faces.reshape(-1, 4)
        if faces_data.shape[1] == 4:
            return faces_data[:, 1:4]
        return smoothed_mesh.faces.reshape(-1, 3)

    def smooth_pymeshlab(self):
        """Apply smoothing using PyMeshLab with better volume preservation"""
        try:
            import pymeshlab as pml
        except ImportError:
            print("  PyMeshLab not available")
            print("  Install with: pip install pymeshlab")
            return False

        input_path = None
        output_path = None
        try:
            if self._mesh_is_empty():
                return False

            original_volume = self._calculate_total_volume()
            with tempfile.NamedTemporaryFile(suffix=".obj", delete=False) as input_file:
                input_path = input_file.name
            with tempfile.NamedTemporaryFile(suffix=".obj", delete=False) as output_file:
                output_path = output_file.name

            self.mesh.export(input_path)
            ms = pml.MeshSet()
            ms.load_new_mesh(input_path)
            ms.apply_filter(
                "apply_coord_taubin_smoothing",
                stepsmoothnum=self.smoothing_iterations,
                lambda_=0.33,  # More conservative (lower = less smoothing)
                mu=-0.34,
            )  # More conservative

            ms.save_current_mesh(output_path)
            return self._load_pymeshlab_result(output_path, original_volume)

        except Exception as e:
            print(f"  PyMeshLab smoothing error: {e}")
            return False
        finally:
            _cleanup_temp_files([input_path, output_path])

    def _load_pymeshlab_result(self, output_path, original_volume):
        if not self._has_usable_output(output_path):
            return False

        smoothed_mesh = trimesh.load(output_path)
        mesh = self._coerce_loaded_mesh(smoothed_mesh)
        if mesh is None:
            return False

        self.mesh = mesh
        volume_info = self._check_volume_preservation(original_volume, "PyMeshLab")
        print(f"  PyMeshLab smoothing: {self.smoothing_iterations} iterations {volume_info}")
        return True

    def smooth_blender_laplacian(self):
        """Apply Blender's Laplacian smoothing with better error handling"""
        temp_script_path, input_path, output_path = _create_temp_paths()

        try:
            self.mesh.export(input_path)
            _write_text_file(temp_script_path, self._blender_laplacian_script(input_path, output_path))
            result = self._run_blender_script(temp_script_path, cwd=os.getcwd())

            if result.returncode != 0:
                self._print_blender_process_error(result, "Blender error")
                return False

            if not self._validate_blender_laplacian_output(output_path):
                return False

            return self._load_blender_result(
                output_path,
                invalid_message="  Blender: Invalid mesh type returned",
                missing_message="  Blender: Failed to load output mesh",
                success_message=f"  Blender Laplacian: {self.smoothing_iterations} iterations with volume preservation",
            )

        except subprocess.TimeoutExpired:
            print("  Blender smoothing: Timeout (5 minutes)")
            return False
        except FileNotFoundError:
            print(f"  Blender smoothing: {_blender_unavailable_message(self.blender_exec)}")
            return False
        except Exception as e:
            print(f"  Blender smoothing error: {e}")
            return False
        finally:
            _cleanup_temp_files([temp_script_path, input_path, output_path])

    def _blender_laplacian_script(self, input_path, output_path):
        return f"""
import bpy
import bmesh

# Clear everything
bpy.ops.wm.read_factory_settings(use_empty=True)

# Import the mesh as OBJ (more reliable)
bpy.ops.wm.obj_import(filepath=r'{input_path}')

# Get the imported object
if bpy.context.selected_objects:
    obj = bpy.context.selected_objects[0]
    bpy.context.view_layer.objects.active = obj

    # Switch to edit mode
    bpy.ops.object.mode_set(mode='EDIT')

    # Select all vertices
    bpy.ops.mesh.select_all(action='SELECT')

    # Apply Laplacian smoothing with volume preservation
    # Use fewer iterations with stronger factor for better results
    bpy.ops.mesh.vertices_smooth_laplacian(
        factor=0.5,
        iterations=1,  # Do one iteration at a time
        use_volume_preserve=True,
        use_x=True, use_y=True, use_z=True
    )

    # Back to object mode
    bpy.ops.object.mode_set(mode='OBJECT')

    # Apply transforms
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)

    # Export as OBJ
    bpy.ops.wm.obj_export(
        filepath=r'{output_path}',
        export_selected_objects=True,
        export_uv=False,
        export_normals=False,
        export_materials=False,
        apply_modifiers=True,
        export_triangulated_mesh=True
    )
else:
    print("ERROR: No object imported")
"""

    def _run_blender_script(self, temp_script_path, cwd=None):
        cmd = [self.blender_exec, "--background", "--python", temp_script_path]
        print(f"  Running: {' '.join(cmd)}")
        kwargs = {"capture_output": True, "text": True, "timeout": 300}
        if cwd is not None:
            kwargs["cwd"] = cwd
        return subprocess.run(cmd, **kwargs)

    def _print_blender_process_error(self, result, label):
        print(f"  {label} (code: {result.returncode})")
        if result.stderr:
            error_lines = result.stderr.split("\n")[-10:]
            print(f"  Blender stderr: {' '.join(error_lines)}")

    def _validate_blender_laplacian_output(self, output_path):
        if os.path.exists(output_path):
            return self._validate_output_size(output_path, "  Blender error")

        print(f"  Blender error: Output file not created at {output_path}")
        obj_files = [f for f in os.listdir(tempfile.gettempdir()) if f.endswith(".obj")]
        if obj_files:
            print(f"  Found OBJ files in temp dir: {obj_files[:3]}")
        return False

    def _validate_output_size(self, output_path, label):
        if os.path.getsize(output_path) >= 1000:
            return True
        print(f"{label}: Output file too small ({os.path.getsize(output_path)} bytes)")
        return False

    def _load_blender_result(self, output_path, invalid_message, missing_message, success_message):
        loaded = trimesh.load(output_path)
        if loaded is None:
            print(missing_message)
            return False

        mesh = self._coerce_loaded_mesh(loaded)
        if mesh is None:
            print(invalid_message)
            return False

        self.mesh = mesh
        if success_message is None:
            print(f"  Blender: {len(self.mesh.vertices):,} vertices, {len(self.mesh.faces):,} faces")
        else:
            print(success_message)
        return True

    def _coerce_loaded_mesh(self, loaded):
        if isinstance(loaded, trimesh.Trimesh):
            return loaded
        if isinstance(loaded, trimesh.Scene):
            return trimesh.util.concatenate(list(loaded.geometry.values()))
        return None

    def smooth_open3d(self):
        """Apply smoothing using Open3D with better volume preservation"""
        try:
            import open3d as o3d
        except ImportError:
            print("  Open3D not available for smoothing")
            print("  Install with: pip install open3d")
            return False

        try:
            if self.mesh is None or len(self.mesh.vertices) == 0:
                return False

            # Calculate total volume of all watertight components
            original_volume = self._calculate_total_volume()

            # Convert trimesh to Open3D
            vertices = np.asarray(self.mesh.vertices, dtype=np.float64)
            triangles = np.asarray(self.mesh.faces, dtype=np.int32)

            o3d_mesh = o3d.geometry.TriangleMesh()
            o3d_mesh.vertices = o3d.utility.Vector3dVector(vertices)
            o3d_mesh.triangles = o3d.utility.Vector3iVector(triangles)

            # Apply Laplacian smoothing with very conservative parameters
            smoothed_mesh = o3d_mesh.filter_smooth_laplacian(
                number_of_iterations=self.smoothing_iterations,
                lambda_filter=0.2,  # Very conservative for volume preservation
            )

            # Convert back to trimesh
            smoothed_vertices = np.asarray(smoothed_mesh.vertices)
            smoothed_faces = np.asarray(smoothed_mesh.triangles)

            # Update mesh
            self.mesh = trimesh.Trimesh(vertices=smoothed_vertices, faces=smoothed_faces, process=False)

            # Verify volume preservation
            volume_info = self._check_volume_preservation(original_volume, "Open3D")
            print(f"  Open3D Laplacian: {self.smoothing_iterations} iterations {volume_info}")
            return True

        except Exception as e:
            print(f"  Open3D smoothing error: {e}")
            return False

    def _calculate_total_volume(self):
        """Calculate total volume of all watertight components"""
        try:
            components = self.mesh.split()
            total_volume = 0
            for comp in components:
                if comp.is_watertight:
                    total_volume += comp.volume
            return total_volume
        except Exception:
            return 0

    def _check_volume_preservation(self, original_volume, method_name):
        """Check and report volume preservation with better accuracy"""
        if original_volume <= 0:
            return "(volume not measurable)"

        try:
            new_volume = self._calculate_total_volume()
        except Exception:
            return f"(volume check failed) with method {method_name}"

        if new_volume <= 0:
            return "(volume not measurable)"
        return self._volume_change_message(new_volume, original_volume)

    def _volume_change_message(self, new_volume, original_volume):
        volume_change = (new_volume - original_volume) / original_volume
        if abs(volume_change) <= 0.01:
            return f"(volume preserved: {volume_change:+.1%})"

        change_type = "increase" if volume_change > 0 else "decrease"
        return f"(volume {change_type}: {abs(volume_change):.1%})"

    def apply_smoothing(self):
        """Apply the selected smoothing method"""
        if self.smoothing_iterations == 0:
            return True  # No smoothing requested

        if self._mesh_is_empty():
            return False

        print(f"  Applying {self.smoothing_method} smoothing...")
        smoothing_method = self._smoothing_callable()
        if smoothing_method is None:
            print(f"  Unknown smoothing method: {self.smoothing_method}")
            return False

        success = smoothing_method()
        if not success:
            print(f"  {self.smoothing_method} smoothing failed, trying Taubin as fallback...")
            success = self.smooth_taubin()

        return success

    def _smoothing_callable(self):
        methods = {
            "taubin": self.smooth_taubin,
            "pymeshlab": self.smooth_pymeshlab,
            "blender": self.smooth_blender_laplacian,
            "open3d": self.smooth_open3d,
        }
        return methods.get(self.smoothing_method)

    def clean_with_pymeshfix(self):
        """Apply PyMeshFix repair with better error handling"""
        try:
            from pymeshfix._meshfix import PyTMesh
        except ImportError:
            print("  PyMeshFix not available")
            return False

        try:
            if self._mesh_is_empty():
                return False

            original_vertices = len(self.mesh.vertices)
            original_faces = len(self.mesh.faces)

            mfix = PyTMesh(False)
            mfix.load_array(np.asarray(self.mesh.vertices), np.asarray(self.mesh.faces))
            mfix.fill_small_boundaries(nbe=self.fill_hole_threshold, refine=True)
            fv, ff = mfix.return_arrays()
            return self._apply_meshfix_result(fv, ff, original_vertices, original_faces)

        except Exception as e:
            print(f"  Repair error: {e}")
            return False

    def _apply_meshfix_result(self, vertices, faces, original_vertices, original_faces):
        if len(vertices) == 0 or len(faces) == 0:
            print("  Repair: No valid mesh returned")
            return False

        self.mesh = trimesh.Trimesh(vertices=vertices, faces=faces, process=False)
        vertex_change = original_vertices - len(self.mesh.vertices)
        face_change = original_faces - len(self.mesh.faces)
        print(f"  Repair: {len(self.mesh.vertices):,} vertices, {len(self.mesh.faces):,} faces")
        self._print_meshfix_change(vertex_change, face_change)
        return True

    def _print_meshfix_change(self, vertex_change, face_change):
        if vertex_change != 0 or face_change != 0:
            print(f"         (changed by {vertex_change:,} vertices, {face_change:,} faces)")

    def clean_with_blender_3d_print(self):
        """Use Blender's 3D Print Toolbox for professional-grade repair"""
        temp_script_path, input_path, output_path = _create_temp_paths()

        try:
            self.mesh.export(input_path)
            _write_text_file(temp_script_path, self._blender_3d_print_script(input_path, output_path))
            result = self._run_blender_script(temp_script_path)

            if result.returncode != 0:
                print(f"  Blender error (code: {result.returncode})")
                return False

            if not self._has_usable_output(output_path):
                print("  Blender: Output file too small or missing")
                return False

            return self._load_blender_result(
                output_path,
                invalid_message="  Blender: Invalid mesh type returned",
                missing_message="  Blender: Failed to load output",
                success_message=None,
            )

        except subprocess.TimeoutExpired:
            print("  Blender: Timeout")
            return False
        except FileNotFoundError:
            print(f"  Blender: {_blender_unavailable_message(self.blender_exec)}")
            return False
        except Exception as e:
            print(f"  Blender error: {e}")
            return False
        finally:
            _cleanup_temp_files([temp_script_path, input_path, output_path])

    def _blender_3d_print_script(self, input_path, output_path):
        return f"""
import bpy
import bmesh

# Clear scene
bpy.ops.wm.read_factory_settings(use_empty=True)

# Import the mesh
bpy.ops.wm.obj_import(filepath=r'{input_path}')

# Get the imported object
obj = bpy.context.selected_objects[0]
bpy.context.view_layer.objects.active = obj

# Enter edit mode
bpy.ops.object.mode_set(mode='EDIT')

# Select all and remove doubles with tighter tolerance
bpy.ops.mesh.select_all(action='SELECT')
bpy.ops.mesh.remove_doubles(threshold=0.0001)

# Check and fix normals
bpy.ops.mesh.normals_make_consistent(inside=False)

# Select non-manifold geometry
bpy.ops.mesh.select_all(action='DESELECT')
bpy.ops.mesh.select_non_manifold()

# Try to fix non-manifold geometry
bpy.ops.mesh.fill_holes(sides=0)  # 0 means fill all holes

# Back to object mode
bpy.ops.object.mode_set(mode='OBJECT')

# Apply all transforms
bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)

# Export
bpy.ops.wm.obj_export(
    filepath=r'{output_path}',
    export_selected_objects=True,
    export_uv=False,
    export_normals=False,
    export_materials=False,
    apply_modifiers=True,
    export_triangulated_mesh=True
)
"""

    def _has_usable_output(self, output_path):
        return os.path.exists(output_path) and os.path.getsize(output_path) > 1000

    def apply_repairs(self):
        """Apply repair pipeline with optional smoothing"""
        if self.mesh is None or len(self.mesh.vertices) == 0:
            return False

        print("  Applying repairs...")

        # Apply smoothing if enabled (FIRST, as requested)
        if self.smoothing_iterations > 0:
            smoothing_success = self.apply_smoothing()
            if not smoothing_success:
                print("  Smoothing failed, continuing with repairs...")

        # Apply repair methods
        fix1_success = self.clean_with_pymeshfix()
        fix2_success = self.clean_with_blender_3d_print()

        return fix1_success or fix2_success

    def is_mesh_good_enough(self):
        """Check if mesh is good enough for practical use"""
        if not self.current_stats:
            return False

        # For practical purposes, we care about:
        # - Having geometry (vertices and faces)
        # - All components being manifold (if we have component data)
        # - Reasonable structure

        if self.current_stats["vertices"] == 0 or self.current_stats["faces"] == 0:
            return False

        # If we have component data, check if all are manifold
        if "manifold_components" in self.current_stats and "components" in self.current_stats:
            if self.current_stats["manifold_components"] != self.current_stats["components"]:
                return False

        return True

    def save_mesh(self, filename):
        """Save the current mesh state with format detection"""
        try:
            os.makedirs(os.path.dirname(os.path.abspath(filename)), exist_ok=True)

            # Detect format from extension
            ext = os.path.splitext(filename)[1].lower()
            supported_formats = [".obj", ".stl", ".ply"]

            if ext not in supported_formats:
                print(f"Warning: Format {ext} not in supported formats {supported_formats}, using OBJ")
                filename = os.path.splitext(filename)[0] + ".obj"

            self.mesh.export(filename)
            print(f"Saved: {filename}")
            return True
        except Exception as e:
            print(f"Error saving: {e}")
            return False

    def automated_repair_session(self, input_file, max_iterations, output_file=None):
        """Run automated repair session with optional smoothing"""
        if output_file is None:
            output_file = self._default_output_file(input_file)

        self._print_session_header(input_file, output_file, max_iterations)
        if not self.load_mesh(input_file):
            return False

        iteration = self._run_repair_iterations(max_iterations)
        return self._finalize_repair_session(iteration, output_file)

    def _default_output_file(self, input_file):
        base, ext = os.path.splitext(input_file)
        return f"{base}_repaired{ext}"

    def _print_session_header(self, input_file, output_file, max_iterations):
        print(f"Input: {input_file}")
        print(f"Output: {output_file}")
        print(f"Max iterations: {max_iterations}")
        print(f"Hole threshold: {self.fill_hole_threshold}")
        if self.smoothing_iterations > 0:
            print(f"Smoothing: {self.smoothing_iterations} {self.smoothing_method} iterations")

    def _run_repair_iterations(self, max_iterations):
        iteration = 0
        while iteration < max_iterations:
            iteration += 1
            if not self._run_single_repair_iteration(iteration, max_iterations):
                break
        return iteration

    def _run_single_repair_iteration(self, iteration, max_iterations):
        print(f"\n--- Iteration {iteration}/{max_iterations} ---")
        if not self.analyze_mesh_quality():
            return False

        self.print_quality_report()
        if iteration > 1 and self.is_mesh_good_enough():
            print("\n✓ Mesh quality acceptable")
            return False

        if self.apply_repairs():
            return True

        print("  Repair failed")
        return False

    def _finalize_repair_session(self, iteration, output_file):
        print("\n" + "=" * 50)
        print("FINAL RESULT")
        print("=" * 50)

        if not self._has_mesh_data():
            print("Process failed: No mesh data")
            return False

        self.analyze_mesh_quality()
        self.print_quality_report()
        print(f"\nIterations completed: {iteration}")
        print(f"Final mesh: {len(self.mesh.vertices):,} vertices, {len(self.mesh.faces):,} faces")
        self.save_mesh(output_file)
        print("\nMesh inspection and repair are complete.")
        return True

    def _has_mesh_data(self):
        return self.mesh is not None and len(self.mesh.vertices) > 0


def _build_clean_mesh_parser():
    parser = argparse.ArgumentParser(description="Advanced Mesh Repair Tool with Multiple Smoothing Methods")
    parser.add_argument("input", help="Input mesh file")
    parser.add_argument("--output", required=True, help="Output mesh file (.obj, .stl, .ply)")
    parser.add_argument("--iterations", type=int, default=3, help="Maximum repair iterations (default: 3)")
    parser.add_argument(
        "--fill_hole_threshold", type=int, default=120, help="Max hole size to fill in boundary edges (default: 120)"
    )
    parser.add_argument("--smoothing", type=int, default=0, help="Smoothing iterations (0 = disabled, default: 0)")
    parser.add_argument(
        "--smoothing-method",
        choices=["taubin", "pymeshlab", "blender", "open3d"],
        default="taubin",
        help="Smoothing method (default: taubin)",
    )
    parser.add_argument("--blender-exec", default="blender", help="Blender executable path (default: blender)")
    return parser


def _validate_clean_mesh_args(args):
    if not os.path.exists(args.input):
        print(f"Error: File not found - {args.input}")
        sys.exit(1)

    output_ext = os.path.splitext(args.output)[1].lower()
    if output_ext not in [".obj", ".stl", ".ply"]:
        print(f"Error: Output format must be .obj, .stl, or .ply, got {output_ext}")
        sys.exit(1)


def _print_clean_mesh_header(args):
    print("Advanced Mesh Repair Tool")
    print("=" * 40)
    if args.smoothing > 0:
        print(f"Smoothing: {args.smoothing} {args.smoothing_method} iterations (volume-preserving)")
        return
    print("Smoothing: Disabled")


def main():
    parser = _build_clean_mesh_parser()
    if len(sys.argv) == 1:
        parser.print_help()
        sys.exit(1)

    args = parser.parse_args()
    _validate_clean_mesh_args(args)
    inspector = MeshQualityInspector(
        fill_hole_threshold=args.fill_hole_threshold,
        blender_exec=args.blender_exec,
        smoothing_iterations=args.smoothing,
        smoothing_method=args.smoothing_method,
    )

    _print_clean_mesh_header(args)
    success = inspector.automated_repair_session(
        input_file=args.input, max_iterations=args.iterations, output_file=args.output
    )

    if not success:
        sys.exit(1)


if __name__ == "__main__":
    main()

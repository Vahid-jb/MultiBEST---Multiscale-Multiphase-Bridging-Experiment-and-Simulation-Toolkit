#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 bright-ideas-clan
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
clean_mesh_with_refine.py

Wrapper launcher that:
 - If --refinement is provided: runs blender (background) with your blender-refinement.py
   to produce a refined mesh file, then runs clean_mesh.py on that refined mesh.
 - If --refinement is NOT provided: directly runs clean_mesh.py on the original input.
 - If --input-file is provided: reads every parameter from that 'key = value' file
   (the file the GUI writes into the output directory) instead of the command line.

IMPORTANT: This script does NOT modify clean_mesh.py or blender-refinement.py.
It simply invokes them as subprocesses. Keep this file next to your originals.
"""

import argparse
import os
import subprocess
import sys
import tempfile
import time

# Force UTF-8 encoding for standard output and error
if sys.platform == "win32":
    for stream in (sys.stdout, sys.stderr):
        if stream is not None and hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

# Path to your original scripts (adjust if located elsewhere)
CLEAN_MESH_SCRIPT = os.path.join(os.path.dirname(__file__), "clean_mesh.py")
BLENDER_REFINEMENT_SCRIPT = os.path.join(os.path.dirname(__file__), "blender-refinement.py")


def _rounded_int(value):
    return str(int(round(float(value))))


# Input-file keys mapped to the wrapper's own options, in command-line order.
WRAPPER_INPUT_KEYS = (
    ("refinement", "--refinement"),
    ("start_voxel", "--start-voxel"),
    ("step", "--step"),
    ("blender_exec", "--blender-exec"),
)

# Input-file keys forwarded to clean_mesh.py, with the normalisation it expects.
CLEAN_MESH_INPUT_KEYS = (
    ("output_file", "--output", str),
    ("iterations", "--iterations", str),
    ("fill_hole_threshold", "--fill_hole_threshold", _rounded_int),
    ("smoothing", "--smoothing", str),
    ("smoothing_method", "--smoothing-method", str.lower),
)


def _bundled_script(filename):
    if not getattr(sys, "frozen", False):
        return os.path.join(os.path.dirname(__file__), filename)

    candidates = [
        os.path.join(getattr(sys, "_MEIPASS", os.path.dirname(sys.executable)), filename),
        os.path.join(os.path.dirname(sys.executable), filename),
    ]
    for candidate in candidates:
        if os.path.isfile(candidate):
            return candidate
    return candidates[0]


def _sibling_executable(script_path):
    if not getattr(sys, "frozen", False):
        return None

    stem = os.path.splitext(os.path.basename(script_path))[0]
    suffix = ".exe" if sys.platform == "win32" else ""
    return os.path.join(os.path.dirname(sys.executable), stem + suffix)


def _remove_file_best_effort(path):
    try:
        os.remove(path)
    except OSError:
        # Best-effort cleanup: preserve the original result even if temp removal fails.
        pass


def _refined_temp_path(input_path):
    _, ext = os.path.splitext(input_path)
    if not ext:
        ext = ".stl"
    tmp_dir = tempfile.gettempdir()
    return os.path.join(tmp_dir, f"refined_{int(time.time() * 1000)}{ext}")


def _build_blender_refinement_command(blender_exec, refinement, input_path, start_voxel, step, temp_path, apply_flag):
    cmd = [
        blender_exec,
        "--background",
        "--python",
        _bundled_script("blender-refinement.py"),
        "--",
        "--refinement",
        str(refinement),
        "--object",
        os.path.abspath(input_path),
        "--start_voxel",
        str(start_voxel),
        "--step",
        str(step),
        "--output",
        os.path.abspath(temp_path),
    ]
    if apply_flag:
        cmd.append("--apply")
    return cmd


def _print_process_output(proc):
    if proc.stdout:
        print(proc.stdout)
    if proc.stderr:
        print(proc.stderr, file=sys.stderr)


def _blender_unavailable_message(blender_exec):
    return (
        f"Blender executable not found: {blender_exec!r}. "
        "Install Blender and make sure it is available on your PATH, "
        "or pass the full executable path with --blender-exec."
    )


def _wait_for_refined_file(temp_path):
    for _attempt in range(10):
        if os.path.exists(temp_path) and os.path.getsize(temp_path) > 200:
            return
        time.sleep(0.1)

    raise RuntimeError(f"Refined file '{temp_path}' missing or too small after Mesh finished.")


def _fsync_best_effort(temp_path):
    try:
        with open(temp_path, "rb") as f:
            os.fsync(f.fileno())
    except OSError:
        # Best-effort flush check only; the file-size validation is the required guard.
        pass


def run_blender_refinement(blender_exec, refinement, input_path, start_voxel, step, apply_flag):
    """
    Run blender refinement and return path to refined mesh.
    This version avoids pre-creating an empty temp file and waits for file system flush.
    """
    temp_path = _refined_temp_path(input_path)
    cmd = _build_blender_refinement_command(
        blender_exec, refinement, input_path, start_voxel, step, temp_path, apply_flag
    )
    print("Running Mesh refinement:")
    print(" ".join(cmd))

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
    except FileNotFoundError as exc:
        _remove_file_best_effort(temp_path)
        raise RuntimeError(_blender_unavailable_message(blender_exec)) from exc

    _print_process_output(proc)
    if proc.returncode != 0:
        _remove_file_best_effort(temp_path)
        raise RuntimeError(f"Mesh refinement failed (exit {proc.returncode}). See output above.")

    _wait_for_refined_file(temp_path)
    _fsync_best_effort(temp_path)
    return temp_path


def run_clean_mesh_on(input_path, extra_args):
    """
    Invoke clean_mesh.py with the given input path and extra_args (list).
    Returns subprocess CompletedProcess.
    """
    clean_mesh_exe = _sibling_executable(CLEAN_MESH_SCRIPT)
    if clean_mesh_exe:
        cmd = [clean_mesh_exe, input_path] + extra_args
    else:
        cmd = [sys.executable, CLEAN_MESH_SCRIPT, input_path] + extra_args
    print("Running clean_mesh.py:")
    print(" ".join(cmd))
    proc = subprocess.run(cmd, capture_output=False, text=True)
    return proc


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


def _is_enabled(value):
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def argv_from_input_file(input_file):
    """Translate an input file written by the GUI into wrapper CLI arguments."""
    params = parse_input_file(input_file)
    argv = []

    for key, flag in WRAPPER_INPUT_KEYS:
        value = params.get(key, "").strip()
        if value:
            argv.extend([flag, value])
    if _is_enabled(params.get("apply_refine", "")):
        argv.append("--apply-refine")

    mesh_file = params.get("mesh_file", "").strip()
    if mesh_file:
        argv.append(mesh_file)
    for key, flag, normalize in CLEAN_MESH_INPUT_KEYS:
        value = params.get(key, "").strip()
        if value:
            argv.extend([flag, normalize(value)])
    return argv


def _build_parser():
    parser = argparse.ArgumentParser(
        description="Wrapper: optional blender refinement then run clean_mesh.py (no edits to originals)."
    )
    parser.add_argument(
        "--input-file",
        help="Parameter file with 'key = value' lines; overrides every other argument when given.",
    )
    # Arguments that control the wrapper / blender refinement
    parser.add_argument(
        "--refinement", type=int, default=0, help="If >0 run blender refinement first with this integer."
    )
    parser.add_argument(
        "--blender-exec",
        default="blender",
        help='Path to blender executable (passed to blender-refinement.py). Defaults to "blender".',
    )
    parser.add_argument(
        "--start-voxel",
        type=float,
        default=0.8,
        help="Start voxel for blender refinement (passed to blender-refinement.py).",
    )
    parser.add_argument(
        "--step", type=float, default=0.2, help="Step reduction per refinement (passed to blender-refinement.py)."
    )
    parser.add_argument(
        "--apply-refine",
        action="store_true",
        help="Pass --apply to blender-refinement.py so refined mesh is applied before export.",
    )
    # All remaining args will be forwarded to clean_mesh.py (so its CLI stays intact)
    parser.add_argument(
        "clean_args",
        nargs=argparse.REMAINDER,
        help="Arguments to forward to clean_mesh.py (use same syntax as before).",
    )
    return parser


def _validate_clean_args(clean_args):
    if not clean_args:
        print(
            "Error: no arguments passed for clean_mesh.py. Provide the same arguments you would pass to clean_mesh.py."
        )
        print("Example: python clean_mesh_with_refine.py input.stl --output final.obj --smoothing 10 ...")
        sys.exit(2)

    input_path = clean_args[0]
    if not os.path.exists(input_path):
        print(f"Error: input file not found: {input_path}")
        sys.exit(1)
    return input_path


def _refined_clean_args(args, input_path):
    clean_args = _clean_args_with_blender_exec(args.clean_args, args.blender_exec)
    if not args.refinement or args.refinement <= 0:
        return clean_args, None

    refined_temp = run_blender_refinement(
        blender_exec=args.blender_exec,
        refinement=args.refinement,
        input_path=input_path,
        start_voxel=args.start_voxel,
        step=args.step,
        apply_flag=args.apply_refine,
    )
    return [refined_temp] + clean_args[1:], refined_temp


def _clean_args_with_blender_exec(clean_args, blender_exec):
    if "--blender-exec" in clean_args:
        return clean_args
    return [*clean_args, "--blender-exec", blender_exec]


def _run_clean_mesh_or_exit(forwarded_args):
    proc = run_clean_mesh_on(forwarded_args[0], forwarded_args[1:])
    if proc.returncode != 0:
        print(f"clean_mesh.py returned non-zero exit code: {proc.returncode}")
        sys.exit(proc.returncode)


def main():
    parser = _build_parser()
    args = parser.parse_args()
    if args.input_file:
        args = parser.parse_args(argv_from_input_file(args.input_file))
    input_path = _validate_clean_args(args.clean_args)
    try:
        forwarded_args, refined_temp = _refined_clean_args(args, input_path)
    except RuntimeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

    try:
        _run_clean_mesh_or_exit(forwarded_args)
    finally:
        if refined_temp:
            _remove_file_best_effort(refined_temp)


if __name__ == "__main__":
    main()

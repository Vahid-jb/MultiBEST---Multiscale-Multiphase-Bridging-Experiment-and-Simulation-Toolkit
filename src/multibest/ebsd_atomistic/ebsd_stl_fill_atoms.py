#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 bright-ideas-clan
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
ebsd_atomistic.py

Enhanced CLI script for EBSD grain processing with unlimited phases and optional verification figures.
Can be run with: python ebsd_atomistic.py input.txt
"""

import argparse
import os
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path

_TRUTHY_VALUES = ("on", "true", "yes", "1")
SUBPROCESS_TEXT_KWARGS = {"encoding": "utf-8", "errors": "replace"}
MAX_CHILD_OUTPUT_LINES = 80


# Force UTF-8 encoding for standard output and error
if sys.platform == "win32":
    for stream in (sys.stdout, sys.stderr):
        if stream is not None and hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)


def _extract_phase_entry(line):
    """Return (phase_num, cif_path) from a 'phase' line, or None if invalid."""
    tokens = line.split()
    if len(tokens) < 2:
        return None
    phase_num = tokens[1]
    for i, tok in enumerate(tokens):
        if tok == "--cif" and i + 1 < len(tokens):
            return phase_num, tokens[i + 1]
    return None


def _apply_config_line(config, line, key, value):
    """Apply a single parsed config line to the running config dict."""
    string_keys = ("grain_data", "stl_dir", "output_dir", "stl_prefix", "assembly_output", "setup")
    bool_keys = ("verification_fig", "assembly")

    if key in string_keys:
        config[key] = value
    elif key in bool_keys:
        config[key] = value.lower() in _TRUTHY_VALUES
    elif key == "phase":
        entry = _extract_phase_entry(line)
        if entry:
            phase_num, cif_path = entry
            config["phases"][phase_num] = cif_path


def parse_input_file(input_file):
    """Parse input file with flexible format supporting unlimited phases.
    Uses exact key matching (first token) so 'assembly' and 'assembly_output' can't clash.
    """
    config = {
        "grain_data": None,
        "stl_dir": None,
        "output_dir": None,
        "stl_prefix": "TriangleFeature_",
        "verification_fig": False,
        "phases": {},
        "setup": "",
        "assembly": False,
        "assembly_output": None,
    }

    with open(input_file) as f:
        lines = [line.strip() for line in f.readlines() if line.strip() and not line.strip().startswith("#")]

    for line in lines:
        parts = line.split(None, 1)
        key = parts[0].lower()
        value = parts[1].strip() if len(parts) > 1 else ""
        _apply_config_line(config, line, key, value)

    return config


def parse_arguments():
    """Parse command line arguments for direct usage"""
    parser = argparse.ArgumentParser(
        description="Process EBSD grain data and fill STL files with atoms",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Usage examples:
  python ebsd_atomistic.py input.txt
  OR
  python ebsd_atomistic.py --grain_data ./grain_data.txt --stl_dir ./stl_files \\
    --phase 1 --cif ./Zn50Cu50.cif --phase 2 --cif ./AnotherPhase.cif \\
    --setup "--pitch 0.3 --padding-angstrom 5.0 --mask-dilate 1 --force-tri --dilate 1 --close 3" \\
    --output_dir ./output_grains --verification_fig off
        """,
    )

    # Input file mode
    parser.add_argument("input_file", nargs="?", help="Input text file with configuration")

    # Direct argument mode
    parser.add_argument("--grain_data", help="Path to grain data file (TSV format)")
    parser.add_argument("--stl_dir", help="Directory containing STL files")
    parser.add_argument("--output_dir", help="Output directory for XYZ files")
    parser.add_argument("--stl_prefix", default="TriangleFeature_", help="Prefix for STL filenames")
    parser.add_argument("--verification_fig", action="store_true", help="Generate verification figures (default: off)")
    parser.add_argument("--assembly", action="store_true", help="Run automatic assembly after processing")
    parser.add_argument("--assembly_output", help="Output filename for assembled XYZ file")

    # Dynamic phase arguments - can have multiple phase+cif pairs
    parser.add_argument(
        "--phase",
        action="append",
        nargs=2,
        metavar=("N", "CIF"),
        help="Phase number and CIF file (can be used multiple times)",
    )

    parser.add_argument("--setup", help="Setup parameters for filling")
    parser.add_argument("--gpt_script", default="gpt-mod-1.py", help="Path to gpt-mod-1.py script")

    return parser.parse_args()


def read_grain_data(file_path):
    """Read grain data from TSV file and return list of valid grains"""
    grains = []

    with open(file_path) as f:
        lines = f.readlines()

        # Skip header
        header = lines[0].strip().split("\t")
        try:
            grain_id_idx = header.index("grain_ID")
            phase_idx = header.index("Phases_Export")
            euler1_idx = header.index("AvgEulerAngles_Export_0")
            euler2_idx = header.index("AvgEulerAngles_Export_1")
            euler3_idx = header.index("AvgEulerAngles_Export_2")
        except ValueError as e:
            print(f"Error: Required column not found in grain data file: {e}")
            sys.exit(1)

        for i, line in enumerate(lines[1:], 1):  # Skip header
            parts = line.strip().split("\t")
            if len(parts) < 6:
                continue

            grain_id = parts[grain_id_idx].strip()
            phase = parts[phase_idx].strip()
            euler1 = parts[euler1_idx].strip()
            euler2 = parts[euler2_idx].strip()
            euler3 = parts[euler3_idx].strip()

            # Skip grains with zero phase or zero Euler angles (low quality)
            if phase == "0" or (euler1 == "0.000000" and euler2 == "0.000000" and euler3 == "0.000000"):
                continue

            grains.append({"id": grain_id, "phase": phase, "euler_angles": (euler1, euler2, euler3)})

    return grains


def find_stl_file(stl_dir, grain_id, prefix):
    """Find STL file for given grain ID - EXACT MATCH ONLY"""
    stl_dir_path = Path(stl_dir)

    # Construct exact filename we're looking for
    expected_filename = f"{prefix}{grain_id}.stl"
    expected_path = stl_dir_path / expected_filename

    if expected_path.exists():
        return str(expected_path)

    return None


def _quote_token(value):
    return shlex.quote(str(value).replace("\\", "/"))


def create_simple_gpt_input_file(stl_path, phase_cif, euler_angles, setup_params, output_xyz, verification_fig=False):
    """Create a simplified input file for gpt-mod-1.py that doesn't require base phase"""

    # Build input file content - SIMPLIFIED for guest-only processing
    lines = []

    # Global options - NO MERGE to avoid base phase requirement
    lines.append("total_num_phases 1")
    lines.append("--merge off")  # Critical: disable merging to avoid base phase requirement

    # Verification figure setting
    lines.append("--validation " + ("on" if verification_fig else "off"))

    # Phase line with Euler angles - explicitly set output file
    euler_str = " ".join(euler_angles)
    phase_line = (
        f"phase_1 guest {_quote_token(stl_path)} "
        f"--cif {_quote_token(phase_cif)} "
        f"--euler {euler_str} "
        f"--out {_quote_token(output_xyz)}"
    )

    # Add the setup parameters directly (no parsing needed)
    if setup_params and setup_params.strip():
        phase_line += f" {setup_params.strip()}"

    lines.append(phase_line)

    return "\n".join(lines)


def _classify_xyz_result(output_xyz):
    """Return 'ok', 'empty', or 'invalid' for the produced XYZ file."""
    if not os.path.exists(output_xyz):
        return "missing", 0
    with open(output_xyz) as xyz_file:
        first_line = xyz_file.readline().strip()
    try:
        atom_count = int(first_line)
    except ValueError:
        return "invalid", 0
    if atom_count > 0:
        return "ok", atom_count
    return "empty", 0


def _atom_filler_command(gpt_script, *args):
    if getattr(sys, "frozen", False):
        return [gpt_script, *args]
    return [sys.executable, gpt_script, *args]


def _atom_filler_env():
    env = os.environ.copy()
    env.setdefault("PYTHONIOENCODING", "utf-8:replace")
    return env


def _run_atom_filler(temp_input_file, gpt_script):
    return subprocess.run(
        _atom_filler_command(gpt_script, temp_input_file),
        capture_output=True,
        text=True,
        **SUBPROCESS_TEXT_KWARGS,
        cwd=os.getcwd(),
        env=_atom_filler_env(),
    )


def _tail_text(text, max_lines=MAX_CHILD_OUTPUT_LINES):
    lines = [line for line in (text or "").splitlines() if line.strip()]
    if len(lines) <= max_lines:
        return lines
    omitted = len(lines) - max_lines
    return [f"... omitted {omitted} earlier lines ...", *lines[-max_lines:]]


def _print_child_output(result):
    for label, text in (("stdout", result.stdout), ("stderr", result.stderr)):
        lines = _tail_text(text)
        if not lines:
            continue
        print(f"  --- gpt-mod-1.py {label} ---")
        for line in lines:
            print(f"  {line}")


def _check_atom_filler_runtime(gpt_script):
    try:
        result = subprocess.run(
            _atom_filler_command(gpt_script, "--help"),
            capture_output=True,
            text=True,
            **SUBPROCESS_TEXT_KWARGS,
            cwd=os.getcwd(),
            env=_atom_filler_env(),
        )
    except Exception as e:
        print(f"Error: gpt-mod-1.py could not start: {e}")
        print("Atomistic grain processing will stop.")
        return False
    if result.returncode == 0:
        return True
    print("Error: gpt-mod-1.py could not start. Atomistic grain processing will stop.")
    _print_child_output(result)
    return False


def _process_single_grain(grain, config, gpt_script):
    """Process a single grain. Returns 'success', 'failed', 'no_stl', or 'no_phase'."""
    grain_id = grain["id"]
    phase = grain["phase"]
    print(f"\nProcessing grain {grain_id} (phase {phase})...")

    if phase not in config["phases"]:
        print(f"  ⚠️  No CIF file defined for phase {phase}, skipping grain {grain_id}")
        return "no_phase"

    stl_path = find_stl_file(config["stl_dir"], grain_id, config["stl_prefix"])
    if not stl_path:
        print(f"  ⚠️  STL file not found for grain {grain_id} (looking for {config['stl_prefix']}{grain_id}.stl)")
        return "no_stl"

    print(f"  Found STL: {stl_path}")
    stl_name = Path(stl_path).stem
    output_xyz = os.path.join(config["output_dir"], f"{stl_name}.xyz")

    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        input_content = create_simple_gpt_input_file(
            stl_path,
            config["phases"][phase],
            grain["euler_angles"],
            config["setup"],
            output_xyz,
            config["verification_fig"],
        )
        f.write(input_content)
        temp_input_file = f.name

    try:
        print("  Running atom-filler...")
        result = _run_atom_filler(temp_input_file, gpt_script)
        if result.returncode != 0:
            _print_child_output(result)
            print(f"  ❌ gpt-mod-1.py failed with return code {result.returncode}")
            return "failed"

        status, atom_count = _classify_xyz_result(output_xyz)
        if status == "ok":
            print(f"  ✅ Successfully created: {output_xyz} with {atom_count} atoms")
            return "success"
        if status == "empty":
            print(f"  ⚠️  Created but empty: {output_xyz}")
        elif status == "invalid":
            print(f"  ❌ Invalid XYZ file: {output_xyz}")
        else:
            print(f"  ❌ Output file not created: {output_xyz}")
        return "failed"
    except Exception as e:
        print(f"  ❌ Error running atom-filler: {e}")
        return "failed"
    finally:
        if os.path.exists(temp_input_file):
            os.unlink(temp_input_file)


def _print_processing_summary(stats, config):
    successful = stats["success"]
    failed = stats["failed"]
    print(f"\n{'=' * 50}")
    print("Processing Summary:")
    print(f"  Successful: {successful}")
    print(f"  Failed: {failed}")
    print(f"  No STL file found: {stats['no_stl']}")
    print(f"  No CIF for phase: {stats['no_phase']}")
    print(f"  Total grains processed: {successful + failed}")
    print(f"Output directory: {config['output_dir']}")
    print(f"Verification figures: {'ON' if config['verification_fig'] else 'OFF'}")
    if successful > 0:
        print(f"\n✅ Successfully processed {successful} grains!")
        print("   Each grain is saved as a separate XYZ file.")
    else:
        print("\n❌ No grains were successfully processed.")
    print(f"{'=' * 50}")


def process_grains_directly(config, gpt_script="gpt-mod-1.py"):
    """Process grains directly without base phase dependency"""
    if not _check_atom_filler_runtime(gpt_script):
        sys.exit(1)
    os.makedirs(config["output_dir"], exist_ok=True)
    print("Reading grain data...")
    grains = read_grain_data(config["grain_data"])
    print(f"Found {len(grains)} valid grains to process")

    stats = {"success": 0, "failed": 0, "no_stl": 0, "no_phase": 0}
    for grain in grains:
        status = _process_single_grain(grain, config, gpt_script)
        stats[status] += 1

    _print_processing_summary(stats, config)

    if config.get("assembly", False):
        run_assembly(config["output_dir"], config["stl_prefix"], config.get("assembly_output"))


def run_assembly(output_dir, stl_prefix, assembly_output=None):
    """
    Run automatic assembly of XYZ files after processing

    Args:
        output_dir (str): Directory containing XYZ files
        stl_prefix (str): Prefix of XYZ files to assemble
        assembly_output (str): Output filename for assembled file
    """
    if not assembly_output:
        # Generate default output name
        assembly_output = os.path.join(output_dir, "assembled_final.xyz")

    # Construct the input prefix for assembly
    input_prefix = os.path.join(output_dir, stl_prefix)

    print(f"\n{'=' * 50}")
    print("Starting automatic assembly...")
    print(f"Input prefix: {input_prefix}")
    print(f"Output file: {assembly_output}")

    try:
        # Find all matching XYZ files (replicating assembly.py logic)
        import glob

        directory = os.path.dirname(input_prefix) if os.path.dirname(input_prefix) else "."
        base_prefix = os.path.basename(input_prefix)
        search_pattern = os.path.join(directory, f"{base_prefix}*.xyz")
        xyz_files = glob.glob(search_pattern)
        xyz_files.sort()

        if not xyz_files:
            print(f"❌ No XYZ files found for assembly with prefix: {input_prefix}")
            print(f"💡 Search pattern was: {search_pattern}")
            return False

        print(f"📁 Found {len(xyz_files)} XYZ files:")
        for file in xyz_files:
            print(f"   - {file}")

        # Combine XYZ files (replicating assembly.py combine_xyz_files function)
        total_atoms = 0
        all_coordinates = []

        print(f"Combining {len(xyz_files)} XYZ files...")

        # First pass: read all files and collect data
        for filename in xyz_files:
            try:
                with open(filename) as infile:
                    lines = infile.readlines()

                # The first line is the number of atoms for that file
                file_atom_count = int(lines[0].strip())
                total_atoms += file_atom_count

                # The second line is the comment/header for that file (we skip it)
                # All subsequent lines are atomic coordinates
                coordinates_from_this_file = lines[2 : 2 + file_atom_count]
                all_coordinates.extend(coordinates_from_this_file)

                print(f"  Added {file_atom_count} atoms from {os.path.basename(filename)}")

            except Exception as e:
                print(f"  Error reading {filename}: {e}")
                continue

        # Write the combined output file
        try:
            with open(assembly_output, "w") as outfile:
                # Write the new header for the combined file
                outfile.write(f"{total_atoms}\n")
                outfile.write("Combined microstructure from multiple grains (automatic assembly)\n")

                # Write all the accumulated atomic coordinates
                outfile.writelines(all_coordinates)

            print(f"✅ Successfully combined {len(xyz_files)} files into {assembly_output}")
            print(f"📊 Total atoms in final structure: {total_atoms:,}")

            return True

        except Exception as e:
            print(f"❌ Error writing output file: {e}")
            return False

    except Exception as e:
        print(f"❌ Error during assembly: {e}")
        return False


def _load_config_from_file(input_file):
    if not os.path.exists(input_file):
        print(f"Error: Input file not found: {input_file}")
        sys.exit(1)
    print(f"Reading configuration from: {input_file}")
    config = parse_input_file(input_file)
    required = {
        "grain_data": "grain_data not specified in input file",
        "stl_dir": "stl_dir not specified in input file",
        "output_dir": "output_dir not specified in input file",
    }
    for key, msg in required.items():
        if not config[key]:
            print(f"Error: {msg}")
            sys.exit(1)
    if not config["phases"]:
        print("Error: No phases defined in input file")
        sys.exit(1)
    return config


def _build_config_from_args(args):
    if not args.grain_data or not args.stl_dir or not args.output_dir:
        print("Error: --grain_data, --stl_dir, and --output_dir are required in direct mode")
        sys.exit(1)
    if not args.phase:
        print("Error: At least one --phase argument is required")
        sys.exit(1)
    config = {
        "grain_data": args.grain_data,
        "stl_dir": args.stl_dir,
        "output_dir": args.output_dir,
        "stl_prefix": args.stl_prefix,
        "verification_fig": args.verification_fig,
        "phases": dict(args.phase),
        "setup": args.setup or "",
        "assembly": args.assembly,
        "assembly_output": args.assembly_output,
    }
    return config


def _validate_paths(config, gpt_script):
    if not os.path.exists(config["grain_data"]):
        print(f"Error: Grain data file not found: {config['grain_data']}")
        sys.exit(1)
    if not os.path.exists(config["stl_dir"]):
        print(f"Error: STL directory not found: {config['stl_dir']}")
        sys.exit(1)
    if not os.path.exists(gpt_script):
        print(f"Error: gpt-mod-1.py script not found: {gpt_script}")
        sys.exit(1)
    for phase_num, cif_path in config["phases"].items():
        if not os.path.exists(cif_path):
            print(f"Error: CIF file for phase {phase_num} not found: {cif_path}")
            sys.exit(1)


def _print_startup_banner(config):
    print("Starting EBSD grain processing...")
    print(f"Grain data: {config['grain_data']}")
    print(f"STL directory: {config['stl_dir']}")
    print(f"Output directory: {config['output_dir']}")
    print(f"STL prefix: {config['stl_prefix']}")
    print(f"Verification figures: {'ON' if config['verification_fig'] else 'OFF'}")
    print(f"Phases defined: {len(config['phases'])}")
    for phase_num, cif_path in config["phases"].items():
        print(f"  Phase {phase_num}: {cif_path}")
    print(f"Setup parameters: {config['setup']}")


def main():
    args = parse_arguments()
    config = _load_config_from_file(args.input_file) if args.input_file else _build_config_from_args(args)
    _validate_paths(config, args.gpt_script)
    _print_startup_banner(config)
    process_grains_directly(config, args.gpt_script)


if __name__ == "__main__":
    main()

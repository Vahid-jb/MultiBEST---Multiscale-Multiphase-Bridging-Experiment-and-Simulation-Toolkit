#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 bright-ideas-clan
#
# SPDX-License-Identifier: GPL-3.0-or-later


"""
GFN2-xTB Structure Relaxation with Safe xTB Subprocess & Robust Mulliken Parsing
Usage:
    python GFN2-xTB.py input.txt
"""

import argparse
import contextlib
import glob
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

SUBPROCESS_TEXT_KWARGS = {"encoding": "utf-8", "errors": "replace"}
GFN0_PARAMETER_FILE = "param_gfn0-xtb.txt"

# Optional dependency checks
try:
    import numpy as np
except ImportError:
    print("Error: NumPy not found. Install with: conda install numpy")
    sys.exit(1)

try:
    from ase.constraints import FixAtoms
    from ase.io import read, write
    from ase.optimize import FIRE, LBFGS
except ImportError as e:
    print(f"Error: ASE components not found: {e}")
    print("Install with: conda install -c conda-forge ase")
    sys.exit(1)


# Force UTF-8 encoding and line buffering on all platforms.
# When stdout is a pipe (frozen binary captured by QProcess), Python defaults to
# block buffering so output only appears after the process exits.  Enabling line
# buffering here makes each print() call immediately visible in the GUI log.
for stream in (sys.stdout, sys.stderr):
    if stream is not None and hasattr(stream, "reconfigure"):
        kwargs = {"line_buffering": True}
        if sys.platform == "win32":
            kwargs["encoding"] = "utf-8"
            kwargs["errors"] = "replace"
        stream.reconfigure(**kwargs)

# xtb python calculator is optional for direct calculator use; we still use CLI for Mulliken robust parsing
try:
    from xtb.ase.calculator import XTB

    HAS_XTB_PY = True
except Exception:
    HAS_XTB_PY = False


class RelaxationIncompleteError(RuntimeError):
    """The run produced output files, but one or more steps did not succeed."""


class OptimizerStalledError(RuntimeError):
    """The ASE optimizer stopped moving the structure before reaching ``fmax``."""


class _AseProgressTracker:
    """Observer that remembers the last evaluable geometry and detects a stalled optimizer.

    FIRE with ``downhill_check`` halves its timestep every time a trial step raises the
    energy.  On a rough potential energy surface the timestep can collapse until the
    displacement underflows, after which the optimizer spins through its entire step
    budget without moving an atom or calling the calculator.  Detecting that here keeps
    a stalled run from masquerading as a long one.

    Parameters
    ----------
    atoms : ase.Atoms
        The structure being optimized, observed in place.
    """

    displacement_tolerance = 1e-8  # Å; below this the optimizer is not moving the structure
    patience = 20  # consecutive motionless steps tolerated before giving up

    def __init__(self, atoms):
        self.atoms = atoms
        self.last_evaluable = None
        self._previous_positions = None
        self._motionless_steps = 0

    def __call__(self):
        try:
            forces = self.atoms.get_forces()
        except Exception:
            return
        if np.all(np.isfinite(forces)):
            self.last_evaluable = self.atoms.positions.copy()
        self._check_for_stall()

    def _check_for_stall(self):
        positions = self.atoms.positions
        if self._previous_positions is not None:
            moved = np.abs(positions - self._previous_positions).max()
            self._motionless_steps = 0 if moved > self.displacement_tolerance else self._motionless_steps + 1
        self._previous_positions = positions.copy()
        if self._motionless_steps >= self.patience:
            raise OptimizerStalledError(
                f"the optimizer stopped moving the structure for {self.patience} consecutive steps; "
                "its timestep has collapsed and no further progress is possible"
            )


class GFN2xTBRelaxation:
    def __init__(self, input_file):
        self.input_file = input_file
        self.config = {}
        self.element_properties = {}
        self.restart_file = None  # Initialize restart_file
        self.optimization_converged = False
        self.mulliken_succeeded = True

    def parse_input_file(self):
        """Parse the input configuration file (robustly parse booleans, ints, floats)."""
        self.config = self._default_config()
        for raw in self._read_config_lines():
            self._parse_config_line(raw.strip())

        # Always generate all outputs
        self.config["calculate_mulliken"] = True
        self.config["calculate_electronic"] = True

        # set xtb_threads default from environment/CPU if not set
        if self.config.get("xtb_threads") is None or self.config.get("xtb_threads") == 1:
            self.config["xtb_threads"] = 1

        # final minimal validation
        if not self.config["input"]:
            raise ValueError("Input structure file must be specified in the input file (input = <path>)")

        self._resolve_config_restart_file()
        self._print_config_summary()

    def _read_config_lines(self):
        if not os.path.exists(self.input_file):
            raise FileNotFoundError(f"Input file '{self.input_file}' not found")
        with open(self.input_file) as f:
            return f.readlines()

    def _default_config(self):
        return {
            "method": "GFN2-xTB",
            "input": "",
            "output": "./relaxed_structure.xyz",
            "optimizer": "lbfgs",
            "steps": 500,
            "max_iterations": 250,
            "fmax": 0.02,
            "accuracy": 1.0,
            "electronic_temperature": 1000,
            "pbc": False,
            "trajectory": False,
            "trajectory_format": "traj",
            "output_format": "xyz",
            "constraints": "none",
            "custom_constraints": "",
            "calculate_mulliken": True,
            "calculate_electronic": True,
            "xtb_threads": 1,
            "xtb_timeout": 3600,
            "restart_mode": "scratch",
            "restart_file": "",
            "restart_dir": "./",
        }

    def _parse_config_line(self, line):
        if not line or line.startswith("#"):
            return
        if self._parse_element_property(line):
            return
        if "=" in line:
            key, value = line.split("=", 1)
            self._set_config_value(key.strip(), self._strip_comment(value))

    def _parse_element_property(self, line):
        parts = line.split()
        if not (parts and parts[0].isalpha() and len(parts[0]) <= 2 and "=" not in line):
            return False
        self.element_properties[parts[0]] = {
            "charge": self._float_or_default(parts[1] if len(parts) > 1 else "", 0.0),
            "spin": self._float_or_default(parts[2] if len(parts) > 2 else "", 0.0),
        }
        return True

    def _set_config_value(self, key, value):
        int_keys = {"steps", "max_iterations", "xtb_threads"}
        float_keys = {"fmax", "accuracy", "electronic_temperature"}
        bool_keys = {
            "pbc",
            "trajectory",
            "calculate_mulliken",
            "calculate_electronic",
            "use_xtb_opt",
            "calculate_charges",
        }
        string_keys = {
            "optimizer",
            "method",
            "output_format",
            "trajectory_format",
            "constraints",
            "custom_constraints",
            "output",
            "restart_mode",
            "restart_file",
            "restart_dir",
        }

        if key in int_keys:
            self.config[key] = self._int_or_none(value)
        elif key in float_keys:
            self.config[key] = self._float_or_default(value, self.config.get(key))
        elif key in bool_keys:
            self.config[key] = self._parse_bool(value)
        elif key in string_keys:
            self.config[key] = value
        else:
            self.config[key] = self._unquote(value.strip())

    @staticmethod
    def _strip_comment(value):
        return value.split("#", 1)[0].strip()

    @staticmethod
    def _unquote(value):
        if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
            return value[1:-1]
        return value

    @classmethod
    def _parse_bool(cls, value):
        if isinstance(value, bool):
            return value
        if value is None:
            return False
        return cls._strip_comment(str(value)).lower() in ("true", "1", "yes", "on", "t")

    @staticmethod
    def _int_or_none(value):
        try:
            return int(value)
        except ValueError:
            try:
                return int(float(value))
            except ValueError:
                return None

    @staticmethod
    def _float_or_default(value, default):
        try:
            return float(value)
        except (TypeError, ValueError):
            try:
                return float(str(value).replace(",", "."))
            except (TypeError, ValueError):
                return default

    def _resolve_config_restart_file(self):
        restart_file = self.config.get("restart_file", "").strip()
        restart_mode = self.config.get("restart_mode", "scratch").strip().lower()
        self.restart_file = None
        if restart_mode == "restart" and restart_file:
            self.restart_file = self._find_valid_restart_file(restart_file)

        if self.restart_file:
            print(f"✅ Restart file found and validated: {self.restart_file}")
        elif restart_mode == "restart" and restart_file:
            print(f"⚠️  Restart file specified but not found or too small: {restart_file}")
        elif restart_mode == "restart":
            print(f"ℹ️  Restart mode is '{restart_mode}' but no valid restart file provided")

    def _find_valid_restart_file(self, restart_file):
        possible_paths = [
            restart_file,
            f"./{restart_file}",
            f"./{restart_file.lstrip('./')}",
            restart_file.lstrip("./"),
        ]
        return self._first_existing_path(possible_paths, min_size=101)

    @staticmethod
    def _first_existing_path(paths, min_size=0):
        for path in paths:
            if path and os.path.exists(path) and os.path.getsize(path) >= min_size:
                return path
        return None

    def _print_config_summary(self):
        print("🔧 Parsed configuration (summary):")
        short_keys = [
            "method",
            "input",
            "output",
            "optimizer",
            "steps",
            "max_iterations",
            "fmax",
            "accuracy",
            "electronic_temperature",
            "pbc",
            "xtb_threads",
            "restart_mode",
            "restart_file",
        ]
        for k in short_keys:
            print(f"   {k:25s} : {self.config.get(k)}")
        if self.element_properties:
            print("🔬 Element-specific properties loaded for:", ",".join(self.element_properties.keys()))

    def run_xtb_opt(self, atoms, charge=0, uhf=0, method=None, iterations=None, restart_file=None):
        """
        Use xTB CLI optimizer (--opt). Supports restart files via --input flag.
        Returns (atoms_relaxed, stdout, stderr, rc, restart_path)
        """
        self._require_gfn0_parameters(method)
        if not self._xtb_executable():
            print("⚠️  xTB binary not found in PATH; cannot use xTB CLI optimizer.")
            return None, "", "xtb-not-found", 127, None

        inp_file = None
        with tempfile.TemporaryDirectory(prefix="multibest_xtb_") as work_dir:
            tmp_in = self._write_temp_xyz(atoms, directory=work_dir)
            try:
                cmd, inp_file = self._build_xtb_opt_command(tmp_in, charge, uhf, method, iterations, restart_file)
                res = subprocess.run(
                    cmd,
                    cwd=work_dir,
                    env=self._xtb_env(),
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=3600,
                    **SUBPROCESS_TEXT_KWARGS,
                )
                stdout = res.stdout or ""
                stderr = res.stderr or ""
                rc = res.returncode
                print(f"🔬 xTB finished with return code: {rc}")

                atoms_relaxed = self._read_xtb_optimized_structure(work_dir, tmp_in)
                restart_path = self._find_xtb_restart_file(work_dir, tmp_in)
                restart_path = self._preserve_xtb_restart_file(restart_path)
                return atoms_relaxed, stdout, stderr, rc, restart_path
            except subprocess.TimeoutExpired:
                print("⚠️ xTB CLI optimizer timed out")
                return None, "", "timeout", 124, None
            except FileNotFoundError:
                print("❌ xTB CLI not found in PATH.")
                return None, "", "xtb-not-found", 127, None
            finally:
                self._cleanup_temp_files(tmp_in, inp_file)

    def _write_temp_xyz(self, atoms, directory=None):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".xyz", delete=False, dir=directory) as tf:
            tmp_in = tf.name
            try:
                write(tmp_in, atoms, format="xyz")
            except Exception:
                # fallback write: basic xyz
                with open(tmp_in, "w") as f:
                    syms = atoms.get_chemical_symbols()
                    f.write(f"{len(syms)}\n\n")
                    for s, pos in zip(syms, atoms.positions):
                        f.write(f"{s} {pos[0]:.8f} {pos[1]:.8f} {pos[2]:.8f}\n")
        return tmp_in

    def _build_xtb_opt_command(self, tmp_in, charge, uhf, method, iterations, restart_file):
        method_flag = {"GFN2-xTB": "--gfn2", "GFN1-xTB": "--gfn1", "GFN0-xTB": "--gfn0"}.get(
            method or self.config.get("method", "GFN2-xTB"), "--gfn2"
        )
        iterations_val = int(iterations if iterations is not None else int(self.config.get("max_iterations", 500)))
        accuracy_val = float(self.config.get("accuracy", 1.0))
        etemp_val = int(self.config.get("electronic_temperature", 3000))

        # Build command with convergence helpers
        cmd = [
            self._xtb_executable() or "xtb",
            tmp_in,
            method_flag,
            "--opt",
            "--charge",
            str(int(round(charge))),
            "--iterations",
            str(iterations_val),
            "--etemp",
            str(etemp_val),
            "--acc",
            str(accuracy_val),
        ]

        inp_file = self._create_xtb_restart_input(restart_file)
        if inp_file:
            cmd += ["--input", inp_file]
        if int(round(uhf)) > 0:
            cmd += ["--uhf", str(int(round(uhf)))]

        print("🔬 Running xTB CLI optimizer:", " ".join(shlex.quote(x) for x in cmd))
        return cmd, inp_file

    def _create_xtb_restart_input(self, restart_file):
        restart_mode = self.config.get("restart_mode", "scratch").strip().lower()
        if restart_mode != "restart":
            return None
        if not (restart_file and os.path.exists(restart_file) and os.path.getsize(restart_file) > 100):
            print(f"⚠️  Restart mode is 'restart' but restart file not found or invalid: {restart_file}")
            return None
        with tempfile.NamedTemporaryFile(mode="w", suffix=".inp", delete=False) as inp_tf:
            inp_tf.write("$restart\n")
            inp_tf.write(f"  file={restart_file}\n")
            inp_tf.write("$end\n")
        print(f"🔧 Using restart file via input: {restart_file}")
        return inp_tf.name

    @classmethod
    def _xtb_env(cls):
        parameter_file = cls._configure_gfn0_parameter_path()
        env = {
            key: value
            for key, value in os.environ.items()
            if not (
                key.upper().startswith("_PYI")
                or key.upper().startswith("PYINSTALLER_")
                or key.upper() in {"PYTHONHOME", "PYTHONPATH"}
            )
        }
        if hasattr(sys, "_MEIPASS"):
            bundle_internal = Path(sys._MEIPASS)
            bundled_paths = [str(bundle_internal), str(bundle_internal / "bin")]
            env["PATH"] = os.pathsep.join([*bundled_paths, env.get("PATH", "")])
        if parameter_file:
            env["XTBPATH"] = str(parameter_file.parent)
        env["OMP_NUM_THREADS"] = "1"
        env["MKL_NUM_THREADS"] = "1"
        env["OPENBLAS_NUM_THREADS"] = "1"
        return env

    @staticmethod
    def _xtb_executable():
        if hasattr(sys, "_MEIPASS"):
            bundled_xtb = Path(sys._MEIPASS) / "bin" / "xtb.EXE"
            if bundled_xtb.is_file():
                return str(bundled_xtb)
        return shutil.which("xtb")

    @classmethod
    def _configure_gfn0_parameter_path(cls):
        """Add a conventional xTB data directory to XTBPATH when available."""
        for directory in cls._xtb_data_directories():
            parameter_file = directory / GFN0_PARAMETER_FILE
            if not parameter_file.is_file():
                continue
            current = os.environ.get("XTBPATH", "")
            entries = [entry for entry in current.split(os.pathsep) if entry]
            if str(directory) not in entries:
                os.environ["XTBPATH"] = os.pathsep.join([str(directory), *entries])
            return parameter_file
        return None

    @staticmethod
    def _xtb_data_directories():
        directories = []
        directories.extend(Path(entry) for entry in os.environ.get("XTBPATH", "").split(os.pathsep) if entry)
        directories.extend(
            [
                Path(sys.prefix) / "share" / "xtb",
                Path(sys.prefix) / "Library" / "share" / "xtb",
                Path(getattr(sys, "_MEIPASS", "")) / "share" / "xtb",
                Path(sys.executable).resolve().parent / "share" / "xtb",
            ]
        )
        xtb_executable = shutil.which("xtb")
        if xtb_executable:
            executable_dir = Path(xtb_executable).resolve().parent
            directories.extend([executable_dir / "share" / "xtb", executable_dir.parent / "share" / "xtb"])
        return dict.fromkeys(directories)

    def _require_gfn0_parameters(self, method=None):
        if (method or self.config.get("method", "GFN2-xTB")) != "GFN0-xTB":
            return
        if self._configure_gfn0_parameter_path() is None:
            raise RuntimeError(
                "GFN0-xTB requires param_gfn0-xtb.txt in XTBPATH. "
                "Install the complete xTB distribution or set XTBPATH to its share/xtb directory. "
                "GFN1-xTB and GFN2-xTB do not require this external parameter file."
            )

    @staticmethod
    @contextlib.contextmanager
    def _external_program_dll_directory():
        """Prevent PyInstaller's Windows DLL override from leaking into xTB."""
        if sys.platform != "win32" or not hasattr(sys, "_MEIPASS"):
            yield
            return

        import ctypes

        set_dll_directory = ctypes.windll.kernel32.SetDllDirectoryW
        set_dll_directory(None)
        try:
            yield
        finally:
            set_dll_directory(str(sys._MEIPASS))

    def _read_xtb_optimized_structure(self, dirp, tmp_in):
        best = self._find_xtb_optimized_structure(dirp, tmp_in)
        if not best:
            return None
        try:
            atoms_relaxed = read(best)
            print(f"✅ Successfully read optimized structure with {len(atoms_relaxed)} atoms")
            return atoms_relaxed
        except Exception as e:
            print(f"❌ Failed to read optimized structure: {e}")
            return None

    def _find_xtb_optimized_structure(self, dirp, tmp_in):
        candidates = [
            os.path.join(dirp, "xtbopt.xyz"),
            os.path.join(dirp, os.path.basename(tmp_in).replace(".xyz", "") + "-xtbopt.xyz"),
            os.path.join(dirp, os.path.basename(tmp_in) + "-xtbopt.xyz"),
        ]
        best = self._first_existing_path(candidates)
        if best:
            print(f"✅ Found optimized structure: {best}")
            return best

        found = glob.glob(os.path.join(dirp, "*xtbopt*.xyz")) + glob.glob(os.path.join(dirp, "xtbopt*.xyz"))
        if found:
            print(f"✅ Found via glob: {found[0]}")
            return found[0]
        return None

    def _find_xtb_restart_file(self, dirp, tmp_in):
        restart_candidates = [
            os.path.join(dirp, "xtbopt.restart"),
            os.path.join(dirp, os.path.basename(tmp_in).replace(".xyz", "") + ".restart"),
            os.path.join(dirp, os.path.basename(tmp_in) + ".restart"),
        ]
        restart_path = self._first_existing_path(restart_candidates, min_size=101)
        if restart_path:
            print(f"✅ Found restart file: {restart_path} (size: {os.path.getsize(restart_path)} bytes)")
        return restart_path

    @staticmethod
    def _preserve_xtb_restart_file(restart_path):
        if not restart_path:
            return None
        restart_dir = tempfile.mkdtemp(prefix="multibest_xtb_restart_")
        preserved_path = os.path.join(restart_dir, os.path.basename(restart_path))
        shutil.copy2(restart_path, preserved_path)
        print(f"✅ Preserved restart file: {preserved_path}")
        return preserved_path

    @staticmethod
    def _cleanup_temp_files(*paths):
        for path in paths:
            try:
                if path and os.path.exists(path):
                    os.unlink(path)
            except OSError:
                # Temporary files may already be removed by the xTB process or another cleanup path.
                pass

    def setup_calculator(self):
        """Setup xtb calculator (via xtb-python) if available, else None"""
        method_map = {"GFN2-xTB": "GFN2-xTB", "GFN1-xTB": "GFN1-xTB", "GFN0-xTB": "GFN0-xTB"}
        method_str = method_map.get(self.config.get("method", "GFN2-xTB"), "GFN2-xTB")
        self._require_gfn0_parameters(method_str)

        if not HAS_XTB_PY:
            print("⚠️  xtb-python not available; the script will still call `xtb` CLI for Mulliken parsing.")
            return None

        calc_kwargs = {
            "method": method_str,
            "accuracy": float(self.config.get("accuracy", 1.0)),
            "electronic_temperature": int(self.config.get("electronic_temperature", 1000)),
            "max_iterations": int(self.config.get("max_iterations", 250)),
        }
        print("⚙️  Setting up XTB ASE calculator with:", calc_kwargs)
        return XTB(**calc_kwargs)

    def apply_element_properties(self, atoms):
        """Apply element-specific charges and magnetic moments (per-atom)"""
        if not self.element_properties:
            print("💡 No element-specific properties defined. Using neutral atoms / zero spins.")
            return atoms, 0.0, 0.0

        total_charge = 0.0
        initial_charges = []
        magnetic_moments = []
        for atom in atoms:
            symbol = atom.symbol
            if symbol in self.element_properties:
                props = self.element_properties[symbol]
                charge = props.get("charge", 0.0)
                total_charge += charge
                initial_charges.append(charge)
                magnetic_moments.append(props.get("spin", 0.0))
            else:
                initial_charges.append(0.0)
                magnetic_moments.append(0.0)
                print(f"⚠️  No element-specific props for {symbol}; using 0,0")

        try:
            atoms.set_initial_charges(initial_charges)
            atoms.set_initial_magnetic_moments(magnetic_moments)
        except Exception:
            # Some ASE readers/calculators do not support initial charge/spin metadata; relaxation can continue.
            pass
        total_spin = sum(magnetic_moments)
        print(f"📊 Total charge from element props: {total_charge:.2f}")
        print(f"📊 Total spin from per-atom element props: {total_spin:.2f}")
        if abs(total_spin) >= 20:
            print(
                "⚠️  Large total spin requested. Element spin values are applied to every atom of that element; "
                "use spin 0 for a neutral or antiferromagnetic bulk model unless a high-spin state is intentional."
            )
        return atoms, total_charge, total_spin

    def apply_constraints(self, atoms):
        """Apply constraints based on configuration"""
        ctype = self.config.get("constraints", "none")
        if ctype == "none":
            print("🔓 No constraints applied")
            return atoms

        if ctype == "bottom":
            fixed_indices, z_threshold = self._bottom_constraint_indices(atoms)
        elif ctype == "custom" and self.config.get("custom_constraints"):
            fixed_indices = self._custom_constraint_indices()
            z_threshold = None
        else:
            fixed_indices = []
            z_threshold = None

        if fixed_indices:
            atoms.set_constraint(FixAtoms(indices=fixed_indices))
            self._print_constraint_summary(ctype, fixed_indices, z_threshold)
        return atoms

    def _bottom_constraint_indices(self, atoms):
        if len(atoms) <= 10:
            return [], None
        z_coords = atoms.positions[:, 2]
        z_min = np.min(z_coords)
        z_threshold = z_min + 0.1 * (np.max(z_coords) - z_min)
        return [i for i, z in enumerate(z_coords) if z < z_threshold], z_threshold

    def _custom_constraint_indices(self):
        fixed_indices = []
        for part in str(self.config.get("custom_constraints")).split(","):
            part = part.strip()
            if part:
                fixed_indices.extend(self._constraint_indices_from_part(part))
        return fixed_indices

    @staticmethod
    def _constraint_indices_from_part(part):
        if "-" not in part:
            return [int(part)]
        start, end = part.split("-", 1)
        return list(range(int(start), int(end) + 1))

    @staticmethod
    def _print_constraint_summary(ctype, fixed_indices, z_threshold):
        if ctype == "bottom":
            print(f"🔒 Constrained {len(fixed_indices)} bottom atoms (z < {z_threshold:.2f} Å)")
        else:
            print(f"🔒 Custom constraints on atoms: {fixed_indices}")

    def setup_pbc(self, atoms):
        """Setup periodic boundary conditions if requested"""
        if self.config.get("pbc", False):
            if self.config.get("method") == "GFN2-xTB":
                raise ValueError(
                    "GFN2-xTB does not support periodic boundary conditions in this xTB backend "
                    "(multipoles are unavailable with PBC). Use GFN1-xTB or disable PBC."
                )
            if not atoms.cell.any():
                pos = atoms.positions
                cell_lengths = np.ptp(pos, axis=0) + 10.0
                atoms.set_cell(cell_lengths)
            atoms.pbc = (True, True, True)
            try:
                print("📦 PBC enabled. Cell lengths:", atoms.cell.lengths())
            except Exception:
                print("📦 PBC enabled.")
        else:
            if atoms.pbc.any():
                print(
                    "⚠️  Input structure contains a periodic cell, but PBC is disabled. "
                    "The structure will be relaxed as an isolated cluster."
                )
            atoms.pbc = (False, False, False)
            print("📦 No periodic boundary conditions")
        return atoms

    def parse_mulliken_analysis(self, output_text, atoms):
        """Robust Mulliken parser: returns (charges_list or None, spins_list or None)"""
        if not output_text:
            return None, None

        text = output_text.replace("\r\n", "\n")
        charges = self._parse_mulliken_charge_table(text) or self._parse_fallback_atom_charges(text, len(atoms))
        charges = self._validated_mulliken_charges(charges, len(atoms))
        spins = self._spins_from_element_properties(atoms)
        return charges, spins

    @staticmethod
    def _parse_mulliken_charge_table(text):
        charge_table_pattern = (
            r"^\s*#\s*Z\s+covCN\s+q\s+C6AA\s+α\(0\).*?(?=\n\s*\n|\n\s*#|\n\s*Wiberg|\n\s*molecular|\n\s*$)"
        )
        charge_match = re.search(charge_table_pattern, text, re.MULTILINE | re.DOTALL)
        if not charge_match:
            return None
        charge_lines = re.findall(r"^\s*\d+\s+\d+\s+\w+\s+[\d.-]+\s+([\d.-]+)", charge_match.group(), re.MULTILINE)
        return [float(val) for val in charge_lines] if charge_lines else None

    @staticmethod
    def _parse_fallback_atom_charges(text, atom_count):
        charges = None
        atom_table_pattern = r"^\s*(\d+)\s+(\d+)\s+(\w+)\s+([\d.-]+)\s+([\d.-]+)\s+([\d.-]+)\s+([\d.-]+)"
        for match in re.findall(atom_table_pattern, text, re.MULTILINE):
            try:
                atom_idx = int(match[0]) - 1
                if charges is None:
                    charges = [0.0] * atom_count
                if atom_idx < len(charges):
                    charges[atom_idx] = float(match[4])
            except (ValueError, IndexError):
                continue
        return charges

    @staticmethod
    def _validated_mulliken_charges(charges, atom_count):
        if charges and len(charges) != atom_count:
            return None
        return charges

    def _spins_from_element_properties(self, atoms):
        spins = [self.element_properties.get(atom.symbol, {}).get("spin", 0.0) for atom in atoms]
        return spins if int(round(sum(spins))) > 0 else None

    def save_mulliken_analysis(self, atoms, charge, uhf, output_base):
        """Run xTB (CLI) to produce Mulliken/pop and save to file; robust retries and logging.

        Returns
        -------
        bool
            ``True`` when the population report was written, ``False`` on any failure.
        """
        print(f"🔬 Starting Mulliken analysis for {len(atoms)} atoms...")

        try:
            temp_xyz = self._write_temp_xyz_for_mulliken(atoms)
        except Exception as e:
            print(f"❌ Failed to write temporary structure: {e}")
            return False

        try:
            cmd = self._build_mulliken_command(temp_xyz, charge, uhf)
            print(f"🔬 Running Mulliken analysis: {' '.join(shlex.quote(x) for x in cmd)}")

            res = subprocess.run(
                cmd,
                env=self._xtb_env(),
                capture_output=True,
                text=True,
                check=False,
                timeout=600,
                **SUBPROCESS_TEXT_KWARGS,
            )
            stdout = res.stdout or ""
            stderr = res.stderr or ""
            rc = res.returncode

            print(f"🔬 Mulliken analysis finished with return code: {rc}")
            self._write_mulliken_log(output_base, cmd, stdout, stderr)
            if rc != 0:
                print(f"❌ xTB Mulliken analysis failed with return code {rc}")
                return False

            charges, spins = self._mulliken_populations(stdout, atoms)
            totals = self._write_mulliken_report(output_base, atoms, charge, uhf, charges, spins)
            self._print_mulliken_summary(f"{output_base}_mulliken.txt", charges, spins, totals)
            return True

        except subprocess.TimeoutExpired:
            print("❌ Mulliken analysis timed out")
            return False
        except Exception as e:
            print(f"❌ Unexpected error in Mulliken analysis: {e}")
            return False
        finally:
            self._cleanup_temp_files(temp_xyz)

    def _write_temp_xyz_for_mulliken(self, atoms):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".xyz", delete=False) as tf:
            temp_xyz = tf.name
            write(temp_xyz, atoms, format="xyz")
        return temp_xyz

    def _build_mulliken_command(self, temp_xyz, charge, uhf):
        method_flag = {"GFN2-xTB": "--gfn2", "GFN1-xTB": "--gfn1", "GFN0-xTB": "--gfn0"}.get(
            self.config.get("method", "GFN2-xTB"), "--gfn2"
        )
        cmd = [
            self._xtb_executable() or "xtb",
            temp_xyz,
            method_flag,
            "--pop",
            "--charge",
            str(charge),
            # Must track the configured SCF limit: transition-metal oxides routinely need
            # far more than a hundred cycles, and a short limit here fails the analysis of
            # a structure the relaxation itself handled fine.
            "--iterations",
            str(int(self.config.get("max_iterations", 250))),
            "--etemp",
            str(int(self.config.get("electronic_temperature", 1000))),
            "--acc",
            str(float(self.config.get("accuracy", 1.0))),
        ]
        if uhf > 0:
            cmd += ["--uhf", str(uhf)]
        return cmd

    @staticmethod
    def _write_mulliken_log(output_base, cmd, stdout, stderr):
        log_file = f"{output_base}.xtb.mulliken.log"
        with open(log_file, "w", encoding="utf-8") as f:
            f.write(f"# xTB Mulliken command: {' '.join(cmd)}\n\n")
            f.write("STDOUT:\n")
            f.write(stdout)
            f.write("\n\nSTDERR:\n")
            f.write(stderr)
        print(f"📝 Mulliken analysis log saved: {log_file}")

    def _mulliken_populations(self, stdout, atoms):
        charges, spins = self.parse_mulliken_analysis(stdout, atoms)
        if charges is None:
            print("⚠️  Could not parse Mulliken charges from xTB output")
            charges = [0.0] * len(atoms)
        if spins is None:
            spins = [self.element_properties.get(atom.symbol, {}).get("spin", 0.0) for atom in atoms]
        return charges, spins

    @staticmethod
    def _write_mulliken_report(output_base, atoms, charge, uhf, charges, spins):
        mulliken_file = f"{output_base}_mulliken.txt"
        total_charge = 0.0
        total_spin = 0.0
        with open(mulliken_file, "w", encoding="utf-8") as f:
            f.write("# Mulliken Charge and Spin Analysis\n")
            f.write(f"# Total charge: {charge}, Total spin: {uhf}\n")
            f.write("# Atom Index, Element, Mulliken Charge, Spin Population\n")
            for i, atom in enumerate(atoms):
                q = charges[i] if i < len(charges) else 0.0
                s = spins[i] if spins and i < len(spins) else 0.0
                total_charge += q
                total_spin += s
                f.write(f"{i:4d} {atom.symbol:2s} {q:12.6f} {s:12.6f}\n")
            f.write(f"# Total Mulliken charge: {total_charge:.6f}\n")
            f.write(f"# Total Mulliken spin: {total_spin:.6f}\n")
        return total_charge, total_spin

    @staticmethod
    def _print_mulliken_summary(mulliken_file, charges, spins, totals):
        total_charge, total_spin = totals
        print(f"📊 Mulliken analysis saved to: {mulliken_file}")
        print(f"📊 Charge range: {min(charges):.3f} to {max(charges):.3f}")
        print(f"📊 Total Mulliken charge: {total_charge:.3f}")
        if spins is not None and any(s != 0 for s in spins):
            print(f"📊 Spin range: {min(spins):.3f} to {max(spins):.3f}")
            print(f"📊 Total Mulliken spin: {total_spin:.3f}")

    def save_electronic_properties(self, atoms, output_base):
        """Save basic electronic properties from calculator (if available)"""
        print("🔬 Saving electronic properties...")
        try:
            calc = atoms.calc
            if calc is None:
                # Return silently without printing confusing warning
                return

            properties_file = f"{output_base}_electronic.txt"
            with open(properties_file, "w", encoding="utf-8") as f:
                f.write("# Electronic properties\n")
                try:
                    energy = atoms.get_potential_energy()
                    f.write(f"Total Energy: {energy:.6f} eV\n")
                    print(f"📊 Total Energy: {energy:.6f} eV")
                except Exception:
                    f.write("Total Energy: Not available\n")
                try:
                    forces = atoms.get_forces()
                    max_force = np.max(np.linalg.norm(forces, axis=1))
                    rms_force = np.sqrt(np.mean(np.linalg.norm(forces, axis=1) ** 2))
                    f.write(f"Max Force: {max_force:.6f} eV/Å\n")
                    f.write(f"RMS Force: {rms_force:.6f} eV/Å\n")
                except Exception:
                    f.write("Forces: Not available\n")
                try:
                    stress = atoms.get_stress()
                    f.write(f"Stress: {stress}\n")
                except Exception:
                    f.write("Stress: Not available\n")
            print(f"📊 Electronic properties saved to: {properties_file}")
        except Exception:
            # Return silently without printing error
            return

    def relax_structure(self):
        """Main relaxation function"""
        print("🚀 Starting GFN-xTB Structure Relaxation")
        self.parse_input_file()

        atoms, total_charge, total_spin = self._prepared_atoms()
        restart_file_to_use = self._restart_file_for_run()
        atoms = self._optimize_atoms(atoms, total_charge, total_spin, restart_file_to_use)
        out_path = self._write_final_structure(atoms)
        total_charge, total_spin = self._final_charge_spin(atoms)
        self._save_final_analysis(atoms, out_path, total_charge, total_spin)
        self._report_outcome(out_path)

    def _report_outcome(self, out_path):
        """Announce success only when every step actually succeeded.

        Output files are written either way, so a caller that only wants the last
        evaluable geometry still gets it; the exit status tells whether the numbers
        in those files can be trusted.

        Raises
        ------
        RelaxationIncompleteError
            If the optimization did not converge or the population analysis failed.
        """
        problems = []
        if not self.optimization_converged:
            problems.append(f"the geometry optimization did not converge to fmax = {self.config.get('fmax', 0.02)}")
        if not self.mulliken_succeeded:
            problems.append("the Mulliken population analysis failed")

        if not problems:
            print("🎉 GFN-xTB relaxation completed successfully!")
            return

        raise RelaxationIncompleteError(
            f"GFN-xTB relaxation finished with problems: {'; '.join(problems)}. "
            f"The last evaluable structure was still written to {out_path}, "
            "but its energies and forces are not converged results."
        )

    def _prepared_atoms(self):
        inp = self.config["input"]
        print(f"📁 Reading structure: {inp}")
        atoms = read(inp)
        print(f"✅ Loaded {len(atoms)} atoms; elements: {set(atoms.get_chemical_symbols())}")
        atoms = self.setup_pbc(atoms)
        atoms, total_charge, total_spin = self.apply_element_properties(atoms)
        atoms = self.apply_constraints(atoms)
        return atoms, total_charge, total_spin

    def _restart_file_for_run(self):
        restart_mode = self.config.get("restart_mode", "scratch").strip().lower()
        if restart_mode == "restart":
            print(f"🔧 Restart mode: {restart_mode}, using restart file: {self.restart_file}")
            return self.restart_file
        print(f"🔧 Restart mode: {restart_mode}, starting from scratch")
        return None

    def _optimize_atoms(self, atoms, total_charge, total_spin, restart_file):
        if self.config.get("use_xtb_opt", True):
            return self._optimize_with_xtb_first(atoms, total_charge, total_spin, restart_file)
        return self._optimize_with_ase_first(atoms, total_charge, total_spin, restart_file)

    def _run_xtb_for_relaxation(self, atoms, total_charge, total_spin, restart_file):
        return self.run_xtb_opt(
            atoms,
            charge=total_charge,
            uhf=total_spin,
            method=self.config.get("method"),
            iterations=self.config.get("max_iterations"),
            restart_file=restart_file,
        )

    def _optimize_with_xtb_first(self, atoms, total_charge, total_spin, restart_file):
        if atoms.pbc.any():
            print(
                "Periodic structure detected; skipping xTB CLI optimization because "
                "the temporary XYZ input cannot preserve its cell."
            )
            return self._optimize_with_ase(atoms)

        print("🔧 Running xTB CLI optimization...")
        if restart_file:
            print(f"🔧 Continuing from restart file: {restart_file}")
        opt_atoms, stdout, stderr, rc, _ = self._run_xtb_for_relaxation(atoms, total_charge, total_spin, restart_file)
        opt_atoms = self._validate_xtb_result(opt_atoms, atoms, rc)
        if opt_atoms is not None:
            self.optimization_converged = True
            print("✅ xTB CLI optimization completed successfully.")
            return opt_atoms

        print("⚠️ xTB CLI optimization failed; falling back to ASE optimizer.")
        if stdout:
            print(f"xTB output: {self._short_process_output(stdout)}")
        if stderr:
            print(f"xTB error: {self._short_process_output(stderr)}")
        return self._optimize_with_ase(atoms)

    @staticmethod
    def _short_process_output(text, max_chars=2000):
        text = str(text).strip()
        if len(text) <= max_chars:
            return text
        half = max_chars // 2
        return text[:half] + "\n... [truncated middle]\n" + text[-half:]

    def _validate_xtb_result(self, opt_atoms, original_atoms, rc):
        """Reject failed/garbage xTB output and restore the periodic cell.

        A nonzero xTB exit code can still leave a stale ``xtbopt.xyz`` on disk;
        reading it yields a structure with the wrong atom count and no cell,
        which later breaks periodic writers (e.g. ``lammps-data``).  Only accept
        a result from a successful run whose atom count matches the input, and
        copy the original cell/PBC back because the xyz round-trip used to drive
        xTB does not preserve lattice information.
        """
        if opt_atoms is None:
            return None
        if rc != 0:
            print(f"⚠️ xTB CLI returned nonzero exit code {rc}; discarding its output.")
            return None
        if len(opt_atoms) != len(original_atoms):
            print(
                f"⚠️ xTB output has {len(opt_atoms)} atoms but the input has "
                f"{len(original_atoms)}; discarding likely-stale result."
            )
            return None
        if original_atoms.cell is not None and original_atoms.cell.any():
            opt_atoms.set_cell(original_atoms.cell)
            opt_atoms.set_pbc(original_atoms.pbc)
        return opt_atoms

    def _optimize_with_ase_first(self, atoms, total_charge, total_spin, restart_file):
        print("🔧 Running ASE optimization with xTB calculator...")
        try:
            return self._optimize_with_ase(atoms)
        except Exception as e:
            print(f"❌ ASE optimizer failed: {e}")
            return self._fallback_xtb_optimization(atoms, total_charge, total_spin, restart_file)

    def _optimize_with_ase(self, atoms):
        if not self._attach_calculator(atoms):
            raise RuntimeError("xtb-python calculator is not available")
        try:
            converged = self._run_ase_optimizer(atoms)
        except Exception as exc:
            raise RuntimeError(f"xTB ASE calculator failed: {exc}") from exc
        self.optimization_converged = converged
        if converged:
            print("✅ ASE optimization converged.")
        else:
            print("⚠️  ASE optimization ended before convergence; writing the last evaluable structure.")
        return atoms

    def _attach_calculator(self, atoms):
        calc = self.setup_calculator()
        if calc is None:
            return False
        atoms.calc = calc
        print("🔧 Running ASE optimization with xTB calculator...")
        return True

    def _fallback_xtb_optimization(self, atoms, total_charge, total_spin, restart_file):
        if atoms.pbc.any():
            raise RuntimeError("xTB CLI fallback cannot preserve periodic cells; use the ASE calculator or disable PBC")
        print("⚠️ xTB calculator not available; using xTB CLI optimizer as fallback.")
        opt_atoms, _, stderr, rc, _ = self._run_xtb_for_relaxation(atoms, total_charge, total_spin, restart_file)
        opt_atoms = self._validate_xtb_result(opt_atoms, atoms, rc)
        if opt_atoms is None:
            if stderr:
                print(f"xTB error: {stderr}")
            raise RuntimeError("xTB CLI optimizer also failed")
        self.optimization_converged = True
        print("✅ xTB CLI optimization completed as fallback.")
        return opt_atoms

    def _run_ase_optimizer(self, atoms):
        if self.config.get("optimizer", "lbfgs").lower() == "lbfgs":
            opt = LBFGS(atoms)
        else:
            opt = FIRE(atoms, dt=0.05, maxstep=0.05, dtmax=0.5, downhill_check=True)

        tracker = _AseProgressTracker(atoms)
        tracker()
        if tracker.last_evaluable is None:
            raise RuntimeError("xTB could not evaluate the initial geometry")
        if hasattr(opt, "attach"):
            opt.attach(tracker, interval=1)

        try:
            return bool(opt.run(fmax=float(self.config.get("fmax", 0.02)), steps=int(self.config.get("steps", 500))))
        except OptimizerStalledError as exc:
            print(f"⚠️  ASE optimization stopped early: {exc}")
            return False
        except Exception as exc:
            atoms.set_positions(tracker.last_evaluable)
            if atoms.calc is not None and hasattr(atoms.calc, "reset"):
                atoms.calc.reset()
            try:
                atoms.get_forces()
            except Exception:
                raise exc
            print(f"⚠️  ASE optimizer encountered an unstable trial geometry: {exc}")
            print("⚠️  Restored the last geometry that xTB could evaluate.")
            return False

    # Map output-file extensions to ASE format names. ASE cannot infer the
    # format for several of these (e.g. ``.lmp``), so we resolve it explicitly.
    EXT_TO_ASE_FORMAT = {
        ".xyz": "xyz",
        ".extxyz": "extxyz",
        ".cif": "cif",
        ".lmp": "lammps-data",
        ".data": "lammps-data",
        ".lammps": "lammps-data",
    }

    def _resolve_output_format(self, out_path):
        """Pick an explicit ASE format from the config, else from the extension."""
        fmt = str(self.config.get("output_format") or "").strip().lower()
        if fmt:
            return fmt
        ext = Path(out_path).suffix.lower()
        return self.EXT_TO_ASE_FORMAT.get(ext, "xyz")

    def _write_final_structure(self, atoms):
        out_path = self.config.get("output", "./relaxed_structure.xyz")
        out_fmt = self._resolve_output_format(out_path)
        # LAMMPS data needs a Masses section so downstream viewers (e.g. OVITO)
        # can map numeric atom types back to chemical elements.
        write_kwargs = {"masses": True} if out_fmt == "lammps-data" else {}
        write(out_path, atoms, format=out_fmt, **write_kwargs)
        print(f"📁 Optimized structure written: {out_path} (format: {out_fmt})")
        return out_path

    def _final_charge_spin(self, atoms):
        total_charge = 0.0
        total_spin = 0.0
        for atom in atoms:
            props = self.element_properties.get(atom.symbol)
            if props:
                total_charge += props.get("charge", 0.0)
                total_spin += props.get("spin", 0.0)
        print(f"📊 Final calculation parameters - Total charge: {total_charge:.1f}, Total spin: {total_spin:.1f}")
        return total_charge, total_spin

    def _save_final_analysis(self, atoms, out_path, total_charge, total_spin):
        print("🔬 Starting Mulliken charge analysis...")
        out_base = Path(out_path).stem
        charge_to_pass = int(round(total_charge))
        uhf_to_pass = int(round(total_spin))
        print(f"🔬 Running Mulliken analysis with charge={charge_to_pass}, uhf={uhf_to_pass}")
        self.mulliken_succeeded = bool(self.save_mulliken_analysis(atoms, charge_to_pass, uhf_to_pass, out_base))

        print("🔬 Calculating electronic properties...")
        self.save_electronic_properties(atoms, out_base)


def main():
    parser = argparse.ArgumentParser(description="GFN-xTB Structure Relaxation")
    parser.add_argument("input_file", help="Input configuration file (e.g., input.txt)")
    args = parser.parse_args()

    if not os.path.exists(args.input_file):
        print(f"Input file '{args.input_file}' not found")
        sys.exit(1)

    relaxer = GFN2xTBRelaxation(args.input_file)
    try:
        relaxer.relax_structure()
    except RelaxationIncompleteError as e:
        # An expected outcome, not a crash: report it plainly and fail the run so the
        # caller does not treat unconverged numbers as results.
        print(f"❌ {e}")
        sys.exit(1)
    except Exception as e:
        print("Fatal error:", e)
        import traceback

        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()

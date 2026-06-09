#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 bright-ideas-clan
#
# SPDX-License-Identifier: GPL-3.0-or-later


"""
SevenNet Structure Relaxation via ASE Interface
Usage:
    python SevenNet.py input.txt
"""

import argparse
import os
import sys
from pathlib import Path

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

try:
    import numpy as np
except ImportError:
    print("Error: NumPy not found. Install with: conda install numpy")
    sys.exit(1)

try:
    from ase.constraints import FixAtoms
    from ase.io import read, write
    from ase.optimize import BFGS, FIRE, LBFGS
except ImportError as e:
    print(f"Error: ASE components not found: {e}")
    print("Install with: conda install -c conda-forge ase")
    sys.exit(1)


def _disable_e3nn_torchscript_for_frozen() -> None:
    """Switch e3nn to eager (non-TorchScript) mode in frozen PyInstaller builds.

    e3nn's ``_codegen_register`` calls ``e3nn.util.jit.compile()`` → ``torch.jit.script()``
    on dynamically-generated ``torch.fx.GraphModule`` submodules during
    ``TensorProduct.__init__``.  TorchScript compilation requires
    ``inspect.getsource()`` to work on those dynamically-generated methods, which
    fails in a frozen binary because ``linecache.lazycache`` cannot resolve the
    module's ``__spec__.loader`` in the PyInstaller import environment.

    Setting ``jit_mode="eager"`` makes ``_codegen_register`` skip
    ``torch.jit.script()`` and keep the raw ``GraphModule`` instead, trading a
    small (~10–30 %) JIT speedup for compatibility.
    """
    if not getattr(sys, "frozen", False):
        return
    try:
        import e3nn

        e3nn.set_optimization_defaults(jit_mode="eager")
    except Exception:
        # If e3nn is unavailable or its optimization API changes, continue with
        # the default import path and let SevenNet report any real import error.
        pass


_disable_e3nn_torchscript_for_frozen()


def _import_sevennet_calculator():
    """Import SevenNet while keeping frozen import failures user-readable."""
    import_errors = []
    for module_name in ("sevenn.calculator", "sevenn.sevennet_calculator"):
        try:
            module = __import__(module_name, fromlist=["SevenNetCalculator"])
            return module.SevenNetCalculator
        except Exception as e:
            import_errors.append(f"{module_name}: {e}")
    print("Error: SevenNet not available:")
    for error in import_errors:
        print(f"   {error}")
    return None


# SevenNet calculator import
SevenNetCalculator = _import_sevennet_calculator()
HAS_SEVENNET = SevenNetCalculator is not None


class SevenNetRelaxation:
    def __init__(self, input_file):
        self.input_file = input_file
        self.config = {}

    def parse_input_file(self):
        """Parse the input configuration file."""
        if not os.path.exists(self.input_file):
            raise FileNotFoundError(f"Input file '{self.input_file}' not found")

        with open(self.input_file) as f:
            lines = f.readlines()

        self.config = self._default_config()

        for line in lines:
            self._parse_config_line(line.strip())

        # Validation
        if not self.config["input"]:
            raise ValueError("Input structure file must be specified (input = <path>)")

        print("🔧 Parsed configuration:")
        for k, v in self.config.items():
            print(f"   {k:20} : {v}")

    @staticmethod
    def _default_config():
        return {
            "method": "SevenNet",
            "input": "",
            "output": "./relaxed_structure.xyz",
            "optimizer": "bfgs",
            "steps": 500,
            "fmax": 0.02,
            "model": "7net-mf-ompa",
            "modal": "mpa",
            "device": "auto",
            "pbc": False,
            "constraints": "none",
            "custom_constraints": "",
        }

    def _parse_config_line(self, line):
        if not line or line.startswith("#") or "=" not in line:
            return
        key, value = line.split("=", 1)
        self._set_config_value(key.strip(), value.split("#", 1)[0].strip())

    def _set_config_value(self, key, value):
        if key == "steps":
            self._set_int_config(key, value)
        elif key == "fmax":
            self._set_float_config(key, value)
        elif key == "pbc":
            self.config[key] = self._parse_bool(value)
        elif key in self._string_config_keys():
            self.config[key] = value

    def _set_int_config(self, key, value):
        try:
            self.config[key] = int(value)
        except ValueError:
            # Invalid user input leaves the documented default in place.
            pass

    def _set_float_config(self, key, value):
        try:
            self.config[key] = float(value)
        except ValueError:
            # Invalid user input leaves the documented default in place.
            pass

    @staticmethod
    def _parse_bool(value):
        if isinstance(value, bool):
            return value
        return str(value).split("#", 1)[0].strip().lower() in ("true", "1", "yes", "on", "t")

    @staticmethod
    def _string_config_keys():
        return {
            "method",
            "input",
            "output",
            "optimizer",
            "model",
            "modal",
            "device",
            "constraints",
            "custom_constraints",
        }

    def setup_calculator(self):
        """Setup SevenNet calculator with actual model keywords"""
        if not HAS_SEVENNET:
            print("❌ SevenNet not available. Check installation.")
            return None

        model = self.config.get("model", "7net-mf-ompa")
        modal = self.config.get("modal", "mpa")
        device = self.config.get("device", "auto")

        try:
            # Use actual SevenNet calculator interface
            calc_kwargs = {"model": model, "device": device}

            # Add modal for multi-fidelity models
            if model in ["7net-mf-ompa", "7net-omat"]:
                calc_kwargs["modal"] = modal

            print(f"⚙️  Setting up SevenNet calculator: {calc_kwargs}")
            calc = SevenNetCalculator(**calc_kwargs)
            return calc
        except Exception as e:
            print(f"❌ Failed to setup SevenNet calculator: {e}")
            return None

    def apply_constraints(self, atoms):
        """Apply constraints based on configuration"""
        ctype = self.config.get("constraints", "none")
        if ctype == "none":
            print("🔓 No constraints applied")
            return atoms

        if ctype == "custom" and self.config.get("custom_constraints"):
            fixed_indices = self._custom_constraint_indices()
            if fixed_indices:
                atoms.set_constraint(FixAtoms(indices=fixed_indices))
                print(f"🔒 Custom constraints on atoms: {fixed_indices}")
        return atoms

    def _custom_constraint_indices(self):
        fixed_indices = []
        for part in str(self.config.get("custom_constraints")).split(","):
            fixed_indices.extend(self._constraint_indices_from_part(part.strip()))
        return fixed_indices

    @staticmethod
    def _constraint_indices_from_part(part):
        if not part:
            return []
        try:
            if "-" in part:
                start, end = part.split("-", 1)
                return list(range(int(start), int(end) + 1))
            return [int(part)]
        except ValueError:
            return []

    def setup_pbc(self, atoms):
        """Setup periodic boundary conditions if requested"""
        if self.config.get("pbc", False):
            if not atoms.cell.any():
                # Add default cell if none exists
                pos = atoms.positions
                cell_lengths = np.ptp(pos, axis=0) + 10.0
                atoms.set_cell(cell_lengths)
            atoms.pbc = (True, True, True)
            print("📦 PBC enabled")
        else:
            atoms.pbc = (False, False, False)
            print("📦 No periodic boundary conditions")
        return atoms

    def relax_structure(self):
        """Main relaxation function using ASE optimizer"""
        print("🚀 Starting SevenNet Structure Relaxation")
        self.parse_input_file()

        # Read structure
        inp = self.config["input"]
        print(f"📁 Reading structure: {inp}")
        atoms = read(inp)
        print(f"✅ Loaded {len(atoms)} atoms; elements: {set(atoms.get_chemical_symbols())}")

        # Setup system
        atoms = self.setup_pbc(atoms)
        atoms = self.apply_constraints(atoms)

        # Setup calculator
        calc = self.setup_calculator()
        if calc is None:
            print("❌ Cannot continue without SevenNet calculator")
            sys.exit(1)
        atoms.calc = calc

        # Run optimization with better optimizer settings
        print("🔧 Running ASE optimization with SevenNet...")

        optimizer_name = self.config.get("optimizer", "bfgs").lower()

        # Choose optimizer with better convergence properties
        if optimizer_name == "lbfgs":
            opt = LBFGS(atoms, memory=10)  # Reduced memory for small systems
        elif optimizer_name == "fire":
            opt = FIRE(atoms)
        else:  # Default to BFGS (most stable)
            opt = BFGS(atoms)

        target_fmax = float(self.config.get("fmax", 0.02))
        max_steps = int(self.config.get("steps", 500))

        try:
            opt.run(fmax=target_fmax, steps=max_steps)

            # Check if optimization actually converged
            forces = atoms.get_forces()
            current_fmax = np.max(np.linalg.norm(forces, axis=1))

            if current_fmax <= target_fmax:
                print("✅ Optimization completed successfully (converged)")
            else:
                print(f"⚠️  Optimization stopped: reached maximum steps ({max_steps}) without convergence")
                print(f"    Current fmax: {current_fmax:.6f} eV/Å, Target: {target_fmax:.6f} eV/Å")

        except Exception as e:
            print(f"⚠️  Optimization ended with error: {e}")

        # Write output
        out_path = self.config.get("output", "./relaxed_structure.xyz")
        try:
            write(out_path, atoms, format="xyz")
            print(f"📁 Optimized structure written: {out_path}")
        except Exception as e:
            print(f"❌ Failed to write output: {e}")

        # Save energy information
        try:
            energy = atoms.get_potential_energy()
            forces = atoms.get_forces()
            max_force = np.max(np.linalg.norm(forces, axis=1))

            print(f"📊 Final energy: {energy:.6f} eV")
            print(f"📊 Maximum force: {max_force:.6f} eV/Å")

            # Write energy to file
            energy_file = Path(out_path).with_suffix(".energy")
            with open(energy_file, "w", encoding="utf-8") as f:
                f.write("# SevenNet Relaxation Results\n")
                f.write(f"Final_energy: {energy:.6f} eV\n")
                f.write(f"Max_force: {max_force:.6f} eV/Å\n")
            print(f"📊 Energy saved: {energy_file}")
        except Exception as e:
            print(f"⚠️  Could not retrieve energy: {e}")

        print("🎉 SevenNet relaxation completed!")


def main():
    parser = argparse.ArgumentParser(description="SevenNet Structure Relaxation")
    parser.add_argument("input_file", help="Input configuration file")
    args = parser.parse_args()

    if not os.path.exists(args.input_file):
        print(f"Input file '{args.input_file}' not found")
        sys.exit(1)

    relaxer = SevenNetRelaxation(args.input_file)
    try:
        relaxer.relax_structure()
    except Exception as e:
        print(f"Fatal error: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()

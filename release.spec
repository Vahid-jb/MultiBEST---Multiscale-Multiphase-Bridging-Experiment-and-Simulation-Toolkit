"""
PyInstaller release bundle for MultiBEST.

Build with:
    uv run --with pyinstaller pyinstaller --clean --noconfirm release.spec

The bundle is created as dist/MultiBEST/ and contains:
    - MultiBEST: the GUI launcher
    - one sibling executable per backend script used by the GUI/workflows

The GUI resolves backend scripts through multibest.gui.utils.general.get_script_path().
In frozen mode that helper maps paths such as input_convertor.py to sibling
executables such as dist/MultiBEST/input_convertor.
"""

# ruff: noqa: F821, I001
from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys
import sysconfig
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs


ROOT = Path(SPECPATH).resolve()
SRC = ROOT / "src"
APP_NAME = "MultiBEST"
RELEASE_PATHS_RUNTIME_HOOK = ROOT / "scripts" / "pyinstaller_hooks" / "rthook_release_paths.py"
QT_PLATFORM_RUNTIME_HOOK = ROOT / "scripts" / "pyinstaller_hooks" / "rthook_qt_platform.py"
PYINSTALLER_HOOKS = ROOT / "scripts" / "pyinstaller_hooks"
CONDA_RUNTIME_LIBRARIES = (
    "libcrypto.so.3",
    "libgio-2.0.so.0",
    "libglib-2.0.so.0",
    "libgmodule-2.0.so.0",
    "libgobject-2.0.so.0",
    "libnghttp2.so.14",
    "libssl.so.3",
    # OVITO GUI imports pull these Qt libraries into the root runtime. On Linux,
    # PyInstaller can discover host /lib64 copies, which may be a different
    # Qt minor version than PySide6's conda QtCore.
    "libQt6Concurrent.so.6",
    "libQt6Xml.so.6",
    # DREAM3D-NX/SIMPLNX is built against conda-forge oneTBB. Other packages
    # such as pymeshlab/open3d may contribute a same-named libtbb.so.12 that
    # lacks required symbols, so force the root runtime to match the env.
    "libtbb.so.12",
    "libtbbmalloc.so.2",
    "libtbbmalloc_proxy.so.2",
    # Primary MKL components. xTB/libmkl_rt may dlopen these unversioned names
    # directly, while torch may link against the .so.2 aliases below.
    "libmkl_core.so",
    "libmkl_gnu_thread.so",
    "libmkl_intel_thread.so",
    "libmkl_intel_lp64.so",
    "libmkl_sequential.so",
    "libmkl_tbb_thread.so",
    "libmkl_rt.so",
    "libiomp5.so",
    # MKL platform-specific dispatcher libraries.
    # liblapack.so.3 in conda is a symlink to libmkl_rt.so.2 (the SDL dispatcher).
    # At runtime libmkl_rt calls dlopen() to load these CPU-specific backends
    # by their unversioned names; they are not discovered by ldd so they must
    # be listed explicitly.
    "libmkl_avx2.so",
    "libmkl_avx2.so.2",
    "libmkl_avx512.so",
    "libmkl_avx512.so.2",
    "libmkl_def.so",
    "libmkl_def.so.2",
    # MKL Vector Math Library (VML) backends, dlopen'd separately from the
    # compute kernels above (e.g. by SevenNet/torch via vdExp, vdErf, ...).
    "libmkl_vml_avx2.so",
    "libmkl_vml_avx2.so.2",
    "libmkl_vml_avx512.so",
    "libmkl_vml_avx512.so.2",
    "libmkl_vml_def.so",
    "libmkl_vml_def.so.2",
)
CONDA_RUNTIME_LIBRARY_ALIASES = (
    # Torch in some conda environments links against the versioned MKL SONAMEs,
    # while the environment only ships the files under unversioned .so names.
    ("libmkl_core.so", "libmkl_core.so.2"),
    ("libmkl_gnu_thread.so", "libmkl_gnu_thread.so.2"),
    ("libmkl_intel_lp64.so", "libmkl_intel_lp64.so.2"),
    # MKL's dispatcher and CPU/VML backends can also be requested by versioned
    # name at runtime via dlopen(), so expose aliases for those as well.
    ("libmkl_rt.so", "libmkl_rt.so.2"),
    ("libmkl_avx2.so", "libmkl_avx2.so.2"),
    ("libmkl_avx512.so", "libmkl_avx512.so.2"),
    ("libmkl_def.so", "libmkl_def.so.2"),
    ("libmkl_vml_avx2.so", "libmkl_vml_avx2.so.2"),
    ("libmkl_vml_avx512.so", "libmkl_vml_avx512.so.2"),
    ("libmkl_vml_def.so", "libmkl_vml_def.so.2"),
)
DREAM3DNX_PYTHON_MODULES = (
    "simplnx",
    "orientationanalysis",
    "itkimageprocessing",
)
DREAM3DNX_RUNTIME_LIBRARIES = (
    "libEbsdLib.so",
    "libITKImageProcessing.simplnx",
    "libmcplotty.so",
    "libNXComponents.so",
    "libNxQtADS.so.0.0.0",
    "libNXVtkLib.so",
    "libOrientationAnalysis.simplnx",
    "libPLUSNative.so",
    "libqmcplotty.so",
    "libsimplnx.so",
    "libSimplnxCore.simplnx",
)
DREAM3DNX_SHARE_TREES = (
    "DREAM3DNX",
    "simplnx",
)
DREAM3DNX_EXECUTABLES = (
    "DREAM3DNX",
    "dream3dnx",
    "nxrunner",
)


def _existing_tree(path: str, dest: str):
    source = ROOT / path
    if source.is_dir():
        return [(str(source), dest)]
    return []


datas = []
binaries = []
hiddenimports = [
    "ase.io.cfg",
    "ase.io.cif",
    "ase.io.cif_unicode",
    "ase.io.extxyz",
    "ase.io.lammpsdata",
    "ase.io.lammpsrun",
    "ase.io.proteindatabank",
    "ase.io.vasp",
    "ase.io.xsf",
    "ase.io.xyz",
    "PySide6.QtCore",
    "PySide6.QtGui",
    "PySide6.QtWidgets",
    "itkimageprocessing",
    "matplotlib.backends.backend_qtagg",
    "numpy",
    "orientationanalysis",
    "ovito._extensions.particles",
    "ovito._extensions.pyscript",
    "ovito.gui._create_qwidget",
    "ovito.gui._create_window",
    "ovito.gui._utility_interface",
    "ovito.nonpublic._lammps_data_io",
    "ovito.plugins",
    "ovito.plugins.ovito_bindings",
    "scipy",
    "simplnx",
    "xtb",
    "xtb._libxtb",
    "xtb.ase",
    "xtb.ase.calculator",
    "xtb.interface",
    "xtb.libxtb",
    # SevenNet: imported dynamically via __import__() in SevenNet.py so PyInstaller
    # cannot discover the dependency statically.  Listing it here both pulls the
    # Python modules into the bundle and triggers hook-sevenn.py (pyz+py mode)
    # so TorchScript's inspect.getsource() can find the source files on disk.
    "sevenn",
    "sevenn.calculator",
    "sevenn.sevennet_calculator",
]

EXCLUDED_HIDDENIMPORT_PARTS = {
    "benchmark",
    "benchmarks",
    "conftest",
    "examples",
    "sphinxext",
    "test",
    "testing",
    "tests",
}

EXCLUDES = [
    "cupy",
    "dask",
    "dash",
    "matplotlib.tests",
    "numba",
    "numpy.tests",
    "open3d.examples",
    "open3d.ml",
    "pandas.tests",
    "plotly",
    "pytest",
    # sklearn is a required dependency of sevenn (scikit-learn is listed in
    # sevenn's package metadata).  Excluding it breaks SevenNet at runtime.
    # "sklearn",
    "tensorflow",
    "tkinter",
    "trame",
]

HEAVY_ML_EXCLUDES = [
    "nvidia",
    "tensorflow",
    "torch",
    "triton",
]

# User-facing files and optional generated documentation. Missing optional trees
# are ignored so the same spec works before and after docs generation.
datas += _existing_tree("docs_site/site", "docs_site/site")
datas += _existing_tree("docs", "docs")
datas += _existing_tree("examples", "examples")
datas += _existing_tree("src/multibest/gui/assets", "multibest/gui/assets")

image_to_mesh_blender_script = SRC / "multibest" / "image_to_mesh" / "Image_to_Mesh.py"
if image_to_mesh_blender_script.is_file():
    datas.append((str(image_to_mesh_blender_script), "image_to_mesh"))

mesh_refinement_blender_script = SRC / "multibest" / "mesh_modification" / "blender-refinement.py"
if mesh_refinement_blender_script.is_file():
    datas.append((str(mesh_refinement_blender_script), "."))

for file_name in ("README.md", "LICENSE", "CHANGELOG.md", "THIRD_PARTY_NOTICES.md"):
    file_path = ROOT / file_name
    if file_path.is_file():
        datas.append((str(file_path), "."))


def collect_package(package_name: str) -> None:
    """Best-effort collection for package data and native libraries."""
    global datas, binaries, hiddenimports

    try:
        package_datas = collect_data_files(package_name)
    except Exception:
        package_datas = []

    try:
        package_binaries = collect_dynamic_libs(package_name)
    except Exception:
        package_binaries = []

    datas += package_datas
    binaries += package_binaries


def collect_executable(executable_name: str, dest: str = ".") -> None:
    """Copy a command-line executable from the build environment when present."""
    executable_path = shutil.which(executable_name)
    if executable_path:
        binaries.append((executable_path, dest))


def collect_dream3dnx_runtime() -> None:
    """Collect DREAM3D-NX/SIMPLNX native runtime files from the active conda env."""
    global datas, binaries

    for module_name in DREAM3DNX_PYTHON_MODULES:
        try:
            module_spec = importlib.util.find_spec(module_name)
        except Exception:
            module_spec = None

        if module_spec and module_spec.origin:
            module_path = Path(module_spec.origin)
            if module_path.is_file():
                collect_linked_conda_libraries(module_path)

    conda_lib = Path(sys.prefix) / "lib"
    if conda_lib.is_dir():
        for library_name in DREAM3DNX_RUNTIME_LIBRARIES:
            library_path = conda_lib / library_name
            if library_path.is_file():
                binaries.append((str(library_path), "."))

    conda_share = Path(sys.prefix) / "share"
    for share_tree in DREAM3DNX_SHARE_TREES:
        share_path = conda_share / share_tree
        if share_path.is_dir():
            datas.append((str(share_path), f"share/{share_tree}"))

    for executable_name in DREAM3DNX_EXECUTABLES:
        collect_executable(executable_name, "bin")


def collect_xtb_parameter_files() -> None:
    """Copy xTB runtime parameter data, including the external GFN0-xTB file."""
    executable_path = shutil.which("xtb")
    candidates = [
        Path(sys.prefix) / "share" / "xtb",
        Path(sys.prefix) / "Library" / "share" / "xtb",
    ]
    if executable_path:
        executable_dir = Path(executable_path).resolve().parent
        candidates.extend([executable_dir / "share" / "xtb", executable_dir.parent / "share" / "xtb"])

    for candidate in dict.fromkeys(candidates):
        if (candidate / "param_gfn0-xtb.txt").is_file():
            datas.append((str(candidate), "share/xtb"))
            return


def _binary_dest_name(entry) -> str | None:
    """Return the bundle-relative name for PyInstaller binary tuple variants."""
    if len(entry) < 2:
        return None

    if len(entry) >= 3:
        return str(entry[0])

    source, dest = entry
    dest = str(dest)
    if dest in ("", "."):
        return Path(str(source)).name
    return str(Path(dest) / Path(str(source)).name)


def _without_root_binary_entries(entries, library_name: str):
    return [entry for entry in entries if _binary_dest_name(entry) != library_name]


def collect_conda_runtime_library(library_name: str) -> None:
    """Prefer conda runtime libraries over copies pulled from nested packages."""
    global binaries

    if sys.platform.startswith("win"):
        return

    library_path = Path(sys.prefix) / "lib" / library_name
    if library_path.is_file():
        binaries = _without_root_binary_entries(binaries, library_name)
        binaries.append((str(library_path), "."))


def prefer_conda_runtime_libraries(analysis: Analysis) -> None:
    """Keep root runtime libraries paired with the active conda environment."""
    if sys.platform.startswith("win"):
        return

    for library_name in CONDA_RUNTIME_LIBRARIES:
        library_path = Path(sys.prefix) / "lib" / library_name
        if not library_path.is_file():
            continue

        analysis.binaries = _without_root_binary_entries(analysis.binaries, library_name)
        analysis.datas = _without_root_binary_entries(analysis.datas, library_name)
        analysis.binaries.append((library_name, str(library_path), "BINARY"))

    for source_name, dest_name in CONDA_RUNTIME_LIBRARY_ALIASES:
        library_path = Path(sys.prefix) / "lib" / source_name
        if not library_path.is_file():
            continue

        analysis.binaries = _without_root_binary_entries(analysis.binaries, dest_name)
        analysis.datas = _without_root_binary_entries(analysis.datas, dest_name)
        analysis.binaries.append((dest_name, str(library_path), "BINARY"))


def collect_linked_conda_libraries(binary_path: Path) -> None:
    """Collect conda libraries linked by a native module."""
    global binaries

    if sys.platform.startswith("win"):
        return

    try:
        conda_prefix = Path(sys.prefix).resolve()
        result = subprocess.run(["ldd", str(binary_path)], capture_output=True, text=True, check=False)
    except Exception:
        return

    for line in result.stdout.splitlines():
        if "=>" not in line:
            continue
        path_text = line.split("=>", 1)[1].strip().split(maxsplit=1)[0]
        if not path_text.startswith("/"):
            continue

        linked_library = Path(path_text)
        try:
            resolved_library = linked_library.resolve()
            resolved_library.relative_to(conda_prefix)
        except (OSError, ValueError):
            continue

        if resolved_library.is_file():
            binaries.append((str(resolved_library), "."))


for package in (
    "ase",
    "cv2",
    "gmsh",
    "h5py",
    "matplotlib",
    "numpy",
    "open3d",
    "ovito",
    "pandas",
    "periodictable",
    "PIL",
    "pymeshfix",
    "pymeshlab",
    "pyvista",
    "pyvistaqt",
    "qtawesome",
    "rtree",
    "scipy",
    "skimage",
    "trimesh",
    "vtk",
):
    collect_package(package)

# Optional scientific backends. These may not be installed in all build
# environments, but when present they need their package metadata and data files.
for package in ("sevenn", "xtb", *DREAM3DNX_PYTHON_MODULES):
    collect_package(package)

collect_dream3dnx_runtime()
collect_executable("xtb", "bin")
collect_xtb_parameter_files()
for library in CONDA_RUNTIME_LIBRARIES:
    collect_conda_runtime_library(library)


def collect_ovito_plugins() -> None:
    """Collect OVITO's native plugin modules from wheel and conda layouts."""
    global datas, binaries

    extension_suffix = sysconfig.get_config_var("EXT_SUFFIX")
    extension_suffixes = tuple(
        suffix for suffix in (extension_suffix, ".so", ".pyd", ".dll", ".dylib", ".ovito.dll") if suffix
    )

    try:
        plugins_spec = importlib.util.find_spec("ovito.plugins")
    except Exception:
        plugins_spec = None

    if plugins_spec and plugins_spec.origin and Path(plugins_spec.origin).is_file():
        datas.append((plugins_spec.origin, "ovito/plugins"))

    search_dirs = set()
    if plugins_spec:
        search_dirs.update(Path(location) for location in (plugins_spec.submodule_search_locations or []) if location)

    try:
        bindings_spec = importlib.util.find_spec("ovito.plugins.ovito_bindings")
    except Exception:
        bindings_spec = None

    if bindings_spec and bindings_spec.origin:
        bindings_path = Path(bindings_spec.origin)
        if bindings_path.is_file():
            search_dirs.add(bindings_path.parent)
            collect_linked_conda_libraries(bindings_path)

    for plugin_dir in sorted(search_dirs):
        if not plugin_dir.is_dir():
            continue
        for plugin in plugin_dir.iterdir():
            if plugin.is_file() and plugin.name.endswith(extension_suffixes):
                binaries.append((str(plugin), "ovito/plugins"))


try:
    ovito_spec = importlib.util.find_spec("ovito")
    ovito_dirs = list(ovito_spec.submodule_search_locations or []) if ovito_spec else []
    if ovito_dirs:
        ovito_plugins = Path(ovito_dirs[0]) / "plugins"
        binaries += [(str(plugin), "ovito/plugins") for plugin in ovito_plugins.glob("*.so")]
except Exception:
    pass

collect_ovito_plugins()

hiddenimports = sorted(
    {module for module in hiddenimports if not EXCLUDED_HIDDENIMPORT_PARTS.intersection(module.split("."))}
)

try:
    datas += collect_data_files("qtawesome")
except Exception:
    pass


def make_analysis(
    script: str,
    extra_pathex: list[str] | None = None,
    extra_excludes: list[str] | None = None,
    runtime_hooks: list[str] | None = None,
) -> Analysis:
    script_path = ROOT / script
    script_dir = script_path.parent
    pathex = [str(SRC), str(script_dir)]
    if extra_pathex:
        pathex.extend(str(ROOT / path) for path in extra_pathex)

    analysis = Analysis(
        [str(script_path)],
        pathex=pathex,
        binaries=binaries,
        datas=datas,
        hiddenimports=hiddenimports,
        hookspath=[str(PYINSTALLER_HOOKS)],
        hooksconfig={},
        runtime_hooks=[str(QT_PLATFORM_RUNTIME_HOOK), str(RELEASE_PATHS_RUNTIME_HOOK), *(runtime_hooks or [])],
        excludes=sorted({*EXCLUDES, *(extra_excludes or [])}),
        noarchive=False,
        optimize=0,
    )
    prefer_conda_runtime_libraries(analysis)
    return analysis


def make_exe(
    name: str,
    script: str,
    *,
    console: bool,
    extra_pathex: list[str] | None = None,
    extra_excludes: list[str] | None = None,
    runtime_hooks: list[str] | None = None,
) -> tuple[EXE, Analysis]:
    analysis = make_analysis(
        script,
        extra_pathex=extra_pathex,
        extra_excludes=extra_excludes,
        runtime_hooks=runtime_hooks,
    )
    pyz = PYZ(analysis.pure)
    exe = EXE(
        pyz,
        analysis.scripts,
        [],
        exclude_binaries=True,
        name=name,
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=True,
        console=console,
        disable_windowed_traceback=False,
        argv_emulation=False,
        target_arch=None,
        codesign_identity=None,
        entitlements_file=None,
    )
    return exe, analysis


gui_exe, gui_analysis = make_exe(
    APP_NAME,
    "src/multibest/gui/main_ui.py",
    console=False,
    extra_pathex=[
        "src/multibest/gui",
        "src/multibest/ebsd_atomistic",
        "src/multibest/mesh_to_atomistic",
    ],
    extra_excludes=HEAVY_ML_EXCLUDES,
    runtime_hooks=[str(ROOT / "scripts" / "pyinstaller_hooks" / "rthook_ovito_gui.py")],
)

backend_specs = [
    ("input_convertor", "src/multibest/input_convertor/input_convertor.py", HEAVY_ML_EXCLUDES),
    ("micro_analysis", "src/multibest/atomistic_to_continuum/micro_analysis.py", HEAVY_ML_EXCLUDES),
    ("mesh_generation", "src/multibest/atomistic_to_continuum/mesh_generation.py", HEAVY_ML_EXCLUDES),
    ("euler_to_angle", "src/multibest/ebsd_atomistic/euler_to_angle.py", HEAVY_ML_EXCLUDES),
    ("stl_ebsd_rescale", "src/multibest/ebsd_atomistic/stl_ebsd_rescale.py", HEAVY_ML_EXCLUDES),
    ("ebsd_stl_fill_atoms", "src/multibest/ebsd_atomistic/ebsd_stl_fill_atoms.py", HEAVY_ML_EXCLUDES),
    ("replicate", "src/multibest/ebsd_atomistic/replicate.py", HEAVY_ML_EXCLUDES),
    ("EBSD_Atomistic", "src/multibest/ebsd_atomistic/EBSD_Atomistic.py", HEAVY_ML_EXCLUDES),
    ("EBSD_visualization", "src/multibest/ebsd_atomistic/EBSD_visualization.py", HEAVY_ML_EXCLUDES),
    ("gpt-mod-1", "src/multibest/mesh_to_atomistic/gpt-mod-1.py", HEAVY_ML_EXCLUDES),
    ("manipulate", "src/multibest/mesh_to_atomistic/manipulate.py", HEAVY_ML_EXCLUDES),
    ("Ovito_Delete_Robust", "src/multibest/mesh_to_atomistic/Ovito_Delete_Robust.py", HEAVY_ML_EXCLUDES),
    ("Mesh_Modification", "src/multibest/mesh_modification/Mesh_Modification.py", HEAVY_ML_EXCLUDES),
    ("clean_mesh", "src/multibest/mesh_modification/clean_mesh.py", HEAVY_ML_EXCLUDES),
    ("blender-refinement", "src/multibest/mesh_modification/blender-refinement.py", HEAVY_ML_EXCLUDES),
    ("rescale", "src/multibest/image_to_mesh/rescale.py", HEAVY_ML_EXCLUDES),
    ("GFN2-xTB", "src/multibest/relaxation/gfn2-xtb/GFN2-xTB.py", HEAVY_ML_EXCLUDES),
    ("SevenNet", "src/multibest/relaxation/sevennet/SevenNet.py", []),
]

backend_builds = [
    make_exe(name, script, console=True, extra_excludes=extra_excludes)
    for name, script, extra_excludes in backend_specs
]

collect_items = [
    gui_exe,
    gui_analysis.binaries,
    gui_analysis.datas,
]
for exe, analysis in backend_builds:
    collect_items.extend([exe, analysis.binaries, analysis.datas])

coll = COLLECT(
    *collect_items,
    strip=False,
    upx=True,
    upx_exclude=[],
    name=APP_NAME,
)

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
    # Several conda packages (pymeshlab/open3d/ovito) may contribute a
    # same-named libtbb.so.12 that lacks required symbols, so force the root
    # runtime to match the build environment.
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
# DREAM3D-NX is deliberately NOT collected. Its conda binaries are proprietary
# (BlueQuartz EULA) and the simplnx sources are AGPL-3.0/commercial, so they
# are not redistributable with this GPL bundle. The EBSD preparation scripts
# below are shipped as plain source and executed by an external DREAM3D-NX
# Python environment resolved at runtime (see multibest.utils.dream3d).
EBSD_SOURCE_DIR = SRC / "multibest" / "ebsd_atomistic"
EBSD_EXTERNAL_SOURCE_SCRIPTS = [
    (str(EBSD_SOURCE_DIR / "EBSD_Atomistic.py"), "ebsd_atomistic"),
    (str(EBSD_SOURCE_DIR / "EBSD_visualization.py"), "ebsd_atomistic"),
]


LFS_POINTER_MAGIC = b"version https://git-lfs.github.com/spec/v1"


def _assert_no_lfs_pointers(directory: Path) -> None:
    """Abort the build when Git LFS payloads have not been fetched.

    ``examples/`` is bundled as data. An unfetched LFS file is a ~130-byte text
    pointer, so without this check the bundle bundles placeholders in place of
    the sample datasets and every example workflow fails on the user's machine
    with a parse error. The build must not succeed quietly in that state.
    """
    pointers = sorted(
        path
        for path in directory.rglob("*")
        if path.is_file() and path.stat().st_size < 1024 and path.read_bytes().startswith(LFS_POINTER_MAGIC)
    )
    if not pointers:
        return

    listed = "\n  ".join(str(path.relative_to(ROOT)) for path in pointers[:10])
    more = "" if len(pointers) <= 10 else f"\n  ... and {len(pointers) - 10} more"
    raise SystemExit(
        f"release.spec: {len(pointers)} Git LFS pointer file(s) found instead of their payloads:\n"
        f"  {listed}{more}\n"
        "Run 'git lfs pull' before building the release bundle."
    )


def _assert_docs_site_is_complete(site: Path) -> None:
    """Abort the build when the GUI help site has not been rendered.

    Only the rendered ``*.html`` files are committed under ``docs_site/site``;
    mkdocs-material's ``assets/`` stylesheets, scripts and fonts are generated.
    Bundling the committed subset alone ships help pages that open unstyled in
    the GUI's help viewer, so a stale site must fail the build rather than
    reach users.
    """
    if not site.is_dir():
        return
    if (site / "assets").is_dir():
        return

    raise SystemExit(
        f"release.spec: {site.relative_to(ROOT)} has no 'assets/' directory, so the GUI help"
        "\npages would ship without their stylesheets and scripts.\n"
        "Run 'just docs' (or 'just docs conda') before building the release bundle."
    )


def _existing_tree(path: str, dest: str):
    source = ROOT / path
    if source.is_dir():
        return [(str(source), dest)]
    return []


datas = [*EBSD_EXTERNAL_SOURCE_SCRIPTS]
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
    "matplotlib.backends.backend_qtagg",
    "numpy",
    "ovito._extensions.particles",
    "ovito._extensions.pyscript",
    "ovito.gui._create_qwidget",
    "ovito.gui._create_window",
    "ovito.gui._utility_interface",
    "ovito.nonpublic._lammps_data_io",
    "ovito.plugins",
    "ovito.plugins.ovito_bindings",
    "scipy",
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
    # dash and plotly are NOT excluded: open3d/__init__.py imports
    # open3d.visualization unconditionally, whose __init__ imports draw_plotly,
    # whose module-level imports are plotly.graph_objects and dash. Excluding
    # either makes "import open3d" raise ModuleNotFoundError, which
    # clean_mesh.smooth_open3d swallows as "Open3D not available for smoothing"
    # while open3d's 217 MB still ships.
    # "dash",
    "matplotlib.tests",
    "numba",
    "numpy.tests",
    "open3d.examples",
    # open3d.ml is NOT excluded: open3d/__init__.py imports it unconditionally.
    # Only the web visualiser is dropped, which is the sole importer of IPython
    # (and through it jedi, ~32 MB).
    "open3d.web_visualizer",
    "IPython",
    "jedi",
    "parso",
    "pandas.tests",
    # "plotly",  — see the dash note above.
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
_assert_docs_site_is_complete(ROOT / "docs_site" / "site")
datas += _existing_tree("docs_site/site", "docs_site/site")
datas += _existing_tree("docs", "docs")
_assert_no_lfs_pointers(ROOT / "examples")
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


# Bundle-relative prefixes that must never be collected. Each is dead weight
# large enough to matter against GitHub's 2 GB release-asset cap.
COLLECTED_PATH_EXCLUDES = (
    # open3d's wheel ships a CUDA pybind (~766 MB) beside the CPU one. Its
    # __init__ probes for it and falls back to __DEVICE_API__ = "cpu" when it
    # is missing, so the CPU module alone is a working open3d.
    "open3d/cuda/",
    # open3d's viewer resources (~37 MB) and notebook extensions. MultiBEST uses
    # open3d only for TriangleMesh smoothing in clean_mesh.py, never its GUI.
    # NOTE: open3d/ml and open3d/_ml3d must stay — open3d/__init__.py imports
    # open3d.ml unconditionally, which imports open3d._ml3d.
    "open3d/resources/",
    "open3d/nbextension/",
    "open3d/labextension/",
    "open3d/examples/",
    # torch's C++ test fixtures (~83 MB). NOTE: torch/bin must stay — torch's
    # __init__ calls _manager_path(), which raises RuntimeError when
    # torch/bin/torch_shm_manager is missing, so dropping it kills SevenNet.
    "torch/test/",
)


def _is_excluded_collected_path(dest: str) -> bool:
    normalized = str(dest).replace("\\", "/")
    return any(normalized.startswith(prefix) or f"/{prefix}" in normalized for prefix in COLLECTED_PATH_EXCLUDES)


def drop_excluded_collected_paths(analysis: Analysis) -> None:
    """Remove COLLECTED_PATH_EXCLUDES entries from a finished analysis.

    Applied to the analysis rather than to ``collect_package`` because most of
    these arrive through PyInstaller's own package hooks, which run during
    ``Analysis`` and never pass through this spec's collection helpers.
    """
    analysis.datas = [entry for entry in analysis.datas if not _is_excluded_collected_path(entry[0])]
    analysis.binaries = [entry for entry in analysis.binaries if not _is_excluded_collected_path(entry[0])]


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
for package in ("sevenn", "xtb"):
    collect_package(package)

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
    drop_excluded_collected_paths(analysis)
    return analysis


# NOTE: strip is deliberately left off. Stripping saves ~450 MB but corrupts
# scipy's vendored libscipy_openblas ("ELF load command address/offset not
# page-aligned"), which kills every backend that imports scipy. PyInstaller's
# strip flag is all-or-nothing, so the size has to come from elsewhere.
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

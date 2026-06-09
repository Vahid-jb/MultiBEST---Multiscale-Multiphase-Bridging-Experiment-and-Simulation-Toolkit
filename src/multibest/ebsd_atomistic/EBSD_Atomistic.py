# SPDX-FileCopyrightText: 2026 bright-ideas-clan
#
# SPDX-License-Identifier: GPL-3.0-or-later

import argparse
import os
import sys
from pathlib import Path

try:
    import orientationanalysis as nxor
    import simplnx as nx
except ImportError as exc:
    missing_name = getattr(exc, "name", "simplnx/orientationanalysis")
    print(
        "Error: DREAM3D-NX/SIMPLNX is required for EBSD preparation.\n"
        "Please install DREAM3D-NX and make sure the Python modules "
        "'simplnx' and 'orientationanalysis' are available in this Python environment.\n"
        f"Missing module: {missing_name}",
        file=sys.stderr,
    )
    sys.exit(1)


# Force UTF-8 encoding for standard output and error
if sys.platform == "win32":
    for stream in (sys.stdout, sys.stderr):
        if stream is not None and hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

# =============================================================================
# Repeated string constants — avoid duplicating literals across the file.
# =============================================================================
IMPORTED_DATA = "ImportedData"
IMAGE_GEOMETRY = "Image Geometry"
CELL_DATA = "Cell Data"
CELL_ENSEMBLE_DATA = "Cell Ensemble Data"
CELL_FEATURE_DATA = "Cell Feature Data"
IMAGE_QUALITY = "Image Quality"
CONFIDENCE_INDEX = "Confidence Index"
SEM_SIGNAL = "SEM Signal"
MISORIENTATION_TOL_PROMPT = "  Misorientation tolerance (default 5.0): "


def _detect_format_from_original_file(f, first_group):
    """Look at OriginalFile in the H5 header; return 'ctf', 'ang', or None."""
    try:
        orig_file_bytes = f[f"{first_group}/Header/OriginalFile"][()]
        orig_file = orig_file_bytes.decode() if hasattr(orig_file_bytes, "decode") else str(orig_file_bytes)
        if orig_file.endswith(".ctf"):
            return "ctf"
        if orig_file.endswith(".ang"):
            return "ang"
    except Exception:
        return None
    return None


def _detect_format_from_arrays(f, first_group):
    """Inspect the Data group's arrays to guess the format."""
    try:
        available_arrays = list(f[f"{first_group}/Data"].keys())
    except Exception:
        return None
    if "BC" in available_arrays and "MAD" in available_arrays:
        return "ctf"
    if CONFIDENCE_INDEX in available_arrays and IMAGE_QUALITY in available_arrays:
        return "ang"
    return None


def _detect_format_from_file_bytes(h5ebsd_file_path):
    """Fallback detector for packaged environments where h5py cannot import."""
    try:
        content = Path(h5ebsd_file_path).read_bytes()
    except Exception:
        return None

    lower_content = content.lower()
    if b".ctf" in lower_content:
        return "ctf"
    if b".ang" in lower_content:
        return "ang"

    has_ctf_arrays = all(name in content for name in (b"BC", b"MAD"))
    has_ang_arrays = all(name in content for name in (b"Confidence Index", b"Image Quality"))
    if has_ang_arrays and not has_ctf_arrays:
        return "ang"
    if has_ctf_arrays and not has_ang_arrays:
        return "ctf"
    return None


def detect_h5ebsd_format(h5ebsd_file_path):
    """Detect CTF or ANG format by directly reading the H5EBSD file structure"""
    try:
        import h5py

        with h5py.File(h5ebsd_file_path, "r") as f:
            groups = [k for k in f.keys() if k.isdigit()]
            if not groups:
                return "unknown"

            first_group = min(groups, key=int)
            fmt = _detect_format_from_original_file(f, first_group)
            if fmt:
                return fmt
            fmt = _detect_format_from_arrays(f, first_group)
            if fmt:
                return fmt
    except Exception as e:
        print(f"Warning: Could not detect format: {e}")
        fmt = _detect_format_from_file_bytes(h5ebsd_file_path)
        if fmt:
            print("Detected format by scanning H5EBSD file contents.")
            return fmt

    return "unknown"


# =============================================================================


def _print_item(index, item):
    try:
        print(f"  [{index}] {item}")
    except UnicodeDecodeError:
        print(f"  [{index}] {repr(item)}")
    except Exception:
        print(f"  [{index}] (unprintable item) {repr(item)}")


def _safe_print(obj, label=""):
    if obj is None:
        return
    try:
        if isinstance(obj, (bytes, bytearray)):
            print(label, obj.decode("utf-8", errors="replace"))
        elif isinstance(obj, (list, tuple)):
            print(label)
            for i, item in enumerate(obj, 1):
                _print_item(i, item)
        else:
            try:
                print(label, obj)
            except UnicodeDecodeError:
                print(label, repr(obj))
    except Exception:
        try:
            print(label, repr(obj))
        except Exception:
            print(label, "<unprintable>")


def check_pipeline_result(result) -> None:
    """
    Robustly handle and report pipeline execution results returned by simplnx.
    This prints type information and safely prints errors/warnings without
    raising UnicodeDecodeError or crashing if the objects contain non-UTF8 bytes.
    """
    try:
        print(f"Pipeline execute returned object of type: {type(result)}")
    except Exception:
        # Informational header only — swallow any print failure so we still report
        # the errors/warnings collected below.
        pass

    inner = getattr(result, "result", None)
    res = inner if inner is not None else result

    _safe_print(getattr(res, "errors", None), "Errors:")
    _safe_print(getattr(res, "warnings", None), "Warnings:")


# -----------------------------------------------------------------------------
# Optional non-interactive "input.txt" support.
# Run:
#   python EBSD_Atomistic.py input.txt
# Or print a template:
#   python EBSD_Atomistic.py --print_template
# -----------------------------------------------------------------------------


def _load_cli_config(config_path: str) -> dict:
    """Load simple key-value config file.
    Format:
      key value...
    Lines starting with # are ignored.
    Keys are case-insensitive.
    """
    cfg = {}
    if not config_path:
        return cfg
    p = Path(config_path)
    if not p.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")
    for raw in p.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split(None, 1)
        key = parts[0].strip().lower()
        val = parts[1].strip() if len(parts) > 1 else ""
        cfg[key] = val
    return cfg


def _ask(cfg: dict, key: str, prompt: str, default=None, cast=str):
    """Get a value from cfg (non-interactive) or via input() (interactive)."""
    key_l = key.lower()
    if cfg is not None and key_l in cfg:
        raw = cfg[key_l]
        if raw == "" and default is not None:
            raw = str(default)
    elif _NON_INTERACTIVE_CONFIG:
        raw = "" if default is None else str(default)
    else:
        raw = input(prompt).strip()
        if raw == "" and default is not None:
            raw = str(default)
    try:
        return cast(raw)
    except Exception:
        if default is None:
            raise
        return cast(default)


_TEMPLATE_INPUT_TXT = """# EBSD_Atomistic.py input file (key value per line)
# Choose ONE of the two modes below:
#
# MODE A (use existing H5EBSD):
# has_h5ebsd yes
# h5ebsd_file your_file.h5ebsd
# data_format ctf            # or ang
# start_slice 1
# end_slice 117
#
# MODE B (convert a stack of .ang/.ctf files to H5EBSD first):
# has_h5ebsd no
# input_dir /path/to/ebsd_slices
# file_prefix Slice_
# start_index 1
# end_index 117
# padding_digits 1
# file_extension .ang        # or .ctf
# file_suffix
# increment_index 1
# z_spacing 0.25
#
# reference_frame_index options:
#   0 = EDAX (.ang)
#   1 = Oxford (.ctf)
#   2 = No/Unknown Transformation
#   3 = HEDM-IceNine
# reference_frame_index 0
#
# stacking_order_index options:
#   0 = LowToHigh (lowest index is Z=0)
#   1 = HighToLow (highest index is Z=0)
# stacking_order_index 1
#
# output_h5ebsd_file output.h5ebsd
#
# Common outputs (both modes):
# output_dream3d output.dream3d
# stl_output_dir .              # default current directory
# grain_data_file grain_data.csv
"""

# Parse CLI args (minimal; keeps original interactive behavior if no config file is provided)
_parser = argparse.ArgumentParser(add_help=True)
_parser.add_argument("input_txt", nargs="?", help="Optional config file for non-interactive execution")
_parser.add_argument("--print_template", action="store_true", help="Print an example input.txt and exit")
_args = _parser.parse_args()
_CFG = _load_cli_config(_args.input_txt) if _args.input_txt else {}
_NON_INTERACTIVE_CONFIG = bool(_args.input_txt)

if _args.print_template:
    print(_TEMPLATE_INPUT_TXT)
    sys.exit(0)
# Interactive input for data type
has_h5ebsd = (
    _ask(_CFG, "has_h5ebsd", "Do you have an existing H5EBSD file? (yes/no): ", default="no", cast=str).strip().lower()
)

current_dir = Path.cwd()

if has_h5ebsd == "yes":
    h5ebsd_file = _ask(
        _CFG, "h5ebsd_file", "Enter the name of the H5EBSD file in the current directory: ", default="", cast=str
    ).strip()
    requested_data_format = (
        _ask(_CFG, "data_format", "Enter H5EBSD data format (ctf/ang, leave blank to detect): ", default="", cast=str)
        .strip()
        .lower()
    )
    if requested_data_format not in ("ctf", "ang"):
        requested_data_format = ""
else:
    requested_data_format = ""
    input_dir = _ask(
        _CFG, "input_dir", "Enter the directory path for the input ebsd files:", default="", cast=str
    ).strip()
    file_prefix = (
        _ask(_CFG, "file_prefix", "Enter file prefix (default Slice_): ", default="Slice_", cast=str).strip()
        or "Slice_"
    )
    start_index = _ask(_CFG, "start_index", "Enter start index (default 1): ", default=1, cast=int)
    end_index = _ask(_CFG, "end_index", "Enter end index (default 117): ", default=117, cast=int)
    padding_digits = _ask(_CFG, "padding_digits", "Enter padding digits (default 1): ", default=1, cast=int)
    file_extension = (
        _ask(_CFG, "file_extension", "Enter file extension (default .ang): ", default=".ang", cast=str).strip()
        or ".ang"
    )
    file_suffix = _ask(_CFG, "file_suffix", "Enter file suffix (default ): ", default="", cast=str).strip()
    increment_index = _ask(_CFG, "increment_index", "Enter increment index (default 1): ", default=1, cast=int)
    z_spacing = _ask(_CFG, "z_spacing", "Enter z spacing (default 0.25): ", default=0.25, cast=float)

    # Get reference frame option from user
    if not (_CFG and "reference_frame_index" in _CFG):
        print("\nSelect Reference Frame Option:")
        print("  0 = EDAX (.ang)")
        print("  1 = Oxford (.ctf)")
        print("  2 = No/Unknown Transformation")
        print("  3 = HEDM-IceNine")
    reference_frame_index = _ask(
        _CFG, "reference_frame_index", "Enter reference frame option (default 0): ", default=0, cast=int
    )

    # Get stacking order from user
    print("\nSelect Stacking Order:")
    print("  0 = Low to High (lowest index is Z=0)")
    print("  1 = High to Low (highest index is Z=0)")
    stacking_order_index = _ask(_CFG, "stacking_order_index", "Enter stacking order (default 1): ", default=1, cast=int)

    h5ebsd_file = _ask(
        _CFG, "output_h5ebsd_file", "Enter the name for the output .h5ebsd file: ", default="", cast=str
    ).strip()

    if not h5ebsd_file.endswith(".h5ebsd"):
        h5ebsd_file += ".h5ebsd"

    output_h5_path = current_dir / h5ebsd_file

    generated_value = nx.GeneratedFileListParameter.ValueType()
    generated_value.input_path = input_dir
    generated_value.ordering = (
        nx.GeneratedFileListParameter.Ordering.LowToHigh
        if stacking_order_index == 0
        else nx.GeneratedFileListParameter.Ordering.HighToLow
    )
    generated_value.file_prefix = file_prefix
    generated_value.file_suffix = file_suffix
    generated_value.file_extension = file_extension
    generated_value.start_index = start_index
    generated_value.end_index = end_index
    generated_value.increment_index = increment_index
    generated_value.padding_digits = padding_digits

    # --- Validate that the input ANG/CTF files actually exist before calling simplnx ---
    # Build the expected filenames from the generated_value parameters and check for missing files.
    expected_files = []
    # Use the same ordering as the converter would (LowToHigh means start_index..end_index)
    step = generated_value.increment_index or 1
    idxs = list(range(generated_value.start_index, generated_value.end_index + 1, step))
    # If HighToLow ordering requested, reverse the list (this does not affect existence check)
    if generated_value.ordering == nx.GeneratedFileListParameter.Ordering.HighToLow:
        idxs = list(reversed(idxs))
    for idx in idxs:
        # zero-pad according to padding_digits
        idx_str = str(idx).zfill(generated_value.padding_digits)
        fname = f"{generated_value.file_prefix}{idx_str}{generated_value.file_suffix}{generated_value.file_extension}"
        expected_files.append(os.path.join(generated_value.input_path, fname))

    missing = [p for p in expected_files if not os.path.exists(p)]
    if missing:
        print("Error: The following input files are missing (conversion cannot proceed):")
        for m in missing:
            print("  -", m)
        print("\nMake sure your `input_dir`, `file_prefix`, `padding_digits`, and indices are correct.")
        sys.exit(1)
    # --- End validation ---

    data_structure_conv = nx.DataStructure()
    result_conv = nxor.EbsdToH5EbsdFilter.execute(
        data_structure=data_structure_conv,
        input_file_list_object=generated_value,
        output_file_path=str(output_h5_path),
        reference_frame_index=reference_frame_index,  # Now set based on user input
        stacking_order_index=stacking_order_index,  # Now set based on user input
        z_spacing=z_spacing,
    )
    check_pipeline_result(result_conv)

# Now proceed with the main pipeline
output_dream3d = _ask(
    _CFG, "output_dream3d", "Enter the name for the output .dream3d file: ", default="", cast=str
).strip()
if not output_dream3d.endswith(".dream3d"):
    output_dream3d += ".dream3d"

input_file_path = current_dir / h5ebsd_file
output_file_path = current_dir / output_dream3d

if not input_file_path.exists():
    print(f"Error: Input file {input_file_path} does not exist.")
    sys.exit(1)

# Create the data structure
data_structure = nx.DataStructure()

# Create an empty pipeline
pipeline = nx.Pipeline()

# Filter 0: ReadH5EbsdFilter
h5ebsd_parameter = nxor.ReadH5EbsdFileParameter.ValueType()
h5ebsd_parameter.euler_representation = 0

# Use the actual slice information from the conversion
if has_h5ebsd == "yes":
    # If user has existing H5EBSD, ask for slice range
    start_slice = _ask(_CFG, "start_slice", "Enter start slice (default 1): ", default=1, cast=int)
    end_slice = _ask(_CFG, "end_slice", "Enter end slice (default 117): ", default=117, cast=int)
else:
    # Use the same slice range that was used for conversion
    start_slice = start_index
    end_slice = end_index

h5ebsd_parameter.start_slice = start_slice
h5ebsd_parameter.end_slice = end_slice

# For existing H5EBSD files, detect format using H5EBSD.py
# For new conversions, we know the format based on reference_frame_index
if has_h5ebsd == "yes":
    print("Detecting H5EBSD file format using H5EBSD.py...")
    detected_data_format = detect_h5ebsd_format(input_file_path)
    print(f"Detected format: {detected_data_format.upper()}")
    if detected_data_format in ("ctf", "ang"):
        data_format = detected_data_format
        if requested_data_format and requested_data_format != detected_data_format:
            print(
                "Warning: Selected H5EBSD format "
                f"{requested_data_format.upper()} does not match detected format "
                f"{detected_data_format.upper()}; using detected format."
            )
    elif requested_data_format:
        data_format = requested_data_format
        print(f"Using selected H5EBSD format: {data_format.upper()}")
    else:
        data_format = detected_data_format

    # Set arrays based on detected format
    if data_format == "ctf":
        h5ebsd_parameter.selected_array_names = ["BC", "BS", "Bands", "Error", "EulerAngles", "MAD", "Phases", "X", "Y"]
    elif data_format == "ang":
        h5ebsd_parameter.selected_array_names = [
            CONFIDENCE_INDEX,
            "EulerAngles",
            "Fit",
            IMAGE_QUALITY,
            "Phases",
            SEM_SIGNAL,
            "X Position",
            "Y Position",
        ]
    else:
        # Fallback: include both formats
        h5ebsd_parameter.selected_array_names = [
            "EulerAngles",
            "Phases",
            "X",
            "Y",  # Common to both
            CONFIDENCE_INDEX,
            IMAGE_QUALITY,
            "Fit",
            SEM_SIGNAL,  # ANG arrays
            "BC",
            "BS",
            "Bands",
            "Error",
            "MAD",  # CTF arrays
        ]
else:
    # For new conversions, we know the format
    if reference_frame_index == 1:  # Oxford/CTF format
        data_format = "ctf"
        h5ebsd_parameter.selected_array_names = ["BC", "BS", "Bands", "Error", "EulerAngles", "MAD", "Phases", "X", "Y"]
    else:  # EDAX/ANG format
        data_format = "ang"
        h5ebsd_parameter.selected_array_names = [
            CONFIDENCE_INDEX,
            "EulerAngles",
            "Fit",
            IMAGE_QUALITY,
            "Phases",
            SEM_SIGNAL,
            "X Position",
            "Y Position",
        ]

print(f"Data format: {data_format.upper() if data_format != 'unknown' else 'To be detected after reading'}")

# =============================================================================
# CUSTOMIZABLE PARAMETERS SECTION
# =============================================================================
print("\n=== Customizable Pipeline Parameters ===")

# Filter 1: MultiThresholdObjectsFilter parameters
if data_format == "ang":
    print("\n[Filter 1] MultiThresholdObjectsFilter (ANG format)")
    image_quality_thresh = _ask(
        _CFG, "image_quality_threshold", "  Image Quality threshold (default 120.0): ", default=120.0, cast=float
    )
    confidence_index_thresh = _ask(
        _CFG, "confidence_index_threshold", "  Confidence Index threshold (default 0.1): ", default=0.1, cast=float
    )
else:  # CTF format
    print("\n[Filter 1] MultiThresholdObjectsFilter (CTF format)")
    bc_thresh = _ask(
        _CFG, "band_contrast_threshold", "  Band Contrast (BC) threshold (default 50.0): ", default=50.0, cast=float
    )
    mad_thresh = _ask(
        _CFG, "mad_threshold", "  Mean Angular Deviation (MAD) threshold (default 1.0): ", default=1.0, cast=float
    )

# Filter 3: AlignSectionsMisorientationFilter
print("\n[Filter 3] AlignSectionsMisorientationFilter")
align_misorientation_tol = _ask(
    _CFG, "align_misorientation_tolerance", MISORIENTATION_TOL_PROMPT, default=5.0, cast=float
)

# Filter 6: BadDataNeighborOrientationCheckFilter
print("\n[Filter 6] BadDataNeighborOrientationCheckFilter")
bad_data_misorientation_tol = _ask(
    _CFG, "bad_data_misorientation_tolerance", MISORIENTATION_TOL_PROMPT, default=5.0, cast=float
)
bad_data_num_neighbors = _ask(
    _CFG, "bad_data_number_of_neighbors", "  Number of neighbors (default 4): ", default=4, cast=int
)

# Filter 7: NeighborOrientationCorrelationFilter
print("\n[Filter 7] NeighborOrientationCorrelationFilter")
neighbor_corr_min_confidence = _ask(
    _CFG,
    "neighbor_correlation_min_confidence",
    "  Minimum confidence (default 0.2): ",
    default=0.20000000298023224,
    cast=float,
)
neighbor_corr_level = _ask(_CFG, "neighbor_correlation_level", "  Correlation level (default 2): ", default=2, cast=int)
neighbor_corr_misorientation_tol = _ask(
    _CFG,
    "neighbor_correlation_misorientation_tolerance",
    MISORIENTATION_TOL_PROMPT,
    default=5.0,
    cast=float,
)

# Filter 8: EBSDSegmentFeaturesFilter
print("\n[Filter 8] EBSDSegmentFeaturesFilter")
segment_misorientation_tol = _ask(
    _CFG, "segment_misorientation_tolerance", MISORIENTATION_TOL_PROMPT, default=5.0, cast=float
)

# Filter 12: MergeTwinsFilter
print("\n[Filter 12] MergeTwinsFilter")
merge_twins_angle_tol = _ask(
    _CFG, "merge_twins_angle_tolerance", "  Angle tolerance (default 2.0): ", default=2.0, cast=float
)
merge_twins_axis_tol = _ask(
    _CFG, "merge_twins_axis_tolerance", "  Axis tolerance (default 3.0): ", default=3.0, cast=float
)

# Filter 14: RequireMinimumSizeFeaturesFilter
print("\n[Filter 14] RequireMinimumSizeFeaturesFilter")
min_feature_size = _ask(
    _CFG, "min_allowed_features_size", "  Minimum allowed features size (default 16): ", default=16, cast=int
)
min_feature_phase = _ask(_CFG, "min_feature_phase_number", "  Phase number (default 0): ", default=0, cast=int)

# Filter 17: RequireMinNumNeighborsFilter
print("\n[Filter 17] RequireMinNumNeighborsFilter")
min_num_neighbors = _ask(_CFG, "min_num_neighbors", "  Minimum number of neighbors (default 2): ", default=2, cast=int)
min_neighbors_phase = _ask(_CFG, "min_num_neighbors_phase", "  Phase number (default 0): ", default=0, cast=int)

# Filter 19: FillBadDataFilter
print("\n[Filter 19] FillBadDataFilter")
min_defect_size = _ask(
    _CFG, "min_allowed_defect_size", "  Minimum allowed defect size (default 1000): ", default=1000, cast=int
)

# Filter 20/21: ErodeDilateBadDataFilter
print("\n[Filter 20/21] ErodeDilateBadDataFilter")
dilate_iterations = _ask(
    _CFG, "dilate_iterations", "  Number of dilation iterations (default 2): ", default=2, cast=int
)
erode_iterations = _ask(_CFG, "erode_iterations", "  Number of erosion iterations (default 2): ", default=2, cast=int)

# Filter 22: ComputeIPFColorsFilter
print("\n[Filter 22] ComputeIPFColorsFilter")
print("  Enter reference direction (3 comma-separated values):")
ref_dir_str = _ask(_CFG, "reference_direction", "  Default: 0.0,0.0,1.0: ", default="0.0,0.0,1.0", cast=str)
reference_dir = [float(x.strip()) for x in ref_dir_str.split(",")]

# Filter 24: SurfaceNetsFilter
print("\n[Filter 24] SurfaceNetsFilter")
smoothing_iters = _ask(_CFG, "smoothing_iterations", "  Smoothing iterations (default 25): ", default=25, cast=int)

print("\n=== End of Customizable Parameters ===\n")


#####################################################################################################################

h5ebsd_parameter.input_file_path = str(input_file_path)
h5ebsd_parameter.use_recommended_transform = True

read_h5_ebsd_args = {
    "cell_attribute_matrix_name": CELL_DATA,
    "cell_ensemble_attribute_matrix_name": CELL_ENSEMBLE_DATA,
    # Create the Image Geometry INSIDE the ImportedData container
    "output_image_geometry_path": nx.DataPath(["ImportedData", IMAGE_GEOMETRY]),
    "read_h5_ebsd_object": h5ebsd_parameter,
}
pipeline.append(nxor.ReadH5EbsdFilter(), read_h5_ebsd_args)


####################################################################################################################
#  Filter 1: MultiThresholdObjectsFilter - Use detected format
threshold_set = nx.ArrayThresholdSet()

if data_format == "ang":
    threshold_1 = nx.ArrayThreshold()
    threshold_1.array_path = nx.DataPath(["ImportedData", IMAGE_GEOMETRY, CELL_DATA, IMAGE_QUALITY])
    threshold_1.comparison = nx.ArrayThreshold.ComparisonType.GreaterThan
    threshold_1.value = image_quality_thresh  # Changed from 120.0

    threshold_2 = nx.ArrayThreshold()
    threshold_2.array_path = nx.DataPath(["ImportedData", IMAGE_GEOMETRY, CELL_DATA, CONFIDENCE_INDEX])
    threshold_2.comparison = nx.ArrayThreshold.ComparisonType.GreaterThan
    threshold_2.value = confidence_index_thresh  # Changed from 0.1

    threshold_set.thresholds = [threshold_1, threshold_2]
    print(f"Using ANG format thresholds: Image Quality > {image_quality_thresh}")
    print(f"Using ANG format thresholds: Confidence Index > {confidence_index_thresh}")

else:  # CTF format or unknown (default to CTF)
    threshold_1 = nx.ArrayThreshold()
    threshold_1.array_path = nx.DataPath(["ImportedData", IMAGE_GEOMETRY, CELL_DATA, "BC"])
    threshold_1.comparison = nx.ArrayThreshold.ComparisonType.GreaterThan
    threshold_1.value = bc_thresh  # Changed from 50.0

    threshold_2 = nx.ArrayThreshold()
    threshold_2.array_path = nx.DataPath(["ImportedData", IMAGE_GEOMETRY, CELL_DATA, "MAD"])
    threshold_2.comparison = nx.ArrayThreshold.ComparisonType.LessThan
    threshold_2.value = mad_thresh  # Changed from 1.0

    threshold_set.thresholds = [threshold_1, threshold_2]
    print(f"Using CTF format thresholds: Band Contrast (BC) > {bc_thresh}, Mean Angular Deviation (MAD) < {mad_thresh}")

#################################################################################################################

multi_threshold_objects_args = {
    "array_thresholds_object": threshold_set,
    "created_mask_type": nx.DataType.boolean,
    "output_data_array_name": "Mask",
}
pipeline.append(nx.MultiThresholdObjectsFilter(), multi_threshold_objects_args)


# Filter 2: ConvertOrientationsFilter
convert_orientations_args = {
    "input_orientation_array_path": nx.DataPath(["ImportedData", IMAGE_GEOMETRY, CELL_DATA, "EulerAngles"]),
    "input_representation_index": 0,
    "output_orientation_array_name": "Quats",
    "output_representation_index": 2,
}
pipeline.append(nxor.ConvertOrientationsFilter(), convert_orientations_args)

# Filter 3: AlignSectionsMisorientationFilter
align_sections_misorientation_args = {
    "alignment_attribute_matrix_name": "Alignment Shifts Data",
    "cell_phases_array_path": nx.DataPath(["ImportedData", IMAGE_GEOMETRY, CELL_DATA, "Phases"]),
    "crystal_structures_array_path": nx.DataPath(
        ["ImportedData", IMAGE_GEOMETRY, CELL_ENSEMBLE_DATA, "CrystalStructures"]
    ),
    "cumulative_shifts_array_name": "Cumulative Shifts",
    "input_image_geometry_path": nx.DataPath(["ImportedData", IMAGE_GEOMETRY]),
    "mask_array_path": nx.DataPath(["ImportedData", IMAGE_GEOMETRY, CELL_DATA, "Mask"]),
    "misorientation_tolerance": align_misorientation_tol,  # Changed from 5.0
    "quats_array_path": nx.DataPath(["ImportedData", IMAGE_GEOMETRY, CELL_DATA, "Quats"]),
    "relative_shifts_array_name": "Relative Shifts",
    "slices_array_name": "Slice Indices",
    "store_alignment_shifts": False,
    "use_mask": True,
}
pipeline.append(nxor.AlignSectionsMisorientationFilter(), align_sections_misorientation_args)

# Filter 4: IdentifySampleFilter
identify_sample_args = {
    "fill_holes": False,
    "input_image_geometry_path": nx.DataPath(["ImportedData", IMAGE_GEOMETRY]),
    "mask_array_path": nx.DataPath(["ImportedData", IMAGE_GEOMETRY, CELL_DATA, "Mask"]),
    "slice_by_slice": False,
    "slice_by_slice_plane_index": 0,
}
pipeline.append(nx.IdentifySampleFilter(), identify_sample_args)

# Filter 5: AlignSectionsFeatureCentroidFilter
align_sections_feature_centroid_args = {
    "alignment_attribute_matrix_name": "Alignment Shifts Data",
    "centroids_array_name": "Centroids",
    "cumulative_shifts_array_name": "Cumulative Shifts",
    "input_image_geometry_path": nx.DataPath(["ImportedData", IMAGE_GEOMETRY]),
    "mask_array_path": nx.DataPath(["ImportedData", IMAGE_GEOMETRY, CELL_DATA, "Mask"]),
    "reference_slice": 0,
    "relative_shifts_array_name": "Relative Shifts",
    "slices_array_name": "Slice Indices",
    "store_alignment_shifts": False,
    "use_reference_slice": True,
}
pipeline.append(nx.AlignSectionsFeatureCentroidFilter(), align_sections_feature_centroid_args)

# Filter 6: BadDataNeighborOrientationCheckFilter
bad_data_neighbor_orientation_check_args = {
    "cell_phases_array_path": nx.DataPath(["ImportedData", IMAGE_GEOMETRY, CELL_DATA, "Phases"]),
    "crystal_structures_array_path": nx.DataPath(
        ["ImportedData", IMAGE_GEOMETRY, CELL_ENSEMBLE_DATA, "CrystalStructures"]
    ),
    "input_image_geometry_path": nx.DataPath(["ImportedData", IMAGE_GEOMETRY]),
    "mask_array_path": nx.DataPath(["ImportedData", IMAGE_GEOMETRY, CELL_DATA, "Mask"]),
    "misorientation_tolerance": bad_data_misorientation_tol,  # Changed from 5.0
    "number_of_neighbors": bad_data_num_neighbors,  # Changed from 4
    "quats_array_path": nx.DataPath(["ImportedData", IMAGE_GEOMETRY, CELL_DATA, "Quats"]),
}
pipeline.append(nxor.BadDataNeighborOrientationCheckFilter(), bad_data_neighbor_orientation_check_args)

# Filter 7: NeighborOrientationCorrelationFilter - Use detected format
if data_format == "ang":
    correlation_array_path = nx.DataPath(["ImportedData", IMAGE_GEOMETRY, CELL_DATA, CONFIDENCE_INDEX])
    print("Using Confidence Index for neighbor orientation correlation")
else:  # CTF format or unknown
    correlation_array_path = nx.DataPath(["ImportedData", IMAGE_GEOMETRY, CELL_DATA, "MAD"])
    print("Using MAD for neighbor orientation correlation")

neighbor_orientation_correlation_args = {
    "cell_phases_array_path": nx.DataPath(["ImportedData", IMAGE_GEOMETRY, CELL_DATA, "Phases"]),
    "correlation_array_path": correlation_array_path,
    "crystal_structures_array_path": nx.DataPath(
        ["ImportedData", IMAGE_GEOMETRY, CELL_ENSEMBLE_DATA, "CrystalStructures"]
    ),
    "ignored_data_array_paths": [],
    "input_image_geometry_path": nx.DataPath(["ImportedData", IMAGE_GEOMETRY]),
    "level": neighbor_corr_level,  # Changed from 2
    "min_confidence": neighbor_corr_min_confidence,  # Changed from 0.20000000298023224
    "misorientation_tolerance": neighbor_corr_misorientation_tol,  # Changed from 5.0
    "quats_array_path": nx.DataPath(["ImportedData", IMAGE_GEOMETRY, CELL_DATA, "Quats"]),
}
pipeline.append(nxor.NeighborOrientationCorrelationFilter(), neighbor_orientation_correlation_args)

# Filter 8: EBSDSegmentFeaturesFilter
ebsd_segment_features_args = {
    "active_array_name": "Active",
    "cell_feature_attribute_matrix_name": CELL_FEATURE_DATA,
    "cell_mask_array_path": nx.DataPath(["ImportedData", IMAGE_GEOMETRY, CELL_DATA, "Mask"]),
    "cell_phases_array_path": nx.DataPath(["ImportedData", IMAGE_GEOMETRY, CELL_DATA, "Phases"]),
    "cell_quats_array_path": nx.DataPath(["ImportedData", IMAGE_GEOMETRY, CELL_DATA, "Quats"]),
    "crystal_structures_array_path": nx.DataPath(
        ["ImportedData", IMAGE_GEOMETRY, CELL_ENSEMBLE_DATA, "CrystalStructures"]
    ),
    "feature_ids_array_name": "FeatureIds",
    "input_image_geometry_path": nx.DataPath(["ImportedData", IMAGE_GEOMETRY]),
    "is_periodic": True,
    "misorientation_tolerance": segment_misorientation_tol,  # Changed from 5.0
    "randomize_features": False,  # Very important
    "use_mask": True,
}
pipeline.append(nxor.EBSDSegmentFeaturesFilter(), ebsd_segment_features_args)

# Filter 9: ComputeFeaturePhasesFilter
compute_feature_phases_args = {
    "cell_features_attribute_matrix_path": nx.DataPath(["ImportedData", IMAGE_GEOMETRY, CELL_FEATURE_DATA]),
    "cell_phases_array_path": nx.DataPath(["ImportedData", IMAGE_GEOMETRY, CELL_DATA, "Phases"]),
    "feature_ids_path": nx.DataPath(["ImportedData", IMAGE_GEOMETRY, CELL_DATA, "FeatureIds"]),
    "feature_phases_array_name": "Phases",
}
pipeline.append(nx.ComputeFeaturePhasesFilter(), compute_feature_phases_args)

# Filter 10: ComputeAvgOrientationsFilter
compute_avg_orientations_args = {
    "avg_euler_angles_array_name": "AvgEulerAngles",
    "avg_quats_array_name": "AvgQuats",
    "cell_feature_attribute_matrix_path": nx.DataPath(["ImportedData", IMAGE_GEOMETRY, CELL_FEATURE_DATA]),
    "cell_feature_ids_array_path": nx.DataPath(["ImportedData", IMAGE_GEOMETRY, CELL_DATA, "FeatureIds"]),
    "cell_phases_array_path": nx.DataPath(["ImportedData", IMAGE_GEOMETRY, CELL_DATA, "Phases"]),
    "cell_quats_array_path": nx.DataPath(["ImportedData", IMAGE_GEOMETRY, CELL_DATA, "Quats"]),
    "crystal_structures_array_path": nx.DataPath(
        ["ImportedData", IMAGE_GEOMETRY, CELL_ENSEMBLE_DATA, "CrystalStructures"]
    ),
}
pipeline.append(nxor.ComputeAvgOrientationsFilter(), compute_avg_orientations_args)

# Filter 11: ComputeFeatureNeighborsFilter (first)
compute_feature_neighbors_1_args = {
    "boundary_cells_name": "BoundaryCells",
    "cell_feature_array_path": nx.DataPath(["ImportedData", IMAGE_GEOMETRY, CELL_FEATURE_DATA]),
    "feature_ids_path": nx.DataPath(["ImportedData", IMAGE_GEOMETRY, CELL_DATA, "FeatureIds"]),
    "input_image_geometry_path": nx.DataPath(["ImportedData", IMAGE_GEOMETRY]),
    "neighbor_list_name": "NeighborList2",
    "number_of_neighbors_name": "NumNeighbors2",
    "shared_surface_area_list_name": "SharedSurfaceAreaList2",
    "store_boundary_cells": False,
    "store_surface_features": False,
    "surface_features_name": "SurfaceFeatures",
}
pipeline.append(nx.ComputeFeatureNeighborsFilter(), compute_feature_neighbors_1_args)

# Filter 12: MergeTwinsFilter
merge_twins_args = {
    "active_array_name": "Active",
    "angle_tolerance": merge_twins_angle_tol,  # Changed from 2.0
    "avg_quats_array_path": nx.DataPath(["ImportedData", IMAGE_GEOMETRY, CELL_FEATURE_DATA, "AvgQuats"]),
    "axis_tolerance": merge_twins_axis_tol,  # Changed from 3.0
    "cell_parent_ids_array_name": "ParentIds",
    "contiguous_neighbor_list_array_path": nx.DataPath(
        ["ImportedData", IMAGE_GEOMETRY, CELL_FEATURE_DATA, "NeighborList2"]
    ),
    "created_feature_attribute_matrix_name": "NewGrain Data",
    "crystal_structures_array_path": nx.DataPath(
        ["ImportedData", IMAGE_GEOMETRY, CELL_ENSEMBLE_DATA, "CrystalStructures"]
    ),
    "feature_ids_path": nx.DataPath(["ImportedData", IMAGE_GEOMETRY, CELL_DATA, "FeatureIds"]),
    "feature_parent_ids_array_name": "ParentIds",
    "feature_phases_array_path": nx.DataPath(["ImportedData", IMAGE_GEOMETRY, CELL_FEATURE_DATA, "Phases"]),
    "seed_array_name": "MergeTwins SeedValue",
    "seed_value": 5489,
    "use_seed": False,
}
pipeline.append(nxor.MergeTwinsFilter(), merge_twins_args)

# Filter 13: ComputeFeatureSizesFilter
compute_feature_sizes_args = {
    "equivalent_diameters_name": "EquivalentDiameters",
    "feature_attribute_matrix_path": nx.DataPath(["ImportedData", IMAGE_GEOMETRY, CELL_FEATURE_DATA]),
    "feature_ids_path": nx.DataPath(["ImportedData", IMAGE_GEOMETRY, CELL_DATA, "FeatureIds"]),
    "input_image_geometry_path": nx.DataPath(["ImportedData", IMAGE_GEOMETRY]),
    "num_elements_name": "NumElements",
    "save_element_sizes": False,
    "volumes_name": "Volumes",
}
pipeline.append(nx.ComputeFeatureSizesFilter(), compute_feature_sizes_args)

# Filter 14: RequireMinimumSizeFeaturesFilter
require_minimum_size_features_args = {
    "apply_single_phase": False,
    "feature_ids_path": nx.DataPath(["ImportedData", IMAGE_GEOMETRY, CELL_DATA, "FeatureIds"]),
    "feature_phases_path": nx.DataPath(""),
    "input_image_geometry_path": nx.DataPath(["ImportedData", IMAGE_GEOMETRY]),
    "min_allowed_features_size": min_feature_size,  # Changed from 16
    "num_cells_path": nx.DataPath(["ImportedData", IMAGE_GEOMETRY, CELL_FEATURE_DATA, "NumElements"]),
    "phase_number": min_feature_phase,  # Changed from 0
}
pipeline.append(nx.RequireMinimumSizeFeaturesFilter(), require_minimum_size_features_args)

# Filter 15: DeleteDataFilter (first)
delete_data_1_args = {
    "removed_data_path": [nx.DataPath(["ImportedData", IMAGE_GEOMETRY, CELL_FEATURE_DATA, "NumNeighbors2"])]
}
pipeline.append(nx.DeleteDataFilter(), delete_data_1_args)

# Filter 16: ComputeFeatureNeighborsFilter (second)
compute_feature_neighbors_2_args = {
    "boundary_cells_name": "BoundaryCells",
    "cell_feature_array_path": nx.DataPath(["ImportedData", IMAGE_GEOMETRY, CELL_FEATURE_DATA]),
    "feature_ids_path": nx.DataPath(["ImportedData", IMAGE_GEOMETRY, CELL_DATA, "FeatureIds"]),
    "input_image_geometry_path": nx.DataPath(["ImportedData", IMAGE_GEOMETRY]),
    "neighbor_list_name": "NeighborList",
    "number_of_neighbors_name": "NumNeighbors",
    "shared_surface_area_list_name": "SharedSurfaceAreaList",
    "store_boundary_cells": False,
    "store_surface_features": False,
    "surface_features_name": "SurfaceFeatures",
}
pipeline.append(nx.ComputeFeatureNeighborsFilter(), compute_feature_neighbors_2_args)

# Filter 17: RequireMinNumNeighborsFilter
require_min_num_neighbors_args = {
    "apply_to_single_phase": False,
    "feature_ids_path": nx.DataPath(["ImportedData", IMAGE_GEOMETRY, CELL_DATA, "FeatureIds"]),
    "feature_phases_path": nx.DataPath(["ImportedData", IMAGE_GEOMETRY, CELL_FEATURE_DATA, "Phases"]),
    "ignored_voxel_arrays": [],
    "input_image_geometry_path": nx.DataPath(["ImportedData", IMAGE_GEOMETRY]),
    "min_num_neighbors": min_num_neighbors,  # Changed from 2
    "num_neighbors_path": nx.DataPath(["ImportedData", IMAGE_GEOMETRY, CELL_FEATURE_DATA, "NumNeighbors"]),
    "phase_number": min_neighbors_phase,  # Changed from 0
}
pipeline.append(nx.RequireMinNumNeighborsFilter(), require_min_num_neighbors_args)

# Filter 18: DeleteDataFilter (second)
delete_data_2_args = {
    "removed_data_path": [
        nx.DataPath(["ImportedData", IMAGE_GEOMETRY, CELL_FEATURE_DATA, "NumNeighbors"]),
        nx.DataPath(["ImportedData", IMAGE_GEOMETRY, CELL_FEATURE_DATA, "Active"]),
        nx.DataPath(["ImportedData", IMAGE_GEOMETRY, CELL_FEATURE_DATA, "AvgEulerAngles"]),
        # nx.DataPath(["ImportedData", IMAGE_GEOMETRY, CELL_FEATURE_DATA, "AvgQuats"]),
        nx.DataPath(["ImportedData", IMAGE_GEOMETRY, CELL_FEATURE_DATA, "EquivalentDiameters"]),
        nx.DataPath(["ImportedData", IMAGE_GEOMETRY, CELL_FEATURE_DATA, "NumElements"]),
        nx.DataPath(["ImportedData", IMAGE_GEOMETRY, CELL_FEATURE_DATA, "ParentIds"]),
        nx.DataPath(["ImportedData", IMAGE_GEOMETRY, CELL_FEATURE_DATA, "Phases"]),
        nx.DataPath(["ImportedData", IMAGE_GEOMETRY, CELL_FEATURE_DATA, "Volumes"]),
    ]
}
pipeline.append(nx.DeleteDataFilter(), delete_data_2_args)

# Filter 19: FillBadDataFilter
fill_bad_data_args = {
    "cell_phases_array_path": nx.DataPath(["ImportedData", IMAGE_GEOMETRY, CELL_DATA, "Phases"]),
    "feature_ids_path": nx.DataPath(["ImportedData", IMAGE_GEOMETRY, CELL_DATA, "FeatureIds"]),
    "ignored_data_array_paths": [],
    "input_image_geometry_path": nx.DataPath(["ImportedData", IMAGE_GEOMETRY]),
    "min_allowed_defect_size": min_defect_size,  # Changed from 1000
    "store_as_new_phase": False,
}
pipeline.append(nx.FillBadDataFilter(), fill_bad_data_args)

# Filter 20: ErodeDilateBadDataFilter (dilate)
erode_dilate_bad_data_1_args = {
    "feature_ids_path": nx.DataPath(["ImportedData", IMAGE_GEOMETRY, CELL_DATA, "FeatureIds"]),
    "ignored_data_array_paths": [],
    "input_image_geometry_path": nx.DataPath(["ImportedData", IMAGE_GEOMETRY]),
    "num_iterations": dilate_iterations,  # Changed from 2
    "operation_index": 0,  # Dilate
    "x_dir_on": True,
    "y_dir_on": True,
    "z_dir_on": True,
}
pipeline.append(nx.ErodeDilateBadDataFilter(), erode_dilate_bad_data_1_args)

# Filter 21: ErodeDilateBadDataFilter (erode)
erode_dilate_bad_data_2_args = {
    "feature_ids_path": nx.DataPath(["ImportedData", IMAGE_GEOMETRY, CELL_DATA, "FeatureIds"]),
    "ignored_data_array_paths": [],
    "input_image_geometry_path": nx.DataPath(["ImportedData", IMAGE_GEOMETRY]),
    "num_iterations": erode_iterations,  # Changed from 2
    "operation_index": 1,  # Erode
    "x_dir_on": True,
    "y_dir_on": True,
    "z_dir_on": True,
}
pipeline.append(nx.ErodeDilateBadDataFilter(), erode_dilate_bad_data_2_args)

# Filter 22: ComputeIPFColorsFilter
compute_ipf_colors_args = {
    "cell_euler_angles_array_path": nx.DataPath(["ImportedData", IMAGE_GEOMETRY, CELL_DATA, "EulerAngles"]),
    "cell_ipf_colors_array_name": "IPFColors",
    "cell_phases_array_path": nx.DataPath(["ImportedData", IMAGE_GEOMETRY, CELL_DATA, "Phases"]),
    "crystal_structures_array_path": nx.DataPath(
        ["ImportedData", IMAGE_GEOMETRY, CELL_ENSEMBLE_DATA, "CrystalStructures"]
    ),
    "mask_array_path": nx.DataPath(["ImportedData", IMAGE_GEOMETRY, CELL_DATA, "Mask"]),
    "reference_dir": reference_dir,  # Changed from [0.0, 0.0, 1.0]
    "use_mask": True,
}
pipeline.append(nxor.ComputeIPFColorsFilter(), compute_ipf_colors_args)

# Filter 24: SurfaceNetsFilter (extract surface mesh from image geometry)
surface_nets_args = {
    # ... (Input parameters remain correct)
    "input_grid_geometry_path": nx.DataPath(["ImportedData", IMAGE_GEOMETRY]),
    "feature_ids_path": nx.DataPath(["ImportedData", IMAGE_GEOMETRY, CELL_DATA, "FeatureIds"]),
    "output_triangle_geometry_path": nx.DataPath("TriangleDataContainer"),
    # 3. Output Attribute Matrix and Array Names (FIX: Using spaces as per documentation)
    "vertex_data_group_name": "Vertex Data",
    "face_data_group_name": "Face Data",
    "face_labels_array_name": "Face Labels",
    "node_types_array_name": "NodeTypes",
    # 4. Critical: Array transfer list (Confirmed correct syntax)
    "input_feature_data_array_paths": [nx.DataPath(["ImportedData", IMAGE_GEOMETRY, CELL_DATA, "FeatureIds"])],
    # 5. Smoothing parameters (Confirmed correct)
    "apply_smoothing": True,
    "smoothing_iterations": 25,
}
pipeline.append(nx.SurfaceNetsFilter(), surface_nets_args)


# Ask user for STL output directory
stl_output_dir = _ask(
    _CFG, "stl_output_dir", "Enter the directory to save STL files (default: current directory): ", default="", cast=str
).strip()
if not stl_output_dir:
    stl_output_dir = str(current_dir)
else:
    # Expand user (~), normalize, and resolve to an absolute path
    stl_output_dir = str(Path(stl_output_dir).expanduser().resolve())

#############################################################################visualization#########################

# Visualization option
ebsd_visualization = _ask(
    _CFG,
    "ebsd_visualization",
    "Generate EBSD visualization plots? (True/False, default False): ",
    default="False",
    cast=lambda x: str(x).lower() == "true",
)
generate_all_slices = _ask(
    _CFG,
    "generate_all_slices",
    "Generate visualizations for ALL slices? (True/False, default False): ",
    default="False",
    cast=lambda x: str(x).lower() == "true",
)
# Get visualization output directory if visualization is enabled
visualization_output_dir = stl_output_dir  # Default to STL directory
if ebsd_visualization:
    visualization_output_dir = _ask(
        _CFG,
        "visualization_output_dir",
        "Enter directory for visualization output (default: same as STL directory): ",
        default=stl_output_dir,
        cast=str,
    ).strip()
    if not visualization_output_dir:
        visualization_output_dir = stl_output_dir

###################################################################################################################

# Filter 25: WriteStlFileFilter (write the triangle geometry to STL file)
write_stl_args = {
    "output_stl_directory": stl_output_dir,
    "input_triangle_geometry_path": nx.DataPath("TriangleDataContainer"),
    "feature_ids_path": nx.DataPath("TriangleDataContainer/Face Data/Face Labels"),
}
pipeline.append(nx.WriteStlFileFilter(), write_stl_args)


# =============================================================================
# EXECUTE THE MAIN PIPELINE FIRST (filters 0-25)
# =============================================================================

print("\n=== Executing Main Pipeline (filters 0-25) ===")
result = pipeline.execute(data_structure)
check_pipeline_result(result)

if not result.valid():
    print("Pipeline execution failed!")
    sys.exit(1)

print("Main pipeline executed successfully!")

#############################################################################visualization#########################

# Run visualization if requested
if ebsd_visualization:
    try:
        from EBSD_visualization import visualize_and_measure

        visualize_and_measure(data_structure, data_format, visualization_output_dir, generate_all_slices)
    except ImportError as e:
        print(f"Warning: Could not import visualization module: {e}")
    except Exception as e:
        print(f"Warning: Visualization failed: {e}")

# -----------------------------------------------------------------------------
pipeline = nx.Pipeline()  # Reset pipeline so post-processing filters do NOT re-run the import/read filters

# Filter 27: WriteASCIIDataFilter (export grain statistics)
grain_data_file = _ask(
    _CFG,
    "grain_data_file",
    "Enter the name for the grain data CSV file (default: grain_data.csv): ",
    default="grain_data.csv",
    cast=str,
).strip()
if not grain_data_file:
    grain_data_file = "grain_data.csv"

# First, let's recompute the feature data that was deleted
# Filter 27A: ComputeFeaturePhasesFilter (recompute phases)
compute_feature_phases_args = {
    "cell_features_attribute_matrix_path": nx.DataPath(["ImportedData", IMAGE_GEOMETRY, CELL_FEATURE_DATA]),
    "cell_phases_array_path": nx.DataPath(["ImportedData", IMAGE_GEOMETRY, CELL_DATA, "Phases"]),
    "feature_ids_path": nx.DataPath(["ImportedData", IMAGE_GEOMETRY, CELL_DATA, "FeatureIds"]),
    "feature_phases_array_name": "Phases_Export",
}
pipeline.append(nx.ComputeFeaturePhasesFilter(), compute_feature_phases_args)

# Filter 27B: ComputeAvgOrientationsFilter (recompute orientations)
compute_avg_orientations_args = {
    "avg_euler_angles_array_name": "AvgEulerAngles_Export",
    "avg_quats_array_name": "AvgQuats_Export",
    "cell_feature_attribute_matrix_path": nx.DataPath(["ImportedData", IMAGE_GEOMETRY, CELL_FEATURE_DATA]),
    "cell_feature_ids_array_path": nx.DataPath(["ImportedData", IMAGE_GEOMETRY, CELL_DATA, "FeatureIds"]),
    "cell_phases_array_path": nx.DataPath(["ImportedData", IMAGE_GEOMETRY, CELL_DATA, "Phases"]),
    "cell_quats_array_path": nx.DataPath(["ImportedData", IMAGE_GEOMETRY, CELL_DATA, "Quats"]),
    "crystal_structures_array_path": nx.DataPath(
        ["ImportedData", IMAGE_GEOMETRY, CELL_ENSEMBLE_DATA, "CrystalStructures"]
    ),
}
pipeline.append(nxor.ComputeAvgOrientationsFilter(), compute_avg_orientations_args)

# Filter 27C: ComputeFeatureCentroidsFilter
compute_centroids_args = {
    "centroids_array_name": "Centroids_Export",
    "feature_attribute_matrix_path": nx.DataPath(["ImportedData", IMAGE_GEOMETRY, CELL_FEATURE_DATA]),
    "feature_ids_path": nx.DataPath(["ImportedData", IMAGE_GEOMETRY, CELL_DATA, "FeatureIds"]),
    "input_image_geometry_path": nx.DataPath(["ImportedData", IMAGE_GEOMETRY]),
}
pipeline.append(nx.ComputeFeatureCentroidsFilter(), compute_centroids_args)

# Filter 27D: ComputeFeatureSizesFilter (recompute after rescaling)
compute_feature_sizes_rescaled_args = {
    "equivalent_diameters_name": "EquivalentDiameters_Export",
    "feature_attribute_matrix_path": nx.DataPath(["ImportedData", IMAGE_GEOMETRY, CELL_FEATURE_DATA]),
    "feature_ids_path": nx.DataPath(["ImportedData", IMAGE_GEOMETRY, CELL_DATA, "FeatureIds"]),
    "input_image_geometry_path": nx.DataPath(["ImportedData", IMAGE_GEOMETRY]),
    "num_elements_name": "NumElements_Export",
    "save_element_sizes": False,
    "volumes_name": "Volumes_Export",
}
pipeline.append(nx.ComputeFeatureSizesFilter(), compute_feature_sizes_rescaled_args)

# Filter 27E: WriteASCIIDataFilter - Export grain data with correct parameter name
write_ascii_args = {
    "output_path": str(current_dir / grain_data_file),  # Using the exact parameter name from the error
    "write_index_array": True,  # This will include grain IDs
    "delimiter": ",",
    "include_headers": True,
    "input_data_array_paths": [
        nx.DataPath(["ImportedData", IMAGE_GEOMETRY, CELL_FEATURE_DATA, "Phases_Export"]),
        nx.DataPath(["ImportedData", IMAGE_GEOMETRY, CELL_FEATURE_DATA, "AvgEulerAngles_Export"]),
        nx.DataPath(["ImportedData", IMAGE_GEOMETRY, CELL_FEATURE_DATA, "EquivalentDiameters_Export"]),
        nx.DataPath(["ImportedData", IMAGE_GEOMETRY, CELL_FEATURE_DATA, "Volumes_Export"]),
        nx.DataPath(["ImportedData", IMAGE_GEOMETRY, CELL_FEATURE_DATA, "NumElements_Export"]),
        nx.DataPath(["ImportedData", IMAGE_GEOMETRY, CELL_FEATURE_DATA, "Centroids_Export"]),
    ],
}
pipeline.append(nx.WriteASCIIDataFilter(), write_ascii_args)

print(f"Grain data will be exported to: {grain_data_file}")

# Filter 28: WriteDREAM3DFilter
write_dream3d_args = {"export_file_path": str(output_file_path), "write_xdmf_file": True}
pipeline.append(nx.WriteDREAM3DFilter(), write_dream3d_args)

# ------------------------------------------------------------------------------------
# Execute the pipeline
result = pipeline.execute(data_structure)
check_pipeline_result(result)

print("\n=== Executing Complete Pipeline ===")

if result.valid():
    print("Pipeline executed successfully")
else:
    print("Pipeline execution failed")
    if hasattr(result, "errors") and result.errors:
        for error in result.errors:
            print(f"Error: {error}")

param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("setup", "run")]
    [string] $Action,

    [string] $EnvName = "mulstibest_msmph",

    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]] $CommandArgs
)

$ErrorActionPreference = "Stop"

function Find-CondaManager {
    foreach ($candidate in @("micromamba", "mamba", "conda")) {
        $cmd = Get-Command $candidate -ErrorAction SilentlyContinue
        if ($cmd) {
            return $cmd.Source
        }
    }

    foreach ($candidate in @(
        "$HOME\micromamba\Library\bin\micromamba.exe",
        "$HOME\micromamba\micromamba.exe",
        "$HOME\miniforge3\Scripts\mamba.exe",
        "$HOME\mambaforge\Scripts\mamba.exe",
        "$HOME\miniconda3\Scripts\conda.exe",
        "$HOME\anaconda3\Scripts\conda.exe",
        "$env:USERPROFILE\miniforge3\Scripts\mamba.exe",
        "$env:USERPROFILE\mambaforge\Scripts\mamba.exe",
        "$env:USERPROFILE\miniconda3\Scripts\conda.exe",
        "$env:USERPROFILE\anaconda3\Scripts\conda.exe"
    )) {
        if ($candidate -and (Test-Path -LiteralPath $candidate)) {
            return $candidate
        }
    }

    throw "No conda-compatible package manager found. Install micromamba, mamba, conda, or Miniconda first."
}

function Invoke-Checked {
    param(
        [Parameter(Mandatory = $true)]
        [string] $Program,

        [Parameter(ValueFromRemainingArguments = $true)]
        [string[]] $Arguments
    )

    & $Program @Arguments
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
}

$manager = Find-CondaManager

if ($Action -eq "run") {
    if (-not $CommandArgs -or $CommandArgs.Count -eq 0) {
        throw "No command was provided for conda run."
    }
    Invoke-Checked $manager run -n $EnvName @CommandArgs
    exit 0
}

$pipPackages = @(
    "ase>=3.28.0",
    "commitizen>=4.5.0",
    "gmsh>=4.13.0",
    "h5py>=3.10.0",
    "mkdocs>=1.6.1",
    "mkdocs-material>=9.7.6",
    "mkdocs-minify-plugin>=0.8.0",
    "opencv-python-headless>=4.8.0",
    "open3d>=0.18.0",
    "pandas>=2.0.0",
    "periodictable>=1.6.0",
    "pre-commit>=4.5.1",
    "pymeshfix>=0.17.0",
    "pymeshlab>=2023.12",
    "pysonar>=1.4.0.4676",
    "pytest>=9.0.2",
    "pytest-cov>=7.1.0",
    "pyvista>=0.43.0",
    "pyvistaqt>=0.11.0",
    "qtawesome>=1.3.0",
    "rtree>=1.4.1",
    "ruff>=0.9",
    "scikit-image>=0.22.0",
    "scipy>=1.11.0",
    "sevenn>=0.11.0",
    "tqdm>=4.66.0",
    "traits>=6.3",
    "trimesh>=4.0.0"
)

Write-Host "Using conda-compatible package manager: $manager"

# Probe whether the environment already exists. A missing env makes the manager
# exit non-zero, which must fall through to the create step below. Run the probe
# in a child scope where the terminating-error behaviour is relaxed
# ($ErrorActionPreference=Stop, and PowerShell 7.3+ treating native non-zero
# exits as terminating errors, would otherwise abort the script here) so that
# only $LASTEXITCODE decides.
& {
    $ErrorActionPreference = "SilentlyContinue"
    $PSNativeCommandUseErrorActionPreference = $false
    & $manager run -n $EnvName python --version *> $null
}
if ($LASTEXITCODE -ne 0) {
    Invoke-Checked $manager create -y -n $EnvName -c conda-forge python=3.12 pip just
}

Invoke-Checked $manager install -y -n $EnvName -c bluequartzsoftware -c conda-forge dream3dnx
Invoke-Checked $manager install -y -n $EnvName -c conda-forge xtb xtb-python
Invoke-Checked $manager install -y -n $EnvName -c conda-forge numpy pillow matplotlib vtk

Write-Host "Installing OVITO with pip on Windows to avoid conda TBB conflicts with DREAM3D-NX."
Invoke-Checked $manager run -n $EnvName python -m pip install --upgrade pip
Invoke-Checked $manager run -n $EnvName python -m pip install @pipPackages
Invoke-Checked $manager run -n $EnvName python -m pip install --no-deps "ovito>=3.14.1,<3.15"
Invoke-Checked $manager run -n $EnvName python -m pip install --no-deps -e .
Invoke-Checked $manager run -n $EnvName python -c "import cv2; import orientationanalysis; import ovito; import PySide6; import simplnx; print('conda environment import check OK')"

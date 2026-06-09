# List available commands
set windows-shell := ["powershell.exe", "-NoLogo", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command"]
#export UV_CACHE_DIR := ".uv-cache"

default:
    @just --list

conda-env := "mulstibest_msmph"
export UV_CACHE_DIR := env_var_or_default("UV_CACHE_DIR", ".uv-cache")

# Install dependencies and set up dev environment
[unix]
setup target="":
    @if [ "{{target}}" = "conda" ]; then \
        just _setup-conda; \
    elif [ -z "{{target}}" ]; then \
        just install; \
        just pre-commit-install; \
    else \
        echo "Unknown setup target '{{target}}'. Use 'just setup' or 'just setup conda'."; \
        exit 2; \
    fi

[windows]
setup target="":
    @if ("{{target}}" -eq "conda") { just _setup-conda } elseif ("{{target}}" -eq "") { just install; if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }; just pre-commit-install } else { Write-Error "Unknown setup target '{{target}}'. Use 'just setup' or 'just setup conda'."; exit 2 }

# Create a conda-style env with EBSD/xTB deps, then install pip deps into it
[unix]
_setup-conda:
    #!/usr/bin/env bash
    set -euo pipefail

    env_name="{{conda-env}}"
    manager=""
    os_name="$(uname -s)"
    is_windows=false
    pip_packages=(
        "ase>=3.28.0"
        "commitizen>=4.5.0"
        "gmsh>=4.13.0"
        "h5py>=3.10.0"
        "mkdocs>=1.6.1"
        "mkdocs-material>=9.7.6"
        "mkdocs-minify-plugin>=0.8.0"
        "opencv-python-headless>=4.8.0"
        "open3d>=0.18.0"
        "pandas>=2.0.0"
        "periodictable>=1.6.0"
        "pre-commit>=4.5.1"
        "pymeshfix>=0.17.0"
        "pymeshlab>=2023.12"
        "pysonar>=1.4.0.4676"
        "pytest>=9.0.2"
        "pytest-cov>=7.1.0"
        "pyvista>=0.43.0"
        "pyvistaqt>=0.11.0"
        "qtawesome>=1.3.0"
        "rtree>=1.4.1"
        "ruff>=0.9"
        "scikit-image>=0.22.0"
        "scipy>=1.11.0"
        "sevenn>=0.11.0"
        "tqdm>=4.66.0"
        "traits>=6.3"
        "trimesh>=4.0.0"
    )
    qt_wayland_packages=()

    case "$os_name" in
        MINGW*|MSYS*|CYGWIN*)
            is_windows=true
            ;;
    esac

    if [ "$os_name" = "Linux" ]; then
        qt_wayland_packages=(qt6-wayland)
    fi

    for candidate in micromamba mamba conda; do
        if command -v "$candidate" >/dev/null 2>&1; then
            manager="$candidate"
            break
        fi
    done

    if [ -z "$manager" ]; then
        for candidate in \
            "$HOME/micromamba/bin/micromamba" \
            "$HOME/miniforge3/bin/mamba" \
            "$HOME/mambaforge/bin/mamba" \
            "$HOME/miniconda3/bin/conda" \
            "$HOME/anaconda3/bin/conda" \
            "/opt/conda/bin/conda"; do
            if [ -x "$candidate" ]; then
                manager="$candidate"
                break
            fi
        done
    fi

    if [ -z "$manager" ]; then
        echo "No conda-compatible package manager found. Install micromamba, mamba, conda, or Miniconda first."
        exit 1
    fi

    echo "Using conda-compatible package manager: $manager"
    if "$manager" run -n "$env_name" python --version >/dev/null 2>&1; then
        echo "Using existing environment: $env_name"
    else
        "$manager" create -y -n "$env_name" -c conda-forge python=3.12 pip just "${qt_wayland_packages[@]}"
    fi
    "$manager" install -y -n "$env_name" -c bluequartzsoftware -c conda-forge dream3dnx
    "$manager" install -y -n "$env_name" -c conda-forge xtb xtb-python
    "$manager" install -y -n "$env_name" -c conda-forge numpy pillow matplotlib vtk pyside6 "${qt_wayland_packages[@]}"
    echo "Installing OVITO with pip to avoid conda TBB conflicts with DREAM3D-NX."
    if [ "$is_windows" != true ]; then
        for conda_ovito_package in ovito anari_ovito ospray_ovito visrtx_ovito; do
            "$manager" remove -y -n "$env_name" "$conda_ovito_package" || true
        done
    fi
    "$manager" run -n "$env_name" python -m pip install --upgrade pip
    "$manager" run -n "$env_name" python -m pip install "${pip_packages[@]}"
    "$manager" run -n "$env_name" python -m pip install --no-deps "ovito>=3.14.1,<3.15"
    "$manager" run -n "$env_name" python -m pip install --no-deps -e .
    "$manager" run -n "$env_name" python -c "import cv2; import orientationanalysis; import ovito; import PySide6; import simplnx; print('conda environment import check OK')"

[windows]
_setup-conda:
    powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File scripts/just_conda.ps1 setup -EnvName "{{conda-env}}"

# Run a command inside the configured conda-style environment
[unix]
_conda-run +command:
    #!/usr/bin/env bash
    set -euo pipefail

    env_name="{{conda-env}}"
    manager=""
    command=( {{command}} )

    for candidate in micromamba mamba conda; do
        if command -v "$candidate" >/dev/null 2>&1; then
            manager="$candidate"
            break
        fi
    done

    if [ -z "$manager" ]; then
        for candidate in \
            "$HOME/micromamba/bin/micromamba" \
            "$HOME/miniforge3/bin/mamba" \
            "$HOME/mambaforge/bin/mamba" \
            "$HOME/miniconda3/bin/conda" \
            "$HOME/anaconda3/bin/conda" \
            "/opt/conda/bin/conda"; do
            if [ -x "$candidate" ]; then
                manager="$candidate"
                break
            fi
        done
    fi

    if [ -z "$manager" ]; then
        echo "No conda-compatible package manager found. Install micromamba, mamba, conda, or Miniconda first."
        exit 1
    fi

    if [ "${XDG_SESSION_TYPE:-}" = "wayland" ]; then
        export QT_QPA_PLATFORM="${QT_QPA_PLATFORM:-wayland;xcb}"
    fi

    "$manager" run -n "$env_name" "${command[@]}"

[windows]
_conda-run +command:
    powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File scripts/just_conda.ps1 run -EnvName "{{conda-env}}" {{command}}

# Install all dependencies
install:
    uv sync --all-groups
    uv pip install -e .

# Install pre-commit hooks
pre-commit-install:
    uv run --no-sync pre-commit install --install-hooks
    uv run --no-sync pre-commit install --hook-type pre-push --install-hooks
    uv run --no-sync pre-commit install --hook-type commit-msg --install-hooks

# Run pre-commit hooks on all files
pre-commit:
    uv run --no-sync pre-commit run --all-files

# Check for lint issues
lint:
    uv run --no-sync ruff check .

# Format code
format:
    uv run --no-sync ruff format .

# Auto-fix lint issues and format
fix:
    uv run --no-sync ruff check --fix .
    uv run --no-sync ruff format .

# Validate lint and format (no writes, CI-safe)
check:
    uv run --no-sync ruff check .
    uv run --no-sync ruff format --check .

# Audit license compliance (SPDX headers, OVITO channel, dep licenses)
license-check:
    uv run python scripts/check_licenses.py

# Run tests with coverage
test:
    uv run --no-sync pytest

# Run all tests with coverage enforcement
test-all:
    uv run --no-sync pytest --cov-fail-under=80

# Start the main GUI interface
[unix]
run target="":
    @if [ "{{target}}" = "conda" ]; then \
        just _conda-run python src/multibest/gui/main_ui.py; \
    elif [ -z "{{target}}" ]; then \
        uv run --no-sync python src/multibest/gui/main_ui.py; \
    else \
        echo "Unknown run target '{{target}}'. Use 'just run' or 'just run conda'."; \
        exit 2; \
    fi

[windows]
run target="":
    @if ("{{target}}" -eq "conda") { just _conda-run python src/multibest/gui/main_ui.py } elseif ("{{target}}" -eq "") { uv run --no-sync python src/multibest/gui/main_ui.py } else { Write-Error "Unknown run target '{{target}}'. Use 'just run' or 'just run conda'."; exit 2 }

# Build the PyInstaller release bundle into dist/MultiBEST
[unix]
release target="":
    @if [ "{{target}}" = "conda" ]; then \
        just _release-conda; \
    elif [ -z "{{target}}" ]; then \
        just _release-uv; \
    else \
        echo "Unknown release target '{{target}}'. Use 'just release' or 'just release conda'."; \
        exit 2; \
    fi

[windows]
release target="":
    @if ("{{target}}" -eq "conda") { just _release-conda } elseif ("{{target}}" -eq "") { just _release-uv } else { Write-Error "Unknown release target '{{target}}'. Use 'just release' or 'just release conda'."; exit 2 }

[unix]
_release-uv:
    UV_CACHE_DIR=/tmp/uv-cache uv run --no-sync --with pyinstaller pyinstaller --clean --noconfirm release.spec
    UV_CACHE_DIR=/tmp/uv-cache uv run --no-sync python -m multibest.tools.install_blender --destination dist/MultiBEST/blender
    python scripts/clear_execstack.py dist/MultiBEST/_internal/libpython*.so*

[windows]
_release-uv:
    $env:UV_CACHE_DIR = ".uv-cache"; uv run --no-sync python -m PyInstaller --version *> $null; if ($LASTEXITCODE -ne 0) { Write-Host "PyInstaller is not installed in the uv environment; falling back to the conda release path."; just _release-conda; exit $LASTEXITCODE }; uv run --no-sync python -m PyInstaller --clean --noconfirm release.spec; if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }; uv run --no-sync python -m multibest.tools.install_blender --destination dist/MultiBEST/blender

[unix]
_release-conda:
    just _conda-run python -m PyInstaller --version || just _conda-run python -m pip install pyinstaller
    just _conda-run python -m PyInstaller --clean --noconfirm release.spec
    just _conda-run python -m multibest.tools.install_blender --destination dist/MultiBEST/blender
    just _conda-run python scripts/clear_execstack.py dist/MultiBEST/_internal/libpython*.so*

[windows]
_release-conda:
    just _conda-run python -m PyInstaller --version; if ($LASTEXITCODE -ne 0) { just _conda-run python -m pip install pyinstaller; if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE } }; just _conda-run python -m PyInstaller --clean --noconfirm release.spec; if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }; just _conda-run python -m multibest.tools.install_blender --destination dist/MultiBEST/blender
# Build/update the GUI help documentation site
docs:
    uv run --no-sync mkdocs build --strict

# Interactive commit with Commitizen
commit:
    uv run --no-sync cz commit

# Bump version and update changelog (interactive)
bump:
    uv run --no-sync cz bump --changelog

# Run SonarCloud analysis locally
[unix]
sonar:
    ./.github/scripts/sonar-scan.sh

[windows]
sonar:
    @if (-not (Get-Command sonar-scanner -ErrorAction SilentlyContinue)) { Write-Error "sonar-scanner not found. Download it from https://docs.sonarcloud.io/advanced-setup/ci-based-analysis/sonarscanner-cli/"; exit 1 }; if (-not $env:SONAR_TOKEN) { $reply = Read-Host "SONAR_TOKEN is not set. Continue without token? [y/N]"; if ($reply -notmatch '^[Yy]$') { exit 1 } }; uv run --no-sync pytest --cov=src/multibest --cov-report=xml --cov-report=term; if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }; if ($env:SONAR_TOKEN) { sonar-scanner "-Dsonar.login=$env:SONAR_TOKEN" } else { sonar-scanner }

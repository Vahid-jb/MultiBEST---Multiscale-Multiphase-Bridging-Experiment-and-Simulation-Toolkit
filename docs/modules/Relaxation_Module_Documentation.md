# Relaxation

## Overview
The **Relaxation Module** provides advanced capabilities for geometry optimization of atomic structures. It offers two distinct high-performance methodologies to suit different accuracy and computational needs:

1.  **GFN2-xTB Relaxation:** A semi-empirical quantum mechanical method. Best for general chemistry, metal-organic frameworks, and varying electronic states (charge/spin). It bridges the gap between force fields and DFT.
2.  **SevenNet Relaxation:** A state-of-the-art Graph Neural Network (GNN) potential. Best for high-accuracy materials chemistry and large systems where near-DFT accuracy is required at a fraction of the cost.

Users can choose the appropriate methodology based on their system type and available computational resources.

---

# Methodology 1: GFN2-xTB Relaxation

## Overview
The **GFN2-xTB Relaxation** component provides a robust interface for performing semi-empirical quantum mechanical geometry optimization using the **GFN-xTB** (Geometry, Frequency, Noncovalent, eXtended Tight Binding) family of methods. It is designed to offer a good balance of accuracy and computational speed for substantial systems.

Key features include:
-   **Multiple Methods:** Supports `GFN2-xTB` (default), `GFN1-xTB`, and `GFN0-xTB`.
-   **Hybrid Optimization Strategy:** Primary optimization via the efficient `xtb`  optimizer, with automatic fallback to ASE's `LBFGS` or `FIRE` optimizers.
-   **Element-Specific Properties:** Allows defining initial charge and spin states for specific elements.
-   **Robust Mulliken Analysis:** Reliably extracts Mulliken charges and spin populations.

## Workflow

1.  **Input Parsing:** Reads parameters and element-specific settings.
2.  **Property Initialization:** Applies Magnetic Moments and Charges based on element definitions.
3.  **Geometry Optimization:**
    -   **Stage 1:** Attempts to run the native `xtb` optimization.
    -   **Stage 2 (ASE Fallback):** Switches to ASE's `LBFGS` or `FIRE` optimizer if the `xtb` fails.
4.  **Analysis:** Saves the structure and runs a single-point energy calculation for electronic properties.

## Optimization Strategy
The module prioritizes the **native `xtb` optimizer** (Rational Function Optimization) because it handles the electronic degrees of freedom (Self-Consistent Charge (SCC) convergence) tightly coupled with geometry steps. ASE optimizers are used as a reliable fallback.

### Electronic Initialization
-   **Charge:** The total system charge is the sum of partial charges defined in the input.
-   **Spin (UHF):** Calculated as the sum of atomic spins (number of unpaired electrons).



## detailed Parameter Guide

### A. General & Electronic Parameters

| Parameter | Default | Description |
| :--- | :--- | :--- |
| `method` | `GFN2-xTB` | **Hamiltonian.** `GFN2-xTB`, `GFN1-xTB`, or `GFN0-xTB`. |
| `electronic temperature`| `1000` | **Smearing (K).** Fermi smearing temperature. |
| `accuracy` | `1.0` | **Grid Accuracy.** Controls grid precision (1.0 = standard). |
| `max iterations` | `250` | **SCC Cycles.** Max electronic iterations per geometry step. |
| `xtb threads` | `1` | **Parallelization.** Number of OMP threads. |

### B. Optimization Parameters

| Parameter | Default | Description |
| :--- | :--- | :--- |
| `use xtb opt` | `True` | **Native Optimization.** If `True`, uses `xtb`. If `False`, uses ASE. |
| `optimizer` | `lbfgs` | **ASE Optimizer.** `lbfgs` or `fire`. Fallback use only. |
| `steps` | `500` | **Max Geometry Steps.** |
| `fmax` | `0.02` | **Force Convergence (eV/Å).** |

### C. Element Properties Section
**Format:** `Element Charge Spin` (e.g., `Fe 0.0 2.2`)
1.  **Charge:** Formal atomic charge.
2.  **Spin:** Magnetic moment (unpaired electrons).

---

# Methodology 2: SevenNet Relaxation

## Overview
The **SevenNet Relaxation** component utilizes **SevenNet**, a Graph Neural Network interatomic potential, via the **ASE** interface. It ensures structures are relaxed to their local energy minima with high accuracy, often comparable to DFT but significantly faster.

Key features include:
-   **Machine Learning Potential:** Utilizes SevenNet (default `7net-mf-ompa`) for high-fidelity predictions.
-   **Flexible Input/Output:** Handles all major structure formats supported by ASE.
-   **Automatic Device Selection:** Seamlessly switches between CPU and GPU (CUDA).

## Workflow

1.  **Structure Loading:** Uses ASE to load the atomic structure.
2.  **Calculator Setup:** Initializes the `SevenNetCalculator`. The underlying library automatically downloads the requested model checkpoint (e.g., `7net-mf-ompa`) if needed.
3.  **Geometry Optimization:** Iteratively moves atoms using ASE optimizers (BFGS, LBFGS, FIRE) until forces drop below the threshold.
4.  **Output:** Writes the relaxed structure and final energy details.

## Methodologies
### 1. SevenNet Potential
SevenNet is a GNN potential designed for general-purpose materials chemistry.
-   **Default Model (`7net-mf-ompa`):** A multi-fidelity model trained on MPtrj and sAlex datasets.
-   **Interaction Range:** Captures long-range interactions effectively through message passing.

### 2. Optimization Algorithms
-   **BFGS:** Recommended for standard relaxations (high stability).
-   **LBFGS:** Best for very large systems (>1000 atoms) to save memory.
-   **FIRE:** Useful for systems far from equilibrium.

## Detailed Parameter Guide

### A. General & Model Parameters

| Parameter | Default | Description |
| :--- | :--- | :--- |
| `method` | `SevenNet` | **Must be SevenNet.** |
| `input` | *(Required)* | **Input File.** Path to the structure file. |
| `output` | `./relaxed_structure.xyz` | **Output File.** |
| `model` | `7net-mf-ompa` | **SevenNet Model.** Options: `7net-mf-ompa` (default), `7net-0`, `7net-omat`. |
| `device` | `auto` | **Compute Device.** `cpu` or `cuda` (GPU). |

### B. Optimization Parameters

| Parameter | Default | Description |
| :--- | :--- | :--- |
| `optimizer` | `bfgs` | **Algorithm.** `bfgs` (robust), `lbfgs` (low memory), `fire`. |
| `steps` | `500` | **Max Steps.** |
| `fmax` | `0.02` | **Force Convergence (eV/Å).** |

### C. System & Constraints

| Parameter | Default | Description |
| :--- | :--- | :--- |
| `pbc` | `False` | **Periodic Boundary Conditions.** `True` (bulk), `False` (cluster). |
| `constraints` | `none` | **Constraint Mode.** `none` or `custom`. |
| `custom constraints`| `""` | **Fixed Atoms.** Indices (`0,1,2`) or ranges (`0-5`) to fix. |

---

## Notes

This module leverages the following advanced computational tools. Use these resources for further information regarding theory, models, and usage:

-   [SevenNet](https://sevennet.readthedocs.io/en/latest/)
-   [xTB](https://xtb-docs.readthedocs.io/en/latest/)

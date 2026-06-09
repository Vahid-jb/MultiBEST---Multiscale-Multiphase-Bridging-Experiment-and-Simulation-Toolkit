# SPDX-FileCopyrightText: 2026 bright-ideas-clan
#
# SPDX-License-Identifier: GPL-3.0-or-later

import argparse
import math
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

# Force UTF-8 encoding for standard output and error
if sys.platform == "win32":
    for stream in (sys.stdout, sys.stderr):
        if stream is not None and hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)


def main():
    # Set up command line arguments
    parser = argparse.ArgumentParser(
        description="Process grain data CSV and convert Euler angles from radians to degrees"
    )
    parser.add_argument("--input", required=True, help="Input CSV file (e.g., grain_data.csv)")
    parser.add_argument("--output", default=None, help="Output text file name (default: processed_<input_name>.txt)")

    args = parser.parse_args()

    # Check if input file exists
    input_path = Path(args.input)
    if not input_path.exists():
        print(f"Error: Input file '{args.input}' not found.")
        sys.exit(1)

    # Set output file name
    if args.output is None:
        output_txt = f"processed_{input_path.stem}.txt"
        output_plot = f"grain_analysis_plots_{input_path.stem}.png"
    else:
        output_txt = args.output
        output_plot = f"grain_analysis_plots_{Path(args.output).stem}.png"

    # Read the CSV file
    df = pd.read_csv(input_path)

    # Function to convert radians to degrees and handle NaN values
    def rad_to_deg_handle_nan(value):
        try:
            # Check if value is NaN
            if pd.isna(value) or math.isnan(value):
                return 0.0
            # Convert radians to degrees
            return math.degrees(float(value))
        except (ValueError, TypeError):
            return 0.0

    # Apply the conversion to Euler angle columns
    euler_columns = ["AvgEulerAngles_Export_0", "AvgEulerAngles_Export_1", "AvgEulerAngles_Export_2"]
    for col in euler_columns:
        df[col] = df[col].apply(rad_to_deg_handle_nan)

    # Add grain_ID column starting from 0
    df.insert(
        0, "grain_ID", range(0, len(df))
    )  # changed from range(1, len(df) + 1) to set assembled stl file id to zero

    # Select the required columns including the new ones
    required_columns = ["grain_ID", "Phases_Export"] + euler_columns + ["EquivalentDiameters_Export", "Volumes_Export"]
    df_output = df[required_columns]

    # Save as tab-separated text file
    df_output.to_csv(output_txt, sep="\t", index=False, float_format="%.6f")

    print(f"File processed successfully! Output saved as '{output_txt}'")

    # Create plots
    plt.style.use("default")
    _, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 10))

    # Plot 1: Euler angles vs grain ID

    ax1.scatter(
        df_output["grain_ID"],
        df_output["AvgEulerAngles_Export_0"],
        label="Euler Angle 0 (φ1)",
        marker="o",
        s=20,
        facecolors="none",
        edgecolors="blue",
        linewidth=0.8,
    )
    ax1.scatter(
        df_output["grain_ID"],
        df_output["AvgEulerAngles_Export_1"],
        label="Euler Angle 1 (Φ)",
        marker="s",
        s=20,
        facecolors="none",
        edgecolors="red",
        linewidth=0.8,
    )
    ax1.scatter(
        df_output["grain_ID"],
        df_output["AvgEulerAngles_Export_2"],
        label="Euler Angle 2 (φ2)",
        marker="^",
        s=20,
        facecolors="none",
        edgecolors="green",
        linewidth=0.8,
    )

    ax1.set_xlabel("Grain ID")
    ax1.set_ylabel("Euler Angles (degrees)")
    ax1.set_title("Euler Angles vs Grain ID")
    ax1.legend()
    ax1.grid(True, alpha=0.3)

    # Plot 2: Grain diameter and volume vs grain ID

    ax2.scatter(
        df_output["grain_ID"],
        df_output["EquivalentDiameters_Export"],
        label="Equivalent Diameter",
        marker="o",
        s=20,
        facecolors="none",
        edgecolors="red",
        linewidth=0.8,
    )
    ax2_twin = ax2.twinx()
    ax2_twin.scatter(
        df_output["grain_ID"],
        df_output["Volumes_Export"],
        label="Volume",
        marker="s",
        s=20,
        facecolors="none",
        edgecolors="blue",
        linewidth=0.8,
    )

    ax2.set_xlabel("Grain ID")
    ax2.set_ylabel("Equivalent Diameter", color="red")
    ax2_twin.set_ylabel("Volume", color="blue")
    ax2.set_title("Grain Diameter and Volume vs Grain ID")
    ax2.grid(True, alpha=0.3)

    # Combine legends for the second plot
    lines1, labels1 = ax2.get_legend_handles_labels()
    lines2, labels2 = ax2_twin.get_legend_handles_labels()
    ax2.legend(lines1 + lines2, labels1 + labels2, loc="upper right")

    plt.tight_layout()
    plt.savefig(output_plot, dpi=300, bbox_inches="tight")
    plt.show()

    print(f"Plots created and saved as '{output_plot}'")

    # Print some statistics
    print("\nData Statistics:")
    print(f"Total grains: {len(df_output)}")
    euler_min = df_output[euler_columns].min().min()
    euler_max = df_output[euler_columns].max().max()
    diameter_min = df_output["EquivalentDiameters_Export"].min()
    diameter_max = df_output["EquivalentDiameters_Export"].max()
    print(f"Euler Angles Range: {euler_min:.2f} to {euler_max:.2f} degrees")
    print(f"Equivalent Diameter Range: {diameter_min:.4f} to {diameter_max:.4f}")
    print(f"Volume Range: {df_output['Volumes_Export'].min():.4f} to {df_output['Volumes_Export'].max():.4f}")


if __name__ == "__main__":
    main()

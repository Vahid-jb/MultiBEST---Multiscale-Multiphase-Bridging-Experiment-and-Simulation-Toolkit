# Image Processing

## Overview

The **Image Processing** module is an integrated, in-process image editor designed to prepare raw experimental images (SEM, optical microscopy, EBSD maps, etc.) into clean binary images for downstream modules such as **Image to Mesh**. No external application is required — the entire editing pipeline runs inside MultiBEST.

The module is split into two functional areas:

1. **Editor** — interactive canvas with drawing tools and automatic image adjustments.
2. **Analysis & Replica Generation** — quantitative section analysis and synthesis of area-preserving random binary replicas for statistical studies.

---

## Core Features

### 1. Image Import and Export

The module accepts common raster formats and exports a grayscale PNG ready for mesh generation:

| Action | Supported Formats |
| :--- | :--- |
| Import | TIFF (`.tif`, `.tiff`), PNG, JPEG, BMP |
| Export | PNG (grayscale) |

### 2. Image Adjustments

Three non-destructive preview-then-apply adjustments are available from the toolbar:

| Adjustment | Parameter | Description |
| :--- | :--- | :--- |
| **Threshold** | Value 0–255 | Converts the image to binary (black/white). Pixels strictly above the value become white (255); the rest become black (0). |
| **Blur** | Sigma 0.1–20.0 px | Gaussian blur — smooths noise before thresholding. Higher sigma = more blur. |
| **Contrast** | Factor −100 to +100 | Stretches or compresses pixel intensities around the midpoint (128). Positive values increase contrast; negative values decrease it. |

Each adjustment shows a live preview on the canvas. Click **Apply** to commit the change to history, or **Cancel** to revert.

### 3. Drawing Tools

Manual editing tools let you correct regions that automatic adjustments cannot fix:

| Tool | Description |
| :--- | :--- |
| **Pen** | Freehand drawing. Configurable color (black or white) and line width (1–50 px). |
| **Eraser** | Paints white over the canvas. Configurable width (1–50 px). |
| **Fill** | Flood-fill starting from the clicked pixel. Configurable color and tolerance (0–255). Higher tolerance fills larger similar-color regions. |
| **Crop** | Drag a rectangle and click **Apply Selection** to crop the image to that region. |
| **Cut** | Drag a rectangle and click **Apply Selection** to fill the selected region with white. |
| **Pan** | Drag to scroll around a zoomed-in image without editing. |

### 4. History (Undo / Redo / Reset)

Every committed action (adjustment or tool stroke) is pushed onto a snapshot stack (maximum 50 entries):

| Button | Action |
| :--- | :--- |
| Undo | Step back one snapshot. |
| Redo | Step forward one snapshot (available after an undo). |
| Reset | Jump back to the originally loaded image. |

### 5. Zoom

| Button | Action |
| :--- | :--- |
| Zoom In | Increase canvas scale. |
| Zoom Out | Decrease canvas scale. |
| Fit to View | Scale the image to fill the available canvas area. |

---

## Workflow: Preparing a Binary Image

A typical image preparation session follows these steps:

1. **Import** — Click **Import Image** and select the source image.
2. **Blur (optional)** — Apply a small Gaussian blur (`sigma` 0.5–2.0) to suppress noise before thresholding.
3. **Threshold** — Drag the slider to the value that cleanly separates the phase of interest from the background. Adjust until the preview shows solid black and white regions.
4. **Touch up** — Use the **Pen**, **Eraser**, or **Fill** tools to fix isolated pixels, bridges, or incorrectly segmented areas.
5. **Crop / Cut (optional)** — Remove border artefacts or unwanted regions.
6. **Export** — Click **Export Image** to save the processed binary image as a PNG.

The exported image can be loaded directly into the **Image to Mesh** module.

---

## Analysis

The **Analysis** panel performs a quantitative section-area analysis on the current editor image without altering it.

### Parameters

| Parameter | Default | Description |
| :--- | :--- | :--- |
| **Threshold** | 127 | Binarization level used only for analysis (does not modify the editor image). |
| **Connectivity** | 8-connected | Connected-component rule. **8-connected** groups diagonal neighbours; **4-connected** does not. |
| **Invert** | Off | When checked, swaps the white and black phase roles before labelling. |
| **Include white** | On | Label and report connected white regions. |
| **Include black** | On | Label and report connected black regions. |

### Output

Clicking **Analyze** switches the view to the **Analyzed** tab, which shows:

- Coloured contours drawn around each detected section.
- Section ID labels (e.g. `W3` for white section 3, `B7` for black section 7) placed at the centroid.

After analysis two additional buttons appear:

| Button | Output |
| :--- | :--- |
| **Save report** | Plain-text `.txt` file with total pixel counts, per-section areas, centroids, and bounding boxes. |
| **Save analyzed image** | PNG of the overlay canvas (contours + labels). |

### Report Format

The saved report contains:

```
BINARY IMAGE SECTION AREA REPORT
============================================================
Input image: <filename>
Image size: <W> x <H> pixels
Total pixels: <N>
Threshold used: <value>
Connectivity used: <value> (8-connected | 4-connected)
White pixels after thresholding: <N>
Black pixels after thresholding: <N>
Sum of all white section areas: <N>
Sum of all black section areas: <N>
...

WHITE SECTIONS
------------------------------------------------------------
Section W1: area = <px>
...

BLACK SECTIONS
------------------------------------------------------------
Section B1: area = <px>
...

DETAILED SECTION TABLE
------------------------------------------------------------
phase   section_id  area  centroid_row  centroid_col  bbox_min_row  bbox_min_col  bbox_max_row  bbox_max_col
...
```

---

## Replica Generation

The **Replica Generation** panel synthesises new binary images that statistically match the original's black-phase area fraction. This is useful for uncertainty quantification and data augmentation in microstructure studies.

Each replica places randomised ellipsoidal blobs onto a white canvas until the total black-pixel count matches the source image, then applies boundary smoothing to produce realistic, connected regions.

### Parameters

| Parameter | Default | Description |
| :--- | :--- | :--- |
| **Count** | 5 | Number of replica images to generate. |
| **Random seed** | 12345 | Seed for the random number generator. Use the same seed to reproduce results; change it to get different realisations. |
| **Min black region** | 500 px | Minimum area of each random blob placed on the canvas. |
| **Max black region** | 5000 px | Maximum area of each random blob. |
| **Boundary σ** | 1.2 | Gaussian sigma applied to blob boundaries to smooth jagged edges. Set to 0 to skip smoothing. |
| **Cleanup width** | 2 | Morphological erosion/dilation radius (px) applied after smoothing to harden boundaries and remove isolated pixels. |

### Output

Clicking **Generate Replicas** opens a directory picker. Each replica is saved as:

```
multibest_<stem>_replica_<n>.png
```

where `<stem>` is the original image filename and `<n>` runs from 1 to **Count**.

### Area Preservation

After blob placement and boundary cleanup the generator enforces the exact black-pixel count of the source image by growing or shrinking the black mask at boundary pixels. The final area fraction therefore always equals the original.

---

## Notes

- The **Threshold** value in the Analysis panel is independent of any threshold applied in the Editor. They can differ.
- The **Delete Image** button (bottom of the left panel) unloads the image and resets all controls; it does not delete the file from disk.
- All editing operations are non-destructive until **Export Image** is clicked — the original file is never overwritten.
- For downstream use in **Image to Mesh**, ensure the exported image is fully binary (only pure black and white pixels) by applying a threshold with a sharp midpoint value (e.g. 127).



This module is built on the following open-source libraries:

[NumPy](https://numpy.org/) Core array representation for all image data; pixel arithmetic for threshold, contrast, and crop operations.<br>
[OpenCV](https://docs.opencv.org/)  Flood-fill, line drawing, contour detection and rendering, Gaussian blur, morphological operations. <br>
[Scikit-image](https://scikit-image.org/) Gaussian filter, connected-component labelling, region properties, small-object and small-hole removal.<br>
[SciPy](https://scipy.org/) fills enclosed holes in binary masks during replica cleanup.<br>
[Pillow](https://pillow.readthedocs.io/) reading source images and saving processed / replica PNG files.

# 🔭 AEON/SOAR Finder Chart Pipeline - Extended Documentation

## 🌙 1. Objective & Scope
The primary objective of this project is to bridge the gap between observation scheduling and telescope operations. Built for 24/7 facility-level operation, this software automatically fetches approved observations, performs astrometric analysis to find optimal guiding stars, downloads/reprojects FITS images, and delivers publication-ready PDFs to Google Drive.

## 🚀 2. Core Architecture & Resiliency

* **Extreme Network Resiliency:** Astronomical databases can be unstable. The pipeline implements exponential backoff (`@retry_with_backoff`) and an automatic fallback chain for catalog queries: **Gaia DR3 $\rightarrow$ Pan-STARRS $\rightarrow$ Legacy Survey $\rightarrow$ 2MASS**.
* **Multiprocessing Engine:** Utilizes Python's `ProcessPoolExecutor` to circumvent the Global Interpreter Lock (GIL). It renders multiple PDFs simultaneously, significantly reducing processing time for large observation batches.
* **Memory & Cache Safety:** Built to run infinitely as a daemon. It forces explicit Matplotlib garbage collection to eliminate memory leaks and automatically prunes the local `./fits_cache` directory if it exceeds 3.0 GB.

## 🛰️ 3. Pipeline Mechanics

### The T-12h Astronomical Night Sorting
To align with standard astronomical practices, the pipeline does not organize files by the UTC time of execution. It reads the target's temporal window, subtracts **12 hours** from the UTC start time, and dynamically generates folders formatted as `Night_YYYY-MM-DD`. If a target has multiple windows, the PDF is generated once but distributed to all applicable night folders.

### Dynamic FOV & Slit Calibration
The `finder.py` engine automatically scales the camera's Field of View (FOV) to tightly wrap the top 3 closest reference stars. However, it strictly enforces the physical constraints of the selected instrument:
* **GOODMAN:** Min 1.8' | Max 7.2' | Slit 234.0"
* **GMOS:** Min 2.0' | Max 5.5' | Slit 108.0"
* **TS4:** Min 1.0' | Max 4.0' | Slit 28.0"

## 🌟 4. Supported Input Formats (Local Batching)

When bypassing the API using `--input-json`, the pipeline accepts two file types:

### A. Advanced JSON Format
The native format supporting full pipeline capabilities, including custom instruments, FOV overrides, and multiple temporal windows.
```json
[
  {
    "id": "obs_001",
    "object_name": "Target_A",
    "ra": "06:45:08.9",
    "dec": "-16:42:58",
    "pa": "150",
    "instrument": "GOODMAN",
    "fov": 4.5,
    "slit": 0.75,
    "windows": [{"start": "2026-03-22T02:00:00Z", "end": "2026-03-22T03:00:00Z"}]
  }
]
```

B. Flat Text Format (.txt or .dat)

A rapid, tabular format ideal for visiting astronomers. It splits lines by whitespace. The parser automatically defaults the instrument to GOODMAN and FOV to 3.0.

Format: Name | RA | DEC | [Notes] | PA=value
```bash
Target_Decimal   183.0512   13.2254    Decimal_Test   PA=45.0
Sirius_Test      06:45:08.9 -16:42:58  Sexagesimal    PA=0.0
M87_Para         187.7059   12.3911    Parallactic    PA=para
```

(Note: Both decimal and sexagesimal coordinates are parsed automatically.)

## 🌌 5. Generated PDF Layout (Finder Chart)

The final document is divided into a logical and visual grid:

Chart I & II (Optical): Displays the target in optical light (r-band). Chart I shows the direct view (North up, East to the left), and Chart II reflects the requested rotation (Position Angle).

Chart III & IV (Infrared): Repeats the process using J-band images from the 2MASS catalog.

Metadata & Tables: The right panel includes the target's name, coordinates in both sexagesimal and decimal formats, and tables detailing the magnitudes and absolute offsets of the guide stars for fine calibration.

## 😃 6. Credits & Appreciation

This project was brought to life thanks to the great teamwork of:

* **Tomas Ahumada**: For initiating the project and generating the original concept and idea.
* **Simon Torres**: For his dedication in implementing the features, and fixing/refining the script. 

Their hard work and contributions were essential to making this tool possible!

## 📝 7. Note on the Orientation of Infrared Finder Charts (Charts III and IV)

When generating the finder charts, you will notice that the plots corresponding to the infrared spectrograph automatically apply an *offset* of **+90 degrees** relative to the Position Angle (PA) requested by the user. 

This correction is intentional and is due to the hardware architecture of the **TripleSpec 4.1 (TS4)** instrument on the SOAR telescope. Unlike traditional optical instruments (such as Goodman) where the slit is typically aligned vertically at PA=0°, the [official NOIRLab observing guide](https://noirlab.edu/science/programs/ctio/instruments/triplespec41-nir-imaging-spectrograph/Observing-Guide) specifies that:

> *"The slit for TripleSpec4 is aligned along the rows of the imaging detector."*

Since the slit is oriented horizontally (along the rows, or the X-axis of the detector), applying this +90° offset in Charts III and IV ensures that the visual representation of the slit against the sky and the reference stars is mathematically accurate.

# 🔭 AEON/SOAR Automated Finder Chart Pipeline - Extended Documentation

## 1. Objective
The primary objective of this project is to provide an enterprise-grade, fully automated pipeline designed to generate astronomical Finder Charts for the SOAR Telescope and the broader AEON (Astronomical Event Observatory Network). Built for 24/7 facility-level operation, this system continuously polls observation schedules, dynamically calculates optimal Fields of View (FOV) based on instrument specifications, queries multiple star catalogs with automatic failovers, and uploads memory-safe PDF renders directly to Google Drive.

## 2. Scope
This software bridges the gap between observation scheduling and telescope operations. Its scope covers:
* **Data Ingestion:** Automatically fetching approved observations via the LCO/AEON API portal, or parsing local user-provided `.json` and `.txt`/`.dat` files. 
* **Astrometric Analysis:** Automatically querying optical and near-infrared databases (Gaia DR3, Pan-STARRS, Legacy Survey, 2MASS) to find optimal guiding stars.
* **Image Processing & Rendering:** Downloading astrometric FITS images, reprojecting them to account for Position Angle (PA) rotations, and generating publication-ready PDFs with accurate WCS coordinate grids and instrument slit overlays.
* **Cloud Delivery:** Synchronously managing Google Drive directories to organize outputs and securely upload final charts.

## 3. Core Strengths & Architecture
* **Extreme Network Resiliency:** Implements exponential backoff (`@retry_with_backoff`) for unstable astronomical databases. If Gaia DR3 is down, it gracefully falls back to Pan-STARRS, then to the Legacy Survey.
* **Multiprocessing Engine:** Utilizes Python's `ProcessPoolExecutor` to circumvent the Global Interpreter Lock (GIL) and Matplotlib's thread-locking issues, rendering multiple PDFs simultaneously.
* **Memory-Safe Daemon:** Built to run infinitely. It forces explicit garbage collection to eliminate memory leaks during 24/7 server operations.

## 4. Pipeline Logic & Mechanics

### Directory Sorting (The T-12h Astronomical Night)
The pipeline does not blindly save files based on the UTC time of execution. To align with astronomical standards, it reads the exact `windows` array from the API, subtracts **12 hours** from the UTC start time, and groups all targets belonging to the same observing night into a specific folder formatted as `Night_YYYY-MM-DD`. If an observation has multiple valid windows, the pipeline generates the PDF *once* but uploads copies to *all* applicable Night folders.

### Dynamic FOV & Slit Calibration
The `finder.py` engine automatically scales the camera Field of View to tightly fit the top 3 closest reference stars. It strictly enforces physical limits defined in the `INSTRUMENT_SPECS` dictionary:
* **GOODMAN:** Min 1.8' | Max 7.2' | Slit 234.0"
* **GMOS:** Min 2.0' | Max 5.5' | Slit 108.0"
* **TS4:** Min 1.0' | Max 4.0' | Slit 28.0"

## 5. Supported Input Formats

When running the pipeline manually using the `--input-json` argument, you can provide two types of files:

### a) The Advanced JSON Format
Native format supporting full pipeline capabilities (custom instruments, FOV overrides, multiple windows).

```bash
[
  {
    "id": "obs_001",
    "object_name": "Target_A",
    "ra": "06:45:08.9",
    "dec": "-16:42:58",
    "pa": "para",
    "instrument": "GMOS",
    "fov": 4.5,
    "slit": 0.75,
    "windows": [{"start": "2026-03-22T02:00:00Z", "end": "2026-03-22T03:00:00Z"}]
  }
]
```

### b) The Flat Text Format (.txt or .dat)
A quick, tabular format ideal for visiting astronomers. The parser splits lines by whitespace. It defaults the instrument to GOODMAN and the FOV to 3.0.

Format: Name   RA   DEC   [Notes]   PA=value

```bash
Target_Decimal   183.0512   13.2254    Decimal_Test   PA=45.0
Sirius_Test      06:45:08.9 -16:42:58  Sexagesimal    PA=0.0
M87_Para         187.7059   12.3911    Parallactic    PA=para
```

## 6. Authentication & Environment Secrets
To authenticate with the AEON/LCO proxy, you must create a .env file in the root directory. Crucially, the API Token string must begin with the word "Token " followed by a space and your key. Example .env file:

SOAR_API_TOKEN=Token a1b2c3d4e5f6g7h8i9j0

# 🔭 AEON/SOAR Automated Finder Chart Pipeline - Extended Documentation

## 1. Objective
The primary objective of this project is to provide an enterprise-grade, fully automated pipeline designed to generate astronomical Finder Charts for the SOAR Telescope and the broader AEON (Astronomical Event Observatory Network). Built for 24/7 facility-level operation, this system continuously polls observation schedules, dynamically calculates optimal Fields of View (FOV) based on instrument specifications, queries multiple star catalogs with automatic failovers, and uploads memory-safe PDF renders directly to Google Drive.

## 2. Scope
This software bridges the gap between observation scheduling and telescope operations. Its scope covers:
* **Data Ingestion:** Automatically fetching the next 30 days of approved observations via the LCO/AEON API portal, or parsing local user-provided `.json` and `.txt`/`.dat` files. 
* **Astrometric Analysis:** Automatically querying optical and near-infrared databases (Gaia DR3, Pan-STARRS, Legacy Survey, 2MASS) to find optimal guiding stars.
* **Image Processing & Rendering:** Downloading astrometric FITS images, reprojecting them to account for Position Angle (PA) rotations, and generating publication-ready PDFs with accurate WCS coordinate grids, dual coordinate displays (Degrees and HMS/DMS), and instrument slit overlays.
***Cloud Delivery:** Synchronously managing Google Drive directories to organize outputs by `Night_YYYY-MM-DD` and securely uploading the final charts.

## 3. Core Strengths
***Extreme Network Resiliency:** Implements exponential backoff (`@retry_with_backoff`) for unstable astronomical databases. If Gaia DR3 is down or lacks coverage, it gracefully falls back to Pan-STARRS, then to the Legacy Survey, ensuring a chart is always generated.
***Multiprocessing Architecture:** Utilizes Python's `ProcessPoolExecutor` to render multiple FITS images and PDFs simultaneously. This circumvents Python's GIL and Matplotlib's thread-locking issues, drastically reducing batch processing times.
***Memory-Safe Daemon Mode:** Built to run infinitely. It uses Matplotlib's headless 'Agg' backend and forces explicit garbage collection (`fig.clf()`, `plt.close('all')`) to completely eliminate memory leaks during 24/7 server operations.
***Thread-Safe Google Drive Integration:** Features a robust Singleton pattern for Google API credentials to avoid rate limits. It utilizes synchronous pre-processing to eliminate race conditions when creating dynamic Night folders.

## 4. Key Properties & Features
***AEON Network & ToO Ready:** Native support for dynamic instrument changes (e.g., SOAR Goodman, Gemini GMOS) and Target of Opportunity (ToO) alerts. It tracks observations by unique API id rather than coordinates, ensuring updated requests are never skipped.
***Smart Dynamic FOV & Star Selection:** Automatically scales the camera FOV to tightly fit the top 3 closest reference stars. It strictly enforces instrument-specific minimum FOVs and automatically excludes reference stars closer than 2.0" to the science target to prevent guiding on blended sources.
* **Flexible Input Parsing:** Capable of digesting both standard AEON JSON structures and flat `.txt` files containing rows of `TargetName HH:MM:SS +/-DD:MM:SS PA=value`, making it highly adaptable for visiting astronomers.
***Intelligent Local Caching:** Synchronously manages a local FITS file cache (capped at 3.0 GB by default) to prevent redundant downloads and save bandwidth.
* **Clean File Management:** By default, the program operates immaculately by utilizing temporary directories for Drive uploads, ensuring it does not clutter the host machine's hard drive unless specifically instructed via the `--output-folder` command line argument. If instructed, it safely checks for the directory's existence and creates it if missing.
* **Data-Driven Titles:** Plot titles clearly state the applied FOV rather than repeating the target name, allowing telescope operators to instantly verify the scale of the image on the screen.

## 5. Project Architecture Map
The pipeline is strictly modularized into four key components:
* **`run_batch.py`**: The Master Controller. Handles multiprocessing, calculates Astronomical Nights (T-12h), manages state (`processed_ids.json`), and coordinates synchronous tasks (cache cleaning, Drive folder creation) to prevent race conditions.
* **`finder.py`**: The Core Plotting Engine. Calculates target-to-star radial distances, dynamically adjusts the FOV based on the `INSTRUMENT_SPECS` dictionary, and uses `reproject` and matplotlib to render the final PDF with WCS-accurate compass roses and slit overlays.
* **`soar_api.py`**: The API Connector. Securely authenticates with the LCO proxy, queries a rolling 31-day window, and formats the raw schedule into a clean JSON digest.
* **`utils.py`**: The Toolbelt. Contains the Astropy coordinate parsers, multithreaded FITS downloaders, Google Drive Singleton handlers, the 3GB local cache manager, and the centralized logging configuration.

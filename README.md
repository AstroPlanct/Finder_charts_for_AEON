# 🔭 AEON/SOAR Finder Pipeline - Quick Start

## Prerequisites
1. Python 3.9+ with dependencies: `pip install numpy matplotlib astropy astroquery pyvo requests python-dotenv google-api-python-client google-auth-httplib2 google-auth-oauthlib reproject charset-normalizer`
2. `.env` file containing: `SOAR_API_TOKEN=Your_Token_Here`
3. `drive_credentials.json` (Google Service Account key) in the root directory.

## Running the Pipeline

**1. Production Mode (Daemon)**
Runs continuously, checks the LCO portal every 5 minutes, and uploads to Google Drive. Does *not* save locally by default. Run this inside `tmux` or `screen`[cite: 15]:
```bash
python run_batch.py --drive-folder "YOUR_DRIVE_FOLDER_ID" --max-workers 4

2. Single Batch / Local Test
Process a specific JSON file once and exit. Add --output-folder if you want to keep the PDFs on your hard drive:

Bash
python run_batch.py --input-json test_observations.json --run-once --output-folder ./my_charts --max-workers 4

3. Standalone Manual Generation
Bypass the API and generate a single chart instantly:

Bash
python finder.py --s-name "Target_X" --ra "183.05" --dec "13.22" --pa-deg 45.0 --instrument "GOODMAN" --output-folder ./my_charts

Note: To force a rerun of completed targets, delete processed_ids.json.

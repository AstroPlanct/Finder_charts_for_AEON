# 🔭 AEON/SOAR Finder Pipeline - Quick Start

A fully automated, enterprise-grade pipeline designed to generate astronomical Finder Charts for the SOAR Telescope and the AEON Network. For an in-depth explanation of the architecture, algorithms, and advanced configurations, please read the (readme_extended.md).

1. ## Prerequisites

#### Python 3.9+ with dependencies:
 
```bash   pip install numpy matplotlib astropy astroquery pyvo requests python-dotenv google-api-python-client google-auth-httplib2 google-auth-oauthlib reproject charset-normalizer
```

#### .env file containing your portal token (must include the word "Token "):

```bash SOAR_API_TOKEN=Token YOUR_SECRET_TOKEN_HERE
```

#### drive_credentials.json (Google Service Account key) placed in the root directory.


2. ## Running the Pipeline

#### Production Mode (Daemon)

Runs continuously, checks the LCO portal every 5 minutes, and uploads to Google Drive. Run this inside tmux or screen:

```bash python run_batch.py --drive-folder "YOUR_DRIVE_FOLDER_ID" --max-workers 4 
```

#### Single Batch / Local Test

Process a specific JSON or TXT file once and exit. Add --output-folder to keep the PDFs on your hard drive:

```bash python run_batch.py --input-json test_targets.json --run-once --output-folder ./my_charts --max-workers 4
```

#### Standalone Manual Generation

Bypass the API entirely and generate a single chart instantly via the CLI:

```bash python finder.py --s-name "Target_X" --ra "183.05" --dec "13.22" --pa-deg 45.0 --instrument "GOODMAN" --output-folder ./my_charts
```

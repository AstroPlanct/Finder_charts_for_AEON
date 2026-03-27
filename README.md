# 🔭 AEON/SOAR Automated Finder Chart Pipeline

An enterprise-grade, fully automated pipeline designed to generate astronomical Finder Charts for the SOAR Telescope and the AEON (Astronomical Event Observatory Network).

This system continuously polls observation schedules, dynamically calculates optimal Fields of View (FOV), queries multiple star catalogs with automatic failovers, and uploads memory-safe PDF renders directly to Google Drive.

For an in-depth explanation of the architecture, fallback algorithms, and advanced configurations, please refer to the readme_extended.md.

## ⚙️ Prerequisites

Python: 3.9+

Dependencies: Install the required packages:

pip install numpy matplotlib astropy astroquery pyvo requests python-dotenv google-api-python-client google-auth-httplib2 google-auth-oauthlib reproject charset-normalizer


LCO/AEON API Credentials: Create a .env file in the root directory. The token must include the word "Token ":

SOAR_API_TOKEN=Token YOUR_SECRET_TOKEN_HERE


Google Drive Credentials (Optional): Place your drive_credentials.json (Service Account key) in the root directory to enable cloud uploads.

## 🚀 Quick Start & Execution Modes

### 1. Production Mode (Daemon)

Runs continuously, checks the LCO portal every 5 minutes, and uploads charts to Google Drive organized by Astronomical Night. Best run inside tmux or screen.

python run_batch.py --drive-folder "YOUR_DRIVE_FOLDER_ID" --max-workers 4


### 2. Single Batch / Local Test

Processes a specific local JSON or TXT file once and exits. Saves the PDFs locally.

python run_batch.py --input-json test_targets.json --run-once --output-folder ./my_charts --max-workers 4


### 3. Standalone Manual Generation

Bypasses the batch processor and generates a single chart instantly via the CLI.

python finder.py --s-name "Target_X" --ra "183.05" --dec "13.22" --pa-deg 45.0 --instrument "GOODMAN" --output-folder ./my_charts


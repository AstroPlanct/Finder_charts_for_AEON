# Import parsing, JSON, and time modules
import argparse
import json
import re
import time
from pathlib import Path
from datetime import datetime, timedelta
# Import ProcessPoolExecutor for true parallel processing (multiprocessing)
from concurrent.futures import ProcessPoolExecutor

# Import the finder module (the plotting engine)
import finder
# Import the API fetcher
from soar_api import fetch_soar_data_to_json
# Import utility functions for Drive, logging, and cache management
from utils import check_file_in_drive, get_or_create_drive_folder, setup_logger, manage_cache_size

# Initialize the logger for the batch processor
logger = setup_logger(name="batch_processor")
# Define the local file used to remember which IDs have already been processed
STATE_FILE = "processed_ids.json"

def load_processed_ids():
    # If the state file exists, read it and return a set of processed IDs
    if Path(STATE_FILE).exists():
        try:
            with open(STATE_FILE, 'r') as f: 
                return set(json.load(f))
        except json.JSONDecodeError:
            # If the file is empty or corrupted, warn the user and start fresh
            logger.warning(f"File {STATE_FILE} is corrupted or empty. Starting fresh.")
            return set()
    # Otherwise, return an empty set
    return set()

def save_processed_ids(ids_set):
    # Save the current set of processed IDs back to the JSON file
    with open(STATE_FILE, 'w') as f: 
        json.dump(list(ids_set), f)

def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--drive-folder", type=str, default=None)
    parser.add_argument("--output-folder", type=str, default=None, help="Local directory to save charts.")
    parser.add_argument("--input-json", type=str, default=None)
    parser.add_argument("--run-once", action="store_true")
    parser.add_argument("--max-workers", type=int, default=4)
    return parser.parse_args()

def process_single_target(obs, args, drive_folder_cache):
    # Extract details from the observation dictionary
    obs_id = obs.get('id')
    s_name = str(obs.get('object_name', 'Unknown')).replace(' ', '_')
    ra, dec = obs.get('ra'), obs.get('dec')
    instrument = obs.get('instrument', 'GOODMAN')

    # Skip this target if critical data is missing
    if ra is None or dec is None or not obs.get('windows'): 
        return None

    # Calculate all applicable Astronomical Nights based on the windows
    target_nights = set()
    for w in obs.get('windows', []):
        start_time_str = w.get('start')
        if not start_time_str: continue
        try:
            # Clean the time string (remove T, Z, and milliseconds)
            clean_time_str = start_time_str.replace('T', ' ').replace('Z', '').split('+')[0].split('.')[0]
            # Subtract 12 hours to calculate the "Astronomical Night"
            night_date = (datetime.strptime(clean_time_str, '%Y-%m-%d %H:%M:%S') - timedelta(hours=12)).strftime('%Y-%m-%d')
            target_nights.add(f"Night_{night_date}")
        except Exception:
            pass
            
    if not target_nights:
        target_nights.add("Night_Unknown")

    # Handle local folder creation for all nights
    output_dirs = []
    if args.output_folder:
        for night in target_nights:
            local_night_folder = Path(args.output_folder) / night
            local_night_folder.mkdir(parents=True, exist_ok=True)
            output_dirs.append(str(local_night_folder))

    # Handle Drive folder ID assignment for all nights
    drive_ids = []
    if args.drive_folder:
        for night in target_nights:
            if night in drive_folder_cache:
                drive_ids.append(drive_folder_cache[night])
    
    raw_pa = obs.get('pa', 0.0)
    is_parallactic = str(raw_pa).lower() in ["para", "parallactic", "paralactico"]
    pa_value = 0.0 if is_parallactic else float(raw_pa)
    clean_inst = str(instrument).upper().replace(' ', '').replace('4.1', '')
    
    logger.info(f"Generating chart: {s_name} (Inst: {instrument}, Nights: {', '.join(target_nights)})")
    try:
        finder.run_pipeline(
            s_name=s_name, ra_str=str(ra), dec_str=str(dec), pa_deg=pa_value,
            instrument=instrument,
            imsize=float(obs.get('fov', 3.0)), radius=1.0, contrast=float(obs.get('contrast', 0.045)),
            slit_width=float(obs.get('slit', 1.0)), 
            output_folders=output_dirs,
            drive_folders=drive_ids,
            is_parallactic=is_parallactic 
        )
        return obs_id
    except Exception as e:
        logger.error(f"Failed to process {s_name}: {e}")
        return None

def process_batch(args):
    # Use the local JSON if provided, otherwise fetch fresh data from the API
    input_file = args.input_json if args.input_json else fetch_soar_data_to_json()
    # Abort if no file was found or generated
    if not input_file or not Path(input_file).exists(): return

    if input_file.lower().endswith('.txt') or input_file.lower().endswith('.dat'):
        targets = parse_txt_observations(input_file)
    else:
        with open(input_file, 'r', encoding='utf-8') as f: 
            targets = json.load(f)

    # Load the IDs we have already processed in the past
    processed_ids = load_processed_ids()
    drive_folder_cache = {}
   
    # --- SYNCHRONOUS PRE-PROCESSING ---
    # Find all unique "Nights" in this batch to prevent Race Conditions
    unique_nights = set()
    batch_filenames = set()
    unique_targets = []
    
    for obs in targets:
        if obs.get('id') in processed_ids: continue
        
        s_name = str(obs.get('object_name', 'Unknown')).replace(' ', '_')
        clean_inst = str(obs.get('instrument', 'GOODMAN')).upper().replace(' ', '').replace('4.1', '')
        raw_pa = obs.get('pa', 0.0)
        is_parallactic = str(raw_pa).lower() in ["para", "parallactic", "paralactico"]
        pa_value = 0.0 if is_parallactic else float(raw_pa)
        
        target_sig = f"{s_name}_{clean_inst}_PA{'PARA' if is_parallactic else pa_value}"
        
        if target_sig in batch_filenames:
            processed_ids.add(obs.get('id'))
            continue
            
        batch_filenames.add(target_sig)
        unique_targets.append(obs)

        # Loop through all windows to find applicable nights
        for w in obs.get('windows', []):
            start_time_str = w.get('start')
            if not start_time_str: continue
            try:
                # Calculate night exactly as in process_single_target
                clean_time_str = start_time_str.replace('T', ' ').replace('Z', '').split('+')[0].split('.')[0]
                night_date = (datetime.strptime(clean_time_str, '%Y-%m-%d %H:%M:%S') - timedelta(hours=12)).strftime('%Y-%m-%d')
                unique_nights.add(f"Night_{night_date}")
            except Exception:
                pass
        
        # If no valid windows were found, assign to Unknown
        if not obs.get('windows'):
            unique_nights.add("Night_Unknown")
    
    # If Drive is enabled, synchronously create/fetch all required folders first        
    if args.drive_folder:
        for night in unique_nights:
            drive_folder_cache[night] = get_or_create_drive_folder(night, args.drive_folder)

    # Synchronously clean up the local FITS cache before launching parallel workers    
    logger.info("Verifying local FITS cache size before parallel processing...")
    manage_cache_size(cache_dir="./fits_cache", max_size_gb=3.0)

    # Launch the parallel processing pool
    with ProcessPoolExecutor(max_workers=args.max_workers) as executor:
        futures = []
        # Submit each unprocessed target to a worker process
        for obs in unique_targets:
            futures.append(executor.submit(process_single_target, obs, args, drive_folder_cache))
        
        # Collect the results as they finish
        for future in futures:
            success_id = future.result()
            # If successful, add the ID to the processed set
            if success_id: processed_ids.add(success_id)
            
    # Save the updated list of processed IDs to the local file
    save_processed_ids(processed_ids)
    
def parse_txt_observations(filepath):
    """
    Parses a flat text file of astronomical targets into a list of dictionaries.
    Expected format per line:
    TargetName  HH:MM:SS.SS  +/-DD:MM:SS.S  Epoch --- Notes PA=value
    """
    targets = []
    
    with open(filepath, 'r', encoding='utf-8') as f:
        lines = f.readlines()
        
    for idx, line in enumerate(lines):
        line = line.strip()
        # Skip empty lines or comments
        if not line or line.startswith("#"): 
            continue
            
        parts = line.split()
        # We need at least Name, RA, and DEC
        if len(parts) < 3: 
            continue
            
        name = parts[0]
        ra_str = parts[1]
        dec_str = parts[2]
        
        # Search for PA= in the line using a Regular Expression
        pa_value = 0.0
        pa_match = re.search(r'PA=([^\s]+)', line, re.IGNORECASE)
        if pa_match:
            raw_pa = pa_match.group(1).lower()
            if raw_pa in ['para', 'parallactic', 'paralactico']:
                pa_value = "para"
            else:
                try: 
                    pa_value = float(raw_pa)
                except ValueError: 
                    pa_value = 0.0 # Default to 0 if parsing fails
                    
        # Create a dummy window for right now so it saves in tonight's folder
        dummy_time = datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')
        
        # Append to our list exactly how the API would format it
        targets.append({
            "id": f"txt_row_{idx+1}_{name}", # Generate a unique pseudo-ID
            "object_name": name,
            "ra": ra_str,
            "dec": dec_str,
            "pa": pa_value,
            "instrument": "GOODMAN", # Default instrument
            "fov": 3.0,              # Default FOV
            "windows": [{"start": dummy_time, "end": dummy_time}]
        })
        
    logger.info(f"Successfully parsed {len(targets)} targets from {filepath}")
    return targets
    
def main():
    # Parse terminal arguments
    args = parse_args()
    
    # If the user requested a single run, do it and exit
    if args.run_once:
        logger.info(f"Running single test cycle with {args.max_workers} parallel workers...")
        process_batch(args)
        return

    # Otherwise, enter an infinite loop (daemon mode)
    while True:
        logger.info(f"Starting review cycle: {time.strftime('%H:%M:%S')}")
        process_batch(args)
        # Sleep for 5 minutes (300 seconds) before checking the API again
        time.sleep(300)

if __name__ == "__main__":
    main()

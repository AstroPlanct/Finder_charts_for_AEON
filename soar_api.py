# Import necessary libraries for HTTP requests, JSON handling, and OS interactions
import requests
import json
import os
# Import datetime tools to calculate time windows
from datetime import datetime, timedelta
# Import load_dotenv to securely read environment variables from a .env file
from dotenv import load_dotenv
# Import our custom logger from utils.py
from utils import setup_logger

# Load the variables from the .env file into the script's environment
load_dotenv()
# Initialize the logger specifically for this API fetcher module
logger = setup_logger(name="api_fetcher")

def fetch_soar_data_to_json():
    # Define the AEON/LCO observation portal API endpoint
    url = "https://soar-proxy.lco.global/observation-portal/api/schedule/"
    
    # Get the current UTC time
    now = datetime.utcnow()
    # Define the search window: from XX days in the past...
    start_str = (now - timedelta(days=47)).strftime('%Y-%m-%d %H:%M:%S')
    # ...up to XX days in the future
    end_str = (now + timedelta(days=0)).strftime('%Y-%m-%d %H:%M:%S')

    # Set up the URL parameters for the API request
    params = {'start': start_str, 'end': end_str, 'limit': 1000}
    # Securely fetch the API token from the environment variables
    api_token = os.getenv('SOAR_API_TOKEN')
    # Disguise the script as a browser to prevent being blocked by basic bot-filters
    headers = {'User-Agent': 'Mozilla/5.0'}
    
    # If a token was found, add it to the Authorization header
    if api_token: 
        headers['Authorization'] = api_token
    # If not, log a warning but try to proceed anyway (might fail if API requires auth)
    else: 
        logger.warning("SOAR_API_TOKEN not found in .env file. Proceeding without authentication.")

    # Initialize an empty list to store the extracted observations
    all_observations = []
    logger.info(f"Downloading AEON API data from {start_str} to {end_str}...")
    
    # Loop through the API pages (pagination) as long as a 'next' URL exists
    while url:
        # Make the GET request to the API
        response = requests.get(url, params=params, headers=headers)
        
        # If the request was successful (HTTP 200 OK)
        if response.status_code == 200:
            # Parse the response as JSON
            data = response.json()
            
            # Loop through each observation in the 'results' list
            for obs in data.get('results', []):
                # Set default values in case they are missing
                ra, dec, instrument = None, None, "UNKNOWN"
                try:
                    # Navigate the nested JSON to extract the target's coordinates
                    config = obs['request']['configurations'][0]
                    ra, dec = config['target'].get('ra'), config['target'].get('dec')
                    # Extract the instrument type, defaulting to GOODMAN if missing
                    instrument = config.get('instrument_type', 'GOODMAN')
                except (KeyError, IndexError, TypeError):
                    # Ignore errors if the structure is incomplete
                    pass

                # Append a clean, simplified dictionary to our list
                all_observations.append({
                    'id': obs.get('id'),
                    'object_name': obs.get('name'),
                    'proposal': obs.get('proposal'),
                    'start_time': obs.get('start'),
                    'instrument': instrument,
                    'ra': ra, 'dec': dec
                })
            
            # Update the URL to the 'next' page provided by the API (if any)
            url, params = data.get('next'), None  
        else:
            # Log an error if the server rejects the request (e.g., 403 Forbidden)
            logger.error(f"API Request failed: {response.status_code}. Response: {response.text}")
            break # Exit the loop on failure

    # If we successfully gathered observations
    if all_observations:
        # Define the output filename
        filename = 'processed_soar_observations.json'
        # Open the file in write mode and dump the JSON data with nice indentation
        with open(filename, 'w', encoding='utf-8') as f: 
            json.dump(all_observations, f, indent=4)
        # Log success and return the filename
        logger.info(f"Saved {len(all_observations)} observations to '{filename}'")
        return filename
    
    # If no data was found, log a warning and return None
    logger.warning("No data found.")
    return None

# If this script is executed directly, run the fetch function
if __name__ == "__main__":
    fetch_soar_data_to_json()

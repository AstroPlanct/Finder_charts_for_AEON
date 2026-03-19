# Import mathematics, logging, hashes, paths, and timing tools
import math
import logging
import hashlib
from pathlib import Path
import time
from functools import wraps

# Import numerical, request, and astronomical query tools
import numpy as np
import requests
import os
import pyvo
import astropy.units as u
from astropy.coordinates import SkyCoord, Angle
from astropy.io import fits
from astropy.time import Time
from astroquery.mast import Catalogs
from astroquery.gaia import Gaia
from astroquery.skyview import SkyView
from astroquery.irsa import Irsa

# Import Google API libraries
from googleapiclient.discovery import build
from google.oauth2 import service_account
from googleapiclient.http import MediaFileUpload

def setup_logger(name="aeon_pipeline", logfile="aeon_pipeline.log", level=logging.INFO):
    # Ensure the directory for the log file exists
    log_path = Path(logfile)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Create the logger object
    logger = logging.getLogger(name)
    logger.setLevel(level)
    
    # Only add handlers if they don't already exist (prevents duplicate log prints)
    if not logger.handlers:
        file_handler = logging.FileHandler(log_path, mode="a")
        formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    return logger

# Initialize the global logger for utils
logger = setup_logger(name="utils")

def retry_with_backoff(retries=5, backoff_in_seconds=2):
    # A Python Decorator to automatically retry a failed function (like a network request)
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            x = 0
            while True:
                try:
                    # Attempt the function execution
                    return func(*args, **kwargs)
                except Exception as e:
                    # If it reaches the max retries, fail and raise the error
                    if x == retries:
                        logger.error(f"❌ Failed after {retries} retries: {e}")
                        raise
                    
                    # Calculate wait time: 2s, 4s, 8s, 16s... (Exponential Backoff)
                    wait = (backoff_in_seconds * 2 ** x)
                    logger.warning(f"⚠️ Query failed ({e}). Retrying in {wait} seconds...")
                    time.sleep(wait)
                    x += 1
        return wrapper
    return decorator

def parse_coords(ra_str, dec_str):
    # Standardize coordinate strings (lowercase, strip whitespace)
    ra_str = str(ra_str).strip().lower()
    dec_str = str(dec_str).strip().lower()
    
    # Check if RA is in hours/minutes/seconds format or decimal format
    if ':' in ra_str or any(c in ra_str for c in 'hms'):
        ra = Angle(ra_str, unit=u.hourangle)
    else:
        ra = Angle(float(ra_str), unit=u.deg)
        
    # Check if DEC is in degrees/minutes/seconds format or decimal format
    if any(c in dec_str for c in 'dms') or ':' in dec_str:
        dec = Angle(dec_str, unit=u.deg)
    else:
        dec = Angle(float(dec_str), unit=u.deg)
        
    # Return coordinates in pure decimal degrees
    return ra.deg, dec.deg

def manage_cache_size(cache_dir="./fits_cache", max_size_gb=3.0):
    # Verify the cache folder exists
    cache_path = Path(cache_dir)
    if not cache_path.exists(): return
    
    # Convert GB limit to bytes
    max_size_bytes = max_size_gb * 1024 * 1024 * 1024
    files, total_size = [], 0
    
    try:
        with os.scandir(cache_dir) as it:
            for entry in it:
                if entry.is_file():
                    stat = entry.stat()
                    size = stat.st_size
                    # Guardamos la ruta, tamaño y fecha de modificación
                    files.append((entry.path, size, stat.st_mtime))
                    total_size += size
    except Exception as e:
        logger.error(f"Error reading cache directory: {e}")
        return
            
    # If the total size exceeds the limit, delete oldest files first
    if total_size > max_size_bytes:
        # Sort by modification time (index 2) ascending (oldest first)
        files.sort(key=lambda x: x[2])
        deleted_count = 0
        
        for path, size, mtime in files:
            try:
                os.remove(path)
                total_size -= size
                deleted_count += 1
                # Stop deleting once we are back under the limit
                if total_size <= max_size_bytes: break
            except Exception as e:
                logger.warning(f"Could not delete cache file {path}: {e}")
                
        if deleted_count > 0:
            logger.info(f"Cache management: Deleted {deleted_count} old files to free space.")

_http_sessions = {}

def get_http_session():
    pid = os.getpid()
    if pid not in _http_sessions:
        _http_sessions[pid] = requests.Session()
    return _http_sessions[pid]

@retry_with_backoff(retries=3)
def fetch_fits_cached(url, cache_dir="./fits_cache"):
    # Ensure cache directory exists
    Path(cache_dir).mkdir(parents=True, exist_ok=True)
    
    # Generate an MD5 hash of the URL to serve as a unique local filename
    url_hash = hashlib.md5(url.encode()).hexdigest()
    cache_file = Path(cache_dir) / f"{url_hash}.fits"
    
    # If file is already cached locally, open and return it
    if cache_file.exists(): 
        return fits.open(cache_file)
        
    session = get_http_session()
    response = session.get(url, timeout=30)
    
    # Validate the response
    if response is None or response.status_code != 200: return None
    # Validate it's a true FITS file by checking its header byte signature ('SIMPLE')
    if not response.content.startswith(b'SIMPLE'): return None
    
    # Write to local cache
    with open(cache_file, 'wb') as f: 
        f.write(response.content)
    # Read back and return
    return fits.open(cache_file)

@retry_with_backoff()
def query_stars_gaia(ra, dec, radius=3):
    # Execute an ADQL (SQL-like) query asynchronously to the Gaia DR3 catalog
    coord = SkyCoord(ra=ra * u.deg, dec=dec * u.deg, frame="icrs")
    query = f"""
    SELECT source_id, ra, dec, pmra, pmdec, phot_g_mean_mag, phot_bp_mean_mag, phot_rp_mean_mag, ruwe
    FROM gaiadr3.gaia_source
    WHERE 1 = CONTAINS(POINT('ICRS', ra, dec), CIRCLE('ICRS', {coord.ra.deg}, {coord.dec.deg}, {(radius*u.arcmin).to(u.deg).value}))
    AND ruwe < 1.4 AND visibility_periods_used > 8 AND astrometric_excess_noise < 1
    ORDER BY phot_g_mean_mag ASC
    """
    job = Gaia.launch_job_async(query)
    df = job.get_results().to_pandas().rename(columns={"phot_g_mean_mag": "mag"})
    
    # Apply Proper Motion adjustments to move stars from Epoch 2016.0 to current day
    df['pmra'], df['pmdec'] = df['pmra'].fillna(0), df['pmdec'].fillna(0)
    dt = Time.now().jyear - 2016.0
    df['ra'] += (df['pmra'] / np.cos(np.deg2rad(df['dec']))) * dt / 3600000.0
    df['dec'] += df['pmdec'] * dt / 3600000.0
    return df

@retry_with_backoff()
def query_stars_ps1(ra, dec, radius=3):
    # Query the Pan-STARRS catalog, filter out galaxies/junk (qualityFlag), sort by magnitude
    coord = SkyCoord(ra * u.deg, dec * u.deg)
    tbl = Catalogs.query_region(coord, radius=radius * u.arcmin, catalog="Panstarrs", table="stack", columns=["raMean", "decMean", "gPSFMag", "rPSFMag", "rKronMag", "qualityFlag"])
    tbl = tbl[(tbl["rPSFMag"] < 19) & (tbl["rPSFMag"] > 14) & (abs(tbl["rPSFMag"] - tbl["rKronMag"]) < 0.05) & (tbl["qualityFlag"] < 128)]
    tbl.sort("rPSFMag")
    return tbl.to_pandas().rename(columns={"raMean": "ra", "decMean": "dec", "gPSFMag": "mag", "rPSFMag": "mag_r"})

@retry_with_backoff()
def query_stars_ls(ra, dec, radius=6):
    # Query NOIRLab's Legacy Survey catalog using a TAP service
    tap_service = pyvo.dal.TAPService("https://datalab.noirlab.edu/tap")
    query = f"SELECT TOP 100 ra, dec, mag_g, mag_r, mag_z FROM ls_dr10.tractor WHERE type = 'PSF' AND ra BETWEEN {ra - radius/2/60} AND {ra + radius/2/60} AND dec BETWEEN {dec - radius/2/60} AND {dec + radius/2/60} AND mag_r < 18"
    return tap_service.run_async(query, language="ADQL").to_table().to_pandas().rename(columns={"mag_g": "mag"})

@retry_with_backoff()
def get_stars_2mass(ra, dec, radius=2):
    # Query the 2MASS Infrared catalog, keeping only cleanly detected stars (ph_qual 'A' or 'B')
    target = SkyCoord(ra * u.deg, dec * u.deg, frame="icrs")
    tbl = Irsa.query_region(target, radius=radius * u.arcmin, catalog="fp_psc")["ra", "dec", "j_m", "j_cmsig", "ph_qual", "cc_flg"]
    good = np.array([ph_qa[0] in ['A', 'B'] for ph_qa in tbl["ph_qual"]])
    return tbl[good].to_pandas().rename(columns={"j_m": "mag"})

def populate_header(hdu, w_mark, pixscale, imsize, s_name, ra, dec, npixels):
    # Helper function to standardize FITS headers across different image surveys
    for k, v in zip(['w_mark', 'pixscale', 'imsize', 's_name', 'ra', 'dec', 'numpix'], [w_mark, pixscale, imsize, s_name, ra, dec, npixels]):
        hdu[0].header[k] = v
    return hdu

def get_image_ps1(ra, dec, s_name, imsize=6):
    # Fetch Pan-STARRS image tile
    url = f"https://alasky.cds.unistra.fr/hips-image-services/hips2fits?width=500&height=500&fov={imsize/60}&ra={ra}&dec={dec}&hips=CDS/P/PanSTARRS/DR1/r"
    hdu = fetch_fits_cached(url)
    if not hdu or len(hdu) == 0: return ''
    return populate_header(hdu, 'PS1', imsize * 60 / len(hdu[0].data), imsize, s_name, ra, dec, len(hdu[0].data))

def get_image_ls(ra, dec, s_name, imsize=6):
    # Fetch NOIRLab Legacy Survey image tile
    numpix = math.ceil(60 * imsize / 0.26)
    url = f"http://legacysurvey.org/viewer/fits-cutout/?ra={ra}&dec={dec}&layer=dr8&pixscale=0.26&bands=r&size={numpix}"
    hdu = fetch_fits_cached(url)
    if not hdu or len(hdu) == 0: return ''
    return populate_header(hdu, 'LS', 0.26, imsize, s_name, ra, dec, numpix)

def get_image_decaps(ra, dec, s_name, imsize=6):
    # Fetch DECaPS image tile
    numpix = math.ceil(60 * imsize / 0.26)
    url = f"http://legacysurvey.org/viewer/fits-cutout/?layer=decaps2&ra={ra}&dec={dec}&pixscale=0.26&bands=r&size={numpix}"
    hdu = fetch_fits_cached(url)
    if not hdu or len(hdu) == 0: return ''
    return populate_header(hdu, 'LS', 0.26, imsize, s_name, ra, dec, numpix)

def get_image_dss(ra, dec, s_name, imsize=6):
    # Fetch Digitized Sky Survey (DSS) image tile as a final fallback
    url = f"http://archive.stsci.edu/cgi-bin/dss_search?v=poss2ukstu_red&r={ra}&dec={dec}&h={imsize}&w={imsize}&e=J2000"
    hdu = fetch_fits_cached(url)
    if not hdu or len(hdu) == 0: return ''
    return populate_header(hdu, 'DSS', imsize * 60 / len(hdu[0].data), imsize, s_name, ra, dec, len(hdu[0].data))

def get_image_2mass(ra, dec, s_name, imsize=6):
    # Attempt to fetch 2MASS image from SkyView
    url = f"https://skyview.gsfc.nasa.gov/current/cgi/runquery.pl?Position={ra},{dec}&Survey=2MASS-J&Radius={imsize/60}&Return=FITS"
    hdu = fetch_fits_cached(url)
    
    # If the direct URL fails, use astroquery's SkyView wrapper as a fallback
    if not hdu or len(hdu) == 0:
        try:
            images = SkyView.get_images(position=SkyCoord(ra * u.deg, dec * u.deg, frame="icrs"), survey=["2MASS-J"], radius=imsize * u.arcmin, pixels=500)
            if not images: return ''
            hdu = images[0]
        except: return ''
        
    npixels = len(hdu[0].data)
    im = hdu[0].data
    # Reject the image if the central portion is entirely full of NaN (empty space)
    cent, width = int(npixels / 2), int(0.05 * npixels)
    test_slice = slice(cent - width, cent + width)
    if np.isnan(im[test_slice, test_slice].flatten()).all() or (im[test_slice, test_slice].flatten() == 0).all(): 
        return ''
        
    return populate_header(hdu, '2MASS', imsize * 60 / npixels, imsize, s_name, ra, dec, npixels)

def get_image_fallbacks(ra, dec, s_name, imsize=5):
    # Helper to validate if a returned image is usable (not completely black/NaN)
    def is_valid(hdu):
        if not hdu or len(hdu) == 0 or hdu[0].data is None: return False
        im = hdu[0].data
        if np.all(np.isnan(im)) or np.all(im == 0) or (np.isnan(im).sum() / im.size > 0.90): return False
        return True

    # Loop through optical surveys in preference order until a valid image is found
    for func in [get_image_ls, get_image_ps1, get_image_decaps, get_image_dss]:
        hdu = func(ra, dec, s_name, imsize=imsize)
        if is_valid(hdu): return hdu
    # Raise error if no survey has coverage here
    raise TypeError("Could not get a valid optical image.")

# Define a global variable to hold the Google Drive service instance (Singleton)
_drive_service_instances = {}

def _get_drive_service(credentials_file="drive_credentials.json"):
    global _drive_service_instances
    pid = os.getpid()
    
    if pid in _drive_service_instances:
        return _drive_service_instances[pid]
        
    # Check if credentials file exists
    if not Path(credentials_file).exists():
        logger.warning(f"Drive credentials '{credentials_file}' not found.")
        return None
        
    try:
        # Load the Service Account credentials with read/write scopes
        creds = service_account.Credentials.from_service_account_file(
            credentials_file, 
            scopes=['https://www.googleapis.com/auth/drive.metadata.readonly', 'https://www.googleapis.com/auth/drive.file']
        )
        _drive_service_instances[pid] = build('drive', 'v3', credentials=creds)
        return _drive_service_instances[pid]
    except Exception as e:
        logger.error(f"Error authenticating with Google Drive: {e}")
        return None

def upload_to_drive(file_path, folder_id, credentials_file="drive_credentials.json"):
    # Grab the authenticated service
    service = _get_drive_service(credentials_file)
    if not service: return None
    try:
        # Prepare the file metadata and media upload object
        file_name = Path(file_path).name
        media = MediaFileUpload(str(file_path), mimetype='application/pdf', resumable=True)
        logger.info(f"Uploading {file_name} to Google Drive...")
        
        # Execute the upload (supportsAllDrives=True allows uploading to Shared Team Drives)
        file = service.files().create(body={'name': file_name, 'parents': [folder_id]}, media_body=media, fields='id', supportsAllDrives=True).execute()
        logger.info(f"Upload successful! Drive ID: {file.get('id')}")
        return file.get('id')
    except Exception as e:
        logger.error(f"Error uploading to Google Drive: {e}")
        return None

def check_file_in_drive(file_name, folder_id, credentials_file="drive_credentials.json"):
    # Grab the authenticated service
    service = _get_drive_service(credentials_file)
    if not service: return False
    try:
        # Search the drive folder for a file matching the exact name
        results = service.files().list(q=f"name='{file_name}' and '{folder_id}' in parents and trashed=false", spaces='drive', fields='files(id, name)', includeItemsFromAllDrives=True, supportsAllDrives=True).execute()
        # Return True if 1 or more files are found
        return len(results.get('files', [])) > 0
    except Exception as e:
        logger.error(f"Error querying Google Drive: {e}")
        return False

def get_or_create_drive_folder(folder_name, parent_folder_id, credentials_file="drive_credentials.json"):
    # Grab the authenticated service
    service = _get_drive_service(credentials_file)
    if not service: return None
    try:
        # Check if the subfolder already exists in the parent folder
        results = service.files().list(q=f"name='{folder_name}' and '{parent_folder_id}' in parents and mimeType='application/vnd.google-apps.folder' and trashed=false", spaces='drive', fields='files(id, name)', includeItemsFromAllDrives=True, supportsAllDrives=True).execute()
        items = results.get('files', [])
        
        # If found, return its ID
        if items: 
            return items[0]['id']
        
        # If not found, create a new folder with that name
        folder = service.files().create(body={'name': folder_name, 'mimeType': 'application/vnd.google-apps.folder', 'parents': [parent_folder_id]}, fields='id', supportsAllDrives=True).execute()
        logger.info(f"Created new Drive subfolder: {folder_name}")
        return folder.get('id')
    except Exception as e:
        logger.error(f"Error managing Google Drive folder: {e}")
        return None

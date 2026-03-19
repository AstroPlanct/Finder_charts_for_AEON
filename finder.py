import argparse
import tempfile
from pathlib import Path
import warnings
from concurrent.futures import ThreadPoolExecutor
import numpy as np
import matplotlib as mpl
# Force Matplotlib to use the 'Agg' backend (Headless mode) to prevent server crashes
mpl.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Circle, Rectangle
import astropy.units as u
from astropy.coordinates import SkyCoord
from astropy.wcs import WCS
from astropy.utils.exceptions import AstropyWarning
from astropy.visualization import ImageNormalize, ZScaleInterval
from reproject import reproject_interp

# Import utilities for data fetching and Drive uploads
from utils import (query_stars_gaia, query_stars_ps1, query_stars_ls, get_stars_2mass, parse_coords, get_image_2mass, get_image_fallbacks, setup_logger, upload_to_drive)

# Suppress annoying warnings from Astropy regarding WCS headers
warnings.simplefilter('ignore', category=AstropyWarning)
warnings.simplefilter('ignore', category=UserWarning)
# Set default font size for the plots
mpl.rcParams["font.size"] = 15

# Initialize logger
logger = setup_logger(name="finder_engine")

def get_stars_optical(ra, dec, radius=3.0):
    # Loop through catalogs in order of preference: Gaia -> PS1 -> LS
    for func, name in [(query_stars_gaia, "Gaia"), (query_stars_ps1, "Pan-STARRS"), (query_stars_ls, "Legacy Survey")]:
        try:
            # Attempt to fetch stars
            stars = func(ra, dec, radius=radius)
            # If successful and not empty, return them immediately
            if stars is not None and not stars.empty: 
                return stars
        except Exception as e: 
            # Log failure and proceed to the next fallback catalog
            logger.warning(f"{name} query failed: {e}")
    # Return empty string if all fail
    return ''

def get_stars(ra, dec, radius=3.0, wv='optical'):
    # Force a large 7.0 arcminute search to capture distant stars in one network request
    search_radius = 7.0 
    logger.info(f"Querying {wv.upper()} reference stars within {search_radius}'...")
    
    # Query optical or IR based on requested wavelength
    stars = get_stars_optical(ra, dec, search_radius) if wv == 'optical' else get_stars_2mass(ra, dec, search_radius)
    
    # If IR (2MASS) fails, fallback to optical stars for the IR plot
    if wv == 'ir' and (isinstance(stars, str) or stars.empty):
        stars = get_stars_optical(ra, dec, search_radius)

    # If we successfully found stars
    if not isinstance(stars, str) and not stars.empty:
        # Create SkyCoord objects for the target and the found stars
        target = SkyCoord(ra * u.deg, dec * u.deg, frame="icrs")
        coords = SkyCoord(stars["ra"].values * u.deg, stars["dec"].values * u.deg, frame="icrs")
        
        # Calculate spherical offsets (North/South, East/West)
        dra, ddec = target.spherical_offsets_to(coords)
        stars["offset_EW_arcsec"], stars["offset_NS_arcsec"] = dra.to(u.arcsec).value, ddec.to(u.arcsec).value
        
        # Calculate total absolute distance (Hypotenuse)
        stars["total_dist_arcsec"] = np.sqrt(stars["offset_EW_arcsec"]**2 + stars["offset_NS_arcsec"]**2)
        
        # Exclude stars that are closer than 2.0 arcseconds to the target (blending prevention)
        stars = stars[stars["total_dist_arcsec"] >= 2.0]
        
        # Sort by distance (closest first) and return
        return stars.sort_values(by="total_dist_arcsec").reset_index(drop=True)
    return ''

def add_compass_rose(ax, visible_size, cx, cy, wcs, is_rotated=False, col="#E69F00"):
    # Calculate lengths and margins for the compass arrows
    length, margin = visible_size * 0.08, visible_size * 0.10
    # Determine placement based on whether the image is inverted
    x0 = (cx + visible_size / 2) - margin if is_rotated else (cx - visible_size / 2) + margin
    y0 = (cy - visible_size / 2) + margin if is_rotated else (cy + visible_size / 2) - margin
    
    # Calculate pixel offsets corresponding to True North and East using WCS
    world_origin = SkyCoord(wcs.wcs.crval[0] * u.deg, wcs.wcs.crval[1] * u.deg, frame="icrs")
    def get_vec(ang):
        p = wcs.world_to_pixel(world_origin.directional_offset_by(ang, 1 * u.arcmin))
        dx, dy = p[0] - wcs.wcs.crpix[0], p[1] - wcs.wcs.crpix[1]
        mag = np.sqrt(dx**2 + dy**2)
        return (dx / mag) * length, (dy / mag) * length if mag != 0 else (0, 0)

    dnx, dny = get_vec(0 * u.deg)
    dex, dey = get_vec(90 * u.deg)

    # Draw the arrows and text labels using the dynamic 'col' argument
    for dx, dy, label in [(dnx, dny, "N"), (dex, dey, "E")]:
        ax.arrow(x0, y0, dx, dy, color=col, width=visible_size*0.002, head_width=visible_size*0.015, zorder=20)
        ax.text(x0 + dx*1.6, y0 + dy*1.6, label, color=col, ha="center", va="center", fontweight="bold", zorder=20)

def draw_crosshair(ax, x, y, gap, arm, color, label=None, offset=0):
    # Draw four lines forming a broken crosshair around the coordinates
    for dx1, dx2, dy1, dy2 in [(gap, arm, 0, 0), (-arm, -gap, 0, 0), (0, 0, gap, arm), (0, 0, -arm, -gap)]:
        ax.plot([x + dx1, x + dx2], [y + dy1, y + dy2], color=color, lw=3 if not label else 2)
    # Add an optional text label (e.g., "a1", "b2")
    if label: 
        ax.text(x + arm + offset, y + arm + offset, label, color=color, fontsize=12, fontweight='bold')

def draw_scale_bar(ax, cx, cy, target_npix, pixscale, is_rotated=False, col='blue'):
    # Calculate pixels for 1 arcminute (60 arcseconds)
    bar_px, bx0, by0 = 60 / pixscale, (cx - target_npix/2) + (target_npix * 0.05), (cy - target_npix/2) + (target_npix * 0.05)
    # Draw the line using the dynamic color
    ax.plot([bx0, bx0 + bar_px], [by0, by0], color=col, lw=3)
    # Add the "1'" text using the dynamic color
    ax.text(bx0 + bar_px/2, by0 + (target_npix * 0.03), "1'", color=col, ha='center', va='top' if is_rotated else 'bottom', fontweight='bold')
    
def fits2image_projected(hdu_opt, hdu_ir, stars_opt, stars_ir, pa_deg=0, imsize=3.0, slit_width=1.0, slit_height=234.0, is_parallactic=False, ra_hms="", dec_dms="", ra_deg="", dec_deg=""):
    # Create the main figure canvas
    fig = plt.figure(figsize=(22, 16))
    # Define a grid layout: 2 rows, 3 columns (Left Image, Rotated Image, Text Box)
    spec = fig.add_gridspec(ncols=3, nrows=2, width_ratios=[4, 4, 2.8], left=0.05, right=0.95, wspace=0.15, hspace=0.2)
    # Set up the text box on the far right    
    ax_text = fig.add_subplot(spec[:, 2]); ax_text.axis("off"); ax_text.set_xlim(0, 1); ax_text.set_ylim(0, 1)

    # Extract header info from whichever FITS file successfully downloaded
    base_hdu = hdu_opt if hdu_opt else hdu_ir
    s_name = base_hdu[0].header['s_name']
    # Muestra máximo 25 caracteres para evitar solapamientos
    display_name = s_name if len(s_name) <= 25 else s_name[:22] + "..."
    ax_text.text(0.0, 0.95, f"{display_name}", color="#8B0000", fontsize=22, fontweight="bold")
    
    # Write the main Title and both coordinates system    
    y_ra, y_dec = 0.89, 0.85
    ax_text.text(0.0, y_ra, "RA:", color="#000080", fontsize=14, fontweight="bold")
    ax_text.text(0.0, y_dec, "DEC:", color="#000080", fontsize=14, fontweight="bold")
    
    ax_text.text(0.15, y_ra, ra_hms, color="#000080", fontsize=14, fontweight="bold")
    ax_text.text(0.15, y_dec, dec_dms, color="#000080", fontsize=14, fontweight="bold")
    
    ax_text.text(0.60, y_ra, f"({ra_deg})", color="#000080", fontsize=14, fontweight="bold")
    ax_text.text(0.60, y_dec, f"({dec_deg})", color="#000080", fontsize=14, fontweight="bold")

    # Print a warning if the observer requested parallactic angle    
    if is_parallactic: 
        ax_text.text(0.0, 0.80, "⚠️ ROTATE TO PARALLACTIC ⚠️", color="red", fontsize=14, fontweight="bold")

# AEON Inner helper function to plot a single row (e.g., Optical or IR row)
    def plot_row(hdu, row_idx, cat_name, filt, y_start, stars_df, p_dir, p_rot):
        # UNITS: slit_height is arcsec, dynamic_imsize is arcmin, pixscale is arcsec/pix
        pix, ra, dec, npix = hdu[0].header['pixscale'], hdu[0].header['ra'], hdu[0].header['dec'], hdu[0].header['numpix']
        
        # Construct a synthetic WCS to handle the requested rotation (PA)
        wcs = WCS(naxis=2)
        wcs.wcs.crpix, wcs.wcs.crval, wcs.wcs.ctype = [npix / 2, npix / 2], [ra, dec], ["RA---TAN", "DEC--TAN"]
        pa_rad = np.deg2rad(pa_deg)
        wcs.wcs.cd = np.array([[np.cos(pa_rad), np.sin(pa_rad)], [-np.sin(pa_rad), np.cos(pa_rad)]]) @ np.array([[-pix / 3600, 0], [0, pix / 3600]])

        try:
            im, _ = reproject_interp((hdu[0].data, WCS(hdu[0].header)), wcs, shape_out=(npix, npix))
        except Exception:
            wcs_base = WCS(naxis=2)
            wcs_base.wcs.crpix, wcs_base.wcs.crval = [npix / 2, npix / 2], [ra, dec]
            wcs_base.wcs.ctype, wcs_base.wcs.cdelt = ["RA---TAN", "DEC--TAN"], [-pix / 3600, pix / 3600]
            im, _ = reproject_interp((hdu[0].data, wcs_base), wcs, shape_out=(npix, npix))

        if im is None or np.all(np.isnan(im)): 
            norm = None
        else:
            v_med = np.nanmedian(im) if not np.all(np.isnan(im)) else 0.0
            im_safe = np.nan_to_num(im, nan=v_med)
            interval = ZScaleInterval(contrast=0.045)
            try: vmin, vmax = interval.get_limits(im_safe)
            except Exception: vmin, vmax = np.min(im_safe), np.max(im_safe)
            norm = ImageNormalize(im_safe, vmin=vmin, vmax=vmax)

        c_main, c_rot_header = "#0033CC", "#CC0000"
        n_d = "I" if row_idx == 0 else "III"
        n_r = "II" if row_idx == 0 else "IV"

        ax_dir, ax_rot = fig.add_subplot(spec[row_idx, 0], projection=wcs), fig.add_subplot(spec[row_idx, 1], projection=wcs)
        cx, target_npix = npix / 2, (imsize * 60) / pix

        for ax, is_rot, num, c_t, c_rose, pa_val in [(ax_dir, False, n_d, c_main, "#E69F00", pa_deg), (ax_rot, True, n_r, c_rot_header, "#CC0000", (pa_deg+180)%360)]:
            ax.imshow(im, origin="lower", norm=norm, cmap="gray_r")
            if is_rot: 
                ax.invert_xaxis(); ax.invert_yaxis()
            
            lim_sign = -1 if is_rot else 1
            ax.set_xlim(cx - lim_sign*target_npix/2, cx + lim_sign*target_npix/2)
            ax.set_ylim(cx - lim_sign*target_npix/2, cx + lim_sign*target_npix/2)
            
            ax.set_title(f"{num} | FOV: {imsize:.1f}' | {cat_name} ({filt}) | PA: {pa_val:.1f}°", color=c_t, fontweight="bold", loc='right')
            ax.grid(color="white", ls="dotted", alpha=0.5)
            
            add_compass_rose(ax, target_npix, cx, cx, wcs, is_rotated=is_rot, col=c_rose)
            draw_scale_bar(ax, cx, cx, target_npix, pix, is_rotated=is_rot, col='blue' if not is_rot else 'purple')

            tx, ty = wcs.world_to_pixel(SkyCoord(ra * u.deg, dec * u.deg, frame="icrs"))
            draw_crosshair(ax, tx, ty, gap=4.0/pix, arm=12.0/pix, color="#D55E00")
            ax.add_patch(Circle((tx, ty), radius=1.0/pix, edgecolor='#D55E00', facecolor='none', lw=1.5, ls='--'))
            ax.add_patch(Rectangle((tx - (slit_width/pix)/2, ty - (slit_height/pix)/2), slit_width/pix, slit_height/pix, facecolor='green', edgecolor='lime', alpha=0.15, zorder=5))

        if not isinstance(stars_df, str) and not stars_df.empty:
            colors = ["#FFD700", "#00BFFF", "#FF00FF"]
            
            # 1. TABLA DIRECTA (Gráficos I o III)
            ax_text.text(0, y_start, f"Chart {n_d} Ref Stars (Offsets):", fontweight="bold", fontsize=11, color=c_main)
            for i, (_, row) in enumerate(stars_df.head(3).iterrows()):
                sx, sy = wcs.world_to_pixel(SkyCoord(row.ra * u.deg, row.dec * u.deg, frame="icrs"))
                draw_crosshair(ax_dir, sx, sy, gap=2.5/pix, arm=7.0/pix, color=colors[i], label=f"{p_dir}{i+1}", offset=3.0/pix)
                
                y_p = y_start - 0.035 - (i * 0.035)
                ax_text.text(0.00, y_p, rf"$\bf{{{p_dir}{i+1}}}$", color=colors[i], fontsize=12)
                ax_text.text(0.10, y_p, f"{row.mag:.1f}m", color=colors[i], fontsize=12)
                ax_text.text(0.35, y_p, rf"$\bf{{{abs(row.offset_EW_arcsec):.1f}''\ {'W' if row.offset_EW_arcsec >= 0 else 'E'}}}$", color=colors[i], fontsize=12)
                ax_text.text(0.70, y_p, rf"$\bf{{{abs(row.offset_NS_arcsec):.1f}''\ {'S' if row.offset_NS_arcsec >= 0 else 'N'}}}$", color=colors[i], fontsize=12)
            
            # 2. TABLA ROTADA (Gráficos II o IV)
            y_rot_start = y_start - 0.16 # Ligeramente más espacio entre I y II
            ax_text.text(0, y_rot_start, f"Chart {n_r} Ref Stars (Offsets):", fontweight="bold", fontsize=11, color=c_rot_header)
            for i, (_, row) in enumerate(stars_df.head(3).iterrows()):
                sx, sy = wcs.world_to_pixel(SkyCoord(row.ra * u.deg, row.dec * u.deg, frame="icrs"))
                draw_crosshair(ax_rot, sx, sy, gap=2.5/pix, arm=7.0/pix, color=colors[i], label=f"{p_rot}{i+1}", offset=3.0/pix)
                
                # INVERTIR OFFSETS PARA EL GRÁFICO ROTADO (Cambia el signo para voltear N/S y E/W)
                inv_EW = -row.offset_EW_arcsec
                inv_NS = -row.offset_NS_arcsec
                
                y_p = y_rot_start - 0.035 - (i * 0.035)
                ax_text.text(0.00, y_p, rf"$\bf{{{p_rot}{i+1}}}$", color=colors[i], fontsize=12)
                ax_text.text(0.10, y_p, f"{row.mag:.1f}m", color=colors[i], fontsize=12)
                ax_text.text(0.35, y_p, rf"$\bf{{{abs(inv_EW):.1f}''\ {'W' if inv_EW >= 0 else 'E'}}}$", color=colors[i], fontsize=12)
                ax_text.text(0.70, y_p, rf"$\bf{{{abs(inv_NS):.1f}''\ {'S' if inv_NS >= 0 else 'N'}}}$", color=colors[i], fontsize=12)
            
            # Retorna un piso con MAYOR ESPACIO (-0.32) para separar correctamente las tablas II y III
            return y_start - 0.32 
        else:
            return y_start - 0.05
    
    # Call the row plotting function for Optical and IR data (if successfully downloaded)
    # Initialize dynamic y_coordinate tracker below titles and RA/DEC headers
    current_y_text = 0.78
    if is_parallactic: 
        current_y_text = 0.76 # Allow room for Red Parallactic Warning

    # Standard Colors for Charts & Tables
    col_opt_direct, col_opt_rot = "#0033CC", "#CC0000" # Blue & Red
    col_ir_direct, col_ir_rot = "#008000", "#800080" # Green & Purple (IR colors)

# Render Optical Row (Chart I & II, Table Header in Blue)
    if hdu_opt: 
        wv_mark = hdu_opt[0].header.get('w_mark', 'Optical')
        filt_mark = "Red" if wv_mark == "DSS" else "r-band"
        # Pasa 'a' para el gráfico I, y 'b' para el gráfico II
        current_y_text = plot_row(hdu_opt, 0, wv_mark, filt_mark, current_y_text, stars_opt, p_dir="a", p_rot="b")

    # Render IR Row (Chart III & IV, Table Header in Green)
    if hdu_ir: 
        # Pasa 'c' para el gráfico III, y 'd' para el gráfico IV
        current_y_text = plot_row(hdu_ir, 1, "2MASS", "J-band", current_y_text, stars_ir, p_dir="c", p_rot="d")
        
    return fig

def run_pipeline(s_name, ra_str, dec_str, instrument="GOODMAN", pa_deg=0.0, imsize=3.0, radius=1.0, contrast=0.045, slit_width=1.0, output_folder=None, drive_folder=None, is_parallactic=False):
    ra, dec = parse_coords(ra_str, dec_str)
    
    # Generate both coordinate strings using astropy SkyCoord
    target_coord = SkyCoord(ra * u.deg, dec * u.deg, frame="icrs")
    ra_hms = target_coord.ra.to_string(unit=u.hour, sep=':', precision=2, pad=True)
    dec_dms = target_coord.dec.to_string(unit=u.deg, sep=':', precision=2, pad=True, alwayssign=True)
    ra_deg = f"{ra:.5f}°"
    dec_deg = f"{dec:.5f}°"

    clean_inst = str(instrument).upper().replace(' ', '').replace('4.1', '')
    
    # AEON Instrument Dictionary configuring physical Slit Height, minimum, and maximum valid FOV
    INSTRUMENT_SPECS = {
        'GOODMAN': {'slit_h': 234.0, 'min_fov': 1.8, 'max_fov': 7.2},
        'GMOS':    {'slit_h': 108.0, 'min_fov': 2.0, 'max_fov': 5.5},
        'TS4':     {'slit_h': 28.0, 'min_fov': 1.0, 'max_fov': 4.0}, 
        'DEFAULT': {'slit_h': 234.0, 'min_fov': 1.8, 'max_fov': 7.0}
    }
    # Retrieve specs using the cleaned instrument name
    specs = INSTRUMENT_SPECS.get(clean_inst, INSTRUMENT_SPECS['DEFAULT'])

    # Query Optical and IR stars concurrently to save network time
    with ThreadPoolExecutor(max_workers=2) as executor:
        stars_opt = executor.submit(get_stars, ra, dec, 7.0, 'optical').result()
        stars_ir = executor.submit(get_stars, ra, dec, 7.0, 'ir').result()

    # Calculate the maximum distance of the selected top 3 stars to determine the required FOV
    max_dist = max([max([abs(r['offset_EW_arcsec'])/60, abs(r['offset_NS_arcsec'])/60]) for df in [stars_opt, stars_ir] if not isinstance(df, str) and not df.empty for _, r in df.head(3).iterrows()] + [0.0])
    
    # Calculate the ideal FOV to wrap the stars, plus 0.4' padding
    ideal_fov = (max_dist * 2) + 0.4 if max_dist > 0 else imsize
    
    # Constrain the final FOV to strictly respect the physical limits of the telescope camera
    dynamic_imsize = round(max(specs['min_fov'], min(ideal_fov, specs['max_fov'])), 1)
    
    # Download Optical and IR FITS images concurrently (asking for a 50% larger image to allow rotation cropping)
    with ThreadPoolExecutor(max_workers=2) as executor:
        f_opt = executor.submit(get_image_fallbacks, ra, dec, s_name, dynamic_imsize*1.5)
        f_ir = executor.submit(get_image_2mass, ra, dec, s_name, dynamic_imsize*1.5)
        try: hdu_opt = f_opt.result()
        except: hdu_opt = None
        try: hdu_ir = f_ir.result()
        except: hdu_ir = None

    # Abort if absolutely no images could be downloaded
    if not hdu_opt and not hdu_ir: 
        raise ValueError("Could not fetch ANY images.")
            
    # Build the plot using the fetched data and dynamic constraints
    fig = fits2image_projected(hdu_opt, hdu_ir, stars_opt, stars_ir, pa_deg=pa_deg, imsize=dynamic_imsize, slit_width=slit_width, slit_height=specs['slit_h'], is_parallactic=is_parallactic, ra_hms=ra_hms, dec_dms=dec_dms, ra_deg=ra_deg, dec_deg=dec_deg)
    
    expected_filename = f"{s_name}_{clean_inst}_FOV{dynamic_imsize}_PA{'PARA' if is_parallactic else pa_deg}.pdf"
    
    # Handle Local Saving vs Temp Uploading
    if output_folder:
        out_dir = Path(output_folder)
        out_dir.mkdir(parents=True, exist_ok=True)
        base = out_dir / expected_filename
        fig.savefig(base, format="pdf", bbox_inches="tight", pad_inches=0.02)
        logger.info(f"Saved locally: {base}")
        if drive_folder: 
            upload_to_drive(base, drive_folder)
    else:
        # If no local saving is requested, but Drive upload is, use a temporary file
        if drive_folder:
            with tempfile.TemporaryDirectory() as tmpdir:
                temp_path = Path(tmpdir) / expected_filename
                fig.savefig(temp_path, format="pdf", bbox_inches="tight", pad_inches=0.02)
                upload_to_drive(temp_path, drive_folder)
                logger.info(f"Uploaded to Drive (Skipped local save): {expected_filename}")
        else:
            logger.warning("Neither output_folder nor drive_folder provided. Chart generated but discarded.")
            
    # Explicitly clear and close the Matplotlib figure to prevent massive memory leaks
    fig.clf() 
    plt.close('all')
    

# If executed from CLI, parse arguments and run
if __name__ == "__main__":
    args = argparse.ArgumentParser()
    args.add_argument("--ra", dest="ra_", required=True)
    args.add_argument("--dec", dest="dec_", required=True)
    args.add_argument("--s-name", default="Target")
    args.add_argument("--pa-deg", type=float, default=0.0)
    args.add_argument("--instrument", type=str, default="GOODMAN")
    args.add_argument("--output-folder", type=str, default='./finder_charts/')
    parsed = args.parse_args()
    run_pipeline(s_name=parsed.s_name, ra_str=parsed.ra_, dec_str=parsed.dec_, instrument=parsed.instrument, pa_deg=parsed.pa_deg, output_folder=parsed.output_folder)

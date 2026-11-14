"""Project-wide configuration and constants.

All values here are sourced from the authoritative USGS Astropedia record for the
MSL Gale Merged Orthophoto Mosaic (v3) and from the mandatory project rules.
Nothing in this file is invented; see README.md for provenance.
"""

from __future__ import annotations

import os

# ---------------------------------------------------------------------------
# Paths (relative to the project root)
# ---------------------------------------------------------------------------
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

DATA_DIR = os.path.join(PROJECT_ROOT, "data")
RAW_DIR = os.path.join(DATA_DIR, "raw")
PROCESSED_DIR = os.path.join(DATA_DIR, "processed")
VECTOR_DIR = os.path.join(DATA_DIR, "vector")
METADATA_DIR = os.path.join(PROJECT_ROOT, "metadata")
OUTPUTS_DIR = os.path.join(PROJECT_ROOT, "outputs")

MANIFEST_PATH = os.path.join(PROJECT_ROOT, "manifest.json")
README_PATH = os.path.join(PROJECT_ROOT, "README.md")

# ---------------------------------------------------------------------------
# Planetary body (mandatory project rules)
# ---------------------------------------------------------------------------
PLANET = "Mars"
IAU_IDENTIFIER = 49900               # IAU body identifier for Mars
MARS_SPHERE_RADIUS_M = 3396190.0     # Mars 2000 sphere radius (metres)

# Gale Crater centre used for the metric compute CRS (~5.4 S, 137.8 E)
GALE_CENTER_LAT = -5.4
GALE_CENTER_LON = 137.8

# ---------------------------------------------------------------------------
# Source dataset (authoritative original raster)
# ---------------------------------------------------------------------------
DATASET_ID = "msl_gale_orthophoto_mosaic_25cm_v3"
DATASET_NAME = "Mars MSL Gale Merged Orthophoto Mosaic 25cm"
DATASET_FILENAME = "MSL_Gale_Orthophoto_Mosaic_25cm_v3.tif"
SOURCE_URL = (
    "https://asc-pds-services.s3.us-west-2.amazonaws.com/"
    "mosaic/MSL_Gale_Orthophoto_Mosaic_25cm_v3.tif"
)
NATIVE_VSI_PATH = "/vsicurl/" + SOURCE_URL

# Viewer URL supplied by the user (NASA Mars Trek; a browser application, not a raster)
VIEWER_URL = (
    "https://trek.nasa.gov/mars/#v=0.1&x=137.50484875935194&y=-4.587047023176908&z=9"
    "&p=urn%3Aogc%3Adef%3Acrs%3AEPSG%3A%3A104905"
    "&d=&l=curiosity_hirise_mosaic%2Ctrue%2C1"
    "&l=Gale_CTX_BlockAdj_dd%2Ctrue%2C1&locale=&b=mars"
    "&e=137.05509596012425%2C-5.044352922849646%2C137.95460155857964%2C-4.129741123504169"
    "&sfz=&w="
)

# Source metadata extracted from the USGS Astropedia FGDC record (see README).
SOURCE_METADATA = {
    "authors": "Fred J. Calef III and Timothy Parker",
    "originators": "JPL-Caltech, NASA, USGS Astrogeology Science Center, University of Arizona",
    "publisher": "USGS Astrogeology Science Center",
    "publication_date": "2016-10-20",
    "edition": "version 3",
    "recommended_citation": (
        "Calef III, F. J., & Parker, T. (2016). MSL Gale Merged Orthophoto Mosaic. "
        "PDS Annex, U.S. Geological Survey."
    ),
    "map_projection_name": "Equirectangular",
    "latitude_type": "Planetocentric",
    "longitude_direction": "Positive East",
    "longitude_domain": "-180 to 180",
    "radius_a_m": 3396190,
    "radius_c_m": 3396190,
    "control_net": "MOLA",
    "declared_resolution_m": 0.25,
    "declared_width": 180000,
    "declared_height": 280000,
    "declared_bands": 1,
    "declared_bit_type": 8,
    "declared_min_lon": 137.094719,
    "declared_max_lon": 137.853896,
    "declared_min_lat": -5.249525,
    "declared_max_lat": -4.068583,
    "external_file_size": "23 GB (as listed; actual HTTP Content-Length differs)",
    "checksum_md5": "e1b8670b605eb593dc1d0551f6c45b64",
    "native_environment": "ESRI ArcInfo",
}

# Bounding box of the *Trek WMTS presentation layer* (rendered tiles) that was
# referenced by the viewer URL. Recorded for comparison with the source raster.
TREK_LAYER = {
    "layer_id": "curiosity_hirise_mosaic",
    "wmts_capabilities": (
        "https://trek.nasa.gov/tiles/Mars/EQ/curiosity_hirise_mosaic/1.0.0/"
        "WMTSCapabilities.xml"
    ),
    "wmts_crs": "urn:ogc:def:crs:EPSG::104905",
    "bbox_lon_lat": [137.1224669, -4.9254743, 137.7298129, -4.2489588],
}

# ---------------------------------------------------------------------------
# Remote access tuning (partial reads over HTTP)
# ---------------------------------------------------------------------------
GDAL_ENV = {
    "GDAL_DISABLE_READDIR_ON_OPEN": "EMPTY_DIR",
    "CPL_VSIL_CURL_ALLOWED_EXTENSIONS": ".tif,.tiff",
    "GDAL_HTTP_VERSION": "2",
    "GDAL_HTTP_MULTIPLEXING": "YES",
    "GDAL_HTTP_MULTIRANGE": "YES",
    "GDAL_HTTP_MERGE_CONSECUTIVE_RANGES": "YES",
    "GDAL_HTTP_MAX_RETRY": "3",
    "VSI_CACHE": "TRUE",
    "VSI_CACHE_SIZE": "50000000",
    "GDAL_NUM_THREADS": "ALL_CPUS",
}

# Upper bound on the number of bytes one AOI extraction may transfer. The
# source rows are stored back-to-back, so a window of ``n`` rows costs
# ``n * width`` bytes (a full-width band) rather than ``n * window_width``.
MAX_TRANSFER_BYTES = 600_000_000      # ~600 MB per AOI (well under the 50 GB source)

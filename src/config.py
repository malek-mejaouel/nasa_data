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

# ---------------------------------------------------------------------------
# Second dataset: local GeoTIFF provided by the user in ressources/
# ---------------------------------------------------------------------------
# The file is the `curiosity_hirise_mosaic` Mars Trek layer footprint, stored in
# the geographic Mars 2000 CRS (ESRI:104905 / GCS_Mars_2000). Its bounds are
# identical to TREK_LAYER["bbox_lon_lat"]. It is read directly from disk
# (read-only) which makes whole-raster statistics feasible.
LOCAL_DATASET_ID = "curiosity_hirise_mosaic"
LOCAL_DATASET_NAME = "Mars Curiosity HiRISE Mosaic (Gale Crater)"
LOCAL_DATASET_FILENAME = "curiosity_hirise_mosaic.tif"
LOCAL_SOURCE_DIR = os.path.join(PROJECT_ROOT, "ressources")
LOCAL_SOURCE_PATH = os.path.join(LOCAL_SOURCE_DIR, LOCAL_DATASET_FILENAME)
LOCAL_SOURCE_ADDRESS = "ressources/" + LOCAL_DATASET_FILENAME

LOCAL_SOURCE_METADATA = {
    "authors": "USGS Astrogeology Science Center",
    "publisher": "USGS Astrogeology Science Center",
    "recommended_citation": (
        "Mars Curiosity HiRISE Mosaic, USGS Astrogeology Science Center, "
        "NASA Mars Trek (trek.nasa.gov)."
    ),
    "provenance_note": (
        "Locally supplied GeoTIFF; its footprint and CRS match the Mars Trek "
        "`curiosity_hirise_mosaic` WMTS layer (urn:ogc:def:crs:EPSG::104905). "
        "The exact upstream processing chain of this particular file is not "
        "documented inside the file itself."
    ),
    "latitude_type": "Planetocentric",
    "longitude_direction": "Positive East",
    "longitude_domain": "-180 to 180",
    "radius_a_m": 3396190,
    "radius_c_m": 3396190,
}

# ---------------------------------------------------------------------------
# LAYER STACK — Layers 2..5 (see src/layer_registry.py)
# ---------------------------------------------------------------------------
# A *dataset* is a source artefact; a *layer* is a processed, viewer-ready
# output in the map stack. Layer 1 (imagery) is produced by the existing
# pipeline. Layers 2..5 are declared below as data so that adding a layer is a
# configuration change, not a code change (see layer_registry.py).

LAYER_STACK_JSON = os.path.join(METADATA_DIR, "layer_stack.json")

# --- Layer 2 — Elevation (raster, continuous -> bilinear) -------------------
# USGS Astropedia "Mars MSL Gale Merged DEM 1 m (v3)". Verified live: HTTP 200,
# Content-Length 3,868,256,546 bytes, image/tiff, Accept-Ranges: bytes.
# Native CRS ESRI:103885 = Mars_2000_Equidistant_Cylindrical_sphere
# (projected equirectangular in metres, R = 3396190 m, not an Earth CRS).
# Layout: 1-row-per-strip (block 1 x 32980), LZW, no overviews -> the existing
# banded remote-read strategy applies. Values float32, NoData -32767.0.
DEM_LAYER_ID = "layer_2_elevation"
DEM_DATASET_ID = "msl_gale_merged_dem_1m_v3"
DEM_NAME = "Mars MSL Gale Merged DEM (1 m)"
DEM_FILENAME = "MSL_Gale_DEM_Mosaic_1m_v3.tif"
DEM_SOURCE_URL = (
    "https://planetarymaps.usgs.gov/mosaic/Mars/MSL/MSL_Gale_DEM_Mosaic_1m_v3.tif"
)
DEM_VSI_PATH = "/vsicurl/" + DEM_SOURCE_URL
DEM_OUTPUT_BASENAME = "dem"
DEM_NODATA = -32767.0
# Vertical units are stated by the authoritative publisher record (see README).
# They are NOT inferred from the pixels; the enrichment carries this evidence.
DEM_VERTICAL_UNIT = "metre"
DEM_BAND_DESCRIPTION = "Elevation (MOLA-tied DEM)"
DEM_SOURCE_METADATA = {
    "publisher": "USGS Astrogeology Science Center",
    "product": "Mars MSL Gale Merged DEM Mosaic 1 m (v3)",
    "product_page": "https://astrogeology.usgs.gov/search/map/mars_msl_gale_merged_dem_1m",
    "recommended_citation": (
        "Mars MSL Gale Merged DEM Mosaic 1 m, USGS Astrogeology Science Center, "
        "PDS Annex."
    ),
    "vertical_crs_units": "Meters (metres) — stated by the publisher record",
    "map_projection_name": "Equirectangular (projected, metres)",
    "latitude_type": "Planetocentric",
    "longitude_direction": "Positive East",
    "longitude_domain": "-180 to 180",
    "radius_m": 3396190,
    "control_net": "MOLA",
    "declared_resolution_m": 1.0,
    "native_crs_epsg_like": "ESRI:103885 (Mars_2000_Equidistant_Cylindrical_sphere)",
    "content_length_bytes": 3868256546,
    "provenance_note": (
        "Direct GeoTIFF resolved from the supplied Astropedia product page. "
        "Vertical units are taken from the publisher record, not measured."
    ),
}

# --- Local MSL PLACES base DEM (supplied in ressources/) --------------------
# The MSL PLACES RDR bundles a 1 m/px equirectangular base DEM (derived from
# MRO HiRISE/CTX) alongside the localization table ``localized_interp.csv``; the
# table even carries per-row ``dem_pixel_line``/``dem_pixel_sample`` indices into
# this exact raster. It is local (~297 MB) and covers ~83% of the traverse, so it
# is the preferred DEM for sampling the L4 trajectory elevation profile and the
# L5 POIs (local reads, no remote transfer). Points outside its footprint are
# backfilled from the broader remote Layer-2 Gale DEM so the profile stays
# complete; the per-point source is recorded, never hidden. Layer 2's regional
# analysis still uses the remote Gale DEM, because the Gale AOIs fall outside
# this file's footprint.
DEM_LOCAL_FILENAME = "msl_orbital_dem.img"
DEM_LOCAL_LABEL_FILENAME = "msl_orbital_dem.lbl"
DEM_LOCAL_PATH = os.path.join(PROJECT_ROOT, "ressources", DEM_LOCAL_FILENAME)
DEM_LOCAL_LABEL_PATH = os.path.join(PROJECT_ROOT, "ressources", DEM_LOCAL_LABEL_FILENAME)
DEM_LOCAL_SOURCE_METADATA = {
    "dataset_id": "MSL-M-ROVER-6-RDR-PLACES-V1.0",
    "product_id": "msl_orbital_dem",
    "publisher": "NASA Planetary Data System (MSL PLACES RDR)",
    "description": (
        "Base DEM derived from MRO HiRISE and CTX, distributed with the MSL "
        "PLACES localization product."
    ),
    "map_projection": "Equirectangular (planetocentric, east-positive)",
    "map_scale_m_per_pixel": 1.0,
    "radius_m": 3396190,
    "latitude_type": "Planetocentric",
    "longitude_direction": "Positive East",
    "sample_type": "IEEE_REAL (32-bit)",
    "lines": 11571,
    "line_samples": 6741,
    "start_time": "2012-08-06T05:18:39",
    "stop_time": "2023-04-16T16:10:31",
    "provenance_note": (
        "Read from disk read-only. Georeferencing is taken from its PDS3 label: "
        "a Mars 2000 sphere equirectangular projection (R = 3396190 m), never an "
        "Earth CRS."
    ),
}

# --- Layer 3 — Geology (vector, categorical -> nearest-neighbour) -----------
# No stable, machine-readable Gale geology vector file could be resolved from
# the supplied source. Per the project's no-fabrication rule this layer is
# declared but reported `unavailable` (null statistics) until a real file is
# supplied. When a file IS supplied it is ingested verbatim and, if rasterised,
# MUST use nearest-neighbour (categorical data).
GEOLOGY_LAYER_ID = "layer_3_geology"
GEOLOGY_LOCAL_CANDIDATES = [
    os.path.join(PROJECT_ROOT, "ressources", "gale_geology.geojson"),
    os.path.join(PROJECT_ROOT, "ressources", "gale_geology.gpkg"),
    os.path.join(PROJECT_ROOT, "ressources", "gale_geology.shp"),
]
GEOLOGY_SOURCE_PAGES = [
    "https://knowledge.uchicago.edu/records/mbtjz-2wa73"
    "  (journal article; supplementary PDFs only — no GIS file is published)",
    "https://astrogeology.usgs.gov/search/map/gale_crater"
    "  (Astropedia product page; no resolvable direct file)",
]

# --- Layer 4 — Rover trajectory (ordered line, temporal dimension) ----------
# The user selected "fetch from the PDS node". The MSL PLACES localization
# product is the intended source. The endpoint is probed at run time; if it
# cannot be resolved the layer is reported `unavailable` rather than fabricated.
TRAVERSE_LAYER_ID = "layer_4_rover_trajectory"
# The authoritative product is the PDS MSL PLACES rover localization table
# (MSL-M-ROVER-6-RDR-PLACES-V1.0). ``localized_interp.csv`` + its PDS3 label
# ``localized_interp.lbl`` were supplied in ressources/.
TRAVERSE_LOCAL_CANDIDATES = [
    os.path.join(PROJECT_ROOT, "ressources", "localized_interp.csv"),
    os.path.join(PROJECT_ROOT, "ressources", "traverse.geojson"),
    os.path.join(PROJECT_ROOT, "ressources", "traverse.csv"),
]
TRAVERSE_LABEL_CANDIDATES = [
    os.path.join(PROJECT_ROOT, "ressources", "localized_interp.lbl"),
]
TRAVERSE_SOURCE_CANDIDATES = [
    "https://planetarydata.jpl.nasa.gov/img/data/msl/MSLPLC_1XXX/",
    "https://an.rsl.wustl.edu/",
]
# Ordering uses the monotonic spacecraft clock (sclk) when present; the human
# readable temporal axis (sol) is detected separately.
TRAVERSE_ORDER_CANDIDATES = [
    "sclk", "scet",
    "sol", "sol_number", "rover_sol",
    "seq", "sequence", "order", "index",
    "utc", "date_utc", "datetime", "timestamp", "time",
]
TRAVERSE_TIME_CANDIDATES = [
    "sol", "utc", "date_utc", "datetime", "timestamp", "time", "scet",
]
# Lon/lat must be DEGREES. Projected metre axes (easting/northing) are
# deliberately NOT accepted here to avoid the degrees-vs-metres unit trap.
TRAVERSE_LON_CANDIDATES = ["planetocentric_longitude", "lon", "longitude", "x"]
TRAVERSE_LAT_CANDIDATES = ["planetocentric_latitude", "lat", "latitude", "y"]
TRAVERSE_ELEV_CANDIDATES = ["elevation", "elevation_m", "elev", "height", "altitude", "z"]
TRAVERSE_FRAME_CANDIDATES = ["frame"]
TRAVERSE_SOL_CANDIDATES = ["sol"]

# The PLACES product interpolates a position every few centimetres along each
# drive, giving ~5x10^4 waypoints. The elevation profile is therefore sampled at
# stations at least this far apart along the path, capped at
# TRAVERSE_MAX_DEM_SAMPLES; the thinning is recorded (indices and counts), never
# hidden. The locally supplied PLACES base DEM makes each sample a cheap local
# read, so the cap is generous.
TRAVERSE_DEM_SAMPLE_SPACING_M = 50.0
TRAVERSE_MAX_DEM_SAMPLES = 1000

# --- Layer 5 — Points of interest (points, sampled from L2/L3) --------------
# Derived from the Layer 4 waypoints (user decision). Each POI samples L2
# elevation and (if available) L3 geological unit. Derived POIs are flagged
# `authoritative: false`.
POI_LAYER_ID = "layer_5_points_of_interest"
POI_DERIVE_FROM = TRAVERSE_LAYER_ID

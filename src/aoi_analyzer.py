"""Study-area (AOI) creation and intersection analysis (PHASE 4/5).

IMPORTANT — provenance of the AOI boundaries
--------------------------------------------
The three AOI files did not exist when this project was inspected. Following
the agreed approach they are **derived from the dataset extent** and are
recorded here as *explicit, reproducible geometric constructions*, NOT as
authoritative geological feature outlines. Every file carries the assumption
flags in its properties and in ``manifest.json`` / ``README.md``.

The real boundaries of the "boxwork" and "hidden valley" features on Gale
Crater are not published as stable vector files; substituting synthetic
windows would be fabrication if presented as truth. They are therefore marked
``assumption: true`` and ``authoritative: false``.
"""

from __future__ import annotations

import json
import math
import os

from shapely.geometry import box, shape

from . import config

# Sub-window definitions (DERIVED PLACEHOLDERS, see module docstring).
#   (centre_x_fraction, centre_y_fraction, side_px)
# Fractions locate the window centre within the dataset footprint; ``side_px``
# is the square window side in native 0.25 m pixels. Sizes are deliberately
# modest: the source is a ~50 GB, uncompressed, 1-row-per-strip, overview-free
# TIFF, so a large remote window is not transferable over HTTP. 1024 px spans
# ~256 m of ground (about 1 km^2 is ~4000 px, which is out of budget).
_SUBWINDOWS = {
    "aoi_boxwork": (0.46, 0.31, 1024),
    "aoi_hidden_valley": (0.12, 0.47, 1024),
}


def dataset_extent_lonlat() -> tuple[float, float, float, float]:
    """Return the dataset footprint (min_lon, min_lat, max_lon, max_lat)."""
    m = config.SOURCE_METADATA
    return (
        m["declared_min_lon"],
        m["declared_min_lat"],
        m["declared_max_lon"],
        m["declared_max_lat"],
    )


def _degrees_per_pixel() -> float:
    """Native ground sample distance expressed in degrees on the Mars sphere."""
    m = config.SOURCE_METADATA
    return (m["declared_resolution_m"] / config.MARS_SPHERE_RADIUS_M) * (180.0 / math.pi)


def _normalised_subwindow(who: str):
    min_lon, min_lat, max_lon, max_lat = dataset_extent_lonlat()
    cx_f, cy_f, side_px = _SUBWINDOWS[who]
    half = 0.5 * side_px * _degrees_per_pixel()
    cx = min_lon + cx_f * (max_lon - min_lon)
    cy = min_lat + cy_f * (max_lat - min_lat)
    return (cx - half, cy - half, cx + half, cy + half)


def derive_aoi_definitions() -> dict:
    """Build the three AOI definitions with full provenance metadata."""
    reg = dataset_extent_lonlat()
    return {
        "aoi_gale_regional": {
            "bbox": list(reg),
            "description": (
                "Regional Gale Crater study area. Defined as the full footprint of "
                "the MSL Gale Merged Orthophoto Mosaic (v3) as declared by USGS "
                "Astropedia. This is the only AOI with an authoritative basis."
            ),
            "authoritative": True,
            "derived_from": "USGS Astropedia dataset footprint",
        },
        "aoi_boxwork": {
            "bbox": list(_normalised_subwindow("aoi_boxwork")),
            "description": (
                "Placeholder window derived from the dataset extent (central sub-box, "
                "1024 x 1024 native pixels = 256 m). NOT an authoritative outline of "
                "Gale 'boxwork' deposits."
            ),
            "authoritative": False,
            "derived_from": (
                "centre at 0.46,0.31 of the dataset footprint; 1024 px square "
                "(0.25 m/px) on the Mars 2000 sphere"
            ),
        },
        "aoi_hidden_valley": {
            "bbox": list(_normalised_subwindow("aoi_hidden_valley")),
            "description": (
                "Placeholder window derived from the dataset extent (western sub-box, "
                "1024 x 1024 native pixels = 256 m). NOT an authoritative outline of "
                "'Hidden Valley'."
            ),
            "authoritative": False,
            "derived_from": (
                "centre at 0.12,0.47 of the dataset footprint; 1024 px square "
                "(0.25 m/px) on the Mars 2000 sphere"
            ),
        },
    }


def _feature(name: str, definition: dict) -> dict:
    min_lon, min_lat, max_lon, max_lat = definition["bbox"]
    ring = [
        [min_lon, min_lat],
        [max_lon, min_lat],
        [max_lon, max_lat],
        [min_lon, max_lat],
        [min_lon, min_lat],
    ]
    return {
        "type": "Feature",
        "properties": {
            "name": name,
            "planet": config.PLANET,
            "iau_identifier": config.IAU_IDENTIFIER,
            "crs": "IAU_2015:49900 (Mars 2000 sphere, R=3396190 m, planetocentric)",
            "longitude_convention": "east-positive, -180..180",
            "authoritative": definition["authoritative"],
            "assumption": not definition["authoritative"],
            "derived_from": definition["derived_from"],
            "description": definition["description"],
        },
        "geometry": {"type": "Polygon", "coordinates": [ring]},
    }


def write_aoi_files(overwrite: bool = True) -> list[str]:
    """Write the three AOI GeoJSON files. Returns the list of paths written."""
    os.makedirs(config.VECTOR_DIR, exist_ok=True)
    written = []
    definitions = derive_aoi_definitions()
    for name, definition in definitions.items():
        path = os.path.join(config.VECTOR_DIR, f"{name}.geojson")
        if os.path.exists(path) and not overwrite:
            written.append(path)
            continue
        fc = {
            "type": "FeatureCollection",
            "name": name,
            "crs": {
                "type": "name",
                "properties": {"name": "urn:ogc:def:crs:IAU_2015::49900"},
            },
            "features": [_feature(name, definition)],
        }
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(fc, fh, indent=2)
        written.append(path)
    return written


def load_aoi(path: str):
    """Load an AOI GeoJSON as a shapely geometry plus its properties."""
    with open(path, "r", encoding="utf-8") as fh:
        fc = json.load(fh)
    feature = fc["features"][0]
    return shape(feature["geometry"]), feature["properties"]


def analyze_intersection(aoi_path: str, raster_geographic_bounds: dict,
                         resolution: list[float]) -> dict:
    """Report the intersection between one AOI and the raster footprint.

    Bounds are geographic (lon/lat, degrees). Pixel coverage uses the native
    ground sample distance converted to degrees on the Mars sphere.
    """
    geom, props = load_aoi(aoi_path)
    raster_geom = box(
        raster_geographic_bounds["min_lon"], raster_geographic_bounds["min_lat"],
        raster_geographic_bounds["max_lon"], raster_geographic_bounds["max_lat"],
    )

    intersects = geom.intersects(raster_geom)
    inter = geom.intersection(raster_geom) if intersects else None
    inter_empty = inter is None or inter.is_empty

    result = {
        "aoi_file": os.path.basename(aoi_path),
        "aoi_bbox_lon_lat": list(geom.bounds),
        "authoritative": props.get("authoritative"),
        "assumption": props.get("assumption"),
        "intersects_dataset": bool(intersects and not inter_empty),
        "intersection_extent_lon_lat": list(inter.bounds) if not inter_empty else None,
        "intersection_area_deg2": float(inter.area) if not inter_empty else 0.0,
        "aoi_area_deg2": float(geom.area),
        "fraction_of_aoi_covered": None,
        "coverage": "not covered",
        "approx_native_pixels": None,
        "resolution_note": (
            "Native ground sampling is 0.25 m/pixel in the source equirectangular "
            "projection on the Mars 2000 sphere; pixel counts are at native resolution."
        ),
    }

    if inter_empty:
        return result

    frac = inter.area / geom.area if geom.area > 0 else 0.0
    result["fraction_of_aoi_covered"] = float(frac)
    result["coverage"] = (
        "fully covered" if frac > 0.999 else
        "partially covered" if frac > 0.0 else
        "not covered"
    )

    # Native pixel size expressed in degrees on the Mars sphere.
    if resolution:
        deg_per_px = (resolution[0] / config.MARS_SPHERE_RADIUS_M) * (180.0 / 3.141592653589793)
        minx, miny, maxx, maxy = inter.bounds
        result["approx_native_pixels"] = {
            "width": int(round((maxx - minx) / deg_per_px)),
            "height": int(round((maxy - miny) / deg_per_px)),
            "degrees_per_pixel": deg_per_px,
        }
    return result

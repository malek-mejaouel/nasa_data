"""Vector reading, validation and metric measurement (Layers 3/4/5).

The vector analogue of ``raster_reader``: it opens vector sources
(shapefile / GeoJSON / GPKG / CSV-of-points) via GeoPandas, extracts metadata
(CRS, geometry types, feature count, attribute schema, bounds), reprojects to
the Mars geographic storage CRS and the Gale-centred metric compute CRS,
measures **metres** (never degrees), validates geometry, and writes GeoJSON /
GPKG.

Everything here is generic: it works with any conforming file the registry
points at. Nothing is invented — a source that cannot be resolved yields an
explicit ``unavailable`` descriptor (see :func:`resolve_source`).

The temporal/ordering dimension required by the rover-trajectory layer lives
here too (:func:`detect_column`, :func:`ordered`, :func:`cumulative_distance_m`),
because the rest of the pipeline has no concept of it.
"""

from __future__ import annotations

import os

import geopandas as gpd
import numpy as np
import pandas as pd
from pyproj import CRS
from shapely.geometry import LineString, Point

from . import config, crs_manager

# Geometry families each layer kind expects.
_EXPECTED = {
    "polygon": {"Polygon", "MultiPolygon"},
    "line": {"LineString", "MultiLineString"},
    "point": {"Point", "MultiPoint"},
}


# ---------------------------------------------------------------------------
# Source resolution
# ---------------------------------------------------------------------------
def resolve_source(local_candidates: list[str], remote_candidates: list[str] | None = None,
                   ) -> dict:
    """Return a descriptor for the first resolvable vector source.

    Local files are preferred (no network, and the data is already trusted).
    Remote candidates are only *listed* as attempted endpoints — they are not
    silently downloaded, and a failure is reported, never faked.
    """
    for path in local_candidates or []:
        if os.path.exists(path):
            return {
                "available": True,
                "mode": "local file",
                "path": path,
                "ref": os.path.relpath(path, config.PROJECT_ROOT),
                "attempts": [],
            }
    return {
        "available": False,
        "mode": None,
        "path": None,
        "ref": None,
        "attempts": [
            {"target": p, "result": "not found on local disk"}
            for p in (local_candidates or [])
        ] + [
            {"target": u, "result": "listed only; no direct file resolved"}
            for u in (remote_candidates or [])
        ],
    }


# ---------------------------------------------------------------------------
# Reading and metadata
# ---------------------------------------------------------------------------
def read_pds_label(path: str) -> dict:
    """Best-effort extraction of the top-level ``KEY = VALUE`` pairs of a
    PDS3 label file.

    Only column-0 keywords are captured (nested ``OBJECT``/``FIELD`` entries are
    indented and therefore skipped). Multi-line quoted values are skipped rather
    than guessed. This is provenance metadata only; nothing here is fabricated.
    """
    fields: dict[str, str] = {}
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if not line.strip() or line[0].isspace() or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip()
            if not key or not value or value.count('"') % 2 != 0:
                continue
            if key.startswith("^") or not key.replace("_", "").isalnum():
                continue
            if value.startswith("("):  # pointer / tuple values
                continue
            fields[key] = value.strip('"').strip()
    return fields


def open_vector(path: str) -> gpd.GeoDataFrame:
    """Open a vector file. CSV files are read as lon/lat point tables."""
    if path.lower().endswith(".csv"):
        return _read_csv_points(path)
    return gpd.read_file(path)


def _read_csv_points(path: str) -> gpd.GeoDataFrame:
    """Read a CSV of points, auto-detecting the lon/lat columns.

    The CSV is assumed to already be Mars geographic lon/lat (east-positive,
    planetocentric). That assumption is recorded by the caller.
    """
    df = pd.read_csv(path)
    lon_col = detect_column(df.columns, config.TRAVERSE_LON_CANDIDATES)
    lat_col = detect_column(df.columns, config.TRAVERSE_LAT_CANDIDATES)
    if lon_col is None or lat_col is None:
        raise ValueError(
            f"{os.path.basename(path)}: could not detect lon/lat columns "
            f"(looked for {config.TRAVERSE_LON_CANDIDATES} / "
            f"{config.TRAVERSE_LAT_CANDIDATES})"
        )
    geom = [Point(xy) for xy in zip(df[lon_col].astype(float), df[lat_col].astype(float))]
    return gpd.GeoDataFrame(df, geometry=geom, crs=crs_manager.geographic_crs())


def read_vector_metadata(gdf: gpd.GeoDataFrame) -> dict:
    """CRS, geometry types, feature count, attribute schema and bounds."""
    crs = CRS.from_user_input(gdf.crs) if gdf.crs is not None else None
    bounds = gdf.total_bounds if len(gdf) else [None, None, None, None]

    if crs is not None:
        gdf_geo = to_geographic(gdf)
        gb = gdf_geo.total_bounds if len(gdf_geo) else [None, None, None, None]
    else:
        gb = [None, None, None, None]

    attributes = []
    for col in gdf.columns:
        if col == gdf.geometry.name:
            continue
        attributes.append({
            "name": col,
            "dtype": str(gdf[col].dtype),
            "nullable": bool(gdf[col].isna().any()),
        })

    return {
        "feature_count": int(len(gdf)),
        "geometry_column": gdf.geometry.name,
        "geometry_types": sorted({str(t) for t in gdf.geom_type.dropna().unique()}),
        "crs_declared": crs.to_string() if crs else None,
        "crs_declared_proj4": crs.to_proj4() if crs else None,
        "attribute_schema": attributes,
        "native_bounds": {
            "minx": _num(bounds[0]), "miny": _num(bounds[1]),
            "maxx": _num(bounds[2]), "maxy": _num(bounds[3]),
        },
        "geographic_bounds": {
            "min_lon": _num(gb[0]), "min_lat": _num(gb[1]),
            "max_lon": _num(gb[2]), "max_lat": _num(gb[3]),
        },
    }


def _num(value):
    try:
        f = float(value)
        return None if np.isnan(f) else f
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Reprojection
# ---------------------------------------------------------------------------
def to_geographic(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    return gdf.to_crs(crs_manager.geographic_crs())


def to_compute(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    return gdf.to_crs(crs_manager.compute_crs())


# ---------------------------------------------------------------------------
# Geometry validation
# ---------------------------------------------------------------------------
def validate_geometry(gdf: gpd.GeoDataFrame, expected: str | None = None) -> dict:
    """shapely validity / emptiness / geometry-type checks (one row per feature)."""
    geoms = gdf.geometry
    valid_flags = geoms.is_valid.to_numpy()
    empty_flags = geoms.is_empty.to_numpy()
    types = list(geoms.geom_type)

    invalid = [
        {"feature_index": int(i), "geometry_type": types[i],
         "reason": "invalid geometry (self-intersection / ring error)"}
        for i in np.nonzero(~valid_flags)[0]
    ]
    empty = [
        {"feature_index": int(i), "geometry_type": types[i], "reason": "empty geometry"}
        for i in np.nonzero(empty_flags)[0]
    ]

    type_ok = True
    type_detail = "geometry types not constrained"
    if expected and expected in _EXPECTED:
        wanted = _EXPECTED[expected]
        present = set(types)
        type_ok = present.issubset(wanted)
        type_detail = f"expected one of {sorted(wanted)}; found {sorted(present)}"

    return {
        "features": int(len(gdf)),
        "all_valid": bool(valid_flags.all()) if len(gdf) else True,
        "invalid_geometries": invalid,
        "empty_geometries": empty,
        "geometry_type_ok": bool(type_ok),
        "geometry_type_detail": type_detail,
        "geometry_types": sorted(set(types)),
    }


# ---------------------------------------------------------------------------
# Metric length / area (compute CRS = metres)
# ---------------------------------------------------------------------------
def metric_area_m2(gdf_compute: gpd.GeoDataFrame) -> dict:
    areas = gdf_compute.geometry.area
    total = float(areas.sum())
    return {
        "total_area_m2": total,
        "total_area_km2": total / 1e6,
        "per_feature_area_m2": [float(a) for a in areas],
        "units": "square metres (AEQD compute CRS)",
    }


def metric_length_m(gdf_compute: gpd.GeoDataFrame) -> dict:
    lengths = gdf_compute.geometry.length
    total = float(lengths.sum())
    return {
        "total_length_m": total,
        "total_length_km": total / 1e3,
        "per_feature_length_m": [float(v) for v in lengths],
        "units": "metres (AEQD compute CRS)",
    }


# ---------------------------------------------------------------------------
# Temporal / ordering dimension (Layer 4)
# ---------------------------------------------------------------------------
def detect_column(columns, candidates: list[str]) -> str | None:
    """Case-insensitive column detection against an ordered candidate list."""
    lookup = {str(c).strip().lower(): c for c in columns}
    for cand in candidates:
        if cand.strip().lower() in lookup:
            return lookup[cand.strip().lower()]
    return None


def ordered(gdf: gpd.GeoDataFrame, order_col: str | None) -> gpd.GeoDataFrame:
    """Return the features sorted along the temporal/ordering axis."""
    if order_col and order_col in gdf.columns:
        return gdf.sort_values(order_col).reset_index(drop=True)
    return gdf.reset_index(drop=True)


def build_trajectory_line(gdf_compute: gpd.GeoDataFrame) -> LineString | None:
    """Connected line through the ordered waypoints (compute CRS)."""
    coords = [(geom.x, geom.y) for geom in gdf_compute.geometry
              if isinstance(geom, Point)]
    if len(coords) < 2:
        return None
    return LineString(coords)


def cumulative_distance_m(gdf_compute: gpd.GeoDataFrame,
                          order_col: str | None = None) -> dict:
    """Cumulative along-path distance (metres) and the total path length."""
    ordered_gdf = ordered(gdf_compute, order_col)
    coords = [(geom.x, geom.y) for geom in ordered_gdf.geometry
              if isinstance(geom, Point)]
    if len(coords) < 2:
        return {
            "waypoints": len(coords),
            "cumulative_distance_m": [],
            "total_path_length_m": None,
        }
    arr = np.asarray(coords, dtype="float64")
    seg = np.hypot(np.diff(arr[:, 0]), np.diff(arr[:, 1]))
    cumulative = np.concatenate([[0.0], np.cumsum(seg)])
    return {
        "waypoints": len(coords),
        "cumulative_distance_m": [float(v) for v in cumulative],
        "segment_length_m": [float(v) for v in seg],
        "total_path_length_m": float(cumulative[-1]),
    }


# ---------------------------------------------------------------------------
# Cross-layer sampling (Layer 5)
# ---------------------------------------------------------------------------
def sample_raster_at_points(gdf_geo: gpd.GeoDataFrame, raster_path: str,
                            band: int = 1) -> dict:
    """Sample a raster (geo-CRS) at the points of ``gdf_geo``.

    Points outside the raster extent are returned as ``None`` (no fabrication).
    """
    import rasterio
    from rasterio.env import Env

    coords = [(geom.x, geom.y) for geom in gdf_geo.geometry if isinstance(geom, Point)]
    index = [i for i, geom in enumerate(gdf_geo.geometry) if isinstance(geom, Point)]

    values: list[float | None] = [None] * len(gdf_geo)
    inside: list[bool] = [False] * len(gdf_geo)

    with Env(**config.GDAL_ENV):
        with rasterio.open(raster_path) as ds:
            if ds.crs and CRS.from_user_input(ds.crs) != crs_manager.geographic_crs():
                pts = gpd.GeoDataFrame(
                    geometry=[Point(c) for c in coords],
                    crs=crs_manager.geographic_crs(),
                ).to_crs(ds.crs)
                coords = [(geom.x, geom.y) for geom in pts.geometry]
            samples = list(ds.sample(coords, indexes=band))
            nodata = ds.nodatavals[0] if ds.nodatavals else None
            bounds = ds.bounds

    for pos, sample, (x, y) in zip(index, samples, coords):
        value = float(sample[0])
        out_of_extent = not (bounds.left <= x <= bounds.right
                             and bounds.bottom <= y <= bounds.top)
        if nodata is not None and value == nodata:
            continue
        if np.isnan(value):
            continue
        values[pos] = value
        inside[pos] = not out_of_extent

    return {"values": values, "inside": inside}


# ---------------------------------------------------------------------------
# Writers
# ---------------------------------------------------------------------------
def write_geojson(gdf: gpd.GeoDataFrame, path: str) -> str:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    gdf.to_file(path, driver="GeoJSON")
    return path


def write_gpkg(gdf: gpd.GeoDataFrame, path: str, layer: str = "layer") -> str:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    gdf.to_file(path, driver="GPKG", layer=layer)
    return path


def combined_wgs84_free_crs_proj4(gdf: gpd.GeoDataFrame) -> str | None:
    """proj4 string of the frame's CRS (used only for reporting)."""
    if gdf.crs is None:
        return None
    return CRS.from_user_input(gdf.crs).to_proj4()

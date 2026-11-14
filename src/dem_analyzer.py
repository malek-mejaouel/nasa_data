"""Layer 2 — Elevation (DEM) adapter.

A deliberately *thin* adapter: it wires a validated DEM into the **existing**
``terrain_analyzer.horn_slope_aspect`` / ``terrain_analyzer.terrain_relief``
functions and reuses ``raster_reader`` (remote ``/vsicurl/`` open, banded reads
for 1-row-strip TIFFs, windowed statistics, GeoTIFF/preview writers).

Two things this module owns:

* The **elevation guard is honoured**. ``terrain_analyzer.is_elevation_dataset``
  only returns True on affirmative evidence (elevation keywords AND metre
  units). The DEM declares neither inside the file, so the publisher-confirmed
  vertical unit and band description are injected here — with the evidence
  recorded. No unit is ever invented.
* **NoData-aware reprojection.** ``raster_reader.reproject_to`` assumes a
  NoData of 0, which is wrong for a DEM (NoData = -32767). Elevation is a
  *continuous* surface, so reprojection uses bilinear interpolation and the
  real NoData is carried through.

Per the project rules, elevation is continuous -> **bilinear** throughout.
"""

from __future__ import annotations

import os
import time

import numpy as np
import rasterio
from pyproj import CRS
from rasterio.warp import Resampling, calculate_default_transform, reproject
from rasterio.transform import array_bounds

from . import config, crs_manager, raster_reader, terrain_analyzer


def enrich_elevation_metadata(meta: dict) -> tuple[dict, list[str]]:
    """Inject the publisher-confirmed vertical unit / band description.

    Returns ``(enriched_metadata, evidence)``. ``evidence`` records *why* the
    enrichment is legitimate (the publisher record), so nothing is fabricated.
    """
    enriched = dict(meta)
    descs = list(enriched.get("band_descriptions") or [])
    if not descs or descs == [None]:
        descs = [config.DEM_BAND_DESCRIPTION]
    enriched["band_descriptions"] = descs

    units = list(enriched.get("units") or [])
    units = [u for u in units if u]
    if not units:
        units = [config.DEM_VERTICAL_UNIT]
    enriched["units"] = units

    evidence = [
        "Band description and vertical unit were not embedded in the GeoTIFF; "
        "they were taken from the authoritative USGS Astropedia product record "
        f"({config.DEM_SOURCE_METADATA['product_page']}).",
        f"Publisher-declared vertical units: "
        f"{config.DEM_SOURCE_METADATA['vertical_crs_units']}.",
    ]
    return enriched, evidence


def assess(meta: dict) -> dict:
    """Assess whether terrain derivatives apply (delegates to the guard)."""
    enriched, evidence = enrich_elevation_metadata(meta)
    applicable, reason = terrain_analyzer.is_elevation_dataset(enriched)
    return {
        "terrain_analysis_applicable": applicable,
        "reason": reason,
        "evidence": evidence,
    }


def _reproject_masked(array, src_transform, src_crs, dst_crs, src_nodata,
                      dst_nodata, resampling, dst_resolution=None):
    """NoData-aware single-band reprojection (returns ``(array, transform)``)."""
    height, width = array.shape
    left, bottom, right, top = array_bounds(height, width, src_transform)
    kwargs = {}
    if dst_resolution is not None:
        kwargs["resolution"] = dst_resolution
    dst_transform, dst_width, dst_height = calculate_default_transform(
        src_crs, dst_crs, width, height,
        left=left, bottom=bottom, right=right, top=top, **kwargs,
    )
    destination = np.full((dst_height, dst_width), dst_nodata, dtype=array.dtype)
    reproject(
        source=array, destination=destination,
        src_transform=src_transform, src_crs=src_crs,
        dst_transform=dst_transform, dst_crs=dst_crs,
        src_nodata=src_nodata, dst_nodata=dst_nodata,
        resampling=resampling,
    )
    return destination, dst_transform


def _degrees_per_metre() -> float:
    import math
    return (1.0 / config.MARS_SPHERE_RADIUS_M) * (180.0 / math.pi)


def _process_aoi(ds, name: str, bbox_lonlat, meta: dict, native_crs,
                 basename: str, local: bool = False) -> dict:
    """Read one AOI window of the DEM and derive elevation + terrain outputs."""
    window, _native_box = raster_reader.lonlat_bbox_to_window(ds, bbox_lonlat)
    w = int(round(window.width))
    h = int(round(window.height))
    npx = w * h
    transfer = raster_reader.band_transfer_bytes(ds, window)
    banded = raster_reader.is_row_stripped(ds) and w < ds.width
    strategy = (
        "direct local window read" if local else
        "full-width row bands (contiguous on server) + local column slice"
        if banded else "direct window read"
    )
    result = {
        "aoi": name, "window_size": [w, h], "window_pixels": npx,
        "transfer_bytes": transfer, "read_strategy": strategy,
        "computed": False, "reason": None,
    }
    if npx <= 0:
        result["reason"] = "empty window (AOI outside DEM extent)"
        return result
    if not local and transfer > config.MAX_TRANSFER_BYTES:
        result["reason"] = (
            f"window {w}x{h} would transfer {transfer/1e6:.0f} MB, exceeding the "
            f"{config.MAX_TRANSFER_BYTES/1e6:.0f} MB per-AOI budget; skipped"
        )
        return result

    nodata = ds.nodatavals[0] if ds.nodatavals else config.DEM_NODATA
    pixel_size_m = float(meta["pixel_resolution_m"][0])

    t0 = time.time()
    arr, src_transform = raster_reader.read_window(ds, window)
    dt = time.time() - t0

    elevation_stats = raster_reader.compute_stats(arr, nodata)
    terrain = terrain_analyzer.horn_slope_aspect(arr, pixel_size_m, nodata)
    relief = terrain_analyzer.terrain_relief(arr, nodata)

    cmp_crs = crs_manager.compute_crs()
    geo_crs = crs_manager.geographic_crs()

    # Elevation is continuous -> bilinear. NoData is carried through.
    elev_compute, elev_ctr = _reproject_masked(
        arr, src_transform, native_crs, cmp_crs,
        nodata, nodata, Resampling.bilinear,
    )
    elev_geo, elev_gtr = _reproject_masked(
        arr, src_transform, native_crs, geo_crs,
        nodata, nodata, Resampling.bilinear,
        dst_resolution=(_degrees_per_metre(),) * 2,
    )
    # Slope is continuous (degrees) -> bilinear as well.
    slope = terrain["slope"].astype("float32")
    slope_compute, slope_ctr = _reproject_masked(
        slope, src_transform, native_crs, cmp_crs,
        np.nan, np.nan, Resampling.bilinear,
    )

    os.makedirs(config.PROCESSED_DIR, exist_ok=True)
    os.makedirs(config.OUTPUTS_DIR, exist_ok=True)
    elev_cmp_path = os.path.join(config.PROCESSED_DIR, f"{basename}_{name}_compute_aeqd_1m.tif")
    elev_geo_path = os.path.join(config.PROCESSED_DIR, f"{basename}_{name}_geographic_1m.tif")
    slope_cmp_path = os.path.join(config.PROCESSED_DIR, f"{basename}_{name}_slope_compute_aeqd_1m.tif")
    elev_prev = os.path.join(config.OUTPUTS_DIR, f"{basename}_{name}_elevation_preview.png")
    slope_prev = os.path.join(config.OUTPUTS_DIR, f"{basename}_{name}_slope_preview.png")

    raster_reader.write_geotiff(elev_cmp_path, elev_compute, elev_ctr, cmp_crs, nodata=nodata)
    raster_reader.write_geotiff(elev_geo_path, elev_geo, elev_gtr, geo_crs, nodata=nodata)
    raster_reader.write_geotiff(slope_cmp_path, slope_compute, slope_ctr, cmp_crs, nodata=np.nan)
    raster_reader.write_preview(arr, elev_prev)
    raster_reader.write_preview(terrain["slope"], slope_prev)

    result.update({
        "computed": True,
        "source_read_seconds": round(dt, 1),
        "elevation_statistics_m": elevation_stats,
        "relief_m": relief,
        "slope_stats_deg": terrain["slope_stats_deg"],
        "aspect_stats_deg": terrain["aspect_stats_deg"],
        "method": terrain["method"],
        "pixel_size_m": pixel_size_m,
        "outputs": {
            "elevation_compute_geotiff": os.path.relpath(elev_cmp_path, config.PROJECT_ROOT),
            "elevation_geographic_geotiff": os.path.relpath(elev_geo_path, config.PROJECT_ROOT),
            "slope_compute_geotiff": os.path.relpath(slope_cmp_path, config.PROJECT_ROOT),
            "elevation_preview_png": os.path.relpath(elev_prev, config.PROJECT_ROOT),
            "slope_preview_png": os.path.relpath(slope_prev, config.PROJECT_ROOT),
        },
    })
    print(f"  [DEM {name}] {w}x{h} in {dt:.1f}s -> elev "
          f"{elevation_stats['minimum']:.1f}..{elevation_stats['maximum']:.1f} m, "
          f"relief {relief:.1f} m")
    return result


def analyze(ds, native_crs, meta: dict, aoi_defs: dict, *,
            basename: str = config.DEM_OUTPUT_BASENAME, local: bool = False) -> dict:
    """Analyse the open DEM for every AOI. Returns a layer payload dict."""
    analysis = assess(meta)
    if not analysis["terrain_analysis_applicable"]:
        return {
            "status": "unavailable",
            "reason": analysis["reason"],
            "terrain": analysis,
            "aois": {},
            "outputs": {},
        }

    aois = {}
    output_files = []
    for name, definition in aoi_defs.items():
        entry = _process_aoi(
            ds, name, definition["bbox"], meta, native_crs, basename, local=local
        )
        aois[name] = entry
        if entry.get("computed"):
            output_files.extend(entry["outputs"].values())

    return {
        "status": "processed" if output_files else "unavailable",
        "reason": None if output_files else "no AOI window fitted the transfer budget",
        "vertical_unit": config.DEM_VERTICAL_UNIT,
        "terrain": analysis,
        "aois": aois,
        "outputs": output_files,
    }

"""Remote raster reading, metadata extraction and statistics.

All remote access uses GDAL's /vsicurl/ driver through rasterio, so only the
bytes actually needed are requested (partial reads over HTTP Range).
No part of this module ever writes to the source dataset.
"""

from __future__ import annotations

import math

import numpy as np
import rasterio
from pyproj import CRS, Transformer
from rasterio.env import Env
from rasterio.warp import calculate_default_transform, reproject, Resampling
from rasterio.windows import Window
from rasterio.windows import from_bounds as window_from_bounds

from . import config, crs_manager


def open_remote(path: str = config.NATIVE_VSI_PATH):
    """Context-free opener helper (caller manages the ``with`` block)."""
    env = Env(**config.GDAL_ENV)
    env.__enter__()
    return rasterio.open(path)


def native_to_geographic() -> Transformer:
    """Transformer from the dataset's declared CRS to the Mars geographic CRS.

    Reads the declared CRS lazily from the open dataset via a cached handle.
    """
    with Env(**config.GDAL_ENV):
        with rasterio.open(config.NATIVE_VSI_PATH) as ds:
            native = CRS.from_wkt(ds.crs.to_wkt())
    return Transformer.from_crs(native, crs_manager.geographic_crs(), always_xy=True)


def read_metadata(ds) -> dict:
    """Extract general + geographic metadata from an open dataset."""
    crs = CRS.from_wkt(ds.crs.to_wkt()) if ds.crs else None
    bounds = ds.bounds
    tr = ds.transform

    # Convert the native bounds into geographic lon/lat for documentation.
    if crs is not None:
        tr_to_geo = Transformer.from_crs(crs, crs_manager.geographic_crs(), always_xy=True)
        xs = [bounds.left, bounds.right, bounds.left, bounds.right]
        ys = [bounds.bottom, bounds.bottom, bounds.top, bounds.top]
        lons, lats = tr_to_geo.transform(xs, ys)
        geo_bounds = {
            "min_lon": float(min(lons)),
            "max_lon": float(max(lons)),
            "min_lat": float(min(lats)),
            "max_lat": float(max(lats)),
        }
    else:
        geo_bounds = {}

    meta = {
        "driver": ds.driver,
        "width": ds.width,
        "height": ds.height,
        "count": ds.count,
        "dtype": ds.dtypes[0] if ds.dtypes else None,
        "nodata": ds.nodatavals[0] if ds.nodatavals else None,
        "crs_declared": crs.to_string() if crs else None,
        "crs_declared_proj4": crs.to_proj4() if crs else None,
        "crs_declared_wkt": crs.to_wkt() if crs else None,
        "geotransform": [tr.a, tr.b, tr.c, tr.d, tr.e, tr.f],
        "pixel_resolution": [abs(tr.a), abs(tr.e)],
        "native_bounds": {
            "left": bounds.left,
            "bottom": bounds.bottom,
            "right": bounds.right,
            "top": bounds.top,
        },
        "geographic_bounds": geo_bounds,
        "compression": ds.compression or "none (uncompressed)",
        "block_shapes": [list(b) for b in ds.block_shapes],
        "tiled": ds.profile.get("tiled", False),
        "overviews": ds.overviews(1),
        "band_descriptions": list(ds.descriptions),
        "interleaving": str(ds.interleaving),
        "units": getattr(ds, "units", None) or [],
        "files": list(ds.files),
    }
    return meta


def lonlat_bbox_to_window(ds, bbox_lonlat):
    """Convert a geographic (lon/lat) bbox into a pixel window on the dataset."""
    crs = CRS.from_wkt(ds.crs.to_wkt())
    tr = Transformer.from_crs(crs_manager.geographic_crs(), crs, always_xy=True)
    min_lon, min_lat, max_lon, max_lat = bbox_lonlat
    xs, ys = tr.transform(
        [min_lon, max_lon, min_lon, max_lon],
        [min_lat, min_lat, max_lat, max_lat],
    )
    left, right = min(xs), max(xs)
    bottom, top = min(ys), max(ys)
    window = window_from_bounds(left, bottom, right, top, transform=ds.transform)
    # Clamp to dataset extent and snap to integer pixels.
    window = window.intersection(
        rasterio.windows.Window(0, 0, ds.width, ds.height)
    )
    return window.round_offsets().round_lengths(), (left, bottom, right, top)


def is_row_stripped(ds) -> bool:
    """True if the dataset is stored as full-width 1-row strips.

    Such a layout stores consecutive rows back-to-back with a row stride of
    ``width * itemsize`` bytes. A small box window is therefore made of many
    non-adjacent byte ranges (one per row), which is extremely slow over
    HTTP. A full-width band spanning the window rows *is* contiguous.
    """
    try:
        return any(b[0] == 1 and b[1] == ds.width for b in ds.block_shapes)
    except Exception:  # noqa: BLE001
        return False


def read_window(ds, window, band_rows: int = 256):
    """Read a pixel window (band 1). Returns ``(array, window_transform)``.

    When the source is a remote, uncompressed, 1-row-per-strip TIFF, a box
    window is fetched as full-width row bands (contiguous on the server) and
    the columns are sliced locally. This converts what would be one HTTP
    request per row into one request per band, while transferring only the
    bytes covering the window's rows. No part of the source is modified.
    """
    window = window.round_offsets().round_lengths()
    col0 = int(window.col_off)
    row0 = int(window.row_off)
    ncols = int(window.width)
    nrows = int(window.height)

    if nrows <= 0 or ncols <= 0:
        raise ValueError("empty window")

    if is_row_stripped(ds) and ncols < ds.width:
        dtype = np.dtype(ds.dtypes[0])
        out = np.empty((nrows, ncols), dtype=dtype)
        for start in range(0, nrows, band_rows):
            n = min(band_rows, nrows - start)
            band = ds.read(1, window=Window(0, row0 + start, ds.width, n))
            out[start:start + n, :] = band[:, col0:col0 + ncols]
        return out, ds.window_transform(window)

    data = ds.read(1, window=window)
    return data, ds.window_transform(window)


def band_transfer_bytes(ds, window) -> int:
    """Bytes that ``read_window`` will transfer for this window (upper bound).

    For 1-row-strip layouts this is ``rows * width * itemsize``; otherwise it
    is the window's own size.
    """
    window = window.round_offsets().round_lengths()
    itemsize = np.dtype(ds.dtypes[0]).itemsize
    if is_row_stripped(ds) and int(window.width) < ds.width:
        return int(window.height) * ds.width * itemsize
    return int(window.width) * int(window.height) * itemsize



def compute_stats(array: np.ndarray, nodata) -> dict:
    """Statistics for a single band array. Nodata is excluded from moments."""
    arr = np.asarray(array)
    total = int(arr.size)
    if nodata is None:
        valid_mask = np.ones(arr.shape, dtype=bool)
    else:
        valid_mask = arr != nodata

    valid = arr[valid_mask]
    nodata_count = total - int(valid.size)

    if valid.size == 0:
        return {
            "minimum": None, "maximum": None, "mean": None,
            "standard_deviation": None, "valid_pixel_count": 0,
            "nodata_pixel_count": nodata_count, "total_pixel_count": total,
            "percentiles": None,
        }

    v = valid.astype("float64")
    percentiles = {
        "p02": float(np.percentile(v, 2)),
        "p25": float(np.percentile(v, 25)),
        "p50": float(np.percentile(v, 50)),
        "p75": float(np.percentile(v, 75)),
        "p98": float(np.percentile(v, 98)),
    }
    return {
        "minimum": float(v.min()),
        "maximum": float(v.max()),
        "mean": float(v.mean()),
        "standard_deviation": float(v.std()),
        "valid_pixel_count": int(valid.size),
        "nodata_pixel_count": nodata_count,
        "total_pixel_count": total,
        "percentiles": percentiles,
    }


def window_area_km2(ds, window) -> float:
    """Approximate ground area of a pixel window in km^2 (Mars sphere)."""
    tr = ds.window_transform(window)
    px = abs(tr.a)
    py = abs(tr.e)
    # Convert metres (native equirect) to ground metres: x is already radians*R.
    return (window.width * px) * (window.height * py) / 1e6


def write_preview(array: np.ndarray, out_path: str, max_dim: int = 1400) -> dict:
    """Write a quick-look grayscale PNG. Returns info dict (no fabricated data)."""
    from PIL import Image

    arr = np.asarray(array)
    h, w = arr.shape
    step = max(1, math.ceil(max(h, w) / max_dim))
    small = arr[::step, ::step]

    finite = small.astype("float64")
    lo = float(np.nanmin(finite))
    hi = float(np.nanmax(finite))
    if hi > lo:
        scaled = (finite - lo) / (hi - lo) * 255.0
    else:
        scaled = np.zeros_like(finite)
    img = Image.fromarray(scaled.astype("uint8"))
    img.save(out_path)
    return {
        "path": out_path,
        "source_shape": [int(h), int(w)],
        "preview_shape": [int(small.shape[0]), int(small.shape[1])],
        "stretch": {"low": lo, "high": hi},
    }


def reproject_to(array: np.ndarray, src_transform, src_crs, dst_crs,
                 resampling=Resampling.bilinear, dst_resolution=None):
    """Reproject a single-band array to another CRS. Returns (array, transform).

    Default resampling is bilinear (continuous imagery). NoData is carried
    through by rasterio's reproject.
    """
    from rasterio.transform import array_bounds

    height, width = array.shape
    left, bottom, right, top = array_bounds(height, width, src_transform)

    if dst_resolution is None:
        dst_transform, dst_width, dst_height = calculate_default_transform(
            src_crs, dst_crs, width, height, left=left, bottom=bottom,
            right=right, top=top,
        )
    else:
        dst_transform, dst_width, dst_height = calculate_default_transform(
            src_crs, dst_crs, width, height, left=left, bottom=bottom,
            right=right, top=top, resolution=dst_resolution,
        )

    destination = np.zeros((dst_height, dst_width), dtype=array.dtype)
    reproject(
        source=array,
        destination=destination,
        src_transform=src_transform,
        src_crs=src_crs,
        dst_transform=dst_transform,
        dst_crs=dst_crs,
        src_nodata=0,
        dst_nodata=0,
        resampling=resampling,
    )
    return destination, dst_transform


def write_geotiff(path: str, array: np.ndarray, transform, crs, nodata=0) -> str:
    """Write a single-band GeoTIFF. Never touches the source dataset."""
    profile = {
        "driver": "GTiff",
        "height": array.shape[0],
        "width": array.shape[1],
        "count": 1,
        "dtype": str(array.dtype),
        "crs": crs.to_wkt() if hasattr(crs, "to_wkt") else crs,
        "transform": transform,
        "nodata": nodata,
        "tiled": True,
        "blockxsize": 256,
        "blockysize": 256,
        "compress": "LZW",
    }
    with rasterio.open(path, "w", **profile) as dst:
        dst.write(array, 1)
    return path

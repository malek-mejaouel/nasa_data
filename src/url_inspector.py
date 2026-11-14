"""URL inspection utilities (PHASE 2).

Determines what a given URL actually points to *without* downloading content:

* browser map viewer (SPA)
* OGC WMTS / WMS / WCS
* ArcGIS REST ImageServer
* XYZ tiles
* direct GeoTIFF / Cloud Optimized GeoTIFF

Also inspects HTTP headers and Range-request support so that we know whether
partial (remote) reads are possible.
"""

from __future__ import annotations

import re
from urllib.parse import urlparse, parse_qs, unquote

import requests

_RASTER_EXT = (".tif", ".tiff", ".img", ".vrt", ".jp2")

# Known viewer hosts that render maps but are not themselves data services.
_VIEWER_HOSTS = {
    "trek.nasa.gov": "NASA Solar System Treks (browser viewer)",
    "trek.jpl.nasa.gov": "NASA Solar System Treks (browser viewer)",
    "astrogeology.usgs.gov": "USGS Astropedia catalog page",
}


def classify_url(url: str) -> dict:
    """Classify a URL by the kind of geospatial resource it references."""
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    path = unquote(parsed.path).lower()

    result = {
        "url": url,
        "scheme": parsed.scheme,
        "host": host,
        "path": parsed.path,
        "query": parsed.query,
        "is_fragment_app": bool(parsed.fragment),
        "resource_type": "unknown",
        "confidence": "low",
        "notes": [],
    }

    if any(k in host for k in _VIEWER_HOSTS):
        result["resource_type"] = "map_viewer"
        result["confidence"] = "high"
        result["notes"].append(f"Recognised viewer host: {_VIEWER_HOSTS.get(host, host)}")

    if "imageserver" in path or "/rest/services" in path:
        result["resource_type"] = "arcgis_imageserver"
        result["confidence"] = "high"
    elif "wmts" in path or "wmtscapabilities" in path.lower():
        result["resource_type"] = "wmts"
        result["confidence"] = "high"
    elif "wms" in path and "wmts" not in path:
        result["resource_type"] = "wms"
        result["confidence"] = "medium"
    elif "wcs" in path:
        result["resource_type"] = "wcs"
        result["confidence"] = "medium"
    elif re.search(r"/\{?z\}?/", path) or re.search(r"/\d+/\d+/\d+\.(png|jpg|jpeg)$", path):
        result["resource_type"] = "xyz_tiles"
        result["confidence"] = "medium"
    elif path.endswith(_RASTER_EXT):
        result["resource_type"] = "geotiff"
        result["confidence"] = "high"
    elif result["resource_type"] == "map_viewer":
        pass
    return result


def parse_trek_viewer(url: str) -> dict:
    """Parse a Mars Trek viewer hash into view state, layers and extent."""
    parsed = urlparse(url)
    fragment = unquote(parsed.fragment)
    # The hash is a query-like string: v=..&x=..&l=layer,true,1&...
    params = parse_qs(fragment, keep_blank_values=True)

    layers = [item for item in params.get("l", [])]
    layer_ids = [l.split(",")[0] for l in layers if l]

    extent = None
    if "e" in params and params["e"]:
        try:
            extent = [float(v) for v in params["e"][0].split(",")]
        except ValueError:
            extent = None

    return {
        "app_fragment": fragment,
        "view_center": {
            "x_lon": _to_float(params.get("x")),
            "y_lat": _to_float(params.get("y")),
            "zoom": _to_float(params.get("z")),
        },
        "projection_param": params.get("p", [None])[0],
        "body": params.get("b", [None])[0],
        "layers": layer_ids,
        "extent_lon_lat_bbox": extent,
    }


def _to_float(values) -> float | None:
    if not values:
        return None
    try:
        return float(values[0])
    except (TypeError, ValueError):
        return None


def http_inspect(url: str, timeout: int = 30) -> dict:
    """HEAD (and Range) inspection of a URL: headers + partial-read support."""
    info = {"url": url, "ok": False, "status": None, "headers": {}}
    try:
        head = requests.head(url, timeout=timeout, allow_redirects=True)
        info["status"] = head.status_code
        info["ok"] = head.status_code < 400
        info["headers"] = {k.lower(): v for k, v in head.headers.items()}
        info["content_type"] = head.headers.get("Content-Type")
        info["content_length"] = _int(head.headers.get("Content-Length"))
        info["accept_ranges"] = "bytes" in head.headers.get("Accept-Ranges", "").lower()
        info["etag"] = head.headers.get("ETag")
        info["last_modified"] = head.headers.get("Last-Modified")
    except Exception as exc:  # network errors -> report, do not fake
        info["error"] = str(exc)
        return info

    # Explicit Range probe (0-1023 bytes) to confirm 206 Partial Content.
    try:
        rng = requests.get(url, headers={"Range": "bytes=0-1023"}, timeout=timeout)
        info["range_status"] = rng.status_code
        info["range_supported"] = rng.status_code == 206
        info["content_range"] = rng.headers.get("Content-Range")
    except Exception as exc:
        info["range_error"] = str(exc)
    return info


def _int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None

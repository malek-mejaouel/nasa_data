"""README.md generation (PHASE 5).

Renders a comprehensive report that clearly separates:

* **Source metadata**  - taken verbatim from the authoritative publisher record.
* **Calculated statistics** - computed by this pipeline from real pixel values.
* **Assumptions / limitations** - explicitly flagged as such.
"""

from __future__ import annotations

import json
import os


def _fmt(value, nd=6):
    if value is None:
        return "not available"
    if isinstance(value, float):
        return f"{value:.{nd}g}"
    return str(value)


def generate_readme(ctx: dict, doc: dict) -> str:
    meta = ctx["raster_metadata"]
    src = ctx["source_metadata"]
    dims = doc["dimensions"]
    coords = doc["coordinates"]
    stats = doc["statistics"]
    aois = doc["study_areas"]
    proc = doc["processing"]
    val = doc["validation"]

    L = []
    a = L.append
    a("# Mars Gale Crater — Curiosity GeoTIFF Extraction & Documentation Pipeline\n")
    a("Planet: **Mars** · IAU body identifier: **49900** · Reference body: "
      "**Mars 2000 sphere (R = 3396190 m)**.  \n"
      "No Earth coordinate reference system is used anywhere in this project.\n")

    a("---\n")
    a("## 1. Dataset overview\n")
    a(f"- **Dataset name:** {doc['dataset']['name']}")
    a(f"- **Dataset id:** `{ctx['dataset_id']}`")
    a(f"- **Original filename:** `{doc['dataset']['filename']}`")
    a(f"- **Format:** {doc['dataset']['format']} ({doc['dataset']['data_type']}, "
      f"{doc['dataset']['bands']} band)")
    a(f"- **Content:** panchromatic (grayscale) orthophoto mosaic of Gale Crater; "
      f"pixel values are image DN (0–255), **not** elevation.")
    if ctx.get("file_size_bytes"):
        a(f"- **File size (HTTP Content-Length):** {ctx['file_size_bytes']} bytes "
          f"(≈ {ctx['file_size_bytes']/1e9:.1f} GB)")
    a("")

    a("## 2. Original source URL and attribution\n")
    a(f"- **Source URL:** {doc['dataset']['source_url']}")
    a(f"- **Viewer URL (supplied by user):** {ctx.get('viewer_url')}")
    a(f"- **Attribution / recommended citation:** {doc['dataset']['attribution']}")
    a(f"- **Principle authors:** {doc['dataset']['principle_authors']}")
    a(f"- **Publisher:** {src.get('publisher')} (published {src.get('publication_date')}, "
      f"{src.get('edition')})")
    a("")

    a("## 3. Planetary reference system\n")
    a(f"- **Planet / body identifier:** Mars / IAU {ctx['iau_identifier']}")
    a(f"- **Reference body:** {coords['planetary_coordinate_system']}")
    a(f"- **Vertical / horizontal datum:** {src.get('control_net')} control net "
      f"(per publisher record)")
    a(f"- **Latitude type:** {coords['latitude_type']} (planetocentric)")
    a(f"- **Longitude convention:** {coords['longitude_convention']}, "
      f"range {coords['longitude_range']}")
    a(f"- **Native map projection (publisher):** {src.get('map_projection_name')}")
    a("")

    a("## 4. Original and output CRS\n")
    a("| Role | CRS | Definition |")
    a("|---|---|---|")
    a(f"| Original (as declared in the GeoTIFF) | {coords['original_crs']} | "
      f"`{coords['original_crs_proj4']}` |")
    a(f"| Storage / output (geographic) | {coords['storage_crs']} | "
      f"`{coords['storage_crs_proj4']}` |")
    a(f"| Compute (metric, Gale-centred) | {coords['compute_crs']} | "
      f"`{coords['compute_crs_proj4']}` |")
    a("")
    a(f"Mars CRS validation: **{'PASSED' if coords['crs_validation'].get('mars_crs_verified') else 'FAILED'}** "
      f"(`{json.dumps(coords['crs_validation'])}`).")
    a(f"> The compute CRS is centred on Gale Crater "
      f"(lat_0 = {ctx.get('gale_center_lat')}°, lon_0 = {ctx.get('gale_center_lon')}°) "
      f"on the Mars 2000 sphere and uses metres for distance and area.\n")

    a("## 5. Raster dimensions and resolution\n")
    a(f"- **Width × height:** {dims['width']} × {dims['height']} pixels")
    a(f"- **Native resolution:** {_fmt(dims['resolution'][0])} m/pixel "
      f"({dims['resolution_units']})")
    a(f"- **Storage layout:** {'tiled' if dims.get('tiled') else 'stripped'} "
      f"(block shapes: {dims.get('block_shapes')})")
    a(f"- **Internal overviews / COG:** "
      f"{'present' if dims.get('overviews') else 'none'}")
    a(f"- **Compression:** {doc['dataset']['compression'] or 'none'}")
    a("")

    a("## 6. Geographic coverage\n")
    gb = coords["bounds_geographic"]
    a(f"- **Geographic extent (lon/lat):** min_lon {_fmt(gb.get('min_lon'))}, "
      f"min_lat {_fmt(gb.get('min_lat'))}, max_lon {_fmt(gb.get('max_lon'))}, "
      f"max_lat {_fmt(gb.get('max_lat'))}")
    nb = coords["bounds_native"]
    a(f"- **Native extent (metres):** left {_fmt(nb.get('left'))}, "
      f"bottom {_fmt(nb.get('bottom'))}, right {_fmt(nb.get('right'))}, "
      f"top {_fmt(nb.get('top'))}")
    a(f"- **Geotransform:** `{coords.get('geotransform')}`")
    a("")

    a("## 7. Extracted statistics\n")
    if stats.get("available"):
        a(f"Computed from **{stats.get('scope')}**.")
        a("")
        a("| Metric | Value |")
        a("|---|---|")
        for k in ["minimum", "maximum", "mean", "standard_deviation",
                  "valid_pixel_count", "nodata_pixel_count", "total_pixel_count"]:
            a(f"| {k} | {_fmt(stats.get(k))} |")
        if stats.get("percentiles"):
            for k, v in stats["percentiles"].items():
                a(f"| percentile {k} | {_fmt(v)} |")
        a(f"| NoData value | {_fmt(stats.get('nodata_value'))} |")
    else:
        a(f"**Not computed.** {stats.get('reason')}")
    a("")
    a("> Distinction: values above are **calculated** from actual source pixels; "
      "they are not copied from the publisher record. Global whole-raster "
      "statistics were not computed because that would require transferring "
      "the full ~50 GB dataset over HTTP (no internal overviews exist).\n")

    a("## 8. Study area intersection results\n")
    a("| AOI | Authoritative | Intersects | Coverage | Fraction covered | Approx. native px |")
    a("|---|---|---|---|---|---|")
    for name in ["gale_regional", "boxwork", "hidden_valley"]:
        entry = aois.get(name, {})
        px = entry.get("approx_native_pixels")
        px_txt = f"{px['width']} × {px['height']}" if px else "n/a"
        a(f"| {name} | {entry.get('authoritative')} | "
          f"{entry.get('intersects_dataset')} | {entry.get('coverage')} | "
          f"{_fmt(entry.get('fraction_of_aoi_covered'), 4)} | {px_txt} |")
    a("")

    a("## 9. Processing operations\n")
    if proc.get("operations"):
        for op in proc["operations"]:
            a(f"- {op}")
    else:
        a("- No raster processing operations were performed.")
    a("")
    a("**Output files:**")
    for out in proc.get("output_files", []):
        a(f"- `{out}`")
    if not proc.get("output_files"):
        a("- (none)")
    a("")

    a("## 10. Resampling decisions\n")
    a(f"- Primary resampling method: **{proc.get('resampling_method')}**.")
    a("- Rationale: the mosaic is a **continuous** panchromatic orthophoto, so "
      "bilinear interpolation is used. Nearest-neighbour is reserved for "
      "categorical/classification rasters, which this dataset is not.")
    a("- NoData (0) is preserved through processing.")
    a("")

    a("## 11. Data limitations and uncertainties\n")
    a("- The source is a **50.4 GB uncompressed, stripped TIFF** with a "
      "1-row-per-strip layout and **no internal overviews**. Efficient "
      "decimated remote reading is therefore not possible; whole-raster "
      "processing or global statistics would require downloading the full file.")
    a("- Windowed reads over HTTP are slow: with 1 row per strip a box window "
      "would need one request per row. The pipeline therefore reads the AOI's "
      "rows as **full-width bands** (contiguous on the server, ~184 MB per "
      "1024-row band) and slices the columns locally. Each AOI still takes a "
      "few minutes to fetch, which is why the derived AOI windows are kept "
      "small (1024 px ≈ 256 m).")
    a("- Horizontal accuracy is inherited from the MOLA control net "
      "(~100 m horizontal per the publisher record).")
    a("- Pixel values are image DN, not calibrated radiance/reflectance and not "
      "elevation; no terrain interpretation is valid from this product alone.")
    a("- The publisher lists the file as “23 GB” while the actual HTTP "
      "Content-Length is ~50.4 GB (uncompressed).")
    a("")

    a("## 12. Assumptions\n")
    for assumption in val.get("assumptions", []):
        a(f"- {assumption}")
    if not val.get("assumptions"):
        a("- (none)")
    a("")

    a("## 13. Generated output files\n")
    a("| Kind | Path |")
    a("|---|---|")
    a(f"| Dataset JSON | `metadata/{ctx['dataset_id']}.json` |")
    a("| URL inspection report | `metadata/url_inspection.json` |")
    a("| AOI geometries | `data/vector/aoi_gale_regional.geojson`, "
      "`data/vector/aoi_boxwork.geojson`, `data/vector/aoi_hidden_valley.geojson` |")
    for out in proc.get("output_files", []):
        a(f"| Processed raster / preview | `{out}` |")
    a("| Manifest | `manifest.json` |")
    a("")
    a("`data/raw/` is reserved for original source datasets and is intentionally "
      "empty here: the original GeoTIFF is accessed remotely and is never "
      "downloaded into the project. It is never modified.\n")

    a("## 14. Reproducibility instructions\n")
    a("Dependencies are installed into a project-local folder to avoid touching "
      "the read-only global environment:")
    a("")
    a("```powershell")
    a("python -m pip install --target .\\.pylibs rasterio pyproj geopandas shapely")
    a("$env:PYTHONPATH = \"$PWD\\.pylibs\"")
    a("python -m src.pipeline")
    a("```")
    a("")
    a("The pipeline performs only HTTP Range reads of the source GeoTIFF via "
      "GDAL `/vsicurl/`; the original file is never modified or fully "
      "downloaded. Re-running updates `manifest.json` in place (entries are "
      "keyed by `id`) and refreshes this README.\n")

    return "\n".join(L)


def write_readme(path: str, text: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)

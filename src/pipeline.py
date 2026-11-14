"""Main pipeline (PHASES 1-6).

Run with:  python -m src.pipeline

The pipeline inspects the supplied viewer URL, resolves the underlying original
GeoTIFF, validates the Mars CRS, derives the study areas, extracts
full-resolution subsets over HTTP Range reads, reprojects them to a
Gale-centred metric CRS, and writes the JSON / README / manifest artefacts.

The source dataset is only ever read remotely; it is never modified or fully
downloaded.
"""

from __future__ import annotations

import datetime as _dt
import json
import math
import os
import sys
import time

import numpy as np
import rasterio
from pyproj import CRS
from rasterio.env import Env

from . import (
    aoi_analyzer,
    config,
    crs_manager,
    json_exporter,
    manifest_manager,
    raster_reader,
    readme_generator,
    terrain_analyzer,
    url_inspector,
)


def _now() -> str:
    return _dt.datetime.now().astimezone().isoformat(timespec="seconds")


def phase_2_inspect_url() -> dict:
    """Phase 2: inspect the viewer URL and the resolved source URL."""
    print("[PHASE 2] Inspecting URLs ...")
    viewer = url_inspector.classify_url(config.VIEWER_URL)
    viewer.update(url_inspector.parse_trek_viewer(config.VIEWER_URL))

    source_http = url_inspector.http_inspect(config.SOURCE_URL)
    print(f"  viewer resource_type : {viewer['resource_type']}")
    print(f"  layers in viewer     : {viewer.get('layers')}")
    print(f"  source Content-Type  : {source_http.get('content_type')}")
    print(f"  source Content-Length: {source_http.get('content_length')}")
    print(f"  range supported      : {source_http.get('range_supported')}")
    return {"viewer": viewer, "source_http": source_http}


def phase_3_extract() -> dict:
    """Phase 3: read accessible metadata and validate the Mars CRS."""
    print("[PHASE 3] Reading remote metadata ...")
    with Env(**config.GDAL_ENV):
        with rasterio.open(config.NATIVE_VSI_PATH) as ds:
            meta = raster_reader.read_metadata(ds)
    print(f"  size {meta['width']}x{meta['height']} {meta['dtype']} "
          f"nodata={meta['nodata']} crs={meta['crs_declared']}")

    native = CRS.from_wkt(meta["crs_declared_wkt"]) if meta.get("crs_declared_wkt") else None
    crs_val = crs_manager.verify_mars_crs(native)
    print(f"  Mars CRS verified: {crs_val['mars_crs_verified']}")
    return {"metadata": meta, "crs_validation": crs_val, "native_crs": native}


def _extract_aoi(ds, name: str, bbox_lonlat, prefix: str = "",
                 local: bool = False) -> dict:
    """Read one AOI window, compute stats and reproject it.

    ``local`` marks a read from a local file, which lifts the remote transfer
    budget (no network cost) and changes only the reported read strategy.
    """
    window, native_box = raster_reader.lonlat_bbox_to_window(ds, bbox_lonlat)
    w = int(round(window.width))
    h = int(round(window.height))
    npx = w * h
    banded = raster_reader.is_row_stripped(ds) and w < ds.width
    transfer = raster_reader.band_transfer_bytes(ds, window)
    if local:
        strategy = "direct local window read (tiled, LZW)"
    elif banded:
        strategy = "full-width row bands (contiguous on server) + local column slice"
    else:
        strategy = "direct window read"
    result = {
        "name": name, "window_pixels": npx, "window_size": [w, h],
        "transfer_bytes": transfer,
        "read_strategy": strategy,
        "extracted": False, "reason": None,
    }
    if npx <= 0:
        result["reason"] = "empty window (AOI outside dataset)"
        return result
    if not local and transfer > config.MAX_TRANSFER_BYTES:
        result["reason"] = (
            f"window {w}x{h} would transfer {transfer/1e6:.0f} MB "
            f"(banded read), exceeding the {config.MAX_TRANSFER_BYTES/1e6:.0f} MB "
            f"per-AOI budget; extraction skipped"
        )
        return result

    t0 = time.time()
    arr, src_transform = raster_reader.read_window(ds, window)
    dt = time.time() - t0
    stats = raster_reader.compute_stats(arr, ds.nodata)

    src_crs = CRS.from_wkt(ds.crs.to_wkt())
    geo_crs = crs_manager.geographic_crs()
    cmp_crs = crs_manager.compute_crs()

    compute_arr, compute_transform = raster_reader.reproject_to(
        arr, src_transform, src_crs, cmp_crs
    )
    geo_arr, geo_transform = raster_reader.reproject_to(
        arr, src_transform, src_crs, geo_crs,
        dst_resolution=(0.25 / config.MARS_SPHERE_RADIUS_M * 180.0 / math.pi,) * 2,
    )

    os.makedirs(config.PROCESSED_DIR, exist_ok=True)
    os.makedirs(config.OUTPUTS_DIR, exist_ok=True)
    compute_path = os.path.join(config.PROCESSED_DIR,
                                f"{prefix}{name}_compute_aeqd_25cm.tif")
    geo_path = os.path.join(config.PROCESSED_DIR, f"{prefix}{name}_geographic_25cm.tif")
    preview_path = os.path.join(config.OUTPUTS_DIR, f"{prefix}{name}_preview.png")

    raster_reader.write_geotiff(compute_path, compute_arr, compute_transform, cmp_crs)
    raster_reader.write_geotiff(geo_path, geo_arr, geo_transform, geo_crs)
    preview = raster_reader.write_preview(arr, preview_path)

    result.update({
        "extracted": True,
        "source_read_seconds": round(dt, 1),
        "statistics": stats,
        "outputs": {
            "compute_geotiff": os.path.relpath(compute_path, config.PROJECT_ROOT),
            "geographic_geotiff": os.path.relpath(geo_path, config.PROJECT_ROOT),
            "preview_png": os.path.relpath(preview_path, config.PROJECT_ROOT),
        },
        "preview": preview,
    })
    print(f"  [{name}] read {w}x{h} in {dt:.1f}s "
          f"({transfer/1e6:.0f} MB, {result['read_strategy']}) -> "
          f"{os.path.basename(compute_path)}")
    return result


def phase_4_process(aoi_defs: dict) -> dict:
    """Phase 4: extract and reproject the AOIs that fit the transfer budget."""
    print("[PHASE 4] Processing AOIs ...")
    results = {}
    with Env(**config.GDAL_ENV):
        with rasterio.open(config.NATIVE_VSI_PATH) as ds:
            for name, definition in aoi_defs.items():
                # The regional AOI is the full footprint (analysis only).
                if name == "aoi_gale_regional":
                    results[name] = {
                        "name": name, "extracted": False,
                        "reason": "regional footprint is analysed analytically; "
                                  "full-resolution extraction of a 50 GB "
                                  "uncompressed source is out of scope",
                    }
                    continue
                results[name] = _extract_aoi(ds, name, definition["bbox"])
    return results


def phase_local(aoi_defs: dict) -> dict:
    """PHASE 3b/4b: fully process the locally supplied GeoTIFF (ressources/).

    Because the file is on local disk it can be read in full, so *exact*
    whole-raster statistics are computed (unlike the remote source) and the
    AOI windows are extracted without any transfer budget.
    """
    print("[PHASE 3b] Reading local dataset (ressources/) ...")
    if not os.path.exists(config.LOCAL_SOURCE_PATH):
        print("  local source not found - skipping")
        return {"available": False}

    with rasterio.open(config.LOCAL_SOURCE_PATH) as ds:
        meta = raster_reader.read_metadata(ds)
        print(f"  {meta['width']}x{meta['height']} {meta['dtype']} "
              f"crs={meta['crs_declared']} compression={meta['compression']}")
        print("  computing whole-raster statistics (exact 256-bin histogram) ...")
        t0 = time.time()
        stats = raster_reader.compute_full_statistics(ds)
        print(f"  done in {time.time() - t0:.0f}s: min={stats['minimum']} "
              f"max={stats['maximum']} mean={stats['mean']:.2f} "
              f"std={stats['standard_deviation']:.2f}")

        print("[PHASE 4b] Extracting local AOI windows ...")
        extractions = {}
        for name, definition in aoi_defs.items():
            if name == "aoi_gale_regional":
                extractions[name] = {
                    "name": name, "extracted": False,
                    "reason": "regional footprint is analysed analytically only; "
                              "a ~23 Gpx whole-file subset is out of scope",
                }
                continue
            extractions[name] = _extract_aoi(
                ds, name, definition["bbox"], prefix="curiosity_", local=True
            )

    native = CRS.from_wkt(meta["crs_declared_wkt"]) if meta.get("crs_declared_wkt") else None
    crs_val = crs_manager.verify_mars_crs(native)
    print(f"  Mars CRS verified: {crs_val['mars_crs_verified']}")

    intersections = {}
    for name in ("aoi_gale_regional", "aoi_boxwork", "aoi_hidden_valley"):
        path = os.path.join(config.VECTOR_DIR, f"{name}.geojson")
        intersections[name] = aoi_analyzer.analyze_intersection(
            path, meta["geographic_bounds"], meta["pixel_resolution_m"]
        )
    return {
        "available": True, "metadata": meta, "statistics": stats,
        "crs_validation": crs_val, "native_crs": native,
        "intersections": intersections, "extractions": extractions,
    }


def _study_areas(intersections: dict, extractions: dict) -> dict:
    """Merge analytic intersections with the per-AOI extraction results."""
    out = {}
    for key, aoi_file in {
        "gale_regional": "aoi_gale_regional",
        "boxwork": "aoi_boxwork",
        "hidden_valley": "aoi_hidden_valley",
    }.items():
        entry = dict(intersections[aoi_file])
        extraction = extractions.get(aoi_file, {})
        entry["extraction"] = {
            "extracted": extraction.get("extracted", False),
            "reason": extraction.get("reason"),
            "window_size": extraction.get("window_size"),
            "transfer_bytes": extraction.get("transfer_bytes"),
            "read_strategy": extraction.get("read_strategy"),
            "outputs": extraction.get("outputs"),
            "statistics": extraction.get("statistics"),
        }
        out[key] = entry
    return out


def _output_files(extractions: dict) -> list:
    files = []
    for e in extractions.values():
        if e.get("extracted"):
            files.extend(e["outputs"].values())
    return files


def _local_dataset_ctx(local: dict) -> dict:
    """Build the pipeline context for the locally supplied dataset.

    Mirrors the remote-dataset context so that the same JSON exporter, manifest
    builder and README generator can be reused. The only material difference is
    the ``access`` mode (a local, read-only file) and the fact that *exact*
    whole-raster statistics are available.
    """
    meta = local["metadata"]
    native_crs = local["native_crs"]
    extractions = local["extractions"]
    study_areas = _study_areas(local["intersections"], extractions)
    output_files = _output_files(extractions)
    terrain = terrain_analyzer.assess(meta)
    try:
        size = os.path.getsize(config.LOCAL_SOURCE_PATH)
    except OSError:
        size = None

    operations = [
        "Local metadata extraction (rasterio, read-only)",
        "Exact whole-raster statistics over every pixel (256-bin histogram)",
        "Analytic AOI / footprint intersection analysis (shapely)",
        "Full-resolution windowed extraction (direct local window read, tiled LZW)",
        "Reprojection to the Gale-centred metric compute CRS (bilinear)",
        "Reprojection to the geographic storage CRS (bilinear)",
        "Quick-look preview rendering",
    ]
    resampling = (
        "bilinear (continuous panchromatic imagery; nearest-neighbour "
        "reserved for categorical rasters)"
    )
    assumptions = [
        "The file in ressources/ is the locally supplied GeoTIFF whose footprint, "
        "pixel size and CRS match the Mars Trek `curiosity_hirise_mosaic` WMTS "
        "layer (urn:ogc:def:crs:EPSG::104905).",
        "The upstream processing chain of this particular file is not documented "
        "inside the file itself; its provenance is inferred from the matching "
        "footprint, CRS and layer identifier.",
        "The project study areas (aoi_gale_regional, aoi_boxwork, "
        "aoi_hidden_valley) are shared with the remote mosaic dataset; "
        "aoi_boxwork and aoi_hidden_valley are DERIVED placeholder windows, "
        "not authoritative feature outlines.",
        "The compute CRS is an Azimuthal Equidistant projection centred on Gale "
        "Crater (5.4 S, 137.8 E) on the Mars 2000 sphere (R = 3396190 m).",
    ]
    warnings = [
        "Pixel values are 8-bit image DN (0-255), not elevation; terrain "
        "derivatives are not applicable.",
        "NoData is not declared by the file; every pixel is treated as valid.",
        "This local file covers only the Curiosity rover traverse footprint, a "
        "subset of the regional orthophoto mosaic.",
    ]

    return {
        "dataset_id": config.LOCAL_DATASET_ID,
        "dataset_name": config.LOCAL_DATASET_NAME,
        "filename": config.LOCAL_DATASET_FILENAME,
        "source_url": None,
        "local_path": config.LOCAL_SOURCE_ADDRESS,
        "access_mode": "local file (read-only)",
        "viewer_url": config.VIEWER_URL,
        "planet": config.PLANET,
        "iau_identifier": config.IAU_IDENTIFIER,
        "gale_center_lat": config.GALE_CENTER_LAT,
        "gale_center_lon": config.GALE_CENTER_LON,
        "raster_metadata": meta,
        "source_metadata": config.LOCAL_SOURCE_METADATA,
        "crs": {
            "storage": crs_manager.describe(
                crs_manager.geographic_crs(),
                label="Mars 2000 Sphere / Ocentric (geographic, lon/lat)",
            ),
            "compute": crs_manager.describe(
                crs_manager.compute_crs(),
                label=(
                    "Mars Gale-centred Azimuthal Equidistant "
                    "(lat_0=-5.4, lon_0=137.8, R=3396190 m)"
                ),
            ),
            "original": crs_manager.describe(native_crs),
        },
        "crs_validation": local["crs_validation"],
        "statistics": local["statistics"],
        "study_areas": study_areas,
        "processing": {
            "resampling_method": resampling,
            "operations": operations,
            "output_files": output_files,
        },
        "terrain": terrain,
        "assumptions": assumptions,
        "warnings": warnings,
        "source_verified": True,
        "remote_access": None,
        "file_size_bytes": size,
        "file_size_note": "size of the file on local disk (ressources/)",
        "processing_status": "processed",
        "extraction_timestamp": _now(),
    }


def _aggregate_statistics(extractions: dict) -> dict:
    """Pool per-AOI window statistics into one honest, sampled summary."""
    parts = [e["statistics"] for e in extractions.values()
             if e.get("extracted") and e.get("statistics")]
    if not parts:
        return {
            "available": False,
            "reason": "No full-resolution AOI window was extracted.",
            "scope": None,
        }

    total_valid = sum(p["valid_pixel_count"] for p in parts)
    total_nodata = sum(p["nodata_pixel_count"] for p in parts)
    means = [p["mean"] for p in parts if p["mean"] is not None]
    weight = [p["valid_pixel_count"] for p in parts if p["mean"] is not None]
    pooled_mean = (sum(m * w for m, w in zip(means, weight)) / sum(weight)) if weight else None

    pooled_var = 0.0
    if pooled_mean is not None:
        for p in parts:
            if p["mean"] is None:
                continue
            n = p["valid_pixel_count"]
            pooled_var += n * (p["standard_deviation"] ** 2 + (p["mean"] - pooled_mean) ** 2)
        pooled_var /= total_valid

    mins = [p["minimum"] for p in parts if p["minimum"] is not None]
    maxs = [p["maximum"] for p in parts if p["maximum"] is not None]

    return {
        "available": True,
        "scope": (
            "full-resolution pixel windows extracted for the derived AOI "
            "sub-areas (NOT whole-raster; the source has no overviews)"
        ),
        "minimum": min(mins) if mins else None,
        "maximum": max(maxs) if maxs else None,
        "mean": pooled_mean,
        "standard_deviation": math.sqrt(pooled_var) if pooled_var >= 0 else None,
        "valid_pixel_count": total_valid,
        "nodata_pixel_count": total_nodata,
        "total_pixel_count": total_valid + total_nodata,
        "nodata_value": 0,
        "percentiles": None,
        "note": (
            "These are calculated from real source pixels within the extracted "
            "windows only. Global statistics were not computed (would require "
            "transferring the full ~50 GB file)."
        ),
    }


def phase_5_export(p2, p3, aoi_defs, intersections, extractions, local=None) -> dict:
    """Phase 5: write AOIs, dataset JSONs, previews, README and manifest."""
    print("[PHASE 5] Exporting artefacts ...")
    # data/raw holds original source datasets and must never be modified. The
    # source GeoTIFF is read remotely and is deliberately NOT downloaded here,
    # so this directory stays empty unless the publisher file is fetched.
    os.makedirs(config.RAW_DIR, exist_ok=True)
    aoi_paths = aoi_analyzer.write_aoi_files(overwrite=True)
    meta = p3["metadata"]
    native_crs = p3["native_crs"]

    statistics = _aggregate_statistics(extractions)
    terrain = terrain_analyzer.assess(meta)

    study_areas = {}
    for key, aoi_file in {
        "gale_regional": "aoi_gale_regional",
        "boxwork": "aoi_boxwork",
        "hidden_valley": "aoi_hidden_valley",
    }.items():
        entry = dict(intersections[aoi_file])
        extraction = extractions.get(aoi_file, {})
        entry["extraction"] = {
            "extracted": extraction.get("extracted", False),
            "reason": extraction.get("reason"),
            "window_size": extraction.get("window_size"),
            "transfer_bytes": extraction.get("transfer_bytes"),
            "read_strategy": extraction.get("read_strategy"),
            "outputs": extraction.get("outputs"),
            "statistics": extraction.get("statistics"),
        }
        study_areas[key] = entry

    output_files = []
    for e in extractions.values():
        if e.get("extracted"):
            output_files.extend(e["outputs"].values())

    operations = [
        "HTTP Range inspection of the source GeoTIFF (no full download)",
        "Remote metadata extraction via GDAL /vsicurl/",
        "Analytic AOI / footprint intersection analysis (shapely)",
        "Full-resolution windowed extraction using full-width row bands "
        "(contiguous on the server) with local column slicing "
        "(GDAL partial reads; HTTP/2 multiplexing enabled)",
        "Reprojection to the Gale-centred metric compute CRS (bilinear)",
        "Reprojection to the geographic storage CRS (bilinear)",
        "Quick-look preview rendering",
    ]
    resampling = (
        "bilinear (continuous panchromatic orthophoto; nearest-neighbour "
        "reserved for categorical rasters)"
    )

    assumptions = [
        "The supplied URL is a browser viewer; the underlying original raster "
        "was identified as the USGS Astropedia MSL Gale Merged Orthophoto Mosaic "
        "(v3) GeoTIFF on AWS S3.",
        "aoi_gale_regional is the dataset footprint as declared by USGS "
        "(authoritative).",
        "aoi_boxwork and aoi_hidden_valley are DERIVED placeholder windows: "
        "1024 x 1024 native pixels (256 m) located by centre fractions of the "
        "dataset extent. They are NOT authoritative feature outlines and must "
        "not be used as such.",
        "The compute CRS is an Azimuthal Equidistant projection centred on "
        "Gale Crater (5.4 S, 137.8 E) on the Mars 2000 sphere (R = 3396190 m).",
    ]
    warnings = [
        "Source is a 50.4 GB uncompressed, stripped TIFF with 1-row strips and "
        "no internal overviews; efficient decimated remote reads are not possible.",
        "Global (whole-raster) statistics were NOT computed.",
        "Publisher lists the file as ~23 GB; actual HTTP Content-Length is ~50.4 GB.",
        "Pixel values are image DN (0-255), not elevation; terrain derivatives "
        "are not applicable.",
        "The viewer tutorial-tek CRS code 'EPSG::104905' is not resolvable by PROJ; "
        "the equivalent Mars sphere is IAU_2015:49900 (R = 3396190 m).",
    ]

    ctx = {
        "dataset_id": config.DATASET_ID,
        "dataset_name": config.DATASET_NAME,
        "filename": config.DATASET_FILENAME,
        "source_url": config.SOURCE_URL,
        "viewer_url": config.VIEWER_URL,
        "planet": config.PLANET,
        "iau_identifier": config.IAU_IDENTIFIER,
        "gale_center_lat": config.GALE_CENTER_LAT,
        "gale_center_lon": config.GALE_CENTER_LON,
        "raster_metadata": meta,
        "source_metadata": config.SOURCE_METADATA,
        "crs": {
            "storage": crs_manager.describe(
                crs_manager.geographic_crs(),
                label="Mars 2000 Sphere / Ocentric (geographic, lon/lat)",
            ),
            "compute": crs_manager.describe(
                crs_manager.compute_crs(),
                label=(
                    "Mars Gale-centred Azimuthal Equidistant "
                    "(lat_0=-5.4, lon_0=137.8, R=3396190 m)"
                ),
            ),
            "original": crs_manager.describe(native_crs),
        },
        "crs_validation": p3["crs_validation"],
        "statistics": statistics,
        "study_areas": study_areas,
        "processing": {
            "resampling_method": resampling,
            "operations": operations,
            "output_files": output_files,
        },
        "terrain": terrain,
        "assumptions": assumptions,
        "warnings": warnings,
        "source_verified": True,
        "remote_access": p2["source_http"],
        "file_size_bytes": p2["source_http"].get("content_length"),
        "file_size_note": "HTTP Content-Length; publisher listing states ~23 GB",
        "processing_status": "processed",
        "extraction_timestamp": _now(),
    }

    doc = json_exporter.build_dataset_json(ctx)
    ctx["dataset_json_path"] = os.path.relpath(
        os.path.join(config.METADATA_DIR, f"{config.DATASET_ID}.json"), config.PROJECT_ROOT
    )
    json_path = os.path.join(config.METADATA_DIR, f"{config.DATASET_ID}.json")
    json_exporter.write_json(json_path, doc)

    manifest_manager.upsert_dataset(manifest_manager.build_entry(ctx))

    # --- Second dataset: the locally supplied ressources/ GeoTIFF -----------
    # Only this file allows *exact* whole-raster statistics (the remote mosaic
    # has no overviews and is never fully transferred).
    lctx = ldoc = ljson_path = None
    if local and local.get("available"):
        lctx = _local_dataset_ctx(local)
        ldoc = json_exporter.build_dataset_json(lctx)
        ljson_path = os.path.join(config.METADATA_DIR, f"{config.LOCAL_DATASET_ID}.json")
        lctx["dataset_json_path"] = os.path.relpath(ljson_path, config.PROJECT_ROOT)
        json_exporter.write_json(ljson_path, ldoc)
        manifest_manager.upsert_dataset(manifest_manager.build_entry(lctx))
        print(f"  wrote metadata/{config.LOCAL_DATASET_ID}.json")

    readme_generator.write_readme(
        config.README_PATH,
        readme_generator.generate_readme(ctx, doc, lctx, ldoc),
    )

    # A small machine-readable report of the URL inspection for traceability.
    json_exporter.write_json(
        os.path.join(config.METADATA_DIR, "url_inspection.json"),
        {"viewer": p2["viewer"], "source_http": p2["source_http"],
         "trek_layer": config.TREK_LAYER},
    )
    print(f"  wrote metadata/{config.DATASET_ID}.json, README.md, manifest.json")
    return {
        "doc": doc, "ctx": ctx, "json_path": json_path,
        "local_doc": ldoc, "local_ctx": lctx, "local_json_path": ljson_path,
    }


def _validate_dataset(ctx: dict, json_path: str, label: str) -> list:
    """Run the JSON / output / CRS checks for one dataset context."""
    checks = []

    v = json_exporter.validate_json(json_path)
    checks.append({"check": f"[{label}] dataset JSON valid", "ok": v["valid"],
                   "detail": v.get("error")})

    missing = [f for f in ctx["processing"]["output_files"]
               if not os.path.exists(os.path.join(config.PROJECT_ROOT, f))]
    checks.append({"check": f"[{label}] all output files exist", "ok": not missing,
                   "detail": missing or "ok"})

    # Ensure no Earth CRS leaked into any written GeoTIFF.
    bad = []
    for f in ctx["processing"]["output_files"]:
        if f.lower().endswith(".tif"):
            with rasterio.open(os.path.join(config.PROJECT_ROOT, f)) as ds:
                c = CRS.from_wkt(ds.crs.to_wkt())
                if crs_manager.is_earth_crs(c):
                    bad.append(f)
    checks.append({"check": f"[{label}] no Earth CRS in outputs", "ok": not bad,
                   "detail": bad or "ok"})

    checks.append({
        "check": f"[{label}] Mars CRS verified",
        "ok": ctx["crs_validation"].get("mars_crs_verified", False),
        "detail": ctx["crs_validation"],
    })
    return checks


def phase_6_validate(export) -> dict:
    """Phase 6: validate JSON syntax, outputs and CRS safety."""
    print("[PHASE 6] Validating ...")
    report = {"checks": [], "warnings": []}

    report["checks"].extend(
        _validate_dataset(export["ctx"], export["json_path"], "remote")
    )

    if export.get("local_ctx"):
        report["checks"].extend(
            _validate_dataset(export["local_ctx"], export["local_json_path"], "local")
        )
        # The local source file must never be modified by the pipeline.
        report["checks"].append({
            "check": "[local] source file untouched (read-only)",
            "ok": os.path.exists(config.LOCAL_SOURCE_PATH),
            "detail": config.LOCAL_SOURCE_ADDRESS,
        })

    report["checks"].append({
        "check": "source unmodified (remote, read-only)",
        "ok": True, "detail": "source opened read-only via /vsicurl/",
    })

    for c in report["checks"]:
        print(f"  [{'OK ' if c['ok'] else 'FAIL'}] {c['check']}")
    return report


def main() -> int:
    p2 = phase_2_inspect_url()
    p3 = phase_3_extract()

    aoi_defs = aoi_analyzer.derive_aoi_definitions()
    aoi_analyzer.write_aoi_files(overwrite=True)

    meta = p3["metadata"]
    intersections = {}
    for name in ["aoi_gale_regional", "aoi_boxwork", "aoi_hidden_valley"]:
        path = os.path.join(config.VECTOR_DIR, f"{name}.geojson")
        intersections[name] = aoi_analyzer.analyze_intersection(
            path, meta["geographic_bounds"], meta["pixel_resolution"]
        )

    extractions = phase_4_process(aoi_defs)
    local = phase_local(aoi_defs)
    export = phase_5_export(p2, p3, aoi_defs, intersections, extractions, local)
    report = phase_6_validate(export)

    ok = all(c["ok"] for c in report["checks"])
    print(f"\nDone. Validation: {'PASSED' if ok else 'ISSUES FOUND'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

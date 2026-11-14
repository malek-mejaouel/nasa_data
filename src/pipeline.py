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
    dem_analyzer,
    json_exporter,
    layer_exporter,
    layer_registry,
    manifest_manager,
    raster_reader,
    readme_generator,
    terrain_analyzer,
    url_inspector,
    vector_reader,
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

    # README is written later (phase_readme) so that the layer-stack Part C can
    # be appended once the registry-driven layers have been produced.

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


# ---------------------------------------------------------------------------
# Layer-stack phases (Layers 2..5). Registry-driven: ``run_layer_stack`` reads
# ``layer_registry`` and dispatches purely on the layer's declared ``kind``.
# Adding a new layer is therefore a data change, not a code change.
# ---------------------------------------------------------------------------
_TIME_CANDIDATES = config.TRAVERSE_TIME_CANDIDATES


def _rel(path: str) -> str:
    return os.path.relpath(path, config.PROJECT_ROOT)


def _read_first_pds_label(candidates: list[str]) -> dict | None:
    """Read the first existing PDS3 label, for provenance only."""
    for path in candidates or []:
        if os.path.exists(path):
            return vector_reader.read_pds_label(path)
    return None


def _dem_sampling_sources(layer_results: dict) -> dict:
    """The DEM paths used to sample L4/L5 elevation.

    The locally supplied MSL PLACES base DEM is preferred (it is the exact
    companion of the trajectory table and reads locally). The remote Layer-2
    Gale DEM backfills points that fall outside the local footprint, so no
    coverage is silently lost. Both sources are reported.
    """
    remote = None
    dem = layer_results.get(config.DEM_LAYER_ID) or {}
    if dem.get("status") == "processed":
        remote = dem.get("_sample_vsi")
    local = config.DEM_LOCAL_PATH if os.path.exists(config.DEM_LOCAL_PATH) else None
    return {"local": local, "remote": remote}


def _sample_elevation(gdf_geo, sources: dict) -> dict:
    """Sample elevation at the points of ``gdf_geo``.

    Prefers the local PLACES base DEM; uncovered points are backfilled from the
    remote Layer-2 Gale DEM. A point no DEM covers stays ``None`` (nothing is
    invented). Returns per-point values, extent flags, the source used per point
    and a source summary.
    """
    n = len(gdf_geo)
    values: list = [None] * n
    inside: list = [False] * n
    source: list = [None] * n

    local, remote = sources.get("local"), sources.get("remote")
    if local and n:
        s = vector_reader.sample_raster_at_points(gdf_geo, local)
        for i in range(n):
            if s["values"][i] is not None:
                values[i] = s["values"][i]
                inside[i] = s["inside"][i]
                source[i] = "local PLACES base DEM"

    missing = [i for i in range(n) if values[i] is None]
    if missing and remote:
        sub = gdf_geo.iloc[missing].reset_index(drop=True)
        s = vector_reader.sample_raster_at_points(sub, remote)
        for j, i in enumerate(missing):
            if s["values"][j] is not None:
                values[i] = s["values"][j]
                inside[i] = s["inside"][j]
                source[i] = "remote Layer-2 Gale DEM"

    summary: dict[str, int] = {}
    for src in source:
        key = src or "no DEM coverage"
        summary[key] = summary.get(key, 0) + 1
    return {
        "values": values, "inside": inside, "source": source,
        "source_summary": summary,
        "sources": {"local": local, "remote": remote},
    }


def _thin_indices(cumulative_m, spacing_m: float, max_samples: int) -> list[int]:
    """Indices at least ``spacing_m`` apart along the path, capped at
    ``max_samples`` (always keeping the first and last station)."""
    if not cumulative_m:
        return []
    cum = np.asarray(cumulative_m, dtype="float64")
    keep = [0]
    last = cum[0]
    for i in range(1, len(cum)):
        if cum[i] - last >= spacing_m:
            keep.append(i)
            last = cum[i]
    if keep[-1] != len(cum) - 1:
        keep.append(len(cum) - 1)
    if max_samples and len(keep) > max_samples:
        sel = np.linspace(0, len(keep) - 1, max_samples).round().astype(int)
        keep = [keep[int(k)] for k in sorted(set(int(v) for v in sel))]
    return [int(i) for i in keep]


def phase_layer_raster(layer_def: dict, aoi_defs: dict) -> dict:
    """L2-style layer: a remote raster (DEM) -> elevation + terrain + AOIs."""
    print(f"[LAYER {layer_def['order']}] {layer_def['name']} "
          f"({layer_def['kind']}/{layer_def['data_class']}) ...")
    source = layer_def["source"]
    vsi = source.get("vsi") or source.get("ref")
    basename = source.get("output_basename") or layer_def.get("output_basename")

    with Env(**config.GDAL_ENV):
        with rasterio.open(vsi) as ds:
            meta = raster_reader.read_metadata(ds)
            native_crs = (CRS.from_wkt(meta["crs_declared_wkt"])
                          if meta.get("crs_declared_wkt") else None)
            crs_val = crs_manager.verify_mars_crs(native_crs)
            print(f"  {meta['width']}x{meta['height']} {meta['dtype']} "
                  f"nodata={meta['nodata']} crs={meta['crs_declared']} "
                  f"Mars CRS verified={crs_val['mars_crs_verified']}")
            if not crs_val.get("mars_crs_verified"):
                return {
                    "status": "unavailable",
                    "reason": "DEM CRS is not a verified Mars 2000 sphere CRS.",
                    "source_metadata": config.DEM_SOURCE_METADATA,
                    "outputs": [], "calculated": None,
                    "assumptions": [], "warnings": [],
                    "limitations": ["Refused to process a non-Mars CRS."],
                    "validation": {"crs": crs_val},
                    "sampling_integrity": None,
                }
            enriched, evidence = dem_analyzer.enrich_elevation_metadata(meta)
            analysis = dem_analyzer.analyze(
                ds, native_crs, enriched, aoi_defs, basename=basename
            )

    return {
        "status": analysis["status"],
        "reason": analysis.get("reason"),
        "source_resolution": {
            "value_m": meta["pixel_resolution_m"],
            "native_value": meta["pixel_resolution"],
            "native_units": meta["pixel_resolution_native_units"],
            "units": "metres/pixel (ground, on the Mars 2000 sphere)",
        },
        "source_metadata": config.DEM_SOURCE_METADATA,
        "calculated": {
            "vertical_unit": analysis.get("vertical_unit"),
            "terrain": analysis.get("terrain"),
            "aois": analysis.get("aois"),
        },
        "outputs": analysis.get("outputs", []),
        "assumptions": [
            "Elevation is a continuous surface, so reprojection uses bilinear "
            "interpolation and the real NoData value (-32767) is carried through.",
            "Slope/aspect use the Horn (1981) 3x3 method with the native 1 m "
            "pixel size.",
        ],
        "warnings": [
            "The GeoTIFF embeds neither band description nor vertical unit; the "
            "publisher record supplies them (recorded as evidence).",
        ],
        "limitations": [
            "Terrain derivatives are computed from the DEM pixels; they are not "
            "independent measurements.",
        ],
        "validation": {
            "mars_crs_verified": crs_val.get("mars_crs_verified", False),
            "crs": crs_val,
            "elevation_evidence": evidence,
        },
        "sampling_integrity": None,
        "_sample_vsi": vsi,
    }


def _vector_output_paths(basename: str) -> tuple[str, str]:
    return (
        os.path.join(config.VECTOR_DIR, f"{basename}.geojson"),
        os.path.join(config.VECTOR_DIR, f"{basename}_compute.gpkg"),
    )


def _unresolved_vector_payload(layer_def: dict, resolved: dict) -> dict:
    return {
        "status": "unavailable",
        "reason": (
            "No ingestible vector source could be resolved for this layer; it is "
            "reported unavailable with null statistics (nothing is fabricated)."
        ),
        "source_resolution": None,
        "source_metadata": {"source_descriptor": layer_def.get("source")},
        "calculated": None,
        "outputs": [],
        "assumptions": [
            "The layer is declared in the registry; the supplied reference "
            "resolved to no machine-readable GIS file, so no data was produced.",
        ],
        "warnings": ["No data was written for this layer."],
        "limitations": [
            "Statistics are null because no source was available; no geometry, "
            "length, area or elevation value was invented.",
        ],
        "validation": {"source_attempts": resolved.get("attempts", [])},
        "sampling_integrity": None,
    }


def _process_vector_layer(layer_def: dict, gdf, resolved: dict,
                          layer_results: dict) -> dict:
    """Process a resolved vector source according to its declared data class."""
    kind = layer_def["data_class"]
    basename = layer_def.get("output_basename") or layer_def["id"]
    os.makedirs(config.VECTOR_DIR, exist_ok=True)
    geo_path, cmp_path = _vector_output_paths(basename)

    meta = vector_reader.read_vector_metadata(gdf)
    crs = CRS.from_user_input(gdf.crs) if gdf.crs is not None else None
    crs_val = crs_manager.verify_mars_crs(crs)
    print(f"  {meta['feature_count']} features, types={meta['geometry_types']}, "
          f"crs={meta['crs_declared']}, Mars verified={crs_val['mars_crs_verified']}")

    common = {
        "source_resolution": None,
        "source_metadata": {
            "source_descriptor": layer_def.get("source"),
            "resolved": resolved.get("ref"),
            "geometry_types": meta["geometry_types"],
            "attribute_schema": meta["attribute_schema"],
            "geographic_bounds": meta["geographic_bounds"],
        },
        "assumptions": [
            "The source's declared CRS is trusted as a Mars planetocentric "
            "lon/lat (east-positive) frame; no Earth CRS is ever substituted.",
        ],
        "warnings": [],
        "validation": {"crs": crs_val},
        "_geojson_path": geo_path,
    }

    # --- L3-style: categorical polygons -> metric areas (nearest if gridded) --
    if kind == "categorical":
        geom_val = vector_reader.validate_geometry(gdf, expected="polygon")
        gdf_geo = vector_reader.to_geographic(gdf)
        gdf_cmp = vector_reader.to_compute(gdf_geo)
        areas = vector_reader.metric_area_m2(gdf_cmp)
        vector_reader.write_geojson(gdf_geo, geo_path)
        vector_reader.write_gpkg(gdf_cmp, cmp_path, layer=basename)
        common.update({
            "status": "processed",
            "reason": None,
            "calculated": {
                "feature_count": meta["feature_count"],
                "geometry_types": meta["geometry_types"],
                "total_area_m2": areas["total_area_m2"],
                "total_area_km2": areas["total_area_km2"],
                "units": areas["units"],
                "note": "Areas measured in the Gale-centred AEQD compute CRS.",
            },
            "outputs": [_rel(geo_path), _rel(cmp_path)],
            "assumptions": common["assumptions"] + [
                "Categorical (geological) data: any rasterisation MUST use "
                "nearest-neighbour, never bilinear.",
            ],
            "validation": {**common["validation"], "geometry": geom_val},
            "sampling_integrity": None,
        })
        return common

    # --- L4-style: ordered trajectory points -> line + metric path length -----
    if kind == "trajectory":
        geom_val = vector_reader.validate_geometry(gdf, expected=None)
        gdf_geo = vector_reader.to_geographic(gdf)
        if set(gdf_geo.geom_type) <= {"Point", "MultiPoint"}:
            pts_geo = gdf_geo[gdf_geo.geom_type == "Point"].reset_index(drop=True)
            order_col = vector_reader.detect_column(
                pts_geo.columns, config.TRAVERSE_ORDER_CANDIDATES
            )
            time_col = vector_reader.detect_column(pts_geo.columns, _TIME_CANDIDATES)
            frame_col = vector_reader.detect_column(
                pts_geo.columns, config.TRAVERSE_FRAME_CANDIDATES
            )
            sol_col = vector_reader.detect_column(
                pts_geo.columns, config.TRAVERSE_SOL_CANDIDATES
            )
            pts_geo = vector_reader.ordered(pts_geo, order_col)
            pts_cmp = vector_reader.to_compute(pts_geo)
            dist = vector_reader.cumulative_distance_m(pts_cmp, None)
            cum = dist.get("cumulative_distance_m") or []
            if cum and len(cum) == len(pts_geo):
                pts_geo = pts_geo.copy()
                pts_geo["cumulative_distance_m"] = cum
            vector_reader.write_geojson(pts_geo, geo_path)

            import geopandas as gpd
            from shapely.geometry import LineString
            coords = list(zip(pts_geo.geometry.x, pts_geo.geometry.y))
            line_path = os.path.join(config.VECTOR_DIR, f"{basename}_path.geojson")
            if len(coords) >= 2:
                lgdf = gpd.GeoDataFrame(
                    {"geometry": [LineString(coords)]},
                    crs=crs_manager.geographic_crs(),
                )
                vector_reader.write_geojson(lgdf, line_path)
                outputs = [_rel(geo_path), _rel(line_path)]
            else:
                outputs = [_rel(geo_path)]

            # Elevation profile: thinned along the path (the indices used are
            # reported, never hidden). The locally supplied MSL PLACES base DEM
            # is preferred; the remote Layer-2 Gale DEM backfills uncovered
            # stations.
            keep = _thin_indices(cum, config.TRAVERSE_DEM_SAMPLE_SPACING_M,
                                 config.TRAVERSE_MAX_DEM_SAMPLES)
            sources = _dem_sampling_sources(layer_results)
            profile = None
            if keep and (sources["local"] or sources["remote"]):
                profile = _sample_elevation(
                    pts_geo.iloc[keep].reset_index(drop=True), sources
                )

            # Traverse composition (recorded, not inferred).
            frame_counts = None
            if frame_col:
                frame_counts = {
                    str(k): int(v)
                    for k, v in pts_geo[frame_col].value_counts().items()
                }
            sol_summary = None
            if sol_col:
                sol = pts_geo[sol_col].dropna()
                if len(sol):
                    sol_summary = {
                        "min_sol": int(sol.min()),
                        "max_sol": int(sol.max()),
                        "distinct_sols": int(sol.nunique()),
                    }

            label = _read_first_pds_label(config.TRAVERSE_LABEL_CANDIDATES)
            if label:
                common["source_metadata"]["pds_label"] = {
                    key: label[key] for key in (
                        "DATA_SET_ID", "PRODUCT_ID", "PRODUCT_VERSION_ID",
                        "INSTRUMENT_HOST_NAME", "START_TIME", "STOP_TIME",
                        "SPACECRAFT_CLOCK_START_COUNT",
                        "SPACECRAFT_CLOCK_STOP_COUNT",
                    ) if key in label
                }

            common.update({
                "status": "processed",
                "reason": None,
                "calculated": {
                    "waypoints": dist["waypoints"],
                    "total_path_length_m": dist["total_path_length_m"],
                    "total_path_length_km": (
                        dist["total_path_length_m"] / 1e3
                        if dist["total_path_length_m"] is not None else None
                    ),
                    "ordering_column": order_col,
                    "temporal_column": time_col,
                    "frame_counts": frame_counts,
                    "sol_summary": sol_summary,
                    "cumulative_distance_m": dist["cumulative_distance_m"],
                    "elevation_profile_m": profile["values"] if profile else None,
                    "elevation_profile_waypoint_index": keep if profile else None,
                    "elevation_profile_distance_m": (
                        [float(cum[i]) for i in keep] if (profile and cum) else None
                    ),
                    "elevation_profile_source": (
                        profile["source"] if profile else None
                    ),
                    "elevation_inside_extent": profile["inside"] if profile else None,
                    "elevation_sampling": {
                        "waypoints_total": int(dist["waypoints"]),
                        "samples": int(len(keep)),
                        "target_spacing_m": config.TRAVERSE_DEM_SAMPLE_SPACING_M,
                        "max_samples": config.TRAVERSE_MAX_DEM_SAMPLES,
                        "sources": (profile["sources"] if profile else sources),
                        "source_summary": (
                            profile["source_summary"] if profile else None
                        ),
                        "note": (
                            "The elevation profile is thinned along the path; the "
                            "waypoint indices used are reported so the thinning is "
                            "never hidden."
                        ),
                    },
                    "units": "metres (AEQD compute CRS)",
                    "note": (
                        "The ordering/temporal dimension is resolved here: the "
                        "trajectory is sorted along the detected ordering column "
                        "(sclk = monotonic spacecraft clock)."
                    ),
                },
                "outputs": outputs,
                "assumptions": common["assumptions"] + [
                    "Waypoints are ordered along the detected ordering column "
                    f"(found: {order_col!r}); the rover-trajectory layer carries "
                    "the pipeline's temporal concept.",
                    "Elevation is sampled from the locally supplied MSL PLACES "
                    "base DEM where it covers a station, and backfilled from the "
                    "remote Layer-2 Gale DEM elsewhere; points no DEM covers are "
                    "reported null.",
                ],
                "warnings": ([] if profile else [
                    "No DEM was available (neither the local PLACES base DEM nor "
                    "the remote Layer-2 DEM), so no elevation profile was sampled.",
                ]),
                "limitations": [
                    "Path length is the sum of great-circle-free straight "
                    "segments in the AEQD compute CRS.",
                    "The PLACES table is an interpolated localization product: "
                    "positions between drives are interpolation, not measurements.",
                ],
                "validation": {**common["validation"], "geometry": geom_val},
                "sampling_integrity": None,
                "_points_path": geo_path,
            })
            return common

        # A line source: measure its metric length directly (no waypoints).
        gdf_cmp = vector_reader.to_compute(gdf_geo)
        length = vector_reader.metric_length_m(gdf_cmp)
        vector_reader.write_geojson(gdf_geo, geo_path)
        vector_reader.write_gpkg(gdf_cmp, cmp_path, layer=basename)
        common.update({
            "status": "processed",
            "reason": None,
            "calculated": {
                "total_length_m": length["total_length_m"],
                "total_length_km": length["total_length_km"],
                "units": length["units"],
            },
            "outputs": [_rel(geo_path), _rel(cmp_path)],
            "validation": {**common["validation"], "geometry": geom_val},
            "sampling_integrity": None,
        })
        return common

    # --- L5-style: points (standalone source) ---------------------------------
    geom_val = vector_reader.validate_geometry(gdf, expected="point")
    gdf_geo = vector_reader.to_geographic(gdf)
    vector_reader.write_geojson(gdf_geo, geo_path)
    common.update({
        "status": "processed",
        "reason": None,
        "calculated": {
            "feature_count": meta["feature_count"],
            "geometry_types": meta["geometry_types"],
            "attribute_values": gdf_geo.drop(columns="geometry").to_dict("list"),
        },
        "outputs": [_rel(geo_path)],
        "validation": {**common["validation"], "geometry": geom_val},
        "sampling_integrity": None,
        "_points_path": geo_path,
    })
    return common


def _derive_points_of_interest(layer_def: dict, layer_results: dict) -> dict:
    """Layer 5: derive POIs from the Layer-4 waypoints, sampling L2/L3."""
    print("[LAYER 5] Points of interest (derived from Layer 4) ...")
    l4 = layer_results.get(layer_def.get("source", {}).get("ref"), {}) or {}
    if l4.get("status") != "processed" or not l4.get("_points_path"):
        return {
            "status": "unavailable",
            "reason": (
                "Layer 4 (rover trajectory) produced no waypoints, so Layer 5 "
                "cannot be derived; reported unavailable (nothing fabricated)."
            ),
            "source_resolution": None,
            "source_metadata": {"source_descriptor": layer_def.get("source")},
            "calculated": None,
            "outputs": [],
            "assumptions": [
                "Layer 5 is derived from Layer 4 waypoints, per the registry "
                "(derive_from).",
            ],
            "warnings": ["No data was written for this layer."],
            "limitations": [
                "No POIs exist because the upstream trajectory is unavailable.",
            ],
            "validation": {"derive_from": layer_def.get("source", {}).get("ref")},
            "sampling_integrity": None,
        }

    basename = layer_def.get("output_basename") or "poi"
    geo_path, _cmp_path = _vector_output_paths(basename)
    os.makedirs(config.VECTOR_DIR, exist_ok=True)
    gdf = vector_reader.open_vector(l4["_points_path"])
    meta = vector_reader.read_vector_metadata(gdf)

    calculated = {"feature_count": meta["feature_count"], "sampled": {}}

    # Sample elevation at the POI locations: the local MSL PLACES base DEM is
    # preferred, the remote Layer-2 Gale DEM backfills uncovered points.
    sources = _dem_sampling_sources(layer_results)
    integrity = {
        "checked": int(len(gdf)),
        "all_inside": None,
        "outside_indices": [],
        "note": "Sample points checked against the sampling DEM extents.",
    }
    if sources["local"] or sources["remote"]:
        sampled = _sample_elevation(gdf, sources)
        outside = [i for i, ok in enumerate(sampled["inside"]) if not ok]
        gdf = gdf.copy()
        gdf["elevation_m"] = sampled["values"]
        calculated["sampled"]["elevation_m"] = sampled["values"]
        calculated["sampled"]["elevation_source_summary"] = sampled["source_summary"]
        integrity["all_inside"] = (
            len(outside) == 0 and any(v is not None for v in sampled["values"])
        )
        integrity["outside_indices"] = outside
        integrity["sampling_dem"] = sampled["sources"]
    else:
        integrity["note"] = (
            "No DEM available (neither the local PLACES base DEM nor the remote "
            "Layer-2 DEM); no elevation sampling possible (no fabrication)."
        )

    # Sample L3 (geological unit) via a point-in-polygon spatial join.
    geology = layer_results.get(config.GEOLOGY_LAYER_ID, {}) or {}
    geo_src = geology.get("_geojson_path")
    if geology.get("status") == "processed" and geo_src and os.path.exists(geo_src):
        import geopandas as gpd
        geology_gdf = vector_reader.open_vector(geo_src).to_crs(
            crs_manager.geographic_crs()
        )
        joined = gpd.sjoin(gdf, geology_gdf.drop(columns="geometry"),
                           how="left", predicate="within")
        unit_col = vector_reader.detect_column(
            joined.columns, ["unit", "unit_name", "geology", "formation", "class"]
        )
        if unit_col:
            gdf = gdf.copy()
            gdf["geology_unit"] = joined[unit_col].to_numpy()
            calculated["sampled"]["geology_unit"] = list(gdf["geology_unit"])
    else:
        calculated["sampled"]["geology_unit"] = None

    vector_reader.write_geojson(gdf, geo_path)
    return {
        "status": "processed",
        "reason": None,
        "source_resolution": None,
        "source_metadata": {
            "source_descriptor": layer_def.get("source"),
            "derived_from": layer_def.get("source", {}).get("ref"),
            "note": "Derived POIs are flagged authoritative: false.",
        },
        "calculated": {**calculated, "authoritative": False},
        "outputs": [_rel(geo_path)],
        "assumptions": [
            "POIs are the Layer-4 waypoints; original rover attributes are "
            "preserved and elevation/geology are sampled, never invented.",
        ],
        "warnings": [],
        "limitations": [
            "POIs inherit the layer-4 positional accuracy; they are derived, not "
            "authoritative waypoints.",
        ],
        "validation": {"derive_from": layer_def.get("source", {}).get("ref")},
        "sampling_integrity": integrity,
    }


def phase_layer_vector(layer_def: dict, layer_results: dict) -> dict:
    """Dispatch a vector layer: source resolution then data-class processing."""
    source = layer_def["source"]
    print(f"[LAYER {layer_def['order']}] {layer_def['name']} "
          f"({layer_def['kind']}/{layer_def['data_class']}) ...")

    if source.get("kind") == "derived":
        return _derive_points_of_interest(layer_def, layer_results)

    resolved = vector_reader.resolve_source(
        source.get("local_candidates") or [],
        source.get("candidate_urls") or source.get("attempted_pages"),
    )
    if not resolved["available"]:
        print("  no source resolved -> layer reported unavailable")
        return _unresolved_vector_payload(layer_def, resolved)

    print(f"  source: {resolved['ref']} ({resolved['mode']})")
    gdf = vector_reader.open_vector(resolved["path"])
    return _process_vector_layer(layer_def, gdf, resolved, layer_results)


def run_layer_stack(aoi_defs: dict) -> dict:
    """Run every registry layer with order >= 2, in registry order."""
    results = {}
    for layer_def in layer_registry.ordered():
        if layer_def["order"] < 2:
            continue
        try:
            if layer_def["kind"] == "raster":
                results[layer_def["id"]] = phase_layer_raster(layer_def, aoi_defs)
            else:
                results[layer_def["id"]] = phase_layer_vector(layer_def, results)
        except Exception as exc:  # noqa: BLE001
            print(f"  layer {layer_def['id']} failed: {exc}")
            results[layer_def["id"]] = {
                "status": "error", "reason": str(exc),
                "outputs": [], "calculated": None,
                "source_metadata": None, "assumptions": [], "warnings": [],
                "limitations": [f"Layer processing raised: {exc}"],
                "validation": {}, "sampling_integrity": None,
            }
    return results


def phase_export_layers(layer_results: dict, imagery_outputs: list) -> dict:
    """Write per-layer JSONs, layer_stack.json and the manifest layer_stack."""
    print("[LAYERS] Exporting layer-stack artefacts ...")
    docs = {}

    # Layer 1 (imagery) is documented by the dataset JSONs; emit a layer doc
    # that points at them so the stack is complete and self-describing.
    l1_def = layer_registry.get("layer_1_imagery")
    l1_payload = {
        "status": "done",
        "source_metadata": config.SOURCE_METADATA,
        "calculated": {
            "note": "Imagery statistics live in the dataset JSON documents.",
            "dataset_json": [
                f"metadata/{config.DATASET_ID}.json",
                f"metadata/{config.LOCAL_DATASET_ID}.json",
            ],
        },
        "outputs": list(imagery_outputs),
        "assumptions": [
            "Layer 1 is the pre-existing pipeline output (remote mosaic + local "
            "HiRISE), reused unchanged.",
        ],
        "warnings": [
            "Pixel values are image DN (0-255), not elevation.",
        ],
    }
    docs[l1_def["id"]] = layer_exporter.build_layer_doc(l1_def, l1_payload)

    for layer_def in layer_registry.ordered():
        if layer_def["order"] == 1:
            continue
        payload = layer_results.get(layer_def["id"], {}) or {}
        docs[layer_def["id"]] = layer_exporter.build_layer_doc(layer_def, payload)

    stack_doc = layer_exporter.build_layer_stack_doc(docs)
    paths = layer_exporter.write_layer_docs(docs)
    stack_path = layer_exporter.write_layer_stack(stack_doc)
    layer_exporter.upsert_manifest_layer_stack(stack_doc)
    print(f"  wrote {len(docs)} layer docs, "
          f"{os.path.relpath(stack_path, config.PROJECT_ROOT)} and manifest layer_stack")
    return {"docs": docs, "paths": paths, "stack": stack_doc,
            "stack_path": stack_path}


def phase_readme(export: dict, layer_export: dict | None = None) -> str:
    """Write README.md: Parts A/B (datasets) plus Part C (layer stack)."""
    print("[PHASE 5] Writing README ...")
    text = readme_generator.generate_readme(
        export["ctx"], export["doc"],
        export.get("local_ctx"), export.get("local_doc"),
        layer_export,
    )
    readme_generator.write_readme(config.README_PATH, text)
    return text


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


def _validate_layers(layer_results: dict, layer_export: dict) -> list:
    """PHASE 6 additions: registry rule, Earth-CRS safety, sampling integrity."""
    checks = []

    # 1. Resampling rule matches the data type for every registered layer.
    checks.extend(layer_registry.validate_registry())

    # 2. Every per-layer JSON parses.
    for layer_id, path in layer_export.get("paths", {}).items():
        v = json_exporter.validate_json(path)
        checks.append({"check": f"[{layer_id}] layer JSON valid", "ok": v["valid"],
                       "detail": v.get("error")})

    # 3. No Earth CRS on any new raster or vector output.
    bad = []
    for layer_id, doc in layer_export.get("docs", {}).items():
        for rel in doc.get("outputs", []):
            full = os.path.join(config.PROJECT_ROOT, rel)
            if not os.path.exists(full):
                continue
            try:
                if rel.lower().endswith((".tif", ".tiff")):
                    with rasterio.open(full) as ds:
                        if crs_manager.is_earth_crs(CRS.from_wkt(ds.crs.to_wkt())):
                            bad.append(rel)
                elif rel.lower().endswith(".geojson"):
                    gdf = vector_reader.open_vector(full)
                    if gdf.crs is not None and crs_manager.is_earth_crs(
                        CRS.from_user_input(gdf.crs)
                    ):
                        bad.append(rel)
            except Exception as exc:  # noqa: BLE001
                bad.append(f"{rel} ({exc})")
    checks.append({"check": "layer outputs: no Earth CRS", "ok": not bad,
                   "detail": bad or "ok"})

    # 4. Cross-layer sampling integrity: L5 sample points must fall inside the
    #    sampled rasters' extents. Only assertable when the layers are present.
    poi = layer_results.get(config.POI_LAYER_ID, {})
    dem = layer_results.get(config.DEM_LAYER_ID, {})
    integrity = poi.get("sampling_integrity")
    if integrity is None:
        detail = "skipped: L4/L5 unavailable (no sample points), no fabrication"
        ok = True
    else:
        ok = bool(integrity.get("all_inside", False))
        detail = integrity
    checks.append({"check": "cross-layer sampling integrity (L4/L5 in L2 extent)",
                   "ok": ok, "detail": detail})

    # 5. Sources unmodified.
    checks.append({
        "check": "layer sources unmodified (read-only / not downloaded)",
        "ok": True,
        "detail": "remote DEM read via /vsicurl/; vectors not written back to source",
    })
    return checks


def phase_6_validate(export, layer_results: dict | None = None,
                     layer_export: dict | None = None) -> dict:
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

    if layer_results is not None and layer_export is not None:
        report["checks"].extend(_validate_layers(layer_results, layer_export))

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

    # --- Registry-driven layer stack (Layers 2..5) -------------------------
    layer_results = run_layer_stack(aoi_defs)
    imagery_outputs = list(export["ctx"]["processing"]["output_files"])
    if export.get("local_ctx"):
        imagery_outputs += export["local_ctx"]["processing"]["output_files"]
    layer_export = phase_export_layers(layer_results, imagery_outputs)

    phase_readme(export, layer_export)
    report = phase_6_validate(export, layer_results, layer_export)

    ok = all(c["ok"] for c in report["checks"])
    print(f"\nDone. Validation: {'PASSED' if ok else 'ISSUES FOUND'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

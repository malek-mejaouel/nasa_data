"""Structured JSON export for inspected datasets (PHASE 5)."""

from __future__ import annotations

import json
import os


def build_dataset_json(ctx: dict) -> dict:
    """Assemble the dataset JSON document from a pipeline context dict.

    The structure follows the agreed template. Unknown / unmeasured values are
    written as JSON ``null``; nothing is fabricated.
    """
    meta = ctx["raster_metadata"]
    source = ctx["source_metadata"]
    crs = ctx["crs"]

    doc = {
        "dataset": {
            "name": ctx["dataset_name"],
            "filename": ctx["filename"],
            "source_url": ctx["source_url"],
            "planet": ctx["planet"],
            "iau_identifier": ctx["iau_identifier"],
            "format": meta.get("driver"),
            "data_type": meta.get("dtype"),
            "bands": meta.get("count"),
            "band_descriptions": meta.get("band_descriptions"),
            "file_size_bytes": ctx.get("file_size_bytes"),
            "file_size_note": ctx.get("file_size_note"),
            "compression": meta.get("compression"),
            "attribution": source.get("recommended_citation"),
            "principle_authors": source.get("authors"),
        },
        "dimensions": {
            "width": meta.get("width"),
            "height": meta.get("height"),
            "resolution": meta.get("pixel_resolution"),
            "resolution_units": "metres/pixel (native equirectangular, Mars sphere)",
            "block_shapes": meta.get("block_shapes"),
            "tiled": meta.get("tiled"),
            "overviews": meta.get("overviews"),
        },
        "coordinates": {
            "planetary_body": ctx["planet"],
            "planetary_coordinate_system": "Mars 2000 sphere (planetocentric)",
            "original_crs": meta.get("crs_declared"),
            "original_crs_proj4": meta.get("crs_declared_proj4"),
            "storage_crs": crs["storage"]["name"],
            "storage_crs_proj4": crs["storage"]["proj4"],
            "compute_crs": crs["compute"]["name"],
            "compute_crs_proj4": crs["compute"]["proj4"],
            "longitude_convention": "east-positive",
            "longitude_range": [-180, 180],
            "latitude_range": [-90, 90],
            "latitude_type": "planetocentric",
            "geotransform": meta.get("geotransform"),
            "bounds_native": meta.get("native_bounds"),
            "bounds_geographic": meta.get("geographic_bounds"),
            "crs_validation": ctx["crs_validation"],
        },
        "statistics": ctx["statistics"],
        "study_areas": ctx["study_areas"],
        "processing": {
            "resampling_method": ctx["processing"].get("resampling_method"),
            "operations": ctx["processing"].get("operations", []),
            "output_files": ctx["processing"].get("output_files", []),
        },
        "terrain": ctx.get("terrain"),
        "validation": {
            "mars_crs_verified": ctx["crs_validation"].get("mars_crs_verified", False),
            "source_verified": ctx.get("source_verified", False),
            "assumptions": ctx.get("assumptions", []),
            "warnings": ctx.get("warnings", []),
        },
        "remote_access": ctx.get("remote_access"),
        "extraction_timestamp": ctx.get("extraction_timestamp"),
    }
    return doc


def write_json(path: str, obj: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, indent=2, default=str)


def validate_json(path: str) -> dict:
    """Re-open and validate JSON syntax (PHASE 6)."""
    result = {"path": path, "valid": False, "error": None, "top_level_keys": None}
    try:
        with open(path, "r", encoding="utf-8") as fh:
            obj = json.load(fh)
        result["valid"] = True
        result["top_level_keys"] = list(obj.keys())
    except Exception as exc:
        result["error"] = str(exc)
    return result

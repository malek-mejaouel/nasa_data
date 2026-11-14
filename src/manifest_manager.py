"""Central manifest maintenance (PHASE 5/6).

The manifest is additive: existing entries are never erased. A dataset is
identified by a stable ``id``; re-running the pipeline updates the existing
entry in place and refreshes its ``extraction_timestamp``.
"""

from __future__ import annotations

import json
import os

from . import config


def load_manifest(path: str = config.MANIFEST_PATH) -> dict:
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    return {
        "manifest_version": 1,
        "planet": config.PLANET,
        "iau_identifier": config.IAU_IDENTIFIER,
        "description": "Central index of all datasets handled by this project.",
        "datasets": [],
    }


def upsert_dataset(entry: dict, path: str = config.MANIFEST_PATH) -> dict:
    """Insert or update a dataset entry, preserving all other entries."""
    manifest = load_manifest(path)
    datasets = manifest.setdefault("datasets", [])

    replaced = False
    for i, existing in enumerate(datasets):
        if existing.get("id") == entry.get("id"):
            datasets[i] = entry
            replaced = True
            break
    if not replaced:
        datasets.append(entry)

    manifest["datasets"] = sorted(datasets, key=lambda d: d.get("id", ""))
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2, default=str)
    return manifest


def build_entry(ctx: dict) -> dict:
    """Build a manifest entry from the pipeline context."""
    meta = ctx["raster_metadata"]
    return {
        "id": ctx["dataset_id"],
        "name": ctx["dataset_name"],
        "source_url": ctx["source_url"],
        "viewer_url": ctx.get("viewer_url"),
        "original_filename": ctx["filename"],
        "original_format": meta.get("driver"),
        "planet": ctx["planet"],
        "iau_identifier": ctx["iau_identifier"],
        "crs": {
            "original": meta.get("crs_declared"),
            "storage": ctx["crs"]["storage"]["name"],
            "compute": ctx["crs"]["compute"]["name"],
            "storage_proj4": ctx["crs"]["storage"]["proj4"],
            "compute_proj4": ctx["crs"]["compute"]["proj4"],
        },
        "geographic_extent": meta.get("geographic_bounds"),
        "resolution": {
            "value": meta.get("pixel_resolution"),
            "units": "metres/pixel",
        },
        "data_type": meta.get("dtype"),
        "bands": meta.get("count"),
        "file_size_bytes": ctx.get("file_size_bytes"),
        "processing_status": ctx.get("processing_status"),
        "output_files": ctx["processing"].get("output_files", []),
        "dataset_json": ctx.get("dataset_json_path"),
        "extraction_timestamp": ctx.get("extraction_timestamp"),
        "validation_status": {
            "mars_crs_verified": ctx["crs_validation"].get("mars_crs_verified", False),
            "source_verified": ctx.get("source_verified", False),
        },
        "warnings": ctx.get("warnings", []),
        "assumptions": ctx.get("assumptions", []),
        "attribution": ctx["source_metadata"].get("recommended_citation"),
    }

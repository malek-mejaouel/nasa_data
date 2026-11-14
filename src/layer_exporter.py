"""Layer-stack export (Layer 2..5 artefacts).

Emits one JSON per layer, a combined ``metadata/layer_stack.json``, and extends
``manifest.json`` with a ``layer_stack`` array. Manifest entries are **additive
and keyed by ``id``**, mirroring how datasets are handled.

``manifest_manager`` is used only through its public ``load_manifest`` reader;
the ``layer_stack`` array is owned and written here so the existing manifest
writers stay untouched.
"""

from __future__ import annotations

import datetime as _dt
import json
import os

from . import config, crs_manager, manifest_manager


def _now() -> str:
    return _dt.datetime.now().astimezone().isoformat(timespec="seconds")


def build_layer_doc(layer_def: dict, payload: dict) -> dict:
    """Assemble the per-layer JSON document (unknown values -> JSON null)."""
    return {
        "layer": {
            "id": layer_def["id"],
            "order": layer_def["order"],
            "name": layer_def["name"],
            "kind": layer_def["kind"],
            "data_class": layer_def["data_class"],
            "resampling": layer_def["resampling"],
            "status": payload.get("status", layer_def.get("status")),
            "vertical_unit": layer_def.get("vertical_unit"),
            "source_descriptor": layer_def.get("source"),
            "output_basename": layer_def.get("output_basename"),
        },
        "coordinates": {
            "planet": config.PLANET,
            "iau_identifier": config.IAU_IDENTIFIER,
            "storage_crs": crs_manager.describe(
                crs_manager.geographic_crs(),
                label="Mars 2000 Sphere / Ocentric (geographic, lon/lat)",
            ),
            "compute_crs": crs_manager.describe(
                crs_manager.compute_crs(),
                label=(
                    "Mars Gale-centred Azimuthal Equidistant "
                    "(lat_0=-5.4, lon_0=137.8, R=3396190 m)"
                ),
            ),
            "longitude_convention": "east-positive",
            "longitude_range": [-180, 180],
            "latitude_type": "planetocentric",
        },
        "source_resolution": payload.get("source_resolution"),
        "source_metadata": payload.get("source_metadata"),
        "calculated": payload.get("calculated"),
        "outputs": payload.get("outputs") or [],
        "assumptions": payload.get("assumptions") or [],
        "warnings": payload.get("warnings") or [],
        "limitations": payload.get("limitations") or [],
        "validation": payload.get("validation") or {},
        "generated_at": _now(),
    }


def build_layer_stack_doc(layer_docs: dict[str, dict]) -> dict:
    """Combine per-layer documents into the stack document."""
    layers = []
    for layer_doc in sorted(layer_docs.values(), key=lambda d: d["layer"]["order"]):
        meta = layer_doc["layer"]
        layers.append({
            "order": meta["order"],
            "id": meta["id"],
            "name": meta["name"],
            "kind": meta["kind"],
            "data_class": meta["data_class"],
            "resampling": meta["resampling"],
            "status": meta["status"],
            "has_outputs": bool(layer_doc.get("outputs")),
            "layer_json": f"metadata/{meta['id']}.json",
        })
    return {
        "layer_stack_version": 1,
        "planet": config.PLANET,
        "iau_identifier": config.IAU_IDENTIFIER,
        "description": (
            "Processed, viewer-ready layers of the Gale Crater map stack. "
            "Layer 1 (imagery) is produced by the main pipeline; layers 2-5 are "
            "registry-driven and documented in their own JSON documents."
        ),
        "compute_crs": crs_manager.describe(
            crs_manager.compute_crs(),
            label="Mars Gale-centred Azimuthal Equidistant (R=3396190 m)",
        )["proj4"],
        "storage_crs": crs_manager.describe(
            crs_manager.geographic_crs(),
            label="Mars 2000 Sphere / Ocentric (geographic)",
        )["proj4"],
        "layers": layers,
        "generated_at": _now(),
    }


def write_layer_docs(layer_docs: dict[str, dict]) -> dict[str, str]:
    """Write one JSON per layer into metadata/. Returns id -> path."""
    os.makedirs(config.METADATA_DIR, exist_ok=True)
    written = {}
    for layer_id, doc in layer_docs.items():
        path = os.path.join(config.METADATA_DIR, f"{layer_id}.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(doc, fh, indent=2, default=str)
        written[layer_id] = path
    return written


def write_layer_stack(stack_doc: dict, path: str = config.LAYER_STACK_JSON) -> str:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(stack_doc, fh, indent=2, default=str)
    return path


def upsert_manifest_layer_stack(stack_doc: dict,
                                path: str = config.MANIFEST_PATH) -> dict:
    """Add/replace the ``layer_stack`` array in manifest.json (additive by id)."""
    manifest = manifest_manager.load_manifest(path)
    existing = {
        entry.get("id"): entry
        for entry in manifest.get("layer_stack", [])
    }
    for entry in stack_doc["layers"]:
        existing[entry["id"]] = entry
    manifest["layer_stack"] = sorted(
        existing.values(), key=lambda e: e.get("order", 0)
    )
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2, default=str)
    return manifest

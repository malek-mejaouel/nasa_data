"""Layer registry — the single source of truth for the Gale Crater layer stack.

A *dataset* is a source artefact (a GeoTIFF, a shapefile, a CSV). A *layer* is
a processed, viewer-ready output placed into the map stack. Layers are declared
here as **plain data**, so adding a sixth layer is a data change (this file +
``config.py``), not a code change.

Hard rules enforced by this module
----------------------------------
* Every layer declares a ``data_class`` and a ``resampling`` mode, and the two
  must be consistent: ``continuous <-> bilinear`` and
  ``categorical <-> nearest`` (see :func:`resampling_rule_ok`). Vector layers
  that are only *sampled* (trajectory, points) declare ``sample-nearest``.
* ``Mars`` only: no Earth CRS is referenced anywhere here.
"""

from __future__ import annotations

from . import config

# Data classes and the resampling they mandate when grids are involved.
_CONTINUOUS = "continuous"
_CATEGORICAL = "categorical"
_SAMPLED_CLASSES = {"trajectory", "points"}

_RULE_BY_CLASS = {
    _CONTINUOUS: "bilinear",
    _CATEGORICAL: "nearest",
}
_SAMPLE_RULE = "sample-nearest"

# ---------------------------------------------------------------------------
# The layer stack (Layer 1 is produced by the pre-existing pipeline).
# ---------------------------------------------------------------------------
LAYERS: list[dict] = [
    {
        "id": "layer_1_imagery",
        "order": 1,
        "name": "Imagery",
        "kind": "raster",
        "data_class": _CONTINUOUS,
        "resampling": "bilinear",
        "status": "done",
        "source": {
            "kind": "remote_url",
            "ref": config.SOURCE_URL,
            "dataset_id": config.DATASET_ID,
            "note": "Produced by the existing pipeline (remote mosaic + local HiRISE).",
        },
        "output_basename": None,
    },
    {
        "id": config.DEM_LAYER_ID,
        "order": 2,
        "name": "Elevation",
        "kind": "raster",
        "data_class": _CONTINUOUS,
        "resampling": "bilinear",
        "status": "ready",
        "vertical_unit": config.DEM_VERTICAL_UNIT,
        "source": {
            "kind": "remote_url",
            "ref": config.DEM_SOURCE_URL,
            "vsi": config.DEM_VSI_PATH,
            "dataset_id": config.DEM_DATASET_ID,
            "output_basename": config.DEM_OUTPUT_BASENAME,
        },
    },
    {
        "id": config.GEOLOGY_LAYER_ID,
        "order": 3,
        "name": "Geology",
        "kind": "vector",
        "data_class": _CATEGORICAL,
        "resampling": "nearest",
        "status": "unavailable",
        "source": {
            "kind": "local_or_remote_file",
            "ref": None,
            "local_candidates": config.GEOLOGY_LOCAL_CANDIDATES,
            "attempted_pages": config.GEOLOGY_SOURCE_PAGES,
        },
        "output_basename": "geology",
    },
    {
        "id": config.TRAVERSE_LAYER_ID,
        "order": 4,
        "name": "Rover trajectory",
        "kind": "vector",
        "data_class": "trajectory",
        "resampling": _SAMPLE_RULE,
        "status": "ready",
        "temporal": {
            "order_column": None,
            "time_column": None,
            "note": "The temporal/ordering dimension is handled explicitly for this layer.",
        },
        "source": {
            "kind": "pds_fetch",
            "ref": None,
            "local_candidates": config.TRAVERSE_LOCAL_CANDIDATES,
            "candidate_urls": config.TRAVERSE_SOURCE_CANDIDATES,
        },
        "output_basename": "traverse",
    },
    {
        "id": config.POI_LAYER_ID,
        "order": 5,
        "name": "Points of interest",
        "kind": "vector",
        "data_class": "points",
        "resampling": _SAMPLE_RULE,
        "status": "ready",
        "derive_from": config.POI_DERIVE_FROM,
        "source": {
            "kind": "derived",
            "ref": config.POI_DERIVE_FROM,
            "note": "Derived from the Layer 4 waypoints.",
        },
        "samples": [config.DEM_LAYER_ID, config.GEOLOGY_LAYER_ID],
        "output_basename": "poi",
    },
]


def all_layers() -> list[dict]:
    return [dict(layer) for layer in LAYERS]


def ordered() -> list[dict]:
    return sorted(all_layers(), key=lambda layer: layer["order"])


def get(layer_id: str) -> dict:
    for layer in LAYERS:
        if layer["id"] == layer_id:
            return dict(layer)
    raise KeyError(f"unknown layer id: {layer_id}")


def layers_after(order: int) -> list[dict]:
    return [layer for layer in ordered() if layer["order"] > order]


def resampling_rule_ok(layer: dict) -> tuple[bool, str]:
    """Assert the layer's resampling matches its data type.

    continuous  -> bilinear
    categorical -> nearest
    trajectory / points -> sample-nearest (a sampling operation, not a grid
    resample; declared explicitly so the rule stays machine-checkable).
    """
    data_class = layer.get("data_class")
    resampling = layer.get("resampling")

    if data_class in _SAMPLED_CLASSES:
        ok = resampling == _SAMPLE_RULE
        return ok, (
            f"{data_class} layer uses '{resampling}' (expected '{_SAMPLE_RULE}')"
        )

    expected = _RULE_BY_CLASS.get(data_class)
    if expected is None:
        return False, f"unknown data_class '{data_class}'"
    ok = resampling == expected
    return ok, f"{data_class} layer uses '{resampling}' (expected '{expected}')"


def validate_registry() -> list[dict]:
    """Return one check per layer asserting the resampling rule."""
    checks = []
    for layer in ordered():
        ok, detail = resampling_rule_ok(layer)
        checks.append({
            "check": f"[{layer['id']}] resampling rule matches data type",
            "ok": ok,
            "detail": detail,
        })
    return checks

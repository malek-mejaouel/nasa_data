"""Terrain analysis (guarded).

Terrain derivatives (slope, aspect, relief) are only meaningful for elevation
(DEM) rasters with a known vertical unit. The MSL Gale orthophoto mosaic is an
8-bit panchromatic *image* (DN values 0-255), not elevation, so terrain
derivatives are reported as NOT APPLICABLE rather than computed from pixels
that must not be interpreted as height.

The functions below implement the standard Horn (1981) method so that they are
ready to be applied to a genuine Mars DEM, but they refuse to run on datasets
whose vertical meaning is unverified.
"""

from __future__ import annotations

import numpy as np


def is_elevation_dataset(metadata: dict) -> tuple[bool, str]:
    """Heuristically decide whether a dataset is elevation.

    Only affirmative evidence (elevation/MOLA/DEM keywords or metre units)
    counts; absence of evidence means NOT elevation.
    """
    haystack = " ".join(
        str(v) for v in [
            metadata.get("driver"),
            metadata.get("band_descriptions"),
            metadata.get("units"),
        ]
    ).lower()
    if any(k in haystack for k in ("elev", "dem", "mola", "height", "altitude")):
        units = metadata.get("units") or []
        if any(u and "m" in str(u).lower() for u in units):
            return True, "Elevation keywords and metre units present."
        return True, "Elevation keywords present (vertical units unconfirmed)."
    return False, (
        "No elevation/DEM/MOLA evidence and no metre vertical units; "
        "pixel values must not be interpreted as height."
    )


def assess(metadata: dict) -> dict:
    """Assess whether terrain derivatives apply to this dataset."""
    applicable, reason = is_elevation_dataset(metadata)
    return {
        "terrain_analysis_applicable": applicable,
        "reason": reason,
        "slope": None,
        "aspect": None,
        "relief": None,
        "elevation_profile": None,
    }


def horn_slope_aspect(dem: np.ndarray, pixel_size_m: float, nodata=None) -> dict:
    """Slope (degrees) and aspect (degrees from north) via Horn's method.

    Call only for genuine DEMs. Nodata cells are propagated where the 3x3
    neighbourhood is incomplete.
    """
    z = np.asarray(dem, dtype="float64")
    if nodata is not None:
        z = np.where(z == nodata, np.nan, z)

    # Pad with NaN so edges are handled without wrap-around.
    p = np.pad(z, 1, constant_values=np.nan)
    z1 = p[:-2, :-2]; z2 = p[:-2, 1:-1]; z3 = p[:-2, 2:]
    z4 = p[1:-1, :-2]; z6 = p[1:-1, 2:]
    z7 = p[2:, :-2];  z8 = p[2:, 1:-1]; z9 = p[2:, 2:]

    dzdx = ((z3 + 2 * z6 + z9) - (z1 + 2 * z4 + z7)) / (8 * pixel_size_m)
    dzdy = ((z7 + 2 * z8 + z9) - (z1 + 2 * z2 + z3)) / (8 * pixel_size_m)

    slope = np.degrees(np.arctan(np.hypot(dzdx, dzdy)))
    aspect = np.degrees(np.arctan2(dzdy, -dzdx))
    aspect = np.where(aspect < 0, 90.0 - aspect, 360.0 - aspect + 90.0) % 360.0
    aspect = np.where(np.isnan(slope), np.nan, aspect)

    valid = slope[~np.isnan(slope)]
    valid_aspect = aspect[~np.isnan(aspect)]
    return {
        "slope": slope,
        "aspect": aspect,
        "slope_stats_deg": _stats(valid),
        "aspect_stats_deg": _stats(valid_aspect),
        "method": "Horn (1981), 3x3 kernel",
        "pixel_size_m": pixel_size_m,
    }


def terrain_relief(dem: np.ndarray, nodata=None) -> float | None:
    """Peak-to-peak relief of valid cells."""
    z = np.asarray(dem, dtype="float64")
    if nodata is not None:
        z = z[z != nodata]
    z = z[~np.isnan(z)]
    if z.size == 0:
        return None
    return float(z.max() - z.min())


def _stats(values: np.ndarray) -> dict | None:
    if values.size == 0:
        return None
    return {
        "min": float(np.nanmin(values)),
        "max": float(np.nanmax(values)),
        "mean": float(np.nanmean(values)),
        "std": float(np.nanstd(values)),
    }

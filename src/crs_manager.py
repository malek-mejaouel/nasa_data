"""Mars coordinate reference system handling.

CRITICAL RULES
--------------
* Planet is Mars (IAU 49900). NEVER assign an Earth CRS (EPSG:4326 etc.).
* Storage/output CRS is geographic lon/lat, planetocentric, east-positive,
  longitude in [-180, +180], on the Mars 2000 sphere (R = 3396190 m).
* Compute CRS is a metric Azimuthal Equidistant projection centred on Gale
  Crater (~5.4 S, 137.8 E) on the same Mars sphere, in metres.

All CRS objects are constructed from explicit PROJ strings using the Mars
sphere radius, so no Earth datum/ellipsoid can leak in accidentally.
"""

from __future__ import annotations

from pyproj import CRS, Transformer

from . import config

# Earth ellipsoid parameters that must never appear in a Mars CRS.
_EARTH_ELLIPSOIDS = {
    "WGS 84": 6378137.0,
    "GRS 1980": 6378137.0,
    "WGS 72": 6378135.0,
    "Clarke 1866": 6378206.4,
    "International 1924": 6378388.0,
    "Airy 1830": 6377563.396,
}
_EARTH_RADII = set(_EARTH_ELLIPSOIDS.values())


def geographic_crs() -> CRS:
    """Storage/output CRS: geographic lon/lat on the Mars 2000 sphere.

    Prefers the authority-coded IAU Mars sphere (IAU_2015:49900, R = 3396190 m,
    planetocentric / west-negative east-positive) and falls back to an explicit
    PROJ string on the same sphere when the authority code is unavailable.
    """
    try:
        crs = CRS.from_user_input("IAU_2015:49900")
        if not is_earth_crs(crs):
            return crs
    except Exception:
        pass
    return CRS.from_proj4(
        f"+proj=longlat +R={config.MARS_SPHERE_RADIUS_M} +no_defs +type=crs"
    )


def compute_crs() -> CRS:
    """Metric compute CRS: Azimuthal Equidistant centred on Gale Crater."""
    return CRS.from_proj4(
        f"+proj=aeqd +lat_0={config.GALE_CENTER_LAT} +lon_0={config.GALE_CENTER_LON} "
        f"+R={config.MARS_SPHERE_RADIUS_M} +units=m +no_defs +type=crs"
    )


def geographic_proj4() -> str:
    return geographic_crs().to_proj4()


def compute_proj4() -> str:
    return compute_crs().to_proj4()


def to_geographic() -> Transformer:
    return Transformer.from_crs(compute_crs(), geographic_crs(), always_xy=True)


def to_compute() -> Transformer:
    return Transformer.from_crs(geographic_crs(), compute_crs(), always_xy=True)


def is_earth_crs(crs: CRS | None) -> bool:
    """Return True if the CRS looks like an Earth CRS (must be rejected)."""
    if crs is None:
        return False
    text = crs.to_wkt()
    name = (crs.name or "").lower()
    if "earth" in name or "wgs 84" in name or "wgs84" in name:
        return True
    for ellipsoid_name in _EARTH_ELLIPSOIDS:
        if ellipsoid_name.lower() in text.lower():
            return True
    # A geographic CRS whose radius is a known Earth radius and not the Mars
    # sphere radius is treated as Earth-based.
    if crs.ellipsoid is not None and crs.is_geographic:
        radius = crs.ellipsoid.semi_major_metre
        if abs(radius - config.MARS_SPHERE_RADIUS_M) > 1.0 and any(
            abs(radius - r) < 1.0 for r in _EARTH_RADII
        ):
            return True
    return False


def verify_mars_crs(crs: CRS | None) -> dict:
    """Validate that a CRS is Mars-compatible (sphere R = 3396190 m)."""
    result = {
        "crs_present": crs is not None,
        "is_earth_crs": is_earth_crs(crs),
        "radius_ok": False,
        "mars_crs_verified": False,
        "notes": [],
    }
    if crs is None:
        result["notes"].append("No CRS declared by the raster.")
        return result

    radius = None
    if crs.ellipsoid is not None:
        radius = crs.ellipsoid.semi_major_metre
    result["declared_name"] = crs.name
    result["declared_proj4"] = crs.to_proj4()
    result["radius_m"] = radius

    if result["is_earth_crs"]:
        result["notes"].append("CRS appears to be Earth-based; rejected.")
        return result

    # Mars is a sphere: check bounding radius where available.
    if radius is not None:
        result["radius_ok"] = abs(radius - config.MARS_SPHERE_RADIUS_M) < 1.0
    else:
        # Sphere via +R in a proj4 string is compliant even when pyproj does not
        # expose an ellipsoid object.
        result["radius_ok"] = f"+R={int(config.MARS_SPHERE_RADIUS_M)}" in crs.to_proj4()

    if result["radius_ok"]:
        result["mars_crs_verified"] = True
    else:
        result["notes"].append(
            "CRS radius does not match the Mars 2000 sphere (3396190 m)."
        )
    return result


def describe(crs: CRS | None, label: str | None = None) -> dict:
    """Compact, JSON-serialisable description of a CRS.

    ``label`` supplies a human-readable name for CRS objects that PROJ cannot
    name (for example a CRS built from a bare PROJ string, which reports
    ``unknown``).
    """
    if crs is None:
        return {"name": None, "proj4": None, "is_earth": False}
    name = crs.name
    if label and (not name or name.strip().lower() == "unknown"):
        name = label
    return {
        "name": name,
        "proj4": crs.to_proj4(),
        "axis_info": [
            {"name": a.name, "unit": a.unit_name, "direction": a.direction}
            for a in crs.axis_info
        ],
        "is_earth": is_earth_crs(crs),
    }

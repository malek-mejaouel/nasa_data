# Mars Gale Crater — Curiosity GeoTIFF Extraction & Documentation Pipeline

Planet: **Mars** · IAU body identifier: **49900** · Reference body: **Mars 2000 sphere (R = 3396190 m)**.  
No Earth coordinate reference system is used anywhere in this project.

---

## 1. Dataset overview

- **Dataset name:** Mars MSL Gale Merged Orthophoto Mosaic 25cm
- **Dataset id:** `msl_gale_orthophoto_mosaic_25cm_v3`
- **Original filename:** `MSL_Gale_Orthophoto_Mosaic_25cm_v3.tif`
- **Format:** GTiff (uint8, 1 band)
- **Content:** panchromatic (grayscale) orthophoto mosaic of Gale Crater; pixel values are image DN (0–255), **not** elevation.
- **File size (HTTP Content-Length):** 50404480837 bytes (≈ 50.4 GB)

## 2. Original source URL and attribution

- **Source URL:** https://asc-pds-services.s3.us-west-2.amazonaws.com/mosaic/MSL_Gale_Orthophoto_Mosaic_25cm_v3.tif
- **Viewer URL (supplied by user):** https://trek.nasa.gov/mars/#v=0.1&x=137.50484875935194&y=-4.587047023176908&z=9&p=urn%3Aogc%3Adef%3Acrs%3AEPSG%3A%3A104905&d=&l=curiosity_hirise_mosaic%2Ctrue%2C1&l=Gale_CTX_BlockAdj_dd%2Ctrue%2C1&locale=&b=mars&e=137.05509596012425%2C-5.044352922849646%2C137.95460155857964%2C-4.129741123504169&sfz=&w=
- **Attribution / recommended citation:** Calef III, F. J., & Parker, T. (2016). MSL Gale Merged Orthophoto Mosaic. PDS Annex, U.S. Geological Survey.
- **Principle authors:** Fred J. Calef III and Timothy Parker
- **Publisher:** USGS Astrogeology Science Center (published 2016-10-20, version 3)

## 3. Planetary reference system

- **Planet / body identifier:** Mars / IAU 49900
- **Reference body:** Mars 2000 sphere (planetocentric)
- **Vertical / horizontal datum:** MOLA control net (per publisher record)
- **Latitude type:** planetocentric (planetocentric)
- **Longitude convention:** east-positive, range [-180, 180]
- **Native map projection (publisher):** Equirectangular

## 4. Original and output CRS

| Role | CRS | Definition |
|---|---|---|
| Original (as declared in the GeoTIFF) | PROJCS["Mars_Equirectangular_clon0",GEOGCS["GCS_Mars_2000_Sphere",DATUM["Mars_2000_(Sphere)",SPHEROID["Mars_2000_Sphere_IAU_IAG",3396190,0],AUTHORITY["ESRI","106971"]],PRIMEM["Reference_Meridian",0],UNIT["degree",0.0174532925199433,AUTHORITY["EPSG","9122"]]],PROJECTION["Equirectangular"],PARAMETER["standard_parallel_1",0],PARAMETER["central_meridian",0],PARAMETER["false_easting",0],PARAMETER["false_northing",0],UNIT["metre",1,AUTHORITY["EPSG","9001"]],AXIS["Easting",EAST],AXIS["Northing",NORTH]] | `+proj=eqc +lat_ts=0 +lat_0=0 +lon_0=0 +x_0=0 +y_0=0 +R=3396190 +units=m +no_defs +type=crs` |
| Storage / output (geographic) | Mars (2015) - Sphere / Ocentric | `+proj=longlat +R=3396190 +no_defs +type=crs` |
| Compute (metric, Gale-centred) | Mars Gale-centred Azimuthal Equidistant (lat_0=-5.4, lon_0=137.8, R=3396190 m) | `+proj=aeqd +lat_0=-5.4 +lon_0=137.8 +x_0=0 +y_0=0 +R=3396190 +units=m +no_defs +type=crs` |

Mars CRS validation: **PASSED** (`{"crs_present": true, "is_earth_crs": false, "radius_ok": true, "mars_crs_verified": true, "notes": [], "declared_name": "Mars_Equirectangular_clon0", "declared_proj4": "+proj=eqc +lat_ts=0 +lat_0=0 +lon_0=0 +x_0=0 +y_0=0 +R=3396190 +units=m +no_defs +type=crs", "radius_m": 3396190.0}`).
> The compute CRS is centred on Gale Crater (lat_0 = -5.4°, lon_0 = 137.8°) on the Mars 2000 sphere and uses metres for distance and area.

## 5. Raster dimensions and resolution

- **Width × height:** 180000 × 280000 pixels
- **Native resolution:** 0.25 m/pixel (metres/pixel (ground, on the Mars 2000 sphere))
- **Storage layout:** stripped (block shapes: [[1, 180000]])
- **Internal overviews / COG:** none
- **Compression:** none (uncompressed)

## 6. Geographic coverage

- **Geographic extent (lon/lat):** min_lon 137.095, min_lat -5.24952, max_lon 137.854, max_lat -4.06858
- **Native extent (metres):** left 8.12625e+06, bottom -311164, right 8.17125e+06, top -241164
- **Geotransform:** `[0.25, 0.0, 8126248.0, 0.0, -0.25, -241164.0]`

## 7. Extracted statistics

Computed from **full-resolution pixel windows extracted for the derived AOI sub-areas (NOT whole-raster; the source has no overviews)**.

| Metric | Value |
|---|---|
| minimum | 36 |
| maximum | 255 |
| mean | 158.307 |
| standard_deviation | 33.8035 |
| valid_pixel_count | 2097152 |
| nodata_pixel_count | 0 |
| total_pixel_count | 2097152 |
| NoData value | 0 |

> Distinction: values above are **calculated** from actual source pixels; they are not copied from the publisher record. Global whole-raster statistics were not computed because that would require transferring the full ~50 GB dataset over HTTP (no internal overviews exist).

## 8. Study area intersection results

| AOI | Authoritative | Intersects | Coverage | Fraction covered | Approx. native px |
|---|---|---|---|---|---|
| gale_regional | True | True | fully covered | 1 | 180000 × 280000 |
| boxwork | False | True | fully covered | 1 | 1024 × 1024 |
| hidden_valley | False | True | fully covered | 1 | 1024 × 1024 |

## 9. Processing operations

- HTTP Range inspection of the source GeoTIFF (no full download)
- Remote metadata extraction via GDAL /vsicurl/
- Analytic AOI / footprint intersection analysis (shapely)
- Full-resolution windowed extraction using full-width row bands (contiguous on the server) with local column slicing (GDAL partial reads; HTTP/2 multiplexing enabled)
- Reprojection to the Gale-centred metric compute CRS (bilinear)
- Reprojection to the geographic storage CRS (bilinear)
- Quick-look preview rendering

**Output files:**
- `data\processed\aoi_boxwork_compute_aeqd_25cm.tif`
- `data\processed\aoi_boxwork_geographic_25cm.tif`
- `outputs\aoi_boxwork_preview.png`
- `data\processed\aoi_hidden_valley_compute_aeqd_25cm.tif`
- `data\processed\aoi_hidden_valley_geographic_25cm.tif`
- `outputs\aoi_hidden_valley_preview.png`

## 10. Resampling decisions

- Primary resampling method: **bilinear (continuous panchromatic orthophoto; nearest-neighbour reserved for categorical rasters)**.
- Rationale: the mosaic is a **continuous** panchromatic orthophoto, so bilinear interpolation is used. Nearest-neighbour is reserved for categorical/classification rasters, which this dataset is not.
- NoData (0) is preserved through processing.

## 11. Data limitations and uncertainties

- The source is a **50.4 GB uncompressed, stripped TIFF** with a 1-row-per-strip layout and **no internal overviews**. Efficient decimated remote reading is therefore not possible; whole-raster processing or global statistics would require downloading the full file.
- Windowed reads over HTTP are slow: with 1 row per strip a box window would need one request per row. The pipeline therefore reads the AOI's rows as **full-width bands** (contiguous on the server, ~184 MB per 1024-row band) and slices the columns locally. Each AOI still takes a few minutes to fetch, which is why the derived AOI windows are kept small (1024 px ≈ 256 m).
- Horizontal accuracy is inherited from the MOLA control net (~100 m horizontal per the publisher record).
- Pixel values are image DN, not calibrated radiance/reflectance and not elevation; no terrain interpretation is valid from this product alone.
- The publisher lists the file as “23 GB” while the actual HTTP Content-Length is ~50.4 GB (uncompressed).

## 12. Assumptions

- The supplied URL is a browser viewer; the underlying original raster was identified as the USGS Astropedia MSL Gale Merged Orthophoto Mosaic (v3) GeoTIFF on AWS S3.
- aoi_gale_regional is the dataset footprint as declared by USGS (authoritative).
- aoi_boxwork and aoi_hidden_valley are DERIVED placeholder windows: 1024 x 1024 native pixels (256 m) located by centre fractions of the dataset extent. They are NOT authoritative feature outlines and must not be used as such.
- The compute CRS is an Azimuthal Equidistant projection centred on Gale Crater (5.4 S, 137.8 E) on the Mars 2000 sphere (R = 3396190 m).

## 13. Generated output files

| Kind | Path |
|---|---|
| Dataset JSON | `metadata/msl_gale_orthophoto_mosaic_25cm_v3.json` |
| URL inspection report | `metadata/url_inspection.json` |
| AOI geometries | `data/vector/aoi_gale_regional.geojson`, `data/vector/aoi_boxwork.geojson`, `data/vector/aoi_hidden_valley.geojson` |
| Processed raster / preview | `data\processed\aoi_boxwork_compute_aeqd_25cm.tif` |
| Processed raster / preview | `data\processed\aoi_boxwork_geographic_25cm.tif` |
| Processed raster / preview | `outputs\aoi_boxwork_preview.png` |
| Processed raster / preview | `data\processed\aoi_hidden_valley_compute_aeqd_25cm.tif` |
| Processed raster / preview | `data\processed\aoi_hidden_valley_geographic_25cm.tif` |
| Processed raster / preview | `outputs\aoi_hidden_valley_preview.png` |
| Manifest | `manifest.json` |

`data/raw/` is reserved for original source datasets and is intentionally empty here: the original GeoTIFF is accessed remotely and is never downloaded into the project. It is never modified.

## 14. Reproducibility instructions

Dependencies are installed into a project-local folder to avoid touching the read-only global environment:

```powershell
python -m pip install --target .\.pylibs rasterio pyproj geopandas shapely
$env:PYTHONPATH = "$PWD\.pylibs"
python -m src.pipeline
```

The pipeline performs only HTTP Range reads of the source GeoTIFF via GDAL `/vsicurl/`; the original file is never modified or fully downloaded. Re-running updates `manifest.json` in place (entries are keyed by `id`) and refreshes this README.

---

# Part B — Second dataset: locally supplied `ressources/` GeoTIFF

This dataset is a file provided directly in the project's `ressources/` folder. Because it is on local disk it can be read in full, which is the only way to obtain **exact whole-raster statistics** (the remote mosaic has no overviews and is never fully transferred). The file is opened read-only and is never modified.

## B.1 Dataset overview

- **Dataset name:** Mars Curiosity HiRISE Mosaic (Gale Crater)
- **Dataset id:** `curiosity_hirise_mosaic`
- **Local path:** `ressources/curiosity_hirise_mosaic.tif`
- **Format:** GTiff (uint8, 1 band)
- **Compression:** Compression.lzw
- **Layout:** tiled (block shapes: [[128, 128]]); internal overviews: none
- **File size (on disk):** 8605826726 bytes (≈ 8.61 GB)
- **Content:** panchromatic (grayscale) HiRISE mosaic of the Gale Crater area; pixel values are image DN (0–255), **not** elevation.

## B.2 Provenance and attribution

- **Attribution / recommended citation:** Mars Curiosity HiRISE Mosaic, USGS Astrogeology Science Center, NASA Mars Trek (trek.nasa.gov).
- **Principle authors:** USGS Astrogeology Science Center
- **Provenance note:** Locally supplied GeoTIFF; its footprint and CRS match the Mars Trek `curiosity_hirise_mosaic` WMTS layer (urn:ogc:def:crs:EPSG::104905). The exact upstream processing chain of this particular file is not documented inside the file itself.
- **Cross-check (viewer):** the file's footprint and CRS match the Mars Trek `curiosity_hirise_mosaic` WMTS layer referenced by the supplied viewer URL.

## B.3 Planetary reference system and CRS

| Role | CRS | Definition |
|---|---|---|
| Original (as declared in the GeoTIFF) | ESRI:104905 | `+proj=longlat +a=3396190 +rf=169.894447223612 +no_defs +type=crs` |
| Storage / output (geographic) | Mars (2015) - Sphere / Ocentric | `+proj=longlat +R=3396190 +no_defs +type=crs` |
| Compute (metric, Gale-centred) | Mars Gale-centred Azimuthal Equidistant (lat_0=-5.4, lon_0=137.8, R=3396190 m) | `+proj=aeqd +lat_0=-5.4 +lon_0=137.8 +x_0=0 +y_0=0 +R=3396190 +units=m +no_defs +type=crs` |

Mars CRS validation: **PASSED** (`{"crs_present": true, "is_earth_crs": false, "radius_ok": true, "mars_crs_verified": true, "notes": [], "declared_name": "GCS_Mars_2000", "declared_proj4": "+proj=longlat +a=3396190 +rf=169.894447223612 +no_defs +type=crs", "radius_m": 3396190.0}`).  
No Earth CRS is used; all CRS objects are built on the Mars 2000 sphere (R = 3396190 m).

## B.4 Dimensions and resolution

- **Width × height:** 144001 × 160401 pixels (23,097,904,401 total)
- **Ground resolution:** 0.25 m/pixel (on the Mars 2000 sphere)
- **Native resolution:** 4.21765e-06 degrees/pixel

## B.5 Geographic coverage

- **Geographic extent (lon/lat):** min_lon 137.122, min_lat -4.92547, max_lon 137.73, max_lat -4.24896
- **Geotransform:** `[4.217651214528874e-06, 0.0, 137.12246691438963, 0.0, -4.217651214528841e-06, -4.248958839494268]`
- This footprint is a subset of the regional orthophoto mosaic (Part A) and matches the Curiosity traverse area shown by Mars Trek.

## B.6 Exact whole-raster statistics

Scope: **whole raster (all pixels read in chunks)**. Computed from every pixel of the file, with NoData excluded (the file declares none).

| Metric | Value |
|---|---|
| minimum | 0 |
| maximum | 255 |
| mean | 144.253 |
| standard_deviation | 38.3846 |
| valid_pixel_count | 23097904401 |
| nodata_pixel_count | 0 |
| total_pixel_count | 23097904401 |
| percentile p02 | 22 |
| percentile p25 | 137 |
| percentile p50 | 156 |
| percentile p75 | 165 |
| percentile p98 | 196 |
| NoData value | not available |

> A full 256-bin histogram (offset 0, 256 populated bins) is stored in the dataset JSON for exact reproduction.

> These are **exact** global statistics, not a sampling of windows: the local file is read in row chunks and an exact 256-bin histogram is accumulated. This is the key piece of information that could not be obtained from the remote source.

## B.7 Study area intersection and extraction

| AOI | Authoritative | Intersects | Coverage | Approx. native px | Extracted |
|---|---|---|---|---|---|
| gale_regional | True | True | partially covered | 144001 × 160401 | False |
| boxwork | False | True | fully covered | 1024 × 1024 | True |
| hidden_valley | False | True | fully covered | 1024 × 1024 | True |

## B.8 Processing operations and output files

- Local metadata extraction (rasterio, read-only)
- Exact whole-raster statistics over every pixel (256-bin histogram)
- Analytic AOI / footprint intersection analysis (shapely)
- Full-resolution windowed extraction (direct local window read, tiled LZW)
- Reprojection to the Gale-centred metric compute CRS (bilinear)
- Reprojection to the geographic storage CRS (bilinear)
- Quick-look preview rendering

**Output files:**
- `data\processed\curiosity_aoi_boxwork_compute_aeqd_25cm.tif`
- `data\processed\curiosity_aoi_boxwork_geographic_25cm.tif`
- `outputs\curiosity_aoi_boxwork_preview.png`
- `data\processed\curiosity_aoi_hidden_valley_compute_aeqd_25cm.tif`
- `data\processed\curiosity_aoi_hidden_valley_geographic_25cm.tif`
- `outputs\curiosity_aoi_hidden_valley_preview.png`

## B.9 Limitations and assumptions

- Pixel values are 8-bit image DN (0-255), not elevation; terrain derivatives are not applicable.
- NoData is not declared by the file; every pixel is treated as valid.
- This local file covers only the Curiosity rover traverse footprint, a subset of the regional orthophoto mosaic.
- The file in ressources/ is the locally supplied GeoTIFF whose footprint, pixel size and CRS match the Mars Trek `curiosity_hirise_mosaic` WMTS layer (urn:ogc:def:crs:EPSG::104905).
- The upstream processing chain of this particular file is not documented inside the file itself; its provenance is inferred from the matching footprint, CRS and layer identifier.
- The project study areas (aoi_gale_regional, aoi_boxwork, aoi_hidden_valley) are shared with the remote mosaic dataset; aoi_boxwork and aoi_hidden_valley are DERIVED placeholder windows, not authoritative feature outlines.
- The compute CRS is an Azimuthal Equidistant projection centred on Gale Crater (5.4 S, 137.8 E) on the Mars 2000 sphere (R = 3396190 m).

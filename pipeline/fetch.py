"""
Download the inputs for Łódź onto the analysis grid (cached in pipeline/cache/, not committed).

    python pipeline/fetch.py

  boundary     OpenStreetMap relation 2413295 (city of Łódź), via Nominatim — © OpenStreetMap contributors, ODbL
  landsat      Landsat 8/9 Collection 2 Level-2 scenes, June–August 2018–2025, read from Microsoft
               Planetary Computer (no account needed); a scene is kept if ≥ 90% of the city is clear.
               Where the surface-temperature product is empty although the pixel is clear (the product
               has no emissivity there: a gap in the ASTER GED input), temperature is recomputed from the
               product's radiance layers with an emissivity estimated from NDVI on the same scene
               (`filled` marks these pixels).
  sentinel2    Sentinel-2 L2A, June–August 2023: median NDVI of clear pixels (cross-check)
  worldcover   ESA WorldCover 2021 v200 land cover
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

import numpy as np
import planetary_computer
import pyproj
import rasterio
import requests
import shapely.geometry as sg
import shapely.ops as so
from pystac_client import Client
from rasterio.enums import Resampling
from rasterio.features import rasterize
from rasterio.transform import from_origin
from rasterio.vrt import WarpedVRT

sys.path.insert(0, str(Path(__file__).parent))
import uhi  # noqa: E402

HERE = Path(__file__).parent
CACHE = HERE / "cache"
CACHE.mkdir(exist_ok=True)
os.environ.setdefault("GDAL_DISABLE_READDIR_ON_OPEN", "EMPTY_DIR")
os.environ.setdefault("GDAL_HTTP_MAX_RETRY", "4")
os.environ.setdefault("GDAL_HTTP_RETRY_DELAY", "2")

OSM_RELATION = 2413295
YEARS = range(2018, 2026)
MIN_CLEAR = 0.90
STAC = "https://planetarycomputer.microsoft.com/api/stac/v1"


def boundary() -> tuple[sg.Polygon, sg.Polygon]:
    """City polygon in WGS84 and in the analysis CRS."""
    path = CACHE / "boundary_osm.geojson"
    if not path.exists():
        r = requests.get(
            "https://nominatim.openstreetmap.org/lookup",
            params={"osm_ids": f"R{OSM_RELATION}", "format": "geojson", "polygon_geojson": 1},
            headers={"User-Agent": "uhi-research-pipeline/1.0"},
            timeout=60,
        )
        r.raise_for_status()
        path.write_text(r.text, encoding="utf-8")
    geo = sg.shape(json.loads(path.read_text(encoding="utf-8"))["features"][0]["geometry"])
    to_utm = pyproj.Transformer.from_crs(4326, uhi.CRS, always_xy=True).transform
    return geo, so.transform(to_utm, geo)


def grid_spec(city_utm) -> dict:
    """10 m analysis grid: the city's bounds plus 1.5 km, snapped to 3 km (a multiple of 10, 30, 250, 500 and 1000 m)."""
    minx, miny, maxx, maxy = city_utm.bounds
    s = 3000
    x0, y0 = np.floor((minx - 1500) / s) * s, np.floor((miny - 1500) / s) * s
    x1, y1 = np.ceil((maxx + 1500) / s) * s, np.ceil((maxy + 1500) / s) * s
    w, h = int((x1 - x0) / uhi.PIXEL), int((y1 - y0) / uhi.PIXEL)
    return {"x0": float(x0), "y1": float(y1), "width": w, "height": h, "transform": from_origin(x0, y1, uhi.PIXEL, uhi.PIXEL)}


def read_onto(href: str, spec: dict, factor: int, resampling=Resampling.nearest, dtype=None) -> np.ndarray:
    """Read a (remote) raster onto the analysis grid at `factor` × 10 m, then repeat to 10 m."""
    w, h = spec["width"] // factor, spec["height"] // factor
    t = from_origin(spec["x0"], spec["y1"], uhi.PIXEL * factor, uhi.PIXEL * factor)
    with rasterio.open(href) as src, WarpedVRT(src, crs=uhi.CRS, transform=t, width=w, height=h, resampling=resampling) as vrt:
        a = vrt.read(1)
    if dtype:
        a = a.astype(dtype)
    return np.repeat(np.repeat(a, factor, axis=0), factor, axis=1) if factor > 1 else a


def city_mask(city_utm, spec) -> np.ndarray:
    return rasterize([(city_utm, 1)], out_shape=(spec["height"], spec["width"]), transform=spec["transform"], fill=0, dtype="uint8").astype(bool)


def fetch_landsat(spec, inside, bbox) -> list[dict]:
    cat = Client.open(STAC, modifier=planetary_computer.sign_inplace)
    items = []
    for y in YEARS:
        items += list(cat.search(collections=["landsat-c2-l2"], bbox=bbox, datetime=f"{y}-06-01/{y}-08-31",
                                 query={"eo:cloud_cover": {"lt": 40}, "platform": {"in": ["landsat-8", "landsat-9"]}}).items())
    items.sort(key=lambda it: it.datetime)
    kept = []
    for it in items:
        date = it.datetime.strftime("%Y-%m-%d")
        base = f"{date}_{it.properties['platform']}_{it.properties['landsat:wrs_path']}.npz"
        out = CACHE / f"landsat_v2_{base}"
        old = CACHE / f"landsat_{base}"
        if not out.exists() and old.exists() and bool(np.load(old)["skipped"]):
            out = old  # already known to be too cloudy
        if not out.exists():
            qa = read_onto(it.assets["qa_pixel"].href, spec, 3)
            clear = uhi.landsat_clear(qa)
            frac = float(clear[inside].mean())
            if frac < MIN_CLEAR:
                print(f"  {date} {it.properties['platform']} path {it.properties['landsat:wrs_path']}: {frac:.0%} of the city clear — skipped")
                np.savez_compressed(out, skipped=True, clear_frac=frac)
                continue
            st = read_onto(it.assets["lwir11"].href, spec, 3)
            red = read_onto(it.assets["red"].href, spec, 3)
            nir = read_onto(it.assets["nir08"].href, spec, 3)
            lst = uhi.landsat_lst_celsius(st)
            nd = uhi.ndvi(uhi.landsat_reflectance(red), uhi.landsat_reflectance(nir))
            lst, filled, fill_rmse = fill_st_gap(it, spec, inside, clear, st, lst, nd)
            ok = clear & np.isfinite(lst) & np.isfinite(nd)
            np.savez_compressed(out, skipped=False, clear_frac=frac, lst=np.where(ok, lst, np.nan).astype("float32"),
                                ndvi=np.where(ok, nd, np.nan).astype("float32"), filled=filled & ok, fill_rmse=fill_rmse,
                                time=it.datetime.isoformat(), platform=it.properties["platform"], scene=it.id)
            print(f"  {date} {it.properties['platform']} path {it.properties['landsat:wrs_path']}: {frac:.0%} clear — kept")
        z = np.load(out)
        if not bool(z["skipped"]):
            kept.append({"date": date, "file": out.name, "clear": float(z["clear_frac"]), "scene": str(z["scene"]),
                         "filled_share": float(z["filled"][inside].mean()), "fill_rmse_k": float(z["fill_rmse"])})
    return kept


def thermal_constants(item) -> tuple[float, float]:
    text = requests.get(item.assets["mtl.txt"].href, timeout=120).text
    k1 = float(re.search(r"K1_CONSTANT_BAND_10 = ([\d.]+)", text).group(1))
    k2 = float(re.search(r"K2_CONSTANT_BAND_10 = ([\d.]+)", text).group(1))
    return k1, k2


def fill_st_gap(item, spec, inside, clear, st, lst, nd):
    """Recompute temperature where the ST product is empty but the pixel is clear (no emissivity there)."""
    gap = clear & (st == 0) & np.isfinite(nd)
    if not gap.any():
        return lst, gap, float("nan")
    k1, k2 = thermal_constants(item)
    raw = {k: read_onto(item.assets[k].href, spec, 3).astype("float64") for k in ("trad", "urad", "drad", "atran", "emis")}
    for k in raw:
        raw[k][raw[k] <= -9999] = np.nan
    trad, urad, drad = raw["trad"] * 1e-3, raw["urad"] * 1e-3, raw["drad"] * 1e-3
    atran, emis = raw["atran"] * 1e-4, raw["emis"] * 1e-4
    ref = inside & clear & (st != 0) & np.isfinite(emis) & np.isfinite(nd)
    e_hat = uhi.emissivity_from_ndvi(nd[ref], emis[ref], nd)
    rec = uhi.surface_temperature_from_radiance(trad, urad, drad, atran, e_hat, k1, k2)
    diff = rec[ref] - lst[ref]
    bias = float(np.nanmean(diff))  # align with the official product on this scene
    rmse = float(np.sqrt(np.nanmean((diff - bias) ** 2)))
    out = lst.copy()
    out[gap] = rec[gap] - bias
    return out, gap & np.isfinite(out), rmse


def fetch_sentinel2(spec, inside, bbox) -> None:
    out = CACHE / "sentinel2_2023_ndvi.npz"
    if out.exists():
        return
    cat = Client.open(STAC, modifier=planetary_computer.sign_inplace)
    items = list(cat.search(collections=["sentinel-2-l2a"], bbox=bbox, datetime="2023-06-01/2023-08-31", query={"eo:cloud_cover": {"lt": 10}}).items())
    stack, dates = [], set()
    for it in items:
        scl = read_onto(it.assets["SCL"].href, spec, 2)
        good = np.isin(scl, [4, 5, 6, 7])  # vegetation, bare, water, unclassified (no cloud, shadow, snow)
        red = read_onto(it.assets["B04"].href, spec, 1, dtype="float64")
        nir = read_onto(it.assets["B08"].href, spec, 1, dtype="float64")
        # processing baseline ≥ 04.00 adds 1000 to reflectance digital numbers
        off = 1000.0 if float(it.properties.get("s2:processing_baseline", "0")) >= 4.0 else 0.0
        v = uhi.ndvi((red - off) / 1e4, (nir - off) / 1e4)
        v[~good | (red == 0)] = np.nan
        stack.append(v.astype("float32"))
        dates.add(it.datetime.strftime("%Y-%m-%d"))
        print(f"  Sentinel-2 {it.id}: {np.isfinite(v[inside]).mean():.0%} of the city usable")
    with np.errstate(all="ignore"):
        med = np.nanmedian(np.stack(stack), axis=0).astype("float32")
    np.savez_compressed(out, ndvi=med, dates=np.array(sorted(dates)))


def fetch_worldcover(spec, bbox) -> None:
    out = CACHE / "worldcover_2021.npz"
    if out.exists():
        return
    cat = Client.open(STAC, modifier=planetary_computer.sign_inplace)
    items = list(cat.search(collections=["esa-worldcover"], bbox=bbox, query={"esa_worldcover:product_version": {"eq": "2.0.0"}}).items())
    lc = np.zeros((spec["height"], spec["width"]), dtype="uint8")
    for it in items:
        a = read_onto(it.assets["map"].href, spec, 1)
        lc = np.where(lc == 0, a, lc)
    np.savez_compressed(out, lc=lc)
    print("  WorldCover tiles:", [it.id for it in items])


def main():
    city_wgs, city_utm = boundary()
    spec = grid_spec(city_utm)
    inside = city_mask(city_utm, spec)
    bbox = list(city_wgs.bounds)
    print(f"grid {spec['width']}×{spec['height']} at 10 m, city {city_utm.area / 1e6:.1f} km²")
    print("Landsat:")
    kept = fetch_landsat(spec, inside, bbox)
    print("Sentinel-2:")
    fetch_sentinel2(spec, inside, bbox)
    print("WorldCover:")
    fetch_worldcover(spec, bbox)
    meta = {"grid": {k: spec[k] for k in ("x0", "y1", "width", "height")}, "crs": uhi.CRS, "landsat": kept, "osm_relation": OSM_RELATION}
    (CACHE / "manifest.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
    print(f"{len(kept)} Landsat scenes kept")


if __name__ == "__main__":
    main()

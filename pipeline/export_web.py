"""
Write the web app's data from the analysis (after analyze.py).

    python pipeline/export_web.py  ->  data/cells_500m.geojson, data/cells_500m.csv, data/boundary.geojson,
                                       data/summary.json, data/rasters/*.png (EPSG:3857 overlays:
                                       anom_<day|mean>, ndvi_<day|mean>, built)
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import numpy as np
import pyproj
import shapely.geometry as sg
import shapely.ops as so
from rasterio.transform import from_origin
from rasterio.warp import Resampling, calculate_default_transform, reproject

sys.path.insert(0, str(Path(__file__).parent))
import uhi  # noqa: E402
from analyze import MAIN, OUT, load_inputs  # noqa: E402
from fetch import boundary  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
RAST = DATA / "rasters"
RAST.mkdir(parents=True, exist_ok=True)

# colour ramps shared with js/scales.js
ANOM_STOPS = [(-6, (33, 102, 172)), (-3, (103, 169, 207)), (0, (230, 230, 226)), (3, (239, 138, 98)), (6, (178, 24, 43))]
NDVI_STOPS = [(0.0, (247, 245, 235)), (0.2, (217, 230, 178)), (0.4, (145, 196, 122)), (0.6, (49, 140, 74)), (0.8, (0, 79, 40))]
BUILT_STOPS = [(0.0, (241, 242, 246)), (0.25, (196, 199, 214)), (0.5, (140, 145, 172)), (0.75, (88, 92, 128)), (1.0, (42, 45, 77))]


def ramp(values: np.ndarray, stops) -> np.ndarray:
    xs = np.array([s[0] for s in stops], dtype=float)
    out = np.zeros(values.shape + (4,), dtype="uint8")
    v = np.clip(values, xs[0], xs[-1])
    for ch in range(3):
        out[..., ch] = np.interp(v, xs, [s[1][ch] for s in stops]).astype("uint8")
    out[..., 3] = np.where(np.isfinite(values), 255, 0)
    return out


MERC_STRETCH = 1 / np.cos(np.radians(51.77))


def to_mercator_png(arr: np.ndarray, spec: dict, name: str, stops, res_m: float = 30.0) -> list:
    """Reproject a 10 m analysis-grid array to Web Mercator and save a coloured PNG; return Leaflet bounds."""
    from PIL import Image

    src_t = spec["transform"]
    h, w = arr.shape
    left, top = spec["x0"], spec["y1"]
    right, bottom = left + w * uhi.PIXEL, top - h * uhi.PIXEL
    dst_t, dw, dh = calculate_default_transform(uhi.CRS, "EPSG:3857", w, h, left, bottom, right, top, resolution=res_m * MERC_STRETCH)
    dst = np.full((dh, dw), np.nan, dtype="float32")
    reproject(arr.astype("float32"), dst, src_transform=src_t, src_crs=uhi.CRS, dst_transform=dst_t, dst_crs="EPSG:3857",
              resampling=Resampling.average, src_nodata=np.nan, dst_nodata=np.nan)
    # 64-level palette PNG (index 0 transparent): same look, a fraction of the size
    lo, hi = stops[0][0], stops[-1][0]
    levels = 63
    q = np.where(np.isfinite(dst), 1 + np.round((np.clip(dst, lo, hi) - lo) / (hi - lo) * (levels - 1)), 0).astype("uint8")
    centres = lo + (np.arange(levels) / (levels - 1)) * (hi - lo)
    pal = ramp(centres, stops)[:, :3]
    img = Image.fromarray(q, "P")
    img.putpalette([0, 0, 0] + pal.ravel().tolist() + [0, 0, 0] * (256 - levels - 1))
    img.save(RAST / f"{name}.png", optimize=True, transparency=0)
    to_wgs = pyproj.Transformer.from_crs(3857, 4326, always_xy=True).transform
    x0, y0 = dst_t.c, dst_t.f
    x1, y1 = x0 + dw * dst_t.a, y0 + dh * dst_t.e
    (lon0, lat0), (lon1, lat1) = to_wgs(x0, y1), to_wgs(x1, y0)
    return [[round(lat0, 6), round(lon0, 6)], [round(lat1, 6), round(lon1, 6)]]


def r(v, d=2):
    return None if v is None or not np.isfinite(v) else round(float(v), d)


def main():
    spec, inside, lc, scenes, s2 = load_inputs()
    dates = [s["date"] for s in scenes]
    res = json.loads((OUT / "results.json").read_text(encoding="utf-8"))
    t = dict(np.load(OUT / f"cells_{MAIN}m.npz"))
    m = dict(np.load(OUT / "main_500m.npz"))
    sel = m["sel"]
    city_wgs, city_utm = boundary()
    to_wgs = pyproj.Transformer.from_crs(uhi.CRS, 4326, always_xy=True).transform

    # boundary (OpenStreetMap, ODbL)
    (DATA / "boundary.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": [{
        "type": "Feature", "properties": {"name": "Łódź", "source": "© OpenStreetMap contributors (ODbL), relation 2413295"},
        "geometry": sg.mapping(city_wgs.simplify(0.00005))}]}), encoding="utf-8")

    # per-cell values for selected cells (fitted, residual, Gi*) — arrays in main_500m.npz are over `sel` only
    idx_sel = np.nonzero(sel)[0]
    pos = {int(c): i for i, c in enumerate(idx_sel)}
    nd_med = float(np.median(m["ndvi"][sel]))
    feats, rows = [], []
    half = MAIN / 2
    for c in range(len(t["x"])):
        x, y = float(t["x"][c]), float(t["y"][c])
        sq = sg.box(x - half, y - half, x + half, y + half).intersection(city_utm)
        if sq.is_empty:
            continue
        geom = so.transform(to_wgs, sq)
        lon, lat = to_wgs(x, y)
        i = pos.get(c)
        hot = cold = prio = False
        fitted = resid = gz = None
        if i is not None:
            gz = float(m["gi_z"][i])
            sig = bool(m["gi_sig"][i])
            hot, cold = sig and gz > 0, sig and gz < 0
            prio = float(m["resid"][i]) > 1.0  # more than 1 °C hotter than vegetation and built-up share predict
            fitted, resid = float(m["fitted"][i]), float(m["resid"][i])
        n_valid = int(np.isfinite(t["anom"][:, c]).sum())
        props = {
            "id": c + 1,
            "lst": r(m["lst"][c], 1) if i is not None else None,
            "anom": r(m["anom"][c], 2) if i is not None else None,
            "ndvi": r(m["ndvi"][c], 3) if i is not None else None,
            "built": r(t["built"][c], 3),
            "tree": r(t["tree"][c], 3),
            "water": r(t["water"][c], 3),
            "fit": r(fitted, 2),
            "res": r(resid, 2),
            "gi": r(gz, 2),
            "spot": "hot" if hot else "cold" if cold else None,
            "prio": bool(prio),
            "inside": r(t["inside"][c], 2),
            "n": n_valid,
            "a": [r(v, 1) for v in t["anom"][:, c]],
            "v": [r(v, 2) for v in t["ndvi"][:, c]],
        }
        feats.append({"type": "Feature", "properties": props,
                      "geometry": json.loads(json.dumps(sg.mapping(geom), default=float), parse_float=lambda s: round(float(s), 5))})
        rows.append([c + 1, round(x), round(y), round(lat, 5), round(lon, 5), props["inside"], props["n"], props["lst"], props["anom"], props["ndvi"],
                     props["built"], props["tree"], props["water"], r(t["dist_km"][c], 2), props["fit"], props["res"], props["gi"],
                     props["spot"] or "", int(props["prio"])])
    (DATA / "cells_500m.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": feats}, separators=(",", ":")), encoding="utf-8")
    with open(DATA / "cells_500m.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["cell_id", "x_utm34n", "y_utm34n", "lat", "lon", "share_inside_city", "clear_dates", "lst_summer_mean_c",
                    "lst_anomaly_c", "ndvi_summer_mean", "built_share", "tree_share", "water_share", "distance_to_centre_km",
                    "predicted_anomaly_c", "residual_c", "gi_star_z", "hotspot", "hotter_than_expected_by_1c"])
        w.writerows(rows)

    # pixel layers (30 m Landsat): the same quantities the grid averages — LST anomaly against the median of the
    # cells that day, and NDVI from the same scene — for each day and their mean; built-up land at 10 m
    water = lc == uhi.WC_WATER
    land = inside & ~water
    rasters = {"anom": {}, "ndvi": {}}
    a_stack, v_stack = [], []
    for i, s in enumerate(scenes):
        a = np.where(land, s["lst"] - np.nanmedian(t["lst"][i]), np.nan)
        v = np.where(land, s["ndvi"], np.nan)
        a_stack.append(a)
        v_stack.append(v)
        rasters["anom"][s["date"]] = to_mercator_png(a, spec, f"anom_{s['date']}", ANOM_STOPS, 30)
        rasters["ndvi"][s["date"]] = to_mercator_png(v, spec, f"ndvi_{s['date']}", NDVI_STOPS, 30)
    with np.errstate(all="ignore"):
        for key, stack, stops in (("anom", a_stack, ANOM_STOPS), ("ndvi", v_stack, NDVI_STOPS)):
            arr = np.stack(stack)
            cnt = np.isfinite(arr).sum(0)
            mean = np.where(cnt >= 0.5 * len(stack), np.nanmean(arr, 0), np.nan)
            rasters[key]["mean"] = to_mercator_png(mean, spec, f"{key}_mean", stops, 30)
    built_px = np.where(inside & (lc == uhi.WC_BUILT), 1.0, np.nan)
    rasters["built"] = to_mercator_png(built_px, spec, "built", BUILT_STOPS, 10)

    mm = res["main"]
    summary = {
        "dates": dates,
        "per_date": res["per_date"],
        "cells": mm["cells"],
        "models": {k: {kk: v[kk] for kk in ("r2", "r2_adj", "r2_blocked_cv", "coef", "resid_morans_i")} for k, v in mm["models"].items()},
        "morans_i": mm["lst_morans_i"]["I"],
        "hotspots": mm["hotspots"],
        "ndvi_median": nd_med,
        "rasters": rasters,
        "scale": res["scale"],
    }
    (DATA / "summary.json").write_text(json.dumps(summary, default=float), encoding="utf-8")
    print(f"{len(feats)} cells exported; {len(list(RAST.glob('*.png')))} pixel layers")


if __name__ == "__main__":
    main()

"""
Grid statistics and the simulation-free analysis for Łódź.

    python pipeline/analyze.py      (after fetch.py)  ->  analysis/results.{json,md}, analysis/cells_*.npz

Cells are squares of 250, 500 or 1000 m on the UTM 34N grid; a cell is kept when at least half of
it lies inside the city. Water pixels (WorldCover) are left out of the temperature and NDVI means.
For each clear summer scene a cell is valid when ≥ 70% of its land pixels are clear. Temperatures
are compared as anomalies: the cell's LST minus the city median of the same scene, which removes
the difference in weather between dates.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pyproj

sys.path.insert(0, str(Path(__file__).parent))
import uhi  # noqa: E402
from fetch import CACHE, boundary, city_mask, grid_spec  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "analysis"
OUT.mkdir(exist_ok=True)

CELL_SIZES = [250, 500, 1000]
MAIN = 500
MIN_INSIDE = 0.5
MIN_CLEAR = 0.7
MIN_DATES_SHARE = 0.75
BLOCK_M = 2000  # spatial blocks for cross-validation and bootstrap
CENTRE_WGS = (19.4560, 51.7769)  # Plac Wolności, city centre


def load_inputs():
    city_wgs, city_utm = boundary()
    spec = grid_spec(city_utm)
    inside = city_mask(city_utm, spec)
    manifest = json.loads((CACHE / "manifest.json").read_text(encoding="utf-8"))
    lc = np.load(CACHE / "worldcover_2021.npz")["lc"]
    scenes = []
    for s in manifest["landsat"]:
        z = np.load(CACHE / s["file"])
        scenes.append({"date": s["date"], "scene": s["scene"], "lst": z["lst"], "ndvi": z["ndvi"], "filled": z["filled"],
                       "filled_share": s.get("filled_share", 0.0), "fill_rmse_k": s.get("fill_rmse_k")})
    # one scene per date (Landsat 8 and 9 can both pass on the same day)
    by_date = {}
    for s in scenes:
        by_date.setdefault(s["date"], s)
    s2 = np.load(CACHE / "sentinel2_2023_ndvi.npz")["ndvi"]
    return spec, inside, lc, [by_date[d] for d in sorted(by_date)], s2


def cell_table(spec, inside, lc, scenes, s2, size):
    ids, nr, nc = uhi.cell_index((spec["height"], spec["width"]), size)
    n = nr * nc
    k = int(size / uhi.PIXEL)
    inside_frac = np.bincount(ids.ravel(), weights=inside.ravel().astype(float), minlength=n) / (k * k)
    keep = inside_frac >= MIN_INSIDE
    water = lc == uhi.WC_WATER
    land = inside & ~water
    t = {
        "row": (np.arange(n) // nc)[keep],
        "col": (np.arange(n) % nc)[keep],
        "inside": inside_frac[keep],
        "built": uhi.zonal_fraction(lc == uhi.WC_BUILT, ids, n, inside)[keep],
        "tree": uhi.zonal_fraction(lc == uhi.WC_TREE, ids, n, inside)[keep],
        "water": uhi.zonal_fraction(water, ids, n, inside)[keep],
        "s2_ndvi": uhi.zonal_mean(s2, ids, n, land)[0][keep],
    }
    land_px = np.bincount(ids[land], minlength=n).astype(float)[keep]
    x0, y1 = spec["x0"], spec["y1"]
    t["x"] = x0 + (t["col"] + 0.5) * size
    t["y"] = y1 - (t["row"] + 0.5) * size
    cx, cy = pyproj.Transformer.from_crs(4326, uhi.CRS, always_xy=True).transform(*CENTRE_WGS)
    t["dist_km"] = np.hypot(t["x"] - cx, t["y"] - cy) / 1000
    lst, nd, anom, filled = [], [], [], []
    for s in scenes:
        filled.append(uhi.zonal_fraction(s["filled"], ids, n, land)[keep])
        m, cnt = uhi.zonal_mean(s["lst"], ids, n, land)
        v, _ = uhi.zonal_mean(s["ndvi"], ids, n, land)
        m, v, cnt = m[keep], v[keep], cnt[keep]
        ok = (land_px > 0) & (cnt / np.maximum(land_px, 1) >= MIN_CLEAR) & (t["water"] < 0.5)
        m = np.where(ok, m, np.nan)
        v = np.where(ok, v, np.nan)
        lst.append(m)
        nd.append(v)
        anom.append(m - np.nanmedian(m))
    t["lst"], t["ndvi"], t["anom"] = np.array(lst), np.array(nd), np.array(anom)  # dates × cells
    t["filled"] = np.nanmax(np.array(filled), axis=0)  # largest share of gap-filled pixels on any date
    t["block"] = (t["x"] // BLOCK_M).astype(int) * 1000 + (t["y"] // BLOCK_M).astype(int)
    return t


def summer_means(t, n_dates):
    valid = np.isfinite(t["anom"])
    enough = valid.sum(axis=0) >= MIN_DATES_SHARE * n_dates
    with np.errstate(all="ignore"):
        return enough, np.nanmean(t["anom"], axis=0), np.nanmean(t["ndvi"], axis=0), np.nanmean(t["lst"], axis=0)


def fit_models(X_by_name, y, blocks, nbrs):
    out = {}
    for name, X in X_by_name.items():
        m = uhi.ols(X, y)
        out[name] = {
            "r2": m["r2"],
            "r2_adj": m["r2_adj"],
            "r2_blocked_cv": uhi.blocked_cv_r2(X, y, blocks),
            "coef": m["beta"].tolist(),
            "resid_morans_i": uhi.morans_i(m["resid"], nbrs, 499)["I"],
        }
    return out


def main():
    spec, inside, lc, scenes, s2 = load_inputs()
    dates = [s["date"] for s in scenes]
    print(f"{len(dates)} clear summer dates: {', '.join(dates)}")
    res = {"dates": dates, "scenes": [s["scene"] for s in scenes],
           "gap_fill": {"city_share": float(np.mean([s["filled_share"] for s in scenes])),
                        "rmse_k": [s["fill_rmse_k"] for s in scenes]},
           "settings": {
        "cell_sizes": CELL_SIZES, "main_cell": MAIN, "min_inside": MIN_INSIDE, "min_clear": MIN_CLEAR,
        "min_dates_share": MIN_DATES_SHARE, "block_m": BLOCK_M}}

    tables = {size: cell_table(spec, inside, lc, scenes, s2, size) for size in CELL_SIZES}
    for size, t in tables.items():
        np.savez_compressed(OUT / f"cells_{size}m.npz", dates=np.array(dates), **t)

    # ---------- main analysis: 500 m, mean summer anomaly ----------
    t = tables[MAIN]
    enough, anom, nd, lst = summer_means(t, len(dates))
    sel = enough & np.isfinite(anom) & np.isfinite(nd) & np.isfinite(t["built"])
    y = anom[sel]
    nbrs = uhi.rook_neighbours(t["row"][sel], t["col"][sel])
    qn = uhi.rook_neighbours(t["row"][sel], t["col"][sel], queen=True)
    blocks = t["block"][sel]
    X = {
        "ndvi": nd[sel][:, None],
        "built": t["built"][sel][:, None],
        "ndvi_built": np.column_stack([nd[sel], t["built"][sel]]),
        "full": np.column_stack([nd[sel], t["built"][sel], t["water"][sel], t["dist_km"][sel]]),
    }
    main = {
        "cells": int(sel.sum()),
        "cells_total": int(len(sel)),
        "lst_morans_i": uhi.morans_i(y, nbrs, 999),
        "corr_ndvi_built": float(np.corrcoef(nd[sel], t["built"][sel])[0, 1]),
        "anom_range": [float(np.percentile(y, 5)), float(np.percentile(y, 95))],
        "models": fit_models(X, y, blocks, nbrs),
        "slope_ndvi_ci": uhi.block_bootstrap_ci(X["ndvi"], y, blocks),
        "slope_ndvi_in_both_ci": uhi.block_bootstrap_ci(X["ndvi_built"], y, blocks, coef=1),
        "slope_built_in_both_ci": uhi.block_bootstrap_ci(X["ndvi_built"], y, blocks, coef=2),
    }
    # local hot and cold spots of the summer anomaly; "hotter than expected" from vegetation and built-up share
    from scipy.stats import norm
    gz = uhi.getis_ord_gi_star(y, qn)
    p = 2 * norm.sf(np.abs(gz))
    sig = uhi.fdr_mask(p, 0.05)
    both = uhi.ols(X["ndvi_built"], y)
    hot = sig & (gz > 0)
    cold = sig & (gz < 0)
    greening = hot & (nd[sel] < np.median(nd[sel]))
    main["hotspots"] = {"hot": int(hot.sum()), "cold": int(cold.sum()), "hot_low_ndvi": int(greening.sum()),
                        "hotter_than_expected_1c": int((both["resid"] > 1).sum()), "cooler_than_expected_1c": int((both["resid"] < -1).sum()),
                        "hot_and_hotter_than_expected_1c": int((hot & (both["resid"] > 1)).sum())}
    res["main"] = main
    np.savez_compressed(OUT / "main_500m.npz", sel=sel, anom=anom, ndvi=nd, lst=lst, gi_z=gz, gi_sig=sig,
                        resid=both["resid"], fitted=both["fitted"], beta=both["beta"])

    # ---------- per date (500 m) ----------
    per = []
    for i, d in enumerate(dates):
        ok = np.isfinite(t["anom"][i]) & np.isfinite(t["ndvi"][i]) & np.isfinite(t["built"])
        yy, xx = t["anom"][i][ok], t["ndvi"][i][ok]
        a = uhi.ols(xx[:, None], yy)
        b = uhi.ols(np.column_stack([xx, t["built"][ok]]), yy)
        per.append({"date": d, "cells": int(ok.sum()), "city_median_lst": float(np.nanmedian(t["lst"][i])),
                    "slope_ndvi": float(a["beta"][1]), "r2_ndvi": a["r2"], "r2_ndvi_built": b["r2"],
                    "spread_p95_p5": float(np.percentile(yy, 95) - np.percentile(yy, 5))})
    res["per_date"] = per

    # ---------- cell size ----------
    scale = {}
    for size, tt in tables.items():
        en, an, ndv, _ = summer_means(tt, len(dates))
        s_ = en & np.isfinite(an) & np.isfinite(ndv)
        nb = uhi.rook_neighbours(tt["row"][s_], tt["col"][s_])
        scale[str(size)] = {
            "cells": int(s_.sum()),
            "r2_ndvi": uhi.ols(ndv[s_][:, None], an[s_])["r2"],
            "r2_ndvi_built": uhi.ols(np.column_stack([ndv[s_], tt["built"][s_]]), an[s_])["r2"],
            "r2_built": uhi.ols(tt["built"][s_][:, None], an[s_])["r2"],
            "lst_morans_i": uhi.morans_i(an[s_], nb, 199)["I"],
        }
    res["scale"] = scale

    # ---------- interior cells only, and a single-date / Sentinel-2 cross-check ----------
    no_fill = sel & (t["filled"] == 0)
    res["without_gap_filled_cells"] = {"cells": int(no_fill.sum()),
                                       "r2_ndvi": uhi.ols(nd[no_fill][:, None], anom[no_fill])["r2"],
                                       "r2_ndvi_built": uhi.ols(np.column_stack([nd[no_fill], t["built"][no_fill]]), anom[no_fill])["r2"]}
    interior = sel & (t["inside"] >= 0.999)
    res["interior"] = {"cells": int(interior.sum()),
                       "r2_ndvi": uhi.ols(nd[interior][:, None], anom[interior])["r2"],
                       "r2_ndvi_built": uhi.ols(np.column_stack([nd[interior], t["built"][interior]]), anom[interior])["r2"]}
    d23 = [i for i, d in enumerate(dates) if d.startswith("2023")]
    if d23:
        i = d23[0]
        ok = np.isfinite(t["anom"][i]) & np.isfinite(t["s2_ndvi"]) & np.isfinite(t["ndvi"][i])
        res["sentinel2_check"] = {
            "date": dates[i], "cells": int(ok.sum()),
            "corr_landsat_s2_ndvi": float(np.corrcoef(t["ndvi"][i][ok], t["s2_ndvi"][ok])[0, 1]),
            "r2_landsat_ndvi": uhi.ols(t["ndvi"][i][ok][:, None], t["anom"][i][ok])["r2"],
            "r2_s2_ndvi": uhi.ols(t["s2_ndvi"][ok][:, None], t["anom"][i][ok])["r2"],
            "slope_s2_ndvi": float(uhi.ols(t["s2_ndvi"][ok][:, None], t["anom"][i][ok])["beta"][1]),
        }

    (OUT / "results.json").write_text(json.dumps(res, indent=1, default=float), encoding="utf-8")
    write_markdown(res)
    print((OUT / "results.md").read_text(encoding="utf-8"))


def write_markdown(r):
    m = r["main"]
    L = [f"# Results\n\n{len(r['dates'])} clear summer Landsat scenes ({r['dates'][0]} … {r['dates'][-1]}); {m['cells']} of {m['cells_total']} 500 m cells.\n",
         f"Moran's I of the mean summer LST anomaly: {m['lst_morans_i']['I']:.2f} (p = {m['lst_morans_i']['p']:.3f}). "
         f"Correlation NDVI–built-up share: {m['corr_ndvi_built']:.2f}. Anomaly 5th–95th percentile: {m['anom_range'][0]:.1f} to {m['anom_range'][1]:.1f} °C.\n",
         "| Model | R² | adj. R² | blocked-CV R² | Moran's I of residuals | coefficients |", "|---|---:|---:|---:|---:|---|"]
    for k, v in m["models"].items():
        L.append(f"| {k} | {v['r2']:.3f} | {v['r2_adj']:.3f} | {v['r2_blocked_cv']:.3f} | {v['resid_morans_i']:.2f} | {', '.join(f'{c:.2f}' for c in v['coef'])} |")
    L.append(f"\nNDVI slope alone: 95% block-bootstrap CI {m['slope_ndvi_ci'][0]:.1f} to {m['slope_ndvi_ci'][1]:.1f} °C per NDVI unit; "
             f"with built-up share: NDVI {m['slope_ndvi_in_both_ci'][0]:.1f} to {m['slope_ndvi_in_both_ci'][1]:.1f}, built-up {m['slope_built_in_both_ci'][0]:.1f} to {m['slope_built_in_both_ci'][1]:.1f}.\n")
    L.append(f"Hot spots {m['hotspots']['hot']}, cold spots {m['hotspots']['cold']}, hot spots with below-median NDVI {m['hotspots']['hot_low_ndvi']}; "
             f"> 1 °C hotter than expected {m['hotspots']['hotter_than_expected_1c']}, > 1 °C cooler {m['hotspots']['cooler_than_expected_1c']}.\n")
    L += ["## Per date (500 m)\n", "| Date | cells | city median LST | NDVI slope | R² NDVI | R² NDVI + built | P95–P5 spread |", "|---|---:|---:|---:|---:|---:|---:|"]
    for p in r["per_date"]:
        L.append(f"| {p['date']} | {p['cells']} | {p['city_median_lst']:.1f} | {p['slope_ndvi']:.1f} | {p['r2_ndvi']:.3f} | {p['r2_ndvi_built']:.3f} | {p['spread_p95_p5']:.1f} |")
    L += ["\n## Cell size\n", "| Cell | cells | R² NDVI | R² built | R² NDVI + built | Moran's I |", "|---|---:|---:|---:|---:|---:|"]
    for k, v in r["scale"].items():
        L.append(f"| {k} m | {v['cells']} | {v['r2_ndvi']:.3f} | {v['r2_built']:.3f} | {v['r2_ndvi_built']:.3f} | {v['lst_morans_i']:.2f} |")
    g = r["gap_fill"]
    w = r["without_gap_filled_cells"]
    L.append(f"\nGap-filled temperature (no emissivity in the product): {g['city_share']:.1%} of the city per scene; reconstruction RMSE vs the product {min(g['rmse_k']):.2f}–{max(g['rmse_k']):.2f} K. "
             f"Without cells containing filled pixels ({w['cells']}): R² NDVI {w['r2_ndvi']:.3f}, NDVI + built {w['r2_ndvi_built']:.3f}.")
    L.append(f"\nInterior cells only ({r['interior']['cells']}): R² NDVI {r['interior']['r2_ndvi']:.3f}, NDVI + built {r['interior']['r2_ndvi_built']:.3f}.")
    if "sentinel2_check" in r:
        s = r["sentinel2_check"]
        L.append(f"\nSentinel-2 check ({s['date']}, {s['cells']} cells): NDVI correlation Landsat–Sentinel-2 {s['corr_landsat_s2_ndvi']:.2f}; R² Landsat NDVI {s['r2_landsat_ndvi']:.3f}, Sentinel-2 NDVI {s['r2_s2_ndvi']:.3f} (slope {s['slope_s2_ndvi']:.1f}).")
    (OUT / "results.md").write_text("\n".join(L) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()

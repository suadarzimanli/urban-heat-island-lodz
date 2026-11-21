"""
Paper figures from the analysis outputs (after analyze.py).

    python pipeline/make_figures.py              -> paper/figures/*.pdf
    python pipeline/make_figures.py --dark DIR   -> dark-background PNG versions (e.g. for a website)
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib.colors import LinearSegmentedColormap  # noqa: E402
from matplotlib.patches import Patch  # noqa: E402

sys.path.insert(0, str(Path(__file__).parent))
import uhi  # noqa: E402
from analyze import OUT, load_inputs  # noqa: E402
from export_web import ANOM_STOPS, NDVI_STOPS  # noqa: E402
from fetch import boundary  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--dark", type=Path, metavar="DIR")
ARGS = ap.parse_args()
DARK = ARGS.dark is not None
FIG = ARGS.dark if DARK else Path(__file__).resolve().parent.parent / "paper" / "figures"
FIG.mkdir(parents=True, exist_ok=True)
EXT = ".png" if DARK else ".pdf"

if DARK:
    C = ["#3987e5", "#d95926", "#199e70", "#c98500"]
    INK, INK2, GRID, BG, OUTLINE = "#f0efec", "#c3c2b7", "#2a2f38", "#14171c", "#f0efec"
else:
    C = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100"]
    INK, INK2, GRID, BG, OUTLINE = "#0b0b0b", "#52514e", "#e6e5e0", "#ffffff", "#111111"
plt.rcParams.update({
    "figure.facecolor": BG, "axes.facecolor": BG, "savefig.facecolor": BG, "text.color": INK, "legend.labelcolor": INK,
    "font.family": "DejaVu Sans", "font.size": 8.5, "axes.edgecolor": INK2, "axes.labelcolor": INK2,
    "xtick.color": INK2, "ytick.color": INK2, "axes.spines.top": False, "axes.spines.right": False,
    "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.8, "axes.axisbelow": True,
    "savefig.bbox": "tight", "savefig.dpi": 300,
})


def cmap(stops, name):
    lo, hi = stops[0][0], stops[-1][0]
    return LinearSegmentedColormap.from_list(name, [((v - lo) / (hi - lo), tuple(c / 255 for c in col)) for v, col in stops]), lo, hi


ANOM_CMAP, A_LO, A_HI = cmap(ANOM_STOPS, "anom")
NDVI_CMAP, N_LO, N_HI = cmap(NDVI_STOPS, "ndvi")
BUILT_CMAP = LinearSegmentedColormap.from_list("built", ["#f1f2f6", "#8c91ac", "#2a2d4d"])

res = json.loads((OUT / "results.json").read_text(encoding="utf-8"))
spec, inside, lc, scenes, s2 = load_inputs()
_, city_utm = boundary()
t = dict(np.load(OUT / "cells_500m.npz"))
m = dict(np.load(OUT / "main_500m.npz"))
sel = m["sel"]
extent = [spec["x0"], spec["x0"] + spec["width"] * uhi.PIXEL, spec["y1"] - spec["height"] * uhi.PIXEL, spec["y1"]]
bx, by = city_utm.exterior.xy
crop = [city_utm.bounds[0] - 500, city_utm.bounds[2] + 500, city_utm.bounds[1] - 500, city_utm.bounds[3] + 500]


def map_axis(ax):
    ax.plot(bx, by, color=OUTLINE, lw=0.8)
    ax.set_xlim(crop[0], crop[1])
    ax.set_ylim(crop[2], crop[3])
    ax.set_aspect("equal")
    ax.set_xticks([])
    ax.set_yticks([])
    ax.grid(False)
    for s in ax.spines.values():
        s.set_visible(False)


def scale_bar(ax, km=5):
    x0, y0 = crop[0] + 800, crop[2] + 800
    ax.plot([x0, x0 + km * 1000], [y0, y0], color=INK, lw=2)
    ax.text(x0 + km * 500, y0 + 400, f"{km} km", ha="center", fontsize=7, color=INK)


# ---------- 1. maps: mean summer anomaly (pixels), vegetation, built-up ----------
water = lc == uhi.WC_WATER
stack = np.stack([np.where(inside & ~water, s["lst"] - np.nanmedian(s["lst"][inside & ~water]), np.nan) for s in scenes])
with np.errstate(all="ignore"):
    cnt = np.isfinite(stack).sum(0)
    mean_anom = np.where(cnt >= 0.5 * len(scenes), np.nanmean(stack, 0), np.nan)
built_px = np.where(inside, (lc == uhi.WC_BUILT).astype(float), np.nan)
fig, axes = plt.subplots(1, 3, figsize=(7.2, 2.9))
panels = [
    (mean_anom[::3, ::3], ANOM_CMAP, A_LO, A_HI, "Summer surface heat (°C vs city median)"),
    (np.where(inside, s2, np.nan)[::2, ::2], NDVI_CMAP, N_LO, N_HI, "Vegetation (NDVI, Sentinel-2 2023)"),
    (built_px[::2, ::2], BUILT_CMAP, 0, 1, "Built-up land (ESA WorldCover 2021)"),
]
for ax, (arr, cm, lo, hi, title) in zip(axes, panels):
    im = ax.imshow(arr, extent=extent, cmap=cm, vmin=lo, vmax=hi, interpolation="nearest")
    map_axis(ax)
    ax.set_title(title, fontsize=7.6, color=INK)
    cb = fig.colorbar(im, ax=ax, orientation="horizontal", fraction=0.05, pad=0.03)
    cb.outline.set_visible(False)
    cb.ax.tick_params(labelsize=6.5, colors=INK2)
    if cm is BUILT_CMAP:
        cb.set_ticks([0, 1], labels=["other", "built-up"])
scale_bar(axes[0])
fig.tight_layout(w_pad=0.6)
fig.savefig(FIG / ("fig-maps" + EXT))
plt.close(fig)

# ---------- 2. scatter: anomaly vs NDVI and vs built-up share ----------
y = m["anom"][sel]
fig, axes = plt.subplots(1, 2, figsize=(7.0, 2.9), sharey=True)
for ax, x, lab, key in [(axes[0], m["ndvi"][sel], "Vegetation (NDVI, mean of clear days)", "ndvi"), (axes[1], t["built"][sel], "Built-up share of the cell", "built")]:
    ax.scatter(x, y, s=5, color=C[0], alpha=0.45, lw=0)
    b = res["main"]["models"][key]["coef"]
    xs = np.linspace(np.nanmin(x), np.nanmax(x), 50)
    ax.plot(xs, b[0] + b[1] * xs, color=C[1], lw=1.8)
    r2 = res["main"]["models"][key]["r2"]
    cv = res["main"]["models"][key]["r2_blocked_cv"]
    ax.text(0.97 if key == "ndvi" else 0.03, 0.95, f"R² = {r2:.2f}\nheld-out blocks: {cv:.2f}", transform=ax.transAxes,
            ha="right" if key == "ndvi" else "left", va="top", fontsize=7.5, color=INK)
    ax.set_xlabel(lab)
axes[0].set_ylabel("Surface heat (°C vs city median)")
fig.tight_layout()
fig.savefig(FIG / ("fig-scatter" + EXT))
plt.close(fig)

# ---------- 3. per date: R² and slope ----------
per = res["per_date"]
dates = [p["date"] for p in per]
xpos = np.arange(len(per))
fig, axes = plt.subplots(2, 1, figsize=(7.0, 3.6), sharex=True, gridspec_kw={"height_ratios": [1.2, 1]})
axes[0].plot(xpos, [p["r2_ndvi_built"] for p in per], "o-", color=C[2], ms=4, lw=1.2, label="Vegetation + built-up share")
axes[0].plot(xpos, [p["r2_ndvi"] for p in per], "o-", color=C[0], ms=4, lw=1.2, label="Vegetation alone")
axes[0].set_ylabel("R²")
axes[0].set_ylim(0, 1)
axes[0].legend(frameon=False, fontsize=7.5, loc="lower right", ncol=2)
axes[1].bar(xpos, [p["slope_ndvi"] / 10 for p in per], color=C[0], width=0.6)
axes[1].set_ylabel("°C per 0.1 NDVI")
axes[1].grid(axis="x", visible=False)
ax2 = axes[1].twinx() if False else None
axes[1].set_xticks(xpos, [f"{d[8:10]}.{d[5:7]}.{d[2:4]}" for d in dates], rotation=60, fontsize=6.8)
for i, p in enumerate(per):
    axes[1].text(i, p["slope_ndvi"] / 10 - 0.08, f"{p['city_median_lst']:.0f}°", ha="center", va="top", fontsize=5.6, color=INK2)
axes[1].set_ylim(min(p["slope_ndvi"] for p in per) / 10 - 0.6, 0)
fig.tight_layout(h_pad=0.4)
fig.savefig(FIG / ("fig-dates" + EXT))
plt.close(fig)

# ---------- 4. residual and hot/cold spot maps ----------
def grid_image(values_sel, fill=np.nan):
    v = np.full(len(t["x"]), fill)
    v[np.nonzero(sel)[0]] = values_sel
    nr = int(t["row"].max()) + 1
    nc = int(t["col"].max()) + 1
    img = np.full((nr, nc), np.nan)
    img[t["row"], t["col"]] = v
    return img


k = int(500 / uhi.PIXEL)
nr_full = -(-spec["height"] // k)
nc_full = -(-spec["width"] // k)
g_extent = [spec["x0"], spec["x0"] + nc_full * 500, spec["y1"] - nr_full * 500, spec["y1"]]


def full_grid(img):
    out = np.full((nr_full, nc_full), np.nan)
    out[: img.shape[0], : img.shape[1]] = img
    return out


RES_CMAP, R_LO, R_HI = cmap([(v / 2, c) for v, c in ANOM_STOPS], "res")
fig, axes = plt.subplots(1, 2, figsize=(7.0, 3.3))
im = axes[0].imshow(full_grid(grid_image(m["resid"])), extent=g_extent, cmap=RES_CMAP, vmin=R_LO, vmax=R_HI, interpolation="nearest")
map_axis(axes[0])
axes[0].set_title("Hotter (+) or cooler (−) than vegetation and built-up share predict (°C)", fontsize=7.2, color=INK)
cb = fig.colorbar(im, ax=axes[0], orientation="horizontal", fraction=0.05, pad=0.03)
cb.outline.set_visible(False)
cb.ax.tick_params(labelsize=6.5, colors=INK2)
spot = np.where(m["gi_sig"] & (m["gi_z"] > 0), 1.0, np.where(m["gi_sig"] & (m["gi_z"] < 0), 0.0, np.nan))
from matplotlib.colors import ListedColormap  # noqa: E402
axes[1].imshow(full_grid(grid_image(spot)), extent=g_extent, cmap=ListedColormap(["#2c6fbb", "#c0392b"]), vmin=0, vmax=1, interpolation="nearest")
map_axis(axes[1])
scale_bar(axes[1])
axes[1].set_title("Hot and cold spots (Gi*, 5% false-discovery rate)", fontsize=7.2, color=INK)
axes[1].legend(handles=[Patch(color="#c0392b", label=f"Hot spot ({res['main']['hotspots']['hot']} cells)"),
                        Patch(color="#2c6fbb", label=f"Cold spot ({res['main']['hotspots']['cold']} cells)")],
               loc="lower center", bbox_to_anchor=(0.5, -0.16), ncol=2, frameon=False, fontsize=7)
fig.tight_layout(w_pad=0.8)
fig.savefig(FIG / ("fig-residuals" + EXT))
plt.close(fig)
print("figures written to", FIG)

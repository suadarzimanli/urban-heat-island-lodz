"""
Shared functions for the Łódź urban heat island pipeline.

Everything is computed on one analysis grid: 10 m pixels in UTM zone 34N (EPSG:32634), so that
250, 500 and 1000 m cells contain whole pixels. Sources are resampled onto it:
  Landsat 8/9 Collection 2 Level-2 (30 m)   surface temperature (ST_B10), red/NIR, QA_PIXEL
  Sentinel-2 L2A (10 m)                     red/NIR and scene classification (cross-check NDVI)
  ESA WorldCover 2021 (10 m)                land cover (built-up, trees, water)
"""
from __future__ import annotations

import numpy as np

CRS = "EPSG:32634"
PIXEL = 10.0  # metres

# Landsat Collection 2 Level-2 scaling (USGS)
ST_SCALE, ST_OFFSET = 0.00341802, 149.0  # kelvin
SR_SCALE, SR_OFFSET = 0.0000275, -0.2
# QA_PIXEL bits that make a pixel unusable: fill, dilated cloud, cirrus, cloud, cloud shadow, snow
QA_BAD_BITS = 0b111111

# ESA WorldCover classes
WC_TREE, WC_SHRUB, WC_GRASS, WC_CROP, WC_BUILT, WC_BARE, WC_SNOW, WC_WATER, WC_WETLAND = 10, 20, 30, 40, 50, 60, 70, 80, 90


def landsat_lst_celsius(st_b10: np.ndarray) -> np.ndarray:
    """Surface temperature in °C from the ST_B10 digital number (0 = fill)."""
    out = st_b10.astype("float64") * ST_SCALE + ST_OFFSET - 273.15
    out[st_b10 == 0] = np.nan
    return out


def landsat_reflectance(dn: np.ndarray) -> np.ndarray:
    out = dn.astype("float64") * SR_SCALE + SR_OFFSET
    out[dn == 0] = np.nan
    return out


def landsat_clear(qa_pixel: np.ndarray) -> np.ndarray:
    """True where the pixel is not fill, cloud, cloud shadow, cirrus or snow."""
    return (qa_pixel.astype("int64") & QA_BAD_BITS) == 0


def surface_temperature_from_radiance(trad, urad, drad, atran, emis, k1, k2) -> np.ndarray:
    """
    Surface temperature (°C) from the Collection 2 ST intermediate bands, for pixels where the
    product has no emissivity (the ASTER GED gap). Inputs are physical values:
      trad, urad, drad in W/(m²·sr·µm), atran and emis unitless; k1, k2 the band's thermal constants.
    L_surface = (TRAD − URAD − τ·(1 − ε)·DRAD) / (τ·ε);  T = K2 / ln(K1 / L + 1)
    """
    with np.errstate(invalid="ignore", divide="ignore"):
        lsurf = (trad - urad - atran * (1 - emis) * drad) / (atran * emis)
        t = k2 / np.log(k1 / lsurf + 1)
    t = t - 273.15
    t[~np.isfinite(t)] = np.nan
    return t


def emissivity_from_ndvi(ndvi_ref, emis_ref, ndvi_target, bin_width: float = 0.02) -> np.ndarray:
    """Emissivity for `ndvi_target` from the median emissivity of reference pixels in NDVI bins (same scene)."""
    ok = np.isfinite(ndvi_ref) & np.isfinite(emis_ref)
    edges = np.arange(-1, 1 + bin_width, bin_width)
    idx = np.digitize(ndvi_ref[ok], edges)
    centres, meds = [], []
    for b in np.unique(idx):
        sel = idx == b
        if sel.sum() >= 50:
            centres.append(float(np.median(ndvi_ref[ok][sel])))
            meds.append(float(np.median(emis_ref[ok][sel])))
    out = np.interp(ndvi_target, centres, meds)
    out[~np.isfinite(ndvi_target)] = np.nan
    return out


def ndvi(red: np.ndarray, nir: np.ndarray) -> np.ndarray:
    with np.errstate(invalid="ignore", divide="ignore"):
        v = (nir - red) / (nir + red)
    v[~np.isfinite(v)] = np.nan
    return np.clip(v, -1, 1)


# ---------------------------------------------------------------- grid cells

def cell_index(shape: tuple[int, int], cell_m: float, pixel_m: float = PIXEL) -> tuple[np.ndarray, int, int]:
    """Cell id per pixel for square cells of `cell_m` metres, row-major from the grid's top-left."""
    k = int(round(cell_m / pixel_m))
    if abs(k * pixel_m - cell_m) > 1e-6:
        raise ValueError("cell size must be a multiple of the pixel size")
    rows, cols = shape
    nr, nc = -(-rows // k), -(-cols // k)
    r = (np.arange(rows) // k)[:, None]
    c = (np.arange(cols) // k)[None, :]
    return (r * nc + c).astype("int64"), nr, nc


def zonal_mean(values: np.ndarray, ids: np.ndarray, n: int, weights: np.ndarray | None = None) -> tuple[np.ndarray, np.ndarray]:
    """Mean of finite values per cell id, and the count of values used."""
    ok = np.isfinite(values)
    if weights is not None:
        ok &= weights
    cnt = np.bincount(ids[ok], minlength=n).astype("float64")
    s = np.bincount(ids[ok], weights=values[ok], minlength=n)
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(cnt > 0, s / cnt, np.nan), cnt


def zonal_fraction(mask: np.ndarray, ids: np.ndarray, n: int, within: np.ndarray | None = None) -> np.ndarray:
    """Share of pixels where `mask` is true, among pixels in `within` (default: all)."""
    w = np.ones_like(mask, dtype=bool) if within is None else within
    tot = np.bincount(ids[w], minlength=n).astype("float64")
    hit = np.bincount(ids[w & mask], minlength=n).astype("float64")
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(tot > 0, hit / tot, np.nan)


# ---------------------------------------------------------------- statistics

def ols(X: np.ndarray, y: np.ndarray) -> dict:
    """Least squares with intercept. Returns coefficients, R², adjusted R², residuals."""
    X1 = np.column_stack([np.ones(len(y)), X])
    beta, *_ = np.linalg.lstsq(X1, y, rcond=None)
    fit = X1 @ beta
    res = y - fit
    ss_res = float(res @ res)
    ss_tot = float(((y - y.mean()) ** 2).sum())
    n, p = X1.shape
    r2 = 1 - ss_res / ss_tot
    return {"beta": beta, "r2": r2, "r2_adj": 1 - (1 - r2) * (n - 1) / (n - p), "fitted": fit, "resid": res}


def rook_neighbours(rows: np.ndarray, cols: np.ndarray, queen: bool = False) -> list[np.ndarray]:
    """Neighbour lists (indices into the arrays) for grid cells given by row/col."""
    pos = {(int(r), int(c)): i for i, (r, c) in enumerate(zip(rows, cols))}
    steps = [(-1, 0), (1, 0), (0, -1), (0, 1)]
    if queen:
        steps += [(-1, -1), (-1, 1), (1, -1), (1, 1)]
    out = []
    for r, c in zip(rows, cols):
        out.append(np.array([pos[(int(r) + dr, int(c) + dc)] for dr, dc in steps if (int(r) + dr, int(c) + dc) in pos], dtype="int64"))
    return out


def morans_i(x: np.ndarray, nbrs: list[np.ndarray], permutations: int = 999, seed: int = 1) -> dict:
    """Global Moran's I with binary row-standardised weights and a permutation p-value."""
    z = x - x.mean()
    def stat(zz):
        lag = np.array([zz[nb].mean() if len(nb) else 0.0 for nb in nbrs])
        return float((zz * lag).sum() / (zz @ zz))
    I = stat(z)
    rng = np.random.default_rng(seed)
    sims = np.array([stat(rng.permutation(z)) for _ in range(permutations)])
    p = (1 + (np.abs(sims) >= abs(I)).sum()) / (permutations + 1)
    return {"I": I, "p": float(p), "expected": -1 / (len(x) - 1)}


def getis_ord_gi_star(x: np.ndarray, nbrs: list[np.ndarray]) -> np.ndarray:
    """Gi* z-scores with binary weights over each cell and its neighbours."""
    n = len(x)
    xbar = x.mean()
    s = np.sqrt((x ** 2).mean() - xbar ** 2)
    z = np.empty(n)
    for i, nb in enumerate(nbrs):
        idx = np.append(nb, i)
        w = len(idx)
        num = x[idx].sum() - xbar * w
        den = s * np.sqrt((n * w - w * w) / (n - 1))
        z[i] = num / den
    return z


def fdr_mask(p: np.ndarray, alpha: float = 0.05) -> np.ndarray:
    """Benjamini–Hochberg: True where the p-value is significant at false-discovery rate `alpha`."""
    order = np.argsort(p)
    ranked = p[order]
    thresh = alpha * (np.arange(1, len(p) + 1) / len(p))
    passed = ranked <= thresh
    k = np.max(np.nonzero(passed)[0]) + 1 if passed.any() else 0
    out = np.zeros(len(p), dtype=bool)
    out[order[:k]] = True
    return out


def blocked_cv_r2(X: np.ndarray, y: np.ndarray, blocks: np.ndarray, folds: int = 5, seed: int = 1) -> float:
    """Out-of-sample R² when whole spatial blocks are held out together."""
    rng = np.random.default_rng(seed)
    ub = np.unique(blocks)
    fold_of = dict(zip(ub, rng.permutation(len(ub)) % folds))
    f = np.array([fold_of[b] for b in blocks])
    pred = np.empty_like(y, dtype="float64")
    for k in range(folds):
        tr, te = f != k, f == k
        m = ols(X[tr], y[tr])
        pred[te] = np.column_stack([np.ones(te.sum()), X[te]]) @ m["beta"]
    return float(1 - ((y - pred) ** 2).sum() / ((y - y.mean()) ** 2).sum())


def block_bootstrap_ci(X: np.ndarray, y: np.ndarray, blocks: np.ndarray, coef: int = 1, reps: int = 999, seed: int = 1) -> tuple[float, float]:
    """95% interval of one coefficient, resampling whole spatial blocks."""
    rng = np.random.default_rng(seed)
    ub = np.unique(blocks)
    members = {b: np.nonzero(blocks == b)[0] for b in ub}
    vals = []
    for _ in range(reps):
        idx = np.concatenate([members[b] for b in rng.choice(ub, len(ub), replace=True)])
        vals.append(ols(X[idx], y[idx])["beta"][coef])
    lo, hi = np.percentile(vals, [2.5, 97.5])
    return float(lo), float(hi)

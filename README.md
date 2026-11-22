# Urban Heat Island — Łódź

[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.24438160.svg)](https://doi.org/10.5281/zenodo.24438160)

Where is Łódź hot on clear summer days, how much of that do vegetation and built-up land explain, and which places are hotter than those two predict? This repository holds an open, reproducible analysis and an interactive web map.

**Web map:** https://suadarzimanli.github.io/urban-heat-island-lodz/
**Paper:** [`paper/urban-heat-island-lodz.pdf`](paper/urban-heat-island-lodz.pdf)

## What it does

- **Twenty clear summer days, 2018–2025.** Every June–August day on which at least 90% of the city was cloud-free in Landsat 8 or 9 imagery.
- **Heat and greenery observed together.** Land surface temperature and vegetation (NDVI) come from the same Landsat scenes. Temperatures are compared as anomalies from the city median of each day, so hot and mild days can be combined.
- **A metric 500 m grid** (UTM zone 34N), 1,176 cells, plus 250 m and 1000 m for comparison. Built-up, tree and water shares come from ESA WorldCover 2021.
- **Statistics that respect space:** regression checked by spatially blocked cross-validation and a block bootstrap, Moran's I, and Getis–Ord Gi* hot and cold spots at a 5% false-discovery rate.
- **Complete coverage:** where the Landsat surface-temperature product is empty although the sky is clear (no emissivity input there), temperature is recomputed from the product's radiance layers with an NDVI-based emissivity (error ≈ 0.55 K), and flagged.
- **Web map:** surface heat, vegetation, built-up share, hotter or cooler than expected, hot and cold spots; satellite pixels (default: 30 m surface heat and vegetation, 10 m built-up land) or the 500 m grid; any single day or the mean; a cell panel with each day's anomaly; a scatter plot linked to the map; light and dark themes; phone layout.

## Key results

| Explaining summer surface heat (1,176 cells of 500 m) by | R² | R² on held-out 2 km blocks |
|---|---:|---:|
| Vegetation (NDVI) | 0.896 | 0.894 |
| Built-up share | 0.699 | 0.691 |
| Both | 0.909 | 0.905 |

- About **2 °C less surface heat per 0.1 NDVI**; surface heat is strongly clustered (Moran's I = 0.76).
- The relationship holds on most single days (median R² 0.85; 15 of 20 days above 0.75), at 250–1000 m cells, without edge cells, without gap-filled cells, and with Sentinel-2 vegetation.
- What vegetation does not explain is spatially organised: the dense historic centre is **cooler than expected**, the airport and large industrial sites **hotter**.
- 181 hot-spot and 120 cold-spot cells; 176 of the hot-spot cells have below-median vegetation.

Full tables: [`analysis/results.md`](analysis/results.md).

## Run the web map

No build step. Serve the folder over HTTP (browsers block `fetch` from `file://`):

```bash
python -m http.server 8000        # then open http://localhost:8000
```

On Windows you can double-click `run_local.bat` (macOS/Linux: `./run_local.sh`).

## Rebuild the analysis

Python 3.10+ with `numpy scipy rasterio shapely pyproj pystac-client planetary-computer requests matplotlib pillow`. All data are public; no account is needed.

```bash
python pipeline/fetch.py          # download Landsat, Sentinel-2, WorldCover and the boundary (cached in pipeline/cache/)
python pipeline/analyze.py        # grid statistics and all models -> analysis/results.{json,md}
python pipeline/export_web.py     # web data -> data/
python pipeline/make_figures.py   # paper figures -> paper/figures/
python -m unittest discover -s pipeline   # 15 tests
node --test tests/                        # 6 tests (web data and colour scales)
```

## Repository

```
index.html  css/style.css  js/app.js  js/scales.js   web map (Leaflet, Chart.js)
data/                cells_500m.{csv,geojson}, boundary.geojson, summary.json, rasters/*.png
pipeline/            fetch.py, analyze.py, export_web.py, make_figures.py, uhi.py (library), test_uhi.py
analysis/            results.json, results.md
paper/               LaTeX source, figures and PDF
tests/               JavaScript tests
```

External libraries are loaded from CDNs at fixed versions with integrity checks: Leaflet 1.9.4 and Chart.js 4.4.1.

## Data sources and licences

- Landsat 8/9 Collection 2 Level-2 — courtesy of the U.S. Geological Survey (public domain), via the Microsoft Planetary Computer.
- Sentinel-2 L2A — contains modified Copernicus Sentinel data (2023).
- ESA WorldCover 2021 v200 — © ESA WorldCover project, CC BY 4.0.
- City boundary — © OpenStreetMap contributors, ODbL (relation 2413295); `data/boundary.geojson` stays under ODbL.

Code: **MIT**. Paper, figures and derived data: **CC BY 4.0** (see [LICENSE](LICENSE)). Please cite using [CITATION.cff](CITATION.cff).

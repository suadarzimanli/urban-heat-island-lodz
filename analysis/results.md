# Results

20 clear summer Landsat scenes (2018-07-04 … 2025-08-16); 1176 of 1176 500 m cells.

Moran's I of the mean summer LST anomaly: 0.76 (p = 0.001). Correlation NDVI–built-up share: -0.81. Anomaly 5th–95th percentile: -4.7 to 5.1 °C.

| Model | R² | adj. R² | blocked-CV R² | Moran's I of residuals | coefficients |
|---|---:|---:|---:|---:|---|
| ndvi | 0.896 | 0.896 | 0.894 | 0.54 | 12.41, -20.47 |
| built | 0.699 | 0.699 | 0.691 | 0.66 | -2.26, 8.93 |
| ndvi_built | 0.909 | 0.909 | 0.905 | 0.48 | 9.80, -17.04, 2.08 |
| full | 0.910 | 0.909 | 0.905 | 0.48 | 9.77, -16.97, 2.09, -6.25, 0.00 |

NDVI slope alone: 95% block-bootstrap CI -21.4 to -19.4 °C per NDVI unit; with built-up share: NDVI -19.0 to -15.0, built-up 1.2 to 2.9.

Hot spots 181, cold spots 120, hot spots with below-median NDVI 176; > 1 °C hotter than expected 96, > 1 °C cooler 111.

## Per date (500 m)

| Date | cells | city median LST | NDVI slope | R² NDVI | R² NDVI + built | P95–P5 spread |
|---|---:|---:|---:|---:|---:|---:|
| 2018-07-04 | 1088 | 35.1 | -17.0 | 0.685 | 0.695 | 9.9 |
| 2018-08-12 | 1145 | 24.9 | -21.3 | 0.501 | 0.611 | 13.0 |
| 2019-06-12 | 1175 | 38.4 | -21.2 | 0.810 | 0.816 | 10.5 |
| 2019-08-24 | 1176 | 31.1 | -14.8 | 0.853 | 0.870 | 7.3 |
| 2019-08-31 | 1168 | 35.6 | -15.4 | 0.848 | 0.853 | 7.2 |
| 2020-07-25 | 1160 | 31.1 | -20.7 | 0.727 | 0.877 | 10.3 |
| 2020-08-17 | 1176 | 33.0 | -20.2 | 0.629 | 0.689 | 10.4 |
| 2021-07-28 | 1106 | 35.6 | -19.0 | 0.389 | 0.471 | 12.1 |
| 2022-06-05 | 1176 | 29.6 | -24.4 | 0.891 | 0.915 | 11.6 |
| 2023-06-08 | 1176 | 35.8 | -23.8 | 0.909 | 0.910 | 12.0 |
| 2023-07-09 | 1176 | 37.2 | -23.3 | 0.895 | 0.896 | 12.1 |
| 2023-08-19 | 1176 | 34.4 | -17.9 | 0.774 | 0.892 | 8.7 |
| 2024-06-09 | 1141 | 30.9 | -24.5 | 0.862 | 0.873 | 12.3 |
| 2024-06-26 | 1109 | 37.5 | -21.0 | 0.830 | 0.832 | 10.7 |
| 2024-08-13 | 1175 | 31.6 | -21.3 | 0.892 | 0.901 | 10.8 |
| 2024-08-28 | 1176 | 33.4 | -16.5 | 0.849 | 0.858 | 7.5 |
| 2024-08-29 | 1175 | 35.4 | -16.1 | 0.864 | 0.865 | 7.4 |
| 2025-06-21 | 1172 | 32.9 | -22.3 | 0.895 | 0.895 | 11.4 |
| 2025-08-15 | 1176 | 35.7 | -18.5 | 0.888 | 0.890 | 9.0 |
| 2025-08-16 | 1175 | 34.3 | -20.6 | 0.897 | 0.903 | 9.9 |

## Cell size

| Cell | cells | R² NDVI | R² built | R² NDVI + built | Moran's I |
|---|---:|---:|---:|---:|---:|
| 250 m | 4695 | 0.860 | 0.661 | 0.873 | 0.81 |
| 500 m | 1176 | 0.896 | 0.699 | 0.909 | 0.76 |
| 1000 m | 293 | 0.914 | 0.727 | 0.931 | 0.71 |

Gap-filled temperature (no emissivity in the product): 3.5% of the city per scene; reconstruction RMSE vs the product 0.51–0.60 K. Without cells containing filled pixels (1086): R² NDVI 0.901, NDVI + built 0.911.

Interior cells only (1060): R² NDVI 0.898, NDVI + built 0.910.

Sentinel-2 check (2023-06-08, 1176 cells): NDVI correlation Landsat–Sentinel-2 0.99; R² Landsat NDVI 0.909, Sentinel-2 NDVI 0.884 (slope -21.4).

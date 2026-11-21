/**
 * Colour scales and formatting shared by the map, legend and charts.
 * The ramps match pipeline/export_web.py so the pixel layers and the grid read the same way.
 *   diverging  surface heat and residuals: blue (cooler) — neutral grey — red (hotter)
 *   sequential vegetation: light to dark green; built-up share: light to dark slate
 */
export const ANOM_STOPS = [
  [-6, [33, 102, 172]],
  [-3, [103, 169, 207]],
  [0, [230, 230, 226]],
  [3, [239, 138, 98]],
  [6, [178, 24, 43]],
];
export const RES_STOPS = ANOM_STOPS.map(([v, c]) => [v / 2, c]); // ±3 °C
export const NDVI_STOPS = [
  [0.0, [247, 245, 235]],
  [0.2, [217, 230, 178]],
  [0.4, [145, 196, 122]],
  [0.6, [49, 140, 74]],
  [0.8, [0, 79, 40]],
];
export const BUILT_STOPS = [
  [0.0, [241, 242, 246]],
  [0.25, [196, 199, 214]],
  [0.5, [140, 145, 172]],
  [0.75, [88, 92, 128]],
  [1.0, [42, 45, 77]],
];
export const SPOT_COLORS = { hot: "#c0392b", cold: "#2c6fbb" };

export const VARIABLES = {
  anom: { label: "Surface heat", unit: "°C vs city median", stops: ANOM_STOPS, fmt: (v) => signed(v, 1, " °C") },
  ndvi: { label: "Vegetation (NDVI)", unit: "", stops: NDVI_STOPS, fmt: (v) => fixed(v, 2) },
  built: { label: "Built-up share", unit: "", stops: BUILT_STOPS, fmt: (v) => pct(v) },
  res: { label: "Hotter or cooler than expected", unit: "°C", stops: RES_STOPS, fmt: (v) => signed(v, 1, " °C") },
  spot: { label: "Hot and cold spots", unit: "", stops: null, fmt: (v) => v ?? "—" },
};

export function rampColor(value, stops) {
  if (value == null || !Number.isFinite(value)) return null;
  const v = Math.min(Math.max(value, stops[0][0]), stops[stops.length - 1][0]);
  for (let i = 1; i < stops.length; i += 1) {
    const [x1, c1] = stops[i];
    const [x0, c0] = stops[i - 1];
    if (v <= x1) {
      const t = x1 === x0 ? 0 : (v - x0) / (x1 - x0);
      const c = c0.map((a, k) => Math.round(a + t * (c1[k] - a)));
      return `rgb(${c[0]}, ${c[1]}, ${c[2]})`;
    }
  }
  const c = stops[stops.length - 1][1];
  return `rgb(${c[0]}, ${c[1]}, ${c[2]})`;
}

export function cssGradient(stops) {
  const lo = stops[0][0];
  const hi = stops[stops.length - 1][0];
  return `linear-gradient(90deg, ${stops.map(([v, c]) => `rgb(${c.join(",")}) ${(((v - lo) / (hi - lo)) * 100).toFixed(0)}%`).join(", ")})`;
}

export function fixed(v, d = 2) {
  return v == null || !Number.isFinite(v) ? "—" : v.toFixed(d);
}

export function signed(v, d = 1, unit = "") {
  if (v == null || !Number.isFinite(v)) return "—";
  const s = v.toFixed(d);
  return `${v > 0 && s !== (0).toFixed(d) ? "+" : ""}${s.replace("-", "−")}${unit}`;
}

export function pct(v) {
  return v == null || !Number.isFinite(v) ? "—" : `${Math.round(v * 100)}%`;
}

/** Least-squares line through finite (x, y) pairs. */
export function fitLine(xs, ys) {
  let n = 0;
  let sx = 0;
  let sy = 0;
  let sxx = 0;
  let sxy = 0;
  let syy = 0;
  for (let i = 0; i < xs.length; i += 1) {
    const x = xs[i];
    const y = ys[i];
    if (!Number.isFinite(x) || !Number.isFinite(y)) continue;
    n += 1;
    sx += x;
    sy += y;
    sxx += x * x;
    sxy += x * y;
    syy += y * y;
  }
  if (n < 3) return null;
  const vx = sxx - (sx * sx) / n;
  const vy = syy - (sy * sy) / n;
  const cxy = sxy - (sx * sy) / n;
  const slope = cxy / vx;
  return { n, slope, intercept: (sy - slope * sx) / n, r2: (cxy * cxy) / (vx * vy) };
}

export function formatDate(iso) {
  if (iso === "mean") return "all clear summer days";
  const d = new Date(`${iso}T00:00:00Z`);
  return d.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" });
}

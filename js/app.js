/**
 * Urban Heat Island — Łódź. Static web app over the pipeline's outputs (data/*.json, data/rasters/*.png).
 * No server code: everything here is read-only visualisation of numbers computed in pipeline/.
 */
import { BUILT_STOPS, cssGradient, fitLine, fixed, formatDate, NDVI_STOPS, pct, rampColor, signed, SPOT_COLORS, VARIABLES } from "./scales.js";

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

const state = {
  variable: "anom",
  date: "mean", // "mean" or an index into summary.dates
  detail: "grid",
  opacity: 0.8,
  priority: false,
  scatterX: "ndvi",
  selected: null, // feature id
  summary: null,
  cells: [],
  byId: new Map(),
};

/* ---------------- map ---------------- */

const map = L.map("map", { preferCanvas: true, zoomSnap: 0.25 }).setView([51.765, 19.46], 11);
L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
  maxZoom: 18,
  attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors · Landsat: USGS · <a href="https://esa-worldcover.org">ESA WorldCover</a>',
}).addTo(map);
L.control.scale({ imperial: false }).addTo(map);
new ResizeObserver(() => map.invalidateSize()).observe($("map"));

let gridLayer = null;
let boundaryLayer = null;
let pixelLayer = null;
let priorityLayer = null;
const layerById = new Map();

/* ---------------- values ---------------- */

const dateIdx = () => (state.date === "mean" ? null : Number(state.date));

function valueOf(p, variable = state.variable) {
  const i = dateIdx();
  switch (variable) {
    case "anom":
      return i == null ? p.anom : p.a[i];
    case "ndvi":
      return i == null ? p.ndvi : p.v[i];
    case "built":
      return p.built;
    case "res":
      return p.res;
    case "spot":
      return p.spot;
    default:
      return null;
  }
}

function fillFor(p) {
  if (state.variable === "spot") return p.spot ? SPOT_COLORS[p.spot] : null;
  return rampColor(valueOf(p), VARIABLES[state.variable].stops);
}

function cellStyle(feature) {
  const p = feature.properties;
  const fill = fillFor(p);
  const selected = p.id === state.selected;
  const showFill = state.detail === "grid" || !pixelsAvailable();
  return {
    color: selected ? "#111" : "rgba(40,40,40,0.35)",
    weight: selected ? 3 : 0.5,
    fillColor: fill ?? "#000",
    fillOpacity: showFill ? (fill ? state.opacity : 0) : 0,
    dashArray: fill || !showFill ? null : "2 3",
  };
}

function pixelsAvailable() {
  return state.variable === "anom" || state.variable === "ndvi";
}

/* ---------------- layers ---------------- */

function drawGrid() {
  gridLayer?.remove();
  layerById.clear();
  gridLayer = L.geoJSON({ type: "FeatureCollection", features: state.cells }, {
    style: cellStyle,
    onEachFeature: (f, layer) => {
      layerById.set(f.properties.id, layer);
      layer.on("click", () => selectCell(f.properties.id, false));
      layer.on("mouseover", () => layer.setStyle({ weight: 2, color: "#111" }));
      layer.on("mouseout", () => layer.setStyle(cellStyle(f)));
      layer.bindTooltip(() => tooltipText(f.properties), { sticky: true, direction: "top", opacity: 0.95 });
    },
  }).addTo(map);
}

function tooltipText(p) {
  const v = valueOf(p);
  const label = VARIABLES[state.variable].label;
  const shown = state.variable === "spot" ? (p.spot ? `${p.spot} spot` : "not a hot or cold spot") : VARIABLES[state.variable].fmt(v);
  return `Cell ${p.id} · ${esc(label)}: ${esc(shown)}`;
}

function restyle() {
  gridLayer?.setStyle(cellStyle);
  drawPriority();
}

function drawPriority() {
  priorityLayer?.remove();
  priorityLayer = null;
  if (!state.priority) return;
  const feats = state.cells.filter((f) => f.properties.prio);
  priorityLayer = L.geoJSON({ type: "FeatureCollection", features: feats }, {
    style: { color: "#111", weight: 2.5, fill: false, dashArray: null },
    interactive: false,
  }).addTo(map);
}

function drawPixels() {
  pixelLayer?.remove();
  pixelLayer = null;
  if (state.detail !== "pixels" || !pixelsAvailable()) return;
  const r = state.summary.rasters;
  const key = state.variable === "ndvi" ? "ndvi" : state.date === "mean" ? "mean" : state.summary.dates[dateIdx()];
  const file = state.variable === "ndvi" ? "ndvi_s2_2023" : key === "mean" ? "anom_mean" : `anom_${key}`;
  pixelLayer = L.imageOverlay(`data/rasters/${file}.png`, r[key], { opacity: state.opacity, interactive: false, className: "pixel-layer" }).addTo(map);
  gridLayer?.bringToFront();
  priorityLayer?.bringToFront();
}

/* ---------------- legend and notes ---------------- */

function renderLegend() {
  const v = VARIABLES[state.variable];
  let html = "";
  if (state.variable === "spot") {
    html = `<div class="legend-cats">
      <span><i style="background:${SPOT_COLORS.hot}"></i> Hot spot — cluster of hotter cells</span>
      <span><i style="background:${SPOT_COLORS.cold}"></i> Cold spot — cluster of cooler cells</span>
      <span><i class="none"></i> Neither</span></div>`;
  } else {
    const stops = v.stops;
    const lo = stops[0][0];
    const hi = stops[stops.length - 1][0];
    const ticks = stops.map(([x]) => `<span style="left:${(((x - lo) / (hi - lo)) * 100).toFixed(1)}%">${esc(v.fmt(x)).replace(" °C", "")}</span>`).join("");
    const ends = {
      anom: ["cooler than the city", "hotter"],
      res: ["cooler than expected", "hotter than expected"],
      ndvi: ["bare / sealed", "dense vegetation"],
      built: ["no built-up land", "fully built-up"],
    }[state.variable];
    html = `<div class="legend-title">${esc(v.label)}${state.variable === "anom" || state.variable === "res" ? " (°C)" : ""}</div>
      <div class="legend-bar" style="background:${cssGradient(stops)}"></div>
      <div class="legend-ticks">${ticks}</div>
      <div class="legend-ends"><span>${esc(ends[0])}</span><span>${esc(ends[1])}</span></div>`;
  }
  html += `<div class="legend-cats"><span><i class="nodata"></i> Not enough clear observations</span>${state.priority ? '<span><i class="prio"></i> More than 1 °C hotter than vegetation and built-up share predict</span>' : ""}</div>`;
  $("legend").innerHTML = html;
}

function renderNotes() {
  const notes = [];
  if (state.detail === "pixels" && !pixelsAvailable()) notes.push("Satellite pixels are available for surface heat and vegetation; this variable is shown on the grid.");
  if (state.detail === "pixels" && state.variable === "ndvi") notes.push("Pixel vegetation: Sentinel-2, 10 m, median of clear summer 2023 days.");
  if (state.date !== "mean" && (state.variable === "res" || state.variable === "spot")) notes.push("Computed from the mean of all clear summer days; the date choice does not apply.");
  if (state.variable === "built") notes.push("Land cover from 2021; the date choice does not apply.");
  $("detail-note").textContent = notes.join(" ");
}

/* ---------------- selected cell ---------------- */

let cellChart = null;
let scatter = null;

function selectCell(id, pan) {
  state.selected = id;
  restyle();
  const layer = layerById.get(id);
  if (pan && layer) map.fitBounds(layer.getBounds(), { maxZoom: 14, padding: [40, 40] });
  renderCell();
  updateScatterHighlight();
}

function renderCell() {
  const f = state.byId.get(state.selected);
  if (!f) return;
  const p = f.properties;
  const spot = p.spot === "hot" ? '<span class="tag tag-hot">Hot spot</span>' : p.spot === "cold" ? '<span class="tag tag-cold">Cold spot</span>' : "";
  const prio = p.prio ? '<span class="tag tag-prio">&gt; 1 °C hotter than expected</span>' : "";
  const i = dateIdx();
  const heat = i == null ? p.anom : p.a[i];
  $("cell-details").innerHTML = `
    <div class="cell-head"><b>Cell ${p.id}</b> ${spot} ${prio}</div>
    <dl class="kv">
      <div><dt>Surface heat (${esc(formatDate(state.date === "mean" ? "mean" : state.summary.dates[i]))})</dt><dd>${signed(heat, 1, " °C")}</dd></div>
      <div><dt>Mean summer surface temperature</dt><dd>${fixed(p.lst, 1)} °C</dd></div>
      <div><dt>Vegetation (NDVI)</dt><dd>${fixed(i == null ? p.ndvi : p.v[i], 2)}</dd></div>
      <div><dt>Built-up · trees · water</dt><dd>${pct(p.built)} · ${pct(p.tree)} · ${pct(p.water)}</dd></div>
      <div><dt>Expected from vegetation and built-up</dt><dd>${signed(p.fit, 1, " °C")}</dd></div>
      <div><dt>Hotter (+) or cooler (−) than expected</dt><dd>${signed(p.res, 1, " °C")}</dd></div>
      <div><dt>Clear observations</dt><dd>${p.n} of ${state.summary.dates.length} days</dd></div>
    </dl>
    ${p.inside < 1 ? `<p class="note">Edge cell: ${pct(p.inside)} lies inside the city.</p>` : ""}`;
  renderCellChart(p);
}

function chartColors() {
  const cs = getComputedStyle(document.documentElement);
  return { text: cs.getPropertyValue("--muted").trim(), grid: cs.getPropertyValue("--chart-grid").trim(), ink: cs.getPropertyValue("--text").trim() };
}

function renderCellChart(p) {
  const c = chartColors();
  const labels = state.summary.dates.map((d) => formatDate(d));
  const data = p.a.map((v) => (v == null ? null : v));
  const colors = data.map((v) => rampColor(v ?? 0, VARIABLES.anom.stops));
  cellChart?.destroy();
  cellChart = new Chart($("cell-chart"), {
    type: "bar",
    data: { labels, datasets: [{ data, backgroundColor: colors, borderRadius: 3, barPercentage: 0.8 }] },
    options: {
      animation: false,
      maintainAspectRatio: false,
      plugins: { legend: { display: false }, tooltip: { callbacks: { label: (ctx) => (ctx.raw == null ? "cloud — no observation" : signed(ctx.raw, 1, " °C vs city median")) } } },
      scales: {
        x: { ticks: { display: false }, grid: { display: false } },
        y: { title: { display: true, text: "°C vs city median", color: c.text }, ticks: { color: c.text }, grid: { color: c.grid } },
      },
    },
  });
}

/* ---------------- scatter ---------------- */

function scatterData() {
  const i = dateIdx();
  const pts = [];
  for (const f of state.cells) {
    const p = f.properties;
    const y = i == null ? p.anom : p.a[i];
    const x = state.scatterX === "built" ? p.built : i == null ? p.ndvi : p.v[i];
    if (y == null || x == null) continue;
    pts.push({ x, y, id: p.id });
  }
  return pts;
}

function renderScatter() {
  const c = chartColors();
  const pts = scatterData();
  const fit = fitLine(pts.map((q) => q.x), pts.map((q) => q.y));
  const xs = pts.map((q) => q.x);
  const lo = Math.min(...xs);
  const hi = Math.max(...xs);
  const line = fit ? [{ x: lo, y: fit.intercept + fit.slope * lo }, { x: hi, y: fit.intercept + fit.slope * hi }] : [];
  const isBuilt = state.scatterX === "built";
  $("scatter-x-label").textContent = isBuilt ? "built-up share" : "vegetation";
  scatter?.destroy();
  scatter = new Chart($("scatter"), {
    type: "scatter",
    data: {
      datasets: [
        { label: "Selected cell", data: [], pointRadius: 7, pointBackgroundColor: "rgba(0,0,0,0)", pointBorderColor: c.ink, pointBorderWidth: 2.5, order: 0 },
        { label: "Grid cells", data: pts, pointRadius: 2.2, pointHoverRadius: 5, pointBackgroundColor: "rgba(120,130,150,0.45)", pointBorderWidth: 0, order: 2 },
        { label: "Fitted line", data: line, type: "line", borderColor: "#c0392b", borderWidth: 2, pointRadius: 0, order: 1 },
      ],
    },
    options: {
      animation: false,
      maintainAspectRatio: false,
      onClick: (_e, els) => {
        const hit = els.find((e) => e.datasetIndex === 1);
        if (hit) selectCell(pts[hit.index].id, true);
      },
      plugins: {
        legend: { display: false },
        tooltip: {
          filter: (item) => item.datasetIndex === 1,
          callbacks: { label: (ctx) => `Cell ${ctx.raw.id}: ${isBuilt ? pct(ctx.raw.x) : `NDVI ${fixed(ctx.raw.x, 2)}`}, ${signed(ctx.raw.y, 1, " °C")}` },
        },
      },
      scales: {
        x: { title: { display: true, text: isBuilt ? "Built-up share" : "Vegetation (NDVI)", color: c.text }, ticks: { color: c.text, callback: (v) => (isBuilt ? pct(v) : v) }, grid: { color: c.grid } },
        y: { title: { display: true, text: "Surface heat (°C vs city median)", color: c.text }, ticks: { color: c.text }, grid: { color: c.grid } },
      },
    },
  });
  $("scatter-note").textContent = fit
    ? `${fit.n} cells, ${formatDate(state.date === "mean" ? "mean" : state.summary.dates[dateIdx()])}. Fitted line: ${isBuilt ? `${signed(fit.slope / 10, 1, " °C")} per 10 percentage points of built-up land` : `${signed(fit.slope / 10, 1, " °C")} per 0.1 NDVI`}; R² = ${fit.r2.toFixed(2)}.`
    : "";
  updateScatterHighlight();
}

function updateScatterHighlight() {
  if (!scatter) return;
  const pt = scatter.data.datasets[1].data.find((q) => q.id === state.selected);
  scatter.data.datasets[0].data = pt ? [pt] : [];
  scatter.update("none");
}

/* ---------------- results ---------------- */

function renderResults() {
  const s = state.summary;
  const m = s.models;
  const row = (label, k) => `<tr><th scope="row">${label}</th><td>${m[k].r2.toFixed(2)}</td><td>${m[k].r2_blocked_cv.toFixed(2)}</td></tr>`;
  $("results").innerHTML = `
    <p>${s.dates.length} clear summer days, ${s.cells} cells of 500 m. Surface heat is strongly clustered (Moran's I = ${s.morans_i.toFixed(2)}).</p>
    <table class="results-table">
      <thead><tr><th scope="col">Explaining surface heat by</th><th scope="col">R²</th><th scope="col">R² on held-out areas</th></tr></thead>
      <tbody>${row("Vegetation alone", "ndvi")}${row("Built-up share alone", "built")}${row("Both", "ndvi_built")}</tbody>
    </table>
    <p>${s.hotspots.hot} cells form hot spots and ${s.hotspots.cold} cold spots; ${s.hotspots.hot_low_ndvi} of the hot-spot cells have below-median vegetation. ${s.hotspots.hotter_than_expected_1c} cells are more than 1 °C hotter than their vegetation and built-up share predict.</p>`;
}

/* ---------------- controls ---------------- */

function fillDates() {
  const sel = $("date-select");
  for (const [i, d] of state.summary.dates.entries()) {
    const o = document.createElement("option");
    o.value = String(i);
    const p = state.summary.per_date[i];
    o.textContent = `${formatDate(d)} — city median ${p.city_median_lst.toFixed(0)} °C`;
    sel.appendChild(o);
  }
}

function refreshAll() {
  restyle();
  drawPixels();
  renderLegend();
  renderNotes();
  renderScatter();
  if (state.selected) renderCell();
}

document.querySelectorAll('input[name="var"]').forEach((r) => r.addEventListener("change", () => { state.variable = r.value; refreshAll(); }));
document.querySelectorAll('input[name="detail"]').forEach((r) => r.addEventListener("change", () => { state.detail = r.value; refreshAll(); }));
document.querySelectorAll('input[name="sx"]').forEach((r) => r.addEventListener("change", () => { state.scatterX = r.value; renderScatter(); }));
$("date-select").addEventListener("change", (e) => { state.date = e.target.value; refreshAll(); });
$("opacity").addEventListener("input", (e) => { state.opacity = Number(e.target.value); restyle(); pixelLayer?.setOpacity(state.opacity); });
$("chk-priority").addEventListener("change", (e) => { state.priority = e.target.checked; drawPriority(); renderLegend(); });
$("btn-about").addEventListener("click", () => $("about-dialog").showModal());
$("btn-downloads").addEventListener("click", () => $("data-dialog").showModal());
for (const d of document.querySelectorAll("dialog")) d.addEventListener("click", (e) => { if (e.target === d) d.close(); });

function applyThemeLabel() {
  $("btn-theme").textContent = document.documentElement.dataset.theme === "light" ? "Dark mode" : "Light mode";
}
$("btn-theme").addEventListener("click", () => {
  const next = document.documentElement.dataset.theme === "light" ? "dark" : "light";
  document.documentElement.dataset.theme = next;
  localStorage.setItem("uhi-theme", next);
  applyThemeLabel();
  renderScatter();
  if (state.selected) renderCell();
});
applyThemeLabel();

/* ---------------- start ---------------- */

async function loadJson(url) {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`${url}: ${r.status}`);
  return r.json();
}

(async function init() {
  try {
    const [summary, cells, boundary] = await Promise.all([loadJson("data/summary.json"), loadJson("data/cells_500m.geojson"), loadJson("data/boundary.geojson")]);
    state.summary = summary;
    state.cells = cells.features;
    for (const f of state.cells) state.byId.set(f.properties.id, f);
    boundaryLayer = L.geoJSON(boundary, { style: { color: "#111", weight: 2, fill: false }, interactive: false }).addTo(map);
    map.fitBounds(boundaryLayer.getBounds(), { padding: [10, 10] });
    drawGrid();
    boundaryLayer.bringToFront();
    fillDates();
    renderResults();
    refreshAll();
    // start with the hottest cell selected, so the detail panel shows something useful
    const hottest = state.cells.filter((f) => f.properties.anom != null).sort((a, b) => b.properties.anom - a.properties.anom)[0];
    if (hottest) selectCell(hottest.properties.id, false);
    $("map-status").hidden = true;
  } catch (err) {
    $("map-status").textContent = "The data could not be loaded. Serve this folder over HTTP (see README).";
    console.error(err);
  }
})();

export { valueOf, NDVI_STOPS, BUILT_STOPS };

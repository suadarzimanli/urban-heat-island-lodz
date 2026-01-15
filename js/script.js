const map = L.map('map', { preferCanvas: true }).setView([51.759, 19.456], 12);

L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
  maxZoom: 19,
  attribution: '&copy; OpenStreetMap contributors'
}).addTo(map);

function diagLog(...args) { console.log("[UHI-DIAG]", ...args); }
function diagErr(...args) { console.error("[UHI-DIAG]", ...args); }

window.addEventListener("unhandledrejection", (e) => diagErr("Unhandled promise rejection:", e.reason));
window.addEventListener("error", (e) => diagErr("Window error:", e.message, e.error));

diagLog("Leaflet version:", L?.version);
diagLog("parseGeoraster exists:", typeof parseGeoraster);

const state = {
  cityLayer: null,
  gridLayer: null,

  ndviTifLayer: null,
  lstTifLayer: null,

  gridStatsLookup: null,
  gridGeojson: null,

  ndviLegendRanges: {
    1: "< 0.10",
    2: "0.10 – 0.30",
    3: "0.30 – 0.50",
    4: "0.50 – 0.70",
    5: "≥ 0.70"
  },
  lstLegendRanges: {
    2: "Coolest areas",
    3: "Moderately cool",
    4: "Hot",
    5: "Hottest areas"
  },
  
  ndviOpacityValue: 0.70,
  lstOpacityValue: 0.65,
};

const el = (id) => document.getElementById(id);

function setCheckbox(id, checked) {
  const c = el(id);
  if (c) c.checked = checked;
}

function legendTitle(txt) {
  return `<div style="font-weight:800;color:rgba(255,255,255,0.85);margin-bottom:6px">${txt}</div>`;
}
function legendRow(color, label) {
  return `
    <div class="legend-row">
      <div class="legend-swatch" style="background:${color}"></div>
      <div>${label}</div>
    </div>
  `;
}

function setLegend(mode) {
  const legend = el('legend');
  if (!legend) return;

  if (!mode) {
    legend.innerHTML = `<div class="legend-hint">Turn on NDVI/LST to see legend.</div>`;
    return;
  }

  if (mode === "ndvi") {
    legend.innerHTML = [
      legendTitle("NDVI classes (raster)"),
      legendRow(ndviClassColor(1), `Class 1: ${state.ndviLegendRanges[1]}`),
      legendRow(ndviClassColor(2), `Class 2: ${state.ndviLegendRanges[2]}`),
      legendRow(ndviClassColor(3), `Class 3: ${state.ndviLegendRanges[3]}`),
      legendRow(ndviClassColor(4), `Class 4: ${state.ndviLegendRanges[4]}`),
      legendRow(ndviClassColor(5), `Class 5: ${state.ndviLegendRanges[5]}`),
      `<div class="legend-hint">0 / NoData = transparent</div>`
    ].join("");
  }

  if (mode === "lst") {
    legend.innerHTML = [
      legendTitle("LST classes (raster)"),
      legendRow(lstClassColor(2), `Class 2: ${state.lstLegendRanges[2]}`),
      legendRow(lstClassColor(3), `Class 3: ${state.lstLegendRanges[3]}`),
      legendRow(lstClassColor(4), `Class 4: ${state.lstLegendRanges[4]}`),
      legendRow(lstClassColor(5), `Class 5: ${state.lstLegendRanges[5]}`),
      `<div class="legend-hint">Other values / NoData = transparent</div>`
    ].join("");
  }
}

el('toggleSidebar')?.addEventListener('click', () => {
  const app = document.querySelector('.app');
  if (!app) return;

  app.classList.toggle('sidebar-collapsed');

  // Leaflet needs to recalc after layout changes
  setTimeout(() => {
    map.invalidateSize(true);
  }, 260);
});

el('btnAbout')?.addEventListener('click', () => el('aboutModal').style.display = '');
el('btnCloseAbout')?.addEventListener('click', () => el('aboutModal').style.display = 'none');
el('aboutModal')?.addEventListener('click', (e) => {
  if (e.target.id === 'aboutModal') el('aboutModal').style.display = 'none';
});

async function loadCity() {
  if (state.cityLayer) return state.cityLayer;

  const city = await fetch('data/lodz_city.geojson').then(r => r.json());
  state.cityLayer = L.geoJSON(city, {
    style: { color: 'black', weight: 2, fill: false }
  }).addTo(map);

  return state.cityLayer;
}

async function unloadCity() {
  if (!state.cityLayer) return;
  map.removeLayer(state.cityLayer);
  state.cityLayer = null;
}

async function loadGridStats() {
  if (state.gridLayer) return state.gridLayer;

  const [gridData, csvText] = await Promise.all([
    fetch('data/lodz_grid.geojson').then(r => r.json()),
    fetch('data/ndvi_lst_grid_stats.csv').then(r => r.text())
  ]);

  const csv = Papa.parse(csvText, { header: true }).data;

  const lookup = {};
  csv.forEach(row => {
    const key = String(row.OBJECTID_1 || "").trim();
    if (key) lookup[key] = row;
  });

  state.gridStatsLookup = lookup;
  state.gridGeojson = gridData;

  state.gridLayer = L.geoJSON(gridData, {
    style: (feature) => {
      const id = String(feature?.properties?.OBJECTID_1 ?? "").trim();
      const props = lookup[id];
      const ndviMedian = props?.MEDIAN;

      return {
        color: 'rgba(0,0,0,0.70)',
        weight: 1.35,
        dashArray: '2,2',
        fillOpacity: 0.78,
        fillColor: getNDVIColorSameAsRaster(ndviMedian)
      };
    },
    onEachFeature: (feature, layer) => {
      const id = String(feature?.properties?.OBJECTID_1 ?? "").trim();
      const props = lookup[id];

      layer.on('mouseover', () => {
        layer.setStyle({ weight: 2.3, color: 'rgba(255,255,255,0.9)', dashArray: null });
      });
      layer.on('mouseout', () => state.gridLayer.resetStyle(layer));

      if (props) {
        const ndvi = safeNum(props.MEDIAN, 3);
        const lst  = safeNum(props.MEAN_1, 2);
        layer.bindPopup(`
          <div style="min-width:220px">
            <div style="font-weight:800;margin-bottom:6px">Grid cell ${id}</div>
            <div><b>NDVI (median):</b> ${ndvi}</div>
            <div><b>LST (mean):</b> ${lst} °C</div>
          </div>
        `);
      } else {
        layer.bindPopup(`<b>Grid cell ${id}</b><div>No CSV stats found.</div>`);
      }
    }
  }).addTo(map);

  return state.gridLayer;
}

async function unloadGridStats() {
  if (!state.gridLayer) return;
  map.removeLayer(state.gridLayer);
  state.gridLayer = null;
}

function safeNum(x, digits) {
  const v = parseFloat(x);
  if (!Number.isFinite(v)) return "—";
  return v.toFixed(digits);
}

function ndviValueToClass(ndviValue) {
  const v = parseFloat(ndviValue);
  if (!Number.isFinite(v)) return 0;
  if (v >= 0.7) return 5;
  if (v >= 0.5) return 4;
  if (v >= 0.3) return 3;
  if (v >= 0.1) return 2;
  return 1;
}
function getNDVIColorSameAsRaster(ndviValue) {
  const cls = ndviValueToClass(ndviValue);
  return ndviClassColor(cls) || "rgba(255,255,255,0.06)";
}

function ndviClassColor(cls) {
  switch (cls) {
    case 1: return "#440154";
    case 2: return "#3b528b";
    case 3: return "#21918c";
    case 4: return "#5ec962";
    case 5: return "#fde725";
    default: return null;
  }
}

function lstClassColor(cls) {
  switch (cls) {
    case 2: return "#2c7bb6";
    case 3: return "#abd9e9";
    case 4: return "#fdae61";
    case 5: return "#d7191c";
    default: return null;
  }
}

function hexToRgb(hex) {
  const h = String(hex || "").replace("#", "");
  if (h.length !== 6) return null;
  return {
    r: parseInt(h.slice(0, 2), 16),
    g: parseInt(h.slice(2, 4), 16),
    b: parseInt(h.slice(4, 6), 16)
  };
}

function ndviClassToRgb(cls) {
  switch (cls) {
    case 1: return hexToRgb("#440154");
    case 2: return hexToRgb("#3b528b");
    case 3: return hexToRgb("#21918c");
    case 4: return hexToRgb("#5ec962");
    case 5: return hexToRgb("#fde725");
    default: return null;
  }
}

function lstClassToRgb(cls) {
  switch (cls) {
    case 2: return hexToRgb("#2c7bb6");
    case 3: return hexToRgb("#abd9e9");
    case 4: return hexToRgb("#fdae61");
    case 5: return hexToRgb("#d7191c");
    default: return null;
  }
}

function renderGeorasterToDataUrl(georaster, type, maxWidth = 1400) {
  const srcW = georaster.width;
  const srcH = georaster.height;
  const band = georaster.values?.[0];
  const nodata = georaster.noDataValue;

  if (!band) throw new Error("GeoTIFF band values missing (values[0]).");

  const scale = Math.min(1, maxWidth / srcW);
  const outW = Math.max(1, Math.round(srcW * scale));
  const outH = Math.max(1, Math.round(srcH * scale));

  const canvas = document.createElement("canvas");
  canvas.width = outW;
  canvas.height = outH;

  const ctx = canvas.getContext("2d");
  const img = ctx.createImageData(outW, outH);
  const data = img.data;

  for (let y = 0; y < outH; y++) {
    const srcY = Math.min(srcH - 1, Math.floor(y / scale));
    const rowArr = band[srcY];
    if (!rowArr) continue;

    for (let x = 0; x < outW; x++) {
      const srcX = Math.min(srcW - 1, Math.floor(x / scale));

      let v = rowArr[srcX];

      if (v === nodata || v === undefined || v === null) v = null;

      let rgb = null;
      if (v !== null) {
        const cls = Math.round(Number(v));

        if (type === "ndvi") {
          if (Number.isFinite(cls) && cls !== 0) rgb = ndviClassToRgb(cls);
        } else if (type === "lst") {
          if (Number.isFinite(cls) && cls >= 2 && cls <= 5) rgb = lstClassToRgb(cls);
        }
      }

      const i = (y * outW + x) * 4;
      if (!rgb) {
        data[i + 3] = 0; 
      } else {
        data[i] = rgb.r;
        data[i + 1] = rgb.g;
        data[i + 2] = rgb.b;
        data[i + 3] = 255;
      }
    }
  }

  ctx.putImageData(img, 0, 0);
  return canvas.toDataURL("image/png");
}

async function loadClassifiedTifAsOverlay({ url, type }) {
  diagLog("Loading TIFF:", type, url);

  const response = await fetch(url);
  diagLog("Fetch status:", response.status, response.statusText);
  if (!response.ok) throw new Error(`Failed to fetch ${url} (${response.status})`);

  const arrayBuffer = await response.arrayBuffer();
  diagLog("TIFF bytes:", arrayBuffer.byteLength);

  if (typeof parseGeoraster !== "function") {
    throw new Error("parseGeoraster is missing. Include georaster script in HTML.");
  }

  const georaster = await parseGeoraster(arrayBuffer);

  console.log("pixelWidth", georaster.pixelWidth, "pixelHeight", georaster.pixelHeight);

  diagLog("Parsed georaster:", {
    width: georaster.width,
    height: georaster.height,
    xmin: georaster.xmin,
    xmax: georaster.xmax,
    ymin: georaster.ymin,
    ymax: georaster.ymax,
    projection: georaster.projection,
    noDataValue: georaster.noDataValue
  });

  const dataUrl = renderGeorasterToDataUrl(georaster, type, 1400);

  const bounds = [[georaster.ymin, georaster.xmin], [georaster.ymax, georaster.xmax]];

  const overlay = L.imageOverlay(dataUrl, bounds, {
    opacity: (type === "ndvi") ? 0.70 : 0.65,
    interactive: false
  }).addTo(map);

  map.fitBounds(bounds, { padding: [20, 20] });

  diagLog("ImageOverlay added + fitBounds done.");
  return overlay;
}

async function clearRasterState() {
  if (state.ndviTifLayer) map.removeLayer(state.ndviTifLayer);
  if (state.lstTifLayer) map.removeLayer(state.lstTifLayer);

  state.ndviTifLayer = null;
  state.lstTifLayer = null;

  const ndviRow = el('ndviOpacityRow');
  const lstRow = el('lstOpacityRow');
  if (ndviRow) ndviRow.style.display = 'none';
  if (lstRow) lstRow.style.display = 'none';

  setCheckbox('chkNdviTif', false);
  setCheckbox('chkLstTif', false);
  setLegend(null);

  map.invalidateSize(true);
}


async function loadNdviTif() {
  await clearRasterState();
  setCheckbox('chkNdviTif', true);

  const slider = el('ndviOpacity');
  if (slider) slider.value = String(state.ndviOpacityValue);

  state.ndviTifLayer = await loadClassifiedTifAsOverlay({
    url: 'data/NDVI_classified.tif',
    type: 'ndvi'
  });
  state.ndviTifLayer.setOpacity(state.ndviOpacityValue);

  const row = el('ndviOpacityRow');
  if (row) row.style.display = '';
  setLegend("ndvi");
}

async function unloadNdviTif() {
  if (!state.ndviTifLayer) return;

  map.removeLayer(state.ndviTifLayer);
  state.ndviTifLayer = null;

  const row = el('ndviOpacityRow');
  if (row) row.style.display = 'none';

  setLegend(null);
}

async function loadLstTif() {
  await clearRasterState();
  setCheckbox('chkLstTif', true);

  const slider = el('lstOpacity');
  if (slider) slider.value = String(state.lstOpacityValue);

  state.lstTifLayer = await loadClassifiedTifAsOverlay({
    url: 'data/LST_classified.tif',
    type: 'lst'
  });

  state.lstTifLayer.setOpacity(state.lstOpacityValue);

  const row = el('lstOpacityRow');
  if (row) row.style.display = '';
  setLegend("lst");
}

async function unloadLstTif() {
  if (!state.lstTifLayer) return;

  map.removeLayer(state.lstTifLayer);
  state.lstTifLayer = null;
  const row = el('lstOpacityRow');
  if (row) row.style.display = 'none';

  setLegend(null);
}

el('chkCity')?.addEventListener('change', async (e) => {
  if (e.target.checked) await loadCity();
  else await unloadCity();
});

el('chkGridStats')?.addEventListener('change', async (e) => {
  if (e.target.checked) await loadGridStats();
  else await unloadGridStats();
});

el('chkNdviTif')?.addEventListener('change', async (e) => {
  if (e.target.checked) {
    try { await loadNdviTif(); }
    catch (err) {
      console.error(err);
      alert("Failed to load NDVI GeoTIFF. Check file path and ensure you run via a server.");
      await clearRasterState();
    }
  } else {
    await unloadNdviTif();
    const row = el('ndviOpacityRow');
    if (row) row.style.display = 'none';
  }
});

el('chkLstTif')?.addEventListener('change', async (e) => {
  if (e.target.checked) {
    try { await loadLstTif(); }
    catch (err) {
      console.error(err);
      alert("Failed to load LST GeoTIFF. Check file path and ensure you run via a server.");
      await clearRasterState();
    }
  } else {
    await unloadLstTif();
    const row = el('lstOpacityRow');
    if (row) row.style.display = 'none';
  }
});

el('ndviOpacity')?.addEventListener('input', (e) => {
  const v = parseFloat(e.target.value);
  if (!Number.isFinite(v)) return;
  state.ndviOpacityValue = v;
  if (state.ndviTifLayer) state.ndviTifLayer.setOpacity(v);
});

el('lstOpacity')?.addEventListener('input', (e) => {
  const v = parseFloat(e.target.value);
  if (!Number.isFinite(v)) return;
  state.lstOpacityValue = v;
  if (state.lstTifLayer) state.lstTifLayer.setOpacity(v);
});

async function exportMapPng() {
  const mapEl = document.getElementById("map");
  if (!mapEl) return;

  const canvas = await html2canvas(mapEl, {
    useCORS: true,
    backgroundColor: null,
    scale: 2
  });

  const dataUrl = canvas.toDataURL("image/png");
  const a = document.createElement("a");
  a.href = dataUrl;
  a.download = `lodz_uhi_map_${new Date().toISOString().slice(0,10)}.png`;
  document.body.appendChild(a);
  a.click();
  a.remove();
}

async function showNdviQuick() {  
  const cb = document.getElementById("chkNdviTif");
  if (cb && !cb.checked) {
    cb.checked = true;
    cb.dispatchEvent(new Event("change"));
  }
}

async function showLstQuick() {
  const cb = document.getElementById("chkLstTif");
  if (cb && !cb.checked) {
    cb.checked = true;
    cb.dispatchEvent(new Event("change"));
  }
}

document.getElementById("btnShowNdvi")?.addEventListener("click", showNdviQuick);
document.getElementById("btnShowLst")?.addEventListener("click", showLstQuick);

document.addEventListener("keydown", (e) => {
  if (e.target && (e.target.tagName === "INPUT" || e.target.tagName === "TEXTAREA")) return;

  const k = String(e.key || "").toLowerCase();
  if (k === "n") showNdviQuick();
  if (k === "t") showLstQuick();
});

document.getElementById("btnExportMapPng")?.addEventListener("click", exportMapPng);

function wireRegressionModal() {
  const btnOpen = el("btnShowRegression");
  const modal   = el("regressionModal");
  const btnX    = el("btnCloseRegression");

  if (!btnOpen || !modal || !btnX) {
    diagLog("Regression modal wiring skipped (missing element):", {
      btnShowRegression: !!btnOpen,
      regressionModal: !!modal,
      btnCloseRegression: !!btnX
    });
    return;
  }

  btnOpen.addEventListener("click", () => {
    modal.style.display = "";
  });

  btnX.addEventListener("click", () => {
    modal.style.display = "none";
  });

  modal.addEventListener("click", (e) => {
    if (e.target === modal) modal.style.display = "none";
  });
}

wireRegressionModal();

document.getElementById("btnShowRegression")?.addEventListener("click", () => {
  document.getElementById("regressionModal").style.display = "";
});

document.getElementById("btnCloseRegression")?.addEventListener("click", () => {
  document.getElementById("regressionModal").style.display = "none";
});

document.getElementById("regressionModal")?.addEventListener("click", (e) => {
  if (e.target.id === "regressionModal") {
    e.currentTarget.style.display = "none";
  }
});

(async function init() {
  await loadCity();
  setLegend(null);

  const ndviRow = el('ndviOpacityRow');
  const lstRow = el('lstOpacityRow');
  if (ndviRow) ndviRow.style.display = 'none';
  if (lstRow) lstRow.style.display = 'none';
})();

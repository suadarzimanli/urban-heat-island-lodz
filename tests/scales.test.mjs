import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { ANOM_STOPS, fitLine, formatDate, pct, rampColor, signed } from "../js/scales.js";

test("diverging scale: neutral at zero, ends clamp", () => {
  assert.equal(rampColor(0, ANOM_STOPS), "rgb(230, 230, 226)");
  assert.equal(rampColor(99, ANOM_STOPS), rampColor(6, ANOM_STOPS));
  assert.equal(rampColor(-99, ANOM_STOPS), rampColor(-6, ANOM_STOPS));
  assert.equal(rampColor(null, ANOM_STOPS), null);
  assert.equal(rampColor(Number.NaN, ANOM_STOPS), null);
});

test("signed values use a real minus and no '+0.0'", () => {
  assert.equal(signed(2.345, 1, " °C"), "+2.3 °C");
  assert.equal(signed(-1.25, 1), "−1.3");
  assert.equal(signed(0.01, 1), "0.0");
  assert.equal(signed(null), "—");
  assert.equal(pct(0.973), "97%");
});

test("fitLine recovers slope and R²", () => {
  const xs = [0.1, 0.3, 0.5, 0.7];
  const f = fitLine(xs, xs.map((x) => 12 - 20 * x));
  assert.ok(Math.abs(f.slope + 20) < 1e-9);
  assert.ok(Math.abs(f.r2 - 1) < 1e-9);
  assert.equal(fitLine([1, 2], [1, 2]), null);
});

test("dates are formatted in UTC", () => {
  assert.equal(formatDate("2023-07-09"), "9 Jul 2023");
  assert.equal(formatDate("mean"), "all clear summer days");
});

test("the web data match the analysis: cells, dates and per-date arrays", () => {
  const summary = JSON.parse(readFileSync(new URL("../data/summary.json", import.meta.url), "utf8"));
  const cells = JSON.parse(readFileSync(new URL("../data/cells_500m.geojson", import.meta.url), "utf8")).features;
  assert.ok(cells.length > 1000);
  for (const f of cells) {
    assert.equal(f.properties.a.length, summary.dates.length);
    assert.equal(f.properties.v.length, summary.dates.length);
  }
  const used = cells.filter((f) => f.properties.anom != null).length;
  assert.equal(used, summary.cells);
  for (const d of [...summary.dates, "mean"]) {
    assert.ok(summary.rasters.anom[d], `surface-heat pixels for ${d}`);
    assert.ok(summary.rasters.ndvi[d], `vegetation pixels for ${d}`);
  }
  assert.ok(summary.rasters.built, "built-up pixels");
});

test("pixel colour ramps match the pipeline", () => {
  const py = readFileSync(new URL("../pipeline/export_web.py", import.meta.url), "utf8");
  for (const [v, c] of ANOM_STOPS) assert.ok(py.includes(`(${v}, (${c.join(", ")}))`), `stop ${v}`);
});

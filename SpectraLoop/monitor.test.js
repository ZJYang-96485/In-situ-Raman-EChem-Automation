const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const { buildEchemSeries, buildSessionPayload, raman } = require("./monitor.js");

test("current data view presents EChem only", () => {
  const html = fs.readFileSync(path.join(__dirname, "echem.html"), "utf8");
  const styles = fs.readFileSync(path.join(__dirname, "styles.css"), "utf8");
  const dataView = html.match(/<section id="data-view"[\s\S]*?<\/section>\s*<footer/)[0];
  assert.match(dataView, /class="synchronized-plots"/);
  assert.match(dataView, /id="timeline-canvas"/);
  assert.equal((dataView.match(/<canvas /g) || []).length, 1);
  assert.doesNotMatch(dataView, /spectrum|RAMAN|Raman/);
  assert.match(html, />EChem Data</);
  assert.doesNotMatch(dataView, /aria-label="Synchronized electrochemistry and Raman plots"/);
  assert.doesNotMatch(dataView, /RDE|RPM|Disk|metric-grid|event-list/);
  assert.match(styles, /\.synchronized-plots\s*\{[^}]*grid-template-columns:\s*minmax\(0, 1fr\)/);
});

test("electrochemistry preview has monotonic time and verified trapezoidal charge", () => {
  const records = buildEchemSeries(false);
  assert.equal(records.length, 241);
  assert.equal(records[0].chronocoulometry_c, 0);
  records.slice(1).forEach((record, index) => {
    const previous = records[index];
    assert.ok(record.elapsed_s > previous.elapsed_s);
    const expected = previous.chronocoulometry_c
      + 0.5 * (previous.current_a + record.current_a) * (record.elapsed_s - previous.elapsed_s);
    assert.ok(Math.abs(record.chronocoulometry_c - expected) < 1e-15);
    assert.equal(record.rde_measured_rpm, null);
    assert.equal(record.ir_compensation.state, "withheld");
  });
});

test("RDE preview changes commanded RPM without inventing measured RPM", () => {
  const records = buildEchemSeries(true);
  assert.equal(records.find((record) => record.elapsed_s === 20).rde_commanded_rpm, 400);
  assert.equal(records.find((record) => record.elapsed_s === 95).rde_commanded_rpm, 2500);
  assert.ok(records.every((record) => record.rde_measured_rpm === null));
});

test("EChem export preserves source timing without Raman alignment fields", () => {
  const payload = buildSessionPayload();
  assert.equal(payload.hardware_connected, false);
  assert.equal(payload.timing_quality, "simulated_unverified");
  assert.equal(raman.length, 0);
  assert.equal(payload.raman.length, 0);
  assert.equal("frame_alignments" in payload, false);
  assert.equal("alignment_method" in payload, false);
  assert.ok(payload.electrochemistry.every((record) => Number.isFinite(record.source_timestamp_s)));
  assert.equal(payload.ir_compensation.applied, false);
  assert.equal(payload.protocol_plan.hash, null);
});

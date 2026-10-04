const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const { buildEchemSeries, buildSessionPayload, raman } = require("./monitor.js");

test("synchronized view is exactly two parallel plots without RDE presentation", () => {
  const html = fs.readFileSync(path.join(__dirname, "echem.html"), "utf8");
  const styles = fs.readFileSync(path.join(__dirname, "styles.css"), "utf8");
  const dataView = html.match(/<section id="data-view"[\s\S]*?<\/section>\s*<footer/)[0];
  assert.match(dataView, /class="synchronized-plots"/);
  assert.equal((dataView.match(/<canvas /g) || []).length, 2);
  assert.match(dataView, /id="timeline-canvas"/);
  assert.match(dataView, /id="spectrum-canvas"/);
  assert.doesNotMatch(dataView, /RDE|RPM|Disk|metric-grid|event-list/);
  assert.match(styles, /\.synchronized-plots\s*\{[^}]*grid-template-columns:\s*repeat\(2,/);
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

test("synchronized export preserves source timing and explicit signed alignments", () => {
  const payload = buildSessionPayload();
  assert.equal(payload.hardware_connected, false);
  assert.equal(payload.timing_quality, "simulated_unverified");
  assert.equal(payload.frame_alignments.length, raman.length);
  assert.ok(payload.electrochemistry.every((record) => Number.isFinite(record.source_timestamp_s)));
  assert.ok(payload.raman.every((frame) => Number.isInteger(frame.sequence)));
  assert.ok(payload.frame_alignments.every((link) => Number.isFinite(link.delta_t_s)));
  assert.equal(payload.ir_compensation.applied, false);
  assert.equal(payload.protocol_plan.hash, null);
});

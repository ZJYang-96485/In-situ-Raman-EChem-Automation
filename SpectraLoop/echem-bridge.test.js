const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const { describeSnapshot } = require("./echem-bridge.js");

test("electrochemistry page exposes bridge, storage, and identity controls", () => {
  const html = fs.readFileSync(path.join(__dirname, "echem.html"), "utf8");
  const clientPosition = html.indexOf("bridge-client.js?v=echem-bridge-4");
  const panelPosition = html.indexOf("echem-bridge.js?v=echem-bridge-4");

  assert.match(html, /id="echem-bridge-summary"/);
  assert.match(html, /id="echem-bridge-check-status"/);
  assert.match(html, /id="echem-select-storage"/);
  assert.match(html, /id="echem-discover-instrument"/);
  assert.match(html, /data-echem-confirmation="cell_output_off"/);
  assert.ok(clientPosition >= 0);
  assert.ok(panelPosition > clientPosition);
});

test("unavailable adapter is visibly different from a disconnected bridge", () => {
  const view = describeSnapshot({
    storage: { configured: true, available: true, folder_name: "experiment-data" },
    instrument: {
      target: "CHI 760E",
      discovery_enabled: false,
      blocker: "No verified adapter.",
    },
  });

  assert.equal(view.header, "Local bridge connected · CHI control locked");
  assert.equal(view.storageLabel, "experiment-data");
  assert.equal(view.instrumentLabel, "CHI 760E · adapter unavailable");
  assert.equal(view.instrumentDetail, "No verified adapter.");
  assert.equal(view.discoveryEnabled, false);
});

test("ready worker enables SDK inspection only, never experiment execution", () => {
  const view = describeSnapshot({
    storage: { configured: false, available: false, folder_name: null },
    instrument: { target: "CHI 760E SDK", discovery_enabled: true },
  });

  assert.equal(view.header, "Local bridge connected - SDK worker ready");
  assert.equal(view.instrumentLabel, "CHI 760E SDK - SDK check ready");
  assert.match(view.instrumentDetail, /physical instrument identity is not confirmed/);
  assert.equal(view.discoveryEnabled, true);
});

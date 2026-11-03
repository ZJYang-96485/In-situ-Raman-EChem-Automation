const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const {
  boundedSDKPlan,
  bounded760EPlan,
  describeSnapshot,
  direct760BSequencePlan,
} = require("./echem-bridge.js");

test("electrochemistry page exposes bridge, storage, and identity controls", () => {
  const html = fs.readFileSync(path.join(__dirname, "echem.html"), "utf8");
  const clientPosition = html.indexOf("bridge-client.js?v=echem-bridge-9");
  const panelPosition = html.indexOf("echem-bridge.js?v=echem-bridge-14");

  assert.match(html, /id="echem-bridge-summary"/);
  assert.match(html, /id="echem-bridge-check-status"/);
  assert.match(html, /id="echem-select-storage"/);
  assert.match(html, /id="echem-discover-instrument"/);
  assert.match(html, /id="protocol-model-functions"/);
  assert.match(html, /data-echem-confirmation="cell_output_off"/);
  assert.match(html, /id="chi760d-prepare-run"/);
  assert.match(html, /id="chi760d-start-run"/);
  assert.match(html, /data-chi760d-confirmation="internal_dummy_only"/);
  assert.match(html, /option value="chi760d-dummy"/);
  assert.match(html, /id="chi760e-prepare-run"/);
  assert.match(html, /id="chi760e-start-run"/);
  assert.match(html, /id="chi760e-stop-run"/);
  assert.match(html, /data-chi-sdk-confirmation="cell_output_confirmed_off"/);
  assert.match(html, /data-chi-sdk-confirmation="target_is_selected_model"/);
  assert.ok(clientPosition >= 0);
  assert.ok(panelPosition > clientPosition);
});

test("available function panels show names without implementation labels", () => {
  const setupSource = fs.readFileSync(path.join(__dirname, "app.js"), "utf8");
  const protocolSource = fs.readFileSync(path.join(__dirname, "protocols.js"), "utf8");
  const setupList = setupSource.slice(
    setupSource.indexOf('document.querySelector("#chi-capabilities").innerHTML'),
    setupSource.indexOf("const modelNotes"),
  );
  const protocolList = protocolSource.slice(
    protocolSource.indexOf('document.querySelector("#protocol-model-functions").innerHTML'),
    protocolSource.indexOf("const functionNotes"),
  );

  assert.doesNotMatch(setupList, /<small>|Documented|Derived|Desktop|Verify SDK/);
  assert.doesNotMatch(protocolList, /<small>|badgeLabel|commissioning/);
  assert.match(setupList, /<strong>\$\{technique\}<\/strong>/);
  assert.match(protocolList, /<strong>\$\{definition\.label\}<\/strong>/);
});

test("repository data default is explained without revealing its full path", () => {
  const view = describeSnapshot({
    storage: {
      configured: true,
      available: true,
      folder_name: "data",
      source: "repository_default",
    },
    instrument: {},
  });

  assert.equal(view.storageLabel, "data");
  assert.match(view.storageDetail, /repository data folder automatically/);
  assert.doesNotMatch(view.storageDetail, /C:\\|\/Users\//);
});

test("760D desktop status enables only the explicit internal-dummy workflow", () => {
  const view = describeSnapshot({
    storage: { configured: true, available: true, folder_name: "data" },
    instrument: { target: "CHI 760D", discovery_enabled: false, blocker: "SDK disabled." },
    desktop_760d: {
      state: "ready_for_internal_dummy",
      experiment_control_enabled: true,
      scope: "internal_dummy_cv_only",
      remote_stop_available: false,
    },
  }, "760D");

  assert.equal(view.header, "Local bridge connected - 760D dummy test ready");
  assert.equal(view.dummyReady, true);
  assert.match(view.dummyDetail, /internal-dummy CV/);
});

test("760D completed series reports saved output progress", () => {
  const view = describeSnapshot({
    storage: { configured: true, available: true, folder_name: "data" },
    desktop_760d: {
      experiment_control_enabled: true,
      active: {
        run_label: "run-123",
        running: false,
        state: "completed",
        text_outputs_detected: 2,
        expected_output_count: 2,
      },
    },
  }, "760D");

  assert.match(view.dummyDetail, /completed with 2\/2 text outputs/);
});

test("unavailable adapter is visibly different from a disconnected bridge", () => {
  const view = describeSnapshot({
    storage: { configured: true, available: true, folder_name: "experiment-data" },
    instrument: {
      target: "CHI 760E",
      commissioning_target_model: "760E",
      discovery_enabled: false,
      blocker: "No verified adapter.",
    },
  });

  assert.equal(view.header, "Local bridge connected · CHI control locked");
  assert.equal(view.storageLabel, "experiment-data");
  assert.equal(view.instrumentLabel, "CHI 760E - adapter unavailable");
  assert.equal(view.instrumentDetail, "No verified adapter.");
  assert.equal(view.discoveryEnabled, false);
});

test("ready worker enables SDK inspection only, never experiment execution", () => {
  const view = describeSnapshot({
    storage: { configured: false, available: false, folder_name: null },
    instrument: {
      target: "CHI 760E SDK",
      commissioning_target_model: "760E",
      discovery_enabled: true,
    },
  });

  assert.equal(view.header, "Local bridge connected - SDK worker ready");
  assert.equal(view.instrumentLabel, "CHI 760E SDK - SDK check ready");
  assert.match(view.instrumentDetail, /physical instrument identity is not confirmed/);
  assert.equal(view.discoveryEnabled, true);
  assert.equal(view.commissioning760EReady, false);
});

test("760E commissioning status exposes only the bounded internal-dummy workflow", () => {
  const view = describeSnapshot({
    storage: { configured: true, available: true, folder_name: "data" },
    instrument: {
      target: "CHI 760E SDK",
      commissioning_target_model: "760E",
      state: "ready_for_internal_dummy",
      discovery_enabled: true,
      experiment_control_enabled: true,
      experiment_scope: "internal_dummy_bounded_cv",
      remote_stop_available: true,
    },
  });

  assert.equal(view.header, "Local bridge connected - 760E dummy CV ready");
  assert.equal(view.commissioning760EReady, true);
  assert.match(view.instrumentLabel, /bounded CV control ready/);
  assert.match(view.commissioning760EDetail, /one bounded internal-dummy CV/);
});

test("single builder CV maps to the exact bounded 760E worker plan", () => {
  const protocol = {
    target_model: "760E",
    protocol_name: "First 760E CV",
    validation: { valid: true },
    ir_compensation: { enabled: false },
    steps: [{
      source_technique: "cv",
      parameters: {
        initial_voltage_v: 0,
        apex1_voltage_v: 0.2,
        apex2_voltage_v: -0.2,
        final_voltage_v: 0,
        scan_rate_v_s: 0.05,
        step_size_v: 0.002,
        cycles: 1,
      },
    }],
  };

  assert.deepEqual(bounded760EPlan(protocol), {
    target_model: "760E",
    initial_potential_v: 0,
    high_potential_v: 0.2,
    low_potential_v: -0.2,
    initial_scan_direction: "positive",
    scan_rate_v_s: 0.05,
    potential_step_v: 0.002,
    quiet_time_s: 0,
    sweep_segments: 2,
  });
  assert.throws(
    () => bounded760EPlan({ ...protocol, ir_compensation: { enabled: true } }),
    /Disable iR compensation/,
  );
  assert.throws(
    () => bounded760EPlan({ ...protocol, steps: [...protocol.steps, protocol.steps[0]] }),
    /exactly one CV step/,
  );
});

test("single builder CV maps to the exact bounded 760B worker plan", () => {
  const protocol = {
    target_model: "760B",
    protocol_name: "First 760B CV",
    validation: { valid: true },
    ir_compensation: { enabled: false },
    steps: [{
      source_technique: "cv",
      parameters: {
        initial_voltage_v: 0,
        apex1_voltage_v: 0.2,
        apex2_voltage_v: -0.2,
        final_voltage_v: 0,
        scan_rate_v_s: 0.05,
        step_size_v: 0.002,
        cycles: 1,
      },
    }],
  };

  assert.deepEqual(boundedSDKPlan(protocol, "760B"), {
    target_model: "760B",
    initial_potential_v: 0,
    high_potential_v: 0.2,
    low_potential_v: -0.2,
    initial_scan_direction: "positive",
    scan_rate_v_s: 0.05,
    potential_step_v: 0.002,
    quiet_time_s: 0,
    sweep_segments: 2,
  });
});

test("760B status exposes the direct verified protocol workflow", () => {
  const view = describeSnapshot({
    storage: { configured: true, available: true, folder_name: "data" },
    instrument: {
      target: "CHI 760B SDK",
      commissioning_target_model: "760B",
      state: "ready_for_internal_dummy",
      discovery_enabled: true,
      experiment_control_enabled: true,
      experiment_scope: "validated_760b_sequence",
      remote_stop_available: true,
    },
  }, "760B");

  assert.equal(view.header, "Local bridge connected - 760B protocol runner ready");
  assert.equal(view.instrumentLabel, "CHI 760B SDK - protocol control ready");
  assert.match(view.instrumentDetail, /Wait, CV, and Amperometric i-t sequences/);
  assert.equal(view.discoveryEnabled, true);
  assert.equal(view.commissioning760EReady, true);
  assert.equal(view.dummyReady, false);
});

test("760B builder sequence maps Wait, CV, and amperometric i-t without discarding settings", () => {
  const protocol = {
    target_model: "760B",
    protocol_name: "CV then i-t",
    validation: { valid: true },
    ir_compensation: { enabled: false, mode: "automatic", ru_retry_count: 5 },
    steps: [
      { source_technique: "wait", parameters: { duration_s: 2 } },
      {
        source_technique: "cv",
        parameters: {
          initial_voltage_v: 0,
          apex1_voltage_v: 0.2,
          apex2_voltage_v: -0.2,
          final_voltage_v: 0,
          scan_rate_v_s: 0.05,
          step_size_v: 0.002,
          cycles: 1,
        },
      },
      {
        source_technique: "it",
        parameters: {
          potential_v: 0.1,
          duration_s: 10,
          sample_period_s: 0.5,
          area_cm2: 1,
        },
      },
    ],
  };

  assert.deepEqual(direct760BSequencePlan(protocol), {
    target_model: "760B",
    protocol_name: "CV then i-t",
    ir_compensation: { enabled: false, mode: "automatic", ru_retry_count: 5 },
    steps: [
      { kind: "wait", duration_s: 2 },
      {
        kind: "cv",
        initial_potential_v: 0,
        high_potential_v: 0.2,
        low_potential_v: -0.2,
        initial_scan_direction: "positive",
        scan_rate_v_s: 0.05,
        potential_step_v: 0.002,
        quiet_time_s: 0,
        sweep_segments: 2,
      },
      {
        kind: "it",
        potential_v: 0.1,
        duration_s: 10,
        sample_period_s: 0.5,
        area_cm2: 1,
        quiet_time_s: 0,
      },
    ],
  });
  assert.throws(
    () => direct760BSequencePlan({ ...protocol, ir_compensation: { enabled: true } }),
    /requires iR disabled/,
  );
});

test("selected SDK model remains locked when the local bridge targets another model", () => {
  const view = describeSnapshot({
    storage: { configured: true, available: true, folder_name: "data" },
    instrument: {
      target: "CHI 760B SDK",
      commissioning_target_model: "760B",
      discovery_enabled: true,
      experiment_control_enabled: true,
    },
  }, "760E");

  assert.equal(view.header, "Local bridge connected · CHI control locked");
  assert.equal(view.instrumentLabel, "CHI 760E - selected bridge does not match");
  assert.match(view.instrumentDetail, /configured for CHI 760B/);
  assert.equal(view.discoveryEnabled, false);
  assert.equal(view.commissioning760EReady, false);
});

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const { stepDefinitions } = require("./protocols.js");
const { buildSimulationSession, evaluateIRFractions } = require("./simulator.js");

function irSettings(overrides = {}) {
  return {
    enabled: true,
    mode: "automatic",
    target_compensation_fraction: 0.95,
    max_compensation_trials: 10,
    ru_retry_count: 5,
    ru_repeatability_limit: 0.05,
    ocp_stabilization_s: 5,
    ocp_stabilization_timeout_s: 30,
    ocp_sample_interval_s: 0.25,
    ocp_stability_window: 5,
    ocp_stability_limit_v: 0.005,
    ocp_abs_limit_v: 2.5,
    ru_frequency_hz: 100000,
    ru_ac_amplitude_v: 0.005,
    ru_settle_s: 0.5,
    continue_without_ir_on_ru_failure: true,
    ...overrides,
  };
}

function step(kind, index = 1, parameterOverrides = {}) {
  const definition = stepDefinitions[kind];
  return {
    index,
    name: definition.label,
    source_technique: kind,
    chi_technique: definition.chi,
    adaptation_status: definition.status,
    ir_compensation_eligible: definition.ir,
    parameters: {
      ...Object.fromEntries(definition.fields.map((field) => [field.key, field.value])),
      ...parameterOverrides,
    },
  };
}

function plan(steps, overrides = {}) {
  return {
    schema_version: "0.3",
    protocol_name: "Simulator test",
    execution_enabled: false,
    raman_sync: { policy: "after_equilibration", timing_quality: "software_best_effort" },
    ir_compensation: irSettings(),
    steps,
    ...overrides,
  };
}

test("all protocol techniques have deterministic connection-free execution models", () => {
  const steps = Object.keys(stepDefinitions).map((kind, index) => step(kind, index + 1));
  const session = buildSimulationSession(plan(steps), { scenario: "standard", sessionId: "all-techniques" });
  const represented = new Set(session.electrochemistry.map((record) => record.source_technique));
  Object.keys(stepDefinitions).filter((kind) => kind !== "wait").forEach((kind) => {
    assert.ok(represented.has(kind), `${kind} should produce simulated data`);
  });
  assert.equal(session.hardware_connected, false);
  assert.equal(session.hardware_calls, 0);
  assert.equal(session.execution_mode, "connection_free_simulation");
  assert.ok(session.electrochemistry.every((record) => record.rde_measured_rpm === null));
  session.electrochemistry.slice(1).forEach((record, index) => {
    assert.ok(record.elapsed_s > session.electrochemistry[index].elapsed_s);
  });
});

test("iR simulation stops at 95 percent or accepts the valid tenth trial", () => {
  const standard = buildSimulationSession(plan([step("ca")]), { scenario: "standard", sessionId: "ir-standard" });
  const early = standard.ir_compensation.per_step_results[0];
  assert.equal(early.accepted_trial, 4);
  assert.equal(early.accepted_fraction, 0.95);
  assert.equal(early.trials.length, 4);
  assert.ok(Number.isFinite(early.requested_compensation_ohm));
  assert.equal(
    early.requested_compensation_ohm,
    Number((early.selected_ru_ohm * early.accepted_fraction).toFixed(6)),
  );
  assert.ok(early.trials.every((trial) => trial.ru_attempts_ohm.length === 5));
  assert.ok(early.trials.every((trial) => trial.repeatability_passed));
  assert.equal(standard.electrochemistry[0].ir_compensation.preparation_result_id, early.result_id);

  const strict = buildSimulationSession(plan([step("ca")], {
    ir_compensation: irSettings({ ru_repeatability_limit: 0.001 }),
  }), { scenario: "standard", sessionId: "ir-strict-repeatability" });
  assert.equal(strict.ir_compensation.per_step_results[0].accepted_trial, 4);

  const ceiling = buildSimulationSession(plan([step("ca")]), { scenario: "trial_10", sessionId: "ir-ceiling" });
  const final = ceiling.ir_compensation.per_step_results[0];
  assert.equal(final.accepted_trial, 10);
  assert.equal(final.accepted_fraction, 0.93);
  assert.equal(final.accepted_at_ceiling, true);
  assert.ok(ceiling.electrochemistry.every((record) => record.ir_compensation.hardware_applied === false));
});

test("Ru fallback, acquisition failure, and cleanup failure remain explicit", () => {
  const fallback = buildSimulationSession(plan([step("ca")]), { scenario: "ru_failure", sessionId: "ru-fallback" });
  assert.equal(fallback.terminal_state, "simulated_complete");
  assert.equal(fallback.ir_compensation.per_step_results[0].accepted_trial, null);
  assert.ok(fallback.events.some((event) => event.type === "ir_preparation_failed"));

  const blocked = buildSimulationSession(plan([step("ca")], {
    ir_compensation: irSettings({ continue_without_ir_on_ru_failure: false }),
  }), { scenario: "ru_failure", sessionId: "ru-blocked" });
  assert.equal(blocked.terminal_state, "simulated_failed");
  assert.match(blocked.run_error, /Final iR trial/);

  const acquisition = buildSimulationSession(plan([step("ca")]), { scenario: "acquisition_failure", sessionId: "acquisition-fault" });
  assert.equal(acquisition.terminal_state, "simulated_failed");
  assert.match(acquisition.run_error, /acquisition failure/);
  assert.equal(acquisition.cleanup_state, "simulated_complete");

  const cleanup = buildSimulationSession(plan([step("ca")]), { scenario: "cleanup_failure", sessionId: "cleanup-fault" });
  assert.equal(cleanup.terminal_state, "simulated_failed");
  assert.equal(cleanup.run_error, null);
  assert.match(cleanup.cleanup_error, /cleanup failure/);
});

test("optional disk RDE remains commanded-only and simulation is EChem-only", () => {
  const session = buildSimulationSession(plan([
    step("levich_rpm_sweep_ca", 1, {
      rpm_values: "400, 900",
      pre_stabilization_s: 1,
      stabilization_s: 1,
      collection_s: 2,
      sample_period_s: 1,
    }),
  ]), { sessionId: "rde" });
  assert.equal(session.optional_disk_rde_demo_enabled, true);
  assert.ok(session.electrochemistry.some((record) => record.rde_commanded_rpm === 900));
  assert.ok(session.electrochemistry.every((record) => record.rde_measured_rpm === null));
  assert.equal(session.raman.length, 0);
  assert.equal(session.instruments.raman.connection, "not_configured");
  assert.equal(session.instruments.raman.simulated, false);
  assert.ok(session.events.some((event) => event.type === "rde_setpoint" && event.detail.includes("measured RPM unavailable")));
});

test("simulated CC uses trapezoidal CA integration without replacing raw current", () => {
  const session = buildSimulationSession(plan([
    step("cc_from_ca", 1, { duration_s: 2, sample_period_s: 1, voltage_v: 0.1 }),
  ], { ir_compensation: irSettings({ enabled: false }) }), { sessionId: "cc-integration" });
  const records = session.electrochemistry;
  assert.equal(records.length, 3);
  records.slice(1).forEach((record, index) => {
    const previous = records[index];
    const expected = previous.chronocoulometry_c
      + 0.5 * (previous.current_a + record.current_a) * (record.elapsed_s - previous.elapsed_s);
    assert.ok(Math.abs(record.chronocoulometry_c - expected) < 1e-15);
    assert.ok(Number.isFinite(record.current_a));
  });
});

test("invalid trial values and invalid protocols cannot be accepted silently", () => {
  const invalidFinal = evaluateIRFractions([...Array(9).fill(0.9), true]);
  assert.equal(invalidFinal.accepted_trial, null);
  assert.match(invalidFinal.failure_reason, /no valid value/);

  const invalidPlan = plan([step("ca", 1, { duration_s: null })]);
  assert.throws(() => buildSimulationSession(invalidPlan), /Duration/);
});

test("electrochemistry page loads the cache-busted simulator before its runner", () => {
  const html = fs.readFileSync(path.join(__dirname, "echem.html"), "utf8");
  const runner = fs.readFileSync(path.join(__dirname, "echem.js"), "utf8");
  const simulatorAsset = "simulator.js?v=echem-simulator-4";
  const runnerAsset = "echem.js?v=echem-simulator-5";

  assert.ok(html.indexOf(simulatorAsset) >= 0);
  assert.ok(html.indexOf(simulatorAsset) < html.indexOf(runnerAsset));
  assert.match(runner, /async function runConnectionFreeSimulation/);
  assert.match(runner, /await ensureSimulationCore\(\)/);
  assert.match(runner, /source\.searchParams\.set\("recovery", Date\.now\(\)\.toString\(\)\)/);
});

test("runner reloads the simulator with a unique URL when its global is missing", async () => {
  const inertElement = { addEventListener() {} };
  let appendedSource = null;
  const context = {
    URL,
    URLSearchParams,
    window: {
      location: {
        href: "https://spectraloop.org/echem.html?view=protocol",
        search: "?view=protocol",
      },
      history: { replaceState() {} },
    },
    document: {
      querySelectorAll() { return []; },
      querySelector() { return inertElement; },
      createElement() { return {}; },
      head: {
        append(script) {
          appendedSource = script.src;
          context.SpectraLoopSimulatorCore = { buildSimulationSession() {} };
          script.onload();
        },
      },
    },
  };
  context.globalThis = context;
  vm.createContext(context);
  vm.runInContext(
    fs.readFileSync(path.join(__dirname, "echem.js"), "utf8"),
    context,
  );

  const recovered = await context.SpectraLoopEchemCore.ensureSimulationCore();

  assert.equal(typeof recovered.buildSimulationSession, "function");
  assert.match(appendedSource, /simulator\.js\?v=echem-simulator-4&recovery=\d+/);
});

test("successful browser simulation is saved and shows its relative folder", async () => {
  const button = { disabled: false, textContent: "Run simulation", addEventListener() {} };
  const builderStatus = { textContent: "" };
  const sessionStatus = { textContent: "" };
  const storageResult = { textContent: "" };
  const storageDetail = { textContent: "" };
  const openButton = { disabled: true, textContent: "Open saved folder", addEventListener() {} };
  const receipt = { classList: { toggle() {} } };
  const inertElement = { addEventListener() {} };
  const session = {
    electrochemistry: [{ elapsed_s: 0 }],
    hardware_connected: false,
    hardware_calls: 0,
    raman: [],
    events: [],
  };
  let loadedSession = null;
  let savedSession = null;
  let openedFolder = null;
  const elements = new Map([
    ["#run-simulation", button],
    ["#simulation-builder-status", builderStatus],
    ["#simulation-session-status", sessionStatus],
    [".simulation-storage-receipt", receipt],
    ["#simulation-storage-result", storageResult],
    ["#simulation-storage-detail", storageDetail],
    ["#open-simulation-folder", openButton],
    ["#simulation-scenario", { value: "standard" }],
    ["#protocol-view", inertElement],
  ]);
  const context = {
    URL,
    URLSearchParams,
    window: {
      location: { href: "https://spectraloop.org/echem.html?view=protocol", search: "?view=protocol" },
      history: { replaceState() {} },
    },
    document: {
      querySelectorAll() { return []; },
      querySelector(selector) { return elements.get(selector) || inertElement; },
    },
    SpectraLoopProtocolCore: {
      buildValidatedPlan() { return { protocol_name: "EChem test", validation: { valid: true, errors: [] } }; },
    },
    SpectraLoopSimulatorCore: {
      buildSimulationSession() { return session; },
    },
    SpectraLoopMonitorCore: {
      loadSimulationSession(value) { loadedSession = value; },
    },
    SpectraLoopEchemBridgeCore: {
      getClient() {
        return {
          async saveSimulation(value) {
            savedSession = value;
            return { simulation: { folder: "simulations/2026-10-19/EChem test/trial-001" } };
          },
          async openSimulationFolder(folder) {
            openedFolder = folder;
          },
        };
      },
    },
  };
  context.globalThis = context;
  vm.createContext(context);
  vm.runInContext(fs.readFileSync(path.join(__dirname, "echem.js"), "utf8"), context);

  await context.SpectraLoopEchemCore.runConnectionFreeSimulation();

  assert.equal(loadedSession, session);
  assert.equal(savedSession, session);
  assert.match(builderStatus.textContent, /saved in simulations\/2026-10-19\/EChem test\/trial-001/);
  assert.equal(sessionStatus.textContent, "Saved in simulations/2026-10-19/EChem test/trial-001");
  assert.equal(storageResult.textContent, "simulations/2026-10-19/EChem test/trial-001");
  assert.equal(openButton.disabled, false);
  await context.SpectraLoopEchemCore.openSavedSimulationFolder();
  assert.equal(openedFolder, "simulations/2026-10-19/EChem test/trial-001");
  assert.equal(storageDetail.textContent, "Opened this trial in Windows File Explorer.");
  assert.equal(button.disabled, false);
  assert.equal(button.textContent, "Run simulation");
});

test("classic simulator script can execute again after its global is removed", () => {
  const source = fs.readFileSync(path.join(__dirname, "simulator.js"), "utf8");
  const context = {};
  vm.createContext(context);

  vm.runInContext(source, context);
  assert.equal(
    typeof context.SpectraLoopSimulatorCore.buildSimulationSession,
    "function",
  );

  delete context.SpectraLoopSimulatorCore;
  vm.runInContext(source, context);

  assert.equal(
    typeof context.SpectraLoopSimulatorCore.buildSimulationSession,
    "function",
  );
});

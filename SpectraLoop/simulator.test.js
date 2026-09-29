const test = require("node:test");
const assert = require("node:assert/strict");

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

test("optional disk RDE remains commanded-only and Raman links keep raw clocks", () => {
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
  assert.ok(session.raman.every((frame) => Number.isFinite(frame.source_timestamp_s)));
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

const test = require("node:test");
const assert = require("node:assert/strict");

const { finiteNumber, restoreSavedSteps, stepDefinitions, validatePlan } = require("./protocols.js");

function validPlan(step) {
  return {
    protocol_name: "offline validation",
    raman_sync: { policy: "after_equilibration" },
    ir_compensation: {
      enabled: false,
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
    },
    steps: [step],
  };
}

test("blank and non-finite numeric input cannot silently become zero", () => {
  assert.equal(finiteNumber(""), null);
  assert.equal(finiteNumber("   "), null);
  assert.equal(finiteNumber("not a number"), null);
  assert.equal(finiteNumber("0"), 0);
});

test("saved plans reject unknown steps and malformed parameters instead of dropping or defaulting them", () => {
  assert.throws(
    () => restoreSavedSteps({ steps: [{ source_technique: "future-mode", name: "unknown", parameters: {} }] }),
    /unknown technique/,
  );
  assert.throws(
    () => restoreSavedSteps({ steps: [{ source_technique: "ca", name: "CA", parameters: "not-an-object" }] }),
    /invalid parameters/,
  );
});

test("validation uses exported source_technique and accepts a valid CA step", () => {
  const result = validatePlan(validPlan({
    name: "CA hold",
    source_technique: "ca",
    adaptation_status: "libec",
    parameters: { voltage_v: 0.1, duration_s: 10, sample_period_s: 1, area_cm2: 1 },
  }));
  assert.deepEqual(result.errors, []);
});

test("every default technique passes and every numeric field becomes blocking when absent", () => {
  Object.entries(stepDefinitions).forEach(([kind, definition]) => {
    const parameters = Object.fromEntries(definition.fields.map((field) => [field.key, field.value]));
    const step = {
      name: definition.label,
      source_technique: kind,
      adaptation_status: definition.status,
      parameters,
    };
    const valid = validatePlan(validPlan(step));
    assert.deepEqual(valid.errors, [], `${kind} defaults should validate`);

    definition.fields.filter((field) => field.type === "number").forEach((field) => {
      const missing = validatePlan(validPlan({
        ...step,
        parameters: { ...parameters, [field.key]: null },
      }));
      assert.ok(
        missing.errors.some((message) => message.includes(field.label)),
        `${kind}.${field.key} should be required`,
      );
    });
  });
});

test("missing numeric values and unknown techniques are blocking errors", () => {
  const missing = validatePlan(validPlan({
    name: "CA hold",
    source_technique: "ca",
    adaptation_status: "libec",
    parameters: { voltage_v: 0.1, duration_s: null, sample_period_s: 1, area_cm2: 1 },
  }));
  assert.ok(missing.errors.some((message) => message.includes("Duration")));

  const unknown = validatePlan(validPlan({
    name: "unknown",
    source_technique: "not-real",
    adaptation_status: "libec",
    parameters: {},
  }));
  assert.ok(unknown.errors.some((message) => message.includes("unrecognized")));
});

test("range direction, sample timing, and RPM list failures are not silent", () => {
  const range = validatePlan(validPlan({
    name: "CA range",
    source_technique: "ca_range",
    adaptation_status: "libec",
    parameters: {
      start_voltage_v: 0,
      end_voltage_v: 1,
      step_voltage_v: -0.1,
      duration_s: 1,
      sample_period_s: 2,
    },
  }));
  assert.ok(range.errors.some((message) => message.includes("increment")));
  assert.ok(range.errors.some((message) => message.includes("sample period")));

  const missedEndpoint = validatePlan(validPlan({
    name: "CA range",
    source_technique: "ca_range",
    adaptation_status: "libec",
    parameters: {
      start_voltage_v: 0,
      end_voltage_v: 1,
      step_voltage_v: 0.3,
      duration_s: 1,
      sample_period_s: 1,
    },
  }));
  assert.ok(missedEndpoint.errors.some((message) => message.includes("land exactly")));

  const rpm = validatePlan(validPlan({
    name: "RPM sweep",
    source_technique: "levich_rpm_sweep_ca",
    adaptation_status: "libec",
    parameters: {
      voltage_v: 0,
      rpm_values: "400, , 1600",
      pre_stabilization_s: 10,
      stabilization_s: 10,
      collection_s: 20,
      sample_period_s: 1,
      area_cm2: 1,
    },
  }));
  assert.ok(rpm.errors.some((message) => message.includes("RPM staircase")));
});

test("iR policy rejects drift from the fixed 95 percent and ten-trial rules", () => {
  const plan = validPlan({
    name: "CA hold",
    source_technique: "ca",
    adaptation_status: "libec",
    parameters: { voltage_v: 0.1, duration_s: 10, sample_period_s: 1, area_cm2: 1 },
  });
  plan.ir_compensation.enabled = true;
  plan.ir_compensation.target_compensation_fraction = 0.9;
  plan.ir_compensation.max_compensation_trials = 9;
  const result = validatePlan(plan);
  assert.ok(result.errors.some((message) => message.includes("95%")));
  assert.ok(result.errors.some((message) => message.includes("fixed at 10")));
});

test("invalid dormant iR settings and Raman policy still block export", () => {
  const plan = validPlan({
    name: "CA hold",
    source_technique: "ca",
    adaptation_status: "libec",
    parameters: { voltage_v: 0.1, duration_s: 10, sample_period_s: 1, area_cm2: 1 },
  });
  plan.ir_compensation.enabled = false;
  plan.ir_compensation.ru_retry_count = null;
  plan.raman_sync.policy = "unknown";
  const result = validatePlan(plan);
  assert.ok(result.errors.some((message) => message.includes("Ru attempts")));
  assert.ok(result.errors.some((message) => message.includes("Raman synchronization")));
});

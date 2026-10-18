const test = require("node:test");
const assert = require("node:assert/strict");

const {
  MODEL_TECHNIQUE_PROFILES,
  finiteNumber,
  normalizeTargetModel,
  restoreSavedSteps,
  stepDefinitions,
  techniqueAvailableForModel,
  validatePlan,
} = require("./protocols.js");

function validPlan(step) {
  return {
    protocol_name: "offline validation",
    target_model: "760E",
    target_platform: "CHI 760E",
    bench_state: "available",
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

test("760B profile permits only offline wait, CV, and amperometric i-t planning", () => {
  assert.deepEqual(MODEL_TECHNIQUE_PROFILES["760B"], ["wait", "cv", "it"]);
  assert.equal(techniqueAvailableForModel("cv", "CHI 760B"), true);
  assert.equal(techniqueAvailableForModel("it", "760B"), true);
  assert.equal(techniqueAvailableForModel("ca", "760B"), false);
  assert.equal(normalizeTargetModel("chi 760b"), "760B");

  const plan = validPlan({
    name: "CA hold",
    source_technique: "ca",
    adaptation_status: "libec",
    parameters: { voltage_v: 0.1, duration_s: 10, sample_period_s: 1, area_cm2: 1 },
  });
  plan.target_model = "760B";
  plan.target_platform = "CHI 760B";
  const result = validatePlan(plan);
  assert.ok(result.errors.some((message) => message.includes("not documented for CHI 760B")));
});

test("busy bench remains valid for offline planning and blocks unsupported 760B iR", () => {
  const plan = validPlan({
    name: "760B CV",
    source_technique: "cv",
    adaptation_status: "libec",
    parameters: {
      initial_voltage_v: 0,
      apex1_voltage_v: 0.2,
      apex2_voltage_v: -0.2,
      final_voltage_v: 0,
      scan_rate_v_s: 0.05,
      step_size_v: 0.002,
      cycles: 1,
    },
  });
  plan.target_model = "760B";
  plan.target_platform = "CHI 760B";
  plan.bench_state = "busy";
  let result = validatePlan(plan);
  assert.deepEqual(result.errors, []);
  assert.ok(result.warnings.some((message) => message.includes("measurement in progress")));

  plan.ir_compensation.enabled = true;
  result = validatePlan(plan);
  assert.ok(result.errors.some((message) => message.includes("not available") && message.includes("760B")));
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

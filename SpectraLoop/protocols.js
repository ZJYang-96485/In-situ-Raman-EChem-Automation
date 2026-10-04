const stepDefinitions = {
  wait: {
    label: "Wait", status: "orchestration", chi: null, ir: false,
    fields: [{ key: "duration_s", label: "Duration (s)", type: "number", value: 30, min: 0 }],
  },
  ocp: {
    label: "OCP", status: "libec", chi: "OCPT", ir: false,
    fields: [
      { key: "duration_s", label: "Duration (s)", type: "number", value: 300, min: 0.001 },
      { key: "sample_period_s", label: "Sample period (s)", type: "number", value: 0.5, min: 0.001 },
      { key: "area_cm2", label: "Area (cm²)", type: "number", value: 1, min: 0.000001 },
    ],
  },
  cv: {
    label: "CV", status: "libec", chi: "CV", ir: true,
    fields: [
      { key: "initial_voltage_v", label: "Initial potential (V)", type: "number", value: 0 },
      { key: "apex1_voltage_v", label: "High vertex (V)", type: "number", value: 0.2 },
      { key: "apex2_voltage_v", label: "Low vertex (V)", type: "number", value: -0.2 },
      { key: "final_voltage_v", label: "Final potential (V)", type: "number", value: 0 },
      { key: "scan_rate_v_s", label: "Scan rate (V/s)", type: "number", value: 0.05, min: 0.000001 },
      { key: "step_size_v", label: "Potential step (V)", type: "number", value: 0.002, min: 0.000001 },
      { key: "cycles", label: "Cycles", type: "number", value: 1, min: 1, integer: true },
    ],
  },
  it: {
    label: "Amperometric i-t", status: "libec", chi: "i-t", ir: false,
    fields: [
      { key: "potential_v", label: "Potential (V)", type: "number", value: 0 },
      { key: "duration_s", label: "Duration (s)", type: "number", value: 300, min: 0.001 },
      { key: "sample_period_s", label: "Sample period (s)", type: "number", value: 1, min: 0.001 },
      { key: "area_cm2", label: "Area (cm²)", type: "number", value: 1, min: 0.000001 },
    ],
  },
  ca: {
    label: "CA", status: "libec", chi: "CA", ir: true,
    fields: [
      { key: "voltage_v", label: "Potential (V)", type: "number", value: 0 },
      { key: "duration_s", label: "Duration (s)", type: "number", value: 300, min: 0.001 },
      { key: "sample_period_s", label: "Sample period (s)", type: "number", value: 1, min: 0.001 },
      { key: "area_cm2", label: "Area (cm²)", type: "number", value: 1, min: 0.000001 },
    ],
  },
  cc_from_ca: {
    label: "CC (chronocoulometry) from CA", status: "derived", chi: "CA + ∫I dt", ir: true,
    derivedOutputs: ["chronocoulometry_C"],
    fields: [
      { key: "voltage_v", label: "CA potential (V)", type: "number", value: 0 },
      { key: "duration_s", label: "Duration (s)", type: "number", value: 300, min: 0.001 },
      { key: "sample_period_s", label: "Sample period (s)", type: "number", value: 1, min: 0.001 },
      { key: "area_cm2", label: "Area (cm²)", type: "number", value: 1, min: 0.000001 },
    ],
  },
  ca_range: {
    label: "CA range", status: "libec", chi: "CA (expanded)", ir: true,
    fields: [
      { key: "start_voltage_v", label: "Start potential (V)", type: "number", value: -0.1 },
      { key: "end_voltage_v", label: "End potential (V)", type: "number", value: -1.6 },
      { key: "step_voltage_v", label: "Increment (V)", type: "number", value: -0.1 },
      { key: "duration_s", label: "Duration per step (s)", type: "number", value: 300, min: 0.001 },
      { key: "sample_period_s", label: "Sample period (s)", type: "number", value: 1, min: 0.001 },
    ],
  },
  step: {
    label: "Multi-potential STEP", status: "libec", chi: "STEP", ir: false,
    fields: [
      { key: "start_voltage_v", label: "Start potential (V)", type: "number", value: -0.1 },
      { key: "step_voltage_v", label: "Increment (V)", type: "number", value: -0.1 },
      { key: "step_count", label: "Step count", type: "number", value: 5, min: 1, integer: true },
      { key: "step_time_s", label: "Time per step (s)", type: "number", value: 60, min: 0.001 },
      { key: "sample_period_s", label: "Sample period (s)", type: "number", value: 1, min: 0.001 },
    ],
  },
  levich_rpm_sweep_ca: {
    label: "Levich CA RPM sweep", status: "libec", chi: "CA + RDE schedule", ir: true,
    fields: [
      { key: "voltage_v", label: "CA potential (V)", type: "number", value: 0 },
      { key: "rpm_values", label: "RPM staircase", type: "text", value: "400, 900, 1600, 2500" },
      { key: "pre_stabilization_s", label: "Initial stabilization (s)", type: "number", value: 10, min: 0 },
      { key: "stabilization_s", label: "Stabilization after change (s)", type: "number", value: 10, min: 0 },
      { key: "collection_s", label: "Collection per RPM (s)", type: "number", value: 20, min: 0.001 },
      { key: "sample_period_s", label: "CA sample period (s)", type: "number", value: 1, min: 0.001 },
      { key: "area_cm2", label: "Area (cm²)", type: "number", value: 1, min: 0.000001 },
    ],
  },
  eis: {
    label: "EIS", status: "libec", chi: "IMP", ir: false,
    fields: [
      { key: "initial_frequency_hz", label: "Initial frequency (Hz)", type: "number", value: 100000, min: 0.000001 },
      { key: "final_frequency_hz", label: "Final frequency (Hz)", type: "number", value: 0.1, min: 0.000001 },
      { key: "points_per_decade", label: "Points per decade", type: "number", value: 10, min: 1, integer: true },
      { key: "ac_voltage_mv_rms", label: "AC amplitude (mV RMS)", type: "number", value: 10, min: 0.001 },
      { key: "dc_voltage_v", label: "DC potential (V)", type: "number", value: 0 },
    ],
  },
  swv: {
    label: "SWV", status: "libec", chi: "SWV", ir: false,
    fields: [
      { key: "initial_voltage_v", label: "Initial potential (V)", type: "number", value: 0 },
      { key: "final_voltage_v", label: "Final potential (V)", type: "number", value: -0.8 },
      { key: "increment_v", label: "Increment (V)", type: "number", value: 0.004, min: 0.000001 },
      { key: "amplitude_v", label: "Amplitude (V)", type: "number", value: 0.025, min: 0.000001 },
      { key: "frequency_hz", label: "Frequency (Hz)", type: "number", value: 15, min: 0.000001 },
    ],
  },
  impe: {
    label: "Impedance–potential", status: "libec", chi: "IMPE", ir: false,
    fields: [
      { key: "initial_voltage_v", label: "Initial potential (V)", type: "number", value: -0.2 },
      { key: "final_voltage_v", label: "Final potential (V)", type: "number", value: 0.8 },
      { key: "potential_step_v", label: "Potential increment (V)", type: "number", value: 0.05, min: 0.000001 },
      { key: "frequency_hz", label: "Frequency (Hz)", type: "number", value: 1000, min: 0.000001 },
      { key: "ac_voltage_mv_rms", label: "AC amplitude (mV RMS)", type: "number", value: 10, min: 0.001 },
    ],
  },
  cp: {
    label: "Chronopotentiometry", status: "libec", chi: "ISTEP/CPCS", ir: false,
    fields: [
      { key: "current_a", label: "Signed current (A)", type: "number", value: 0.00001 },
      { key: "duration_s", label: "Duration (s)", type: "number", value: 60, min: 0.001 },
      { key: "sample_period_s", label: "Sample period (s)", type: "number", value: 0.5, min: 0.001 },
      { key: "voltage_limit_low_v", label: "Lower potential limit (V)", type: "number", value: -1 },
      { key: "voltage_limit_high_v", label: "Upper potential limit (V)", type: "number", value: 1 },
    ],
  },
  cc_charge: {
    label: "Constant-current charge", status: "derived", chi: "ISTEP/CPCS + integration", ir: false,
    fields: [
      { key: "current_a", label: "Current magnitude (A)", type: "number", value: 0.00001, min: 0.000000001 },
      { key: "duration_s", label: "Maximum duration (s)", type: "number", value: 60, min: 0.001 },
      { key: "sample_period_s", label: "Sample period (s)", type: "number", value: 1, min: 0.001 },
      { key: "voltage_cutoff_v", label: "Upper potential cutoff (V)", type: "number", value: 4.2 },
    ],
  },
  cc_discharge: {
    label: "Constant-current discharge", status: "derived", chi: "ISTEP/CPCS + integration", ir: false,
    fields: [
      { key: "current_a", label: "Current magnitude (A)", type: "number", value: 0.00001, min: 0.000000001 },
      { key: "duration_s", label: "Maximum duration (s)", type: "number", value: 60, min: 0.001 },
      { key: "sample_period_s", label: "Sample period (s)", type: "number", value: 1, min: 0.001 },
      { key: "voltage_cutoff_v", label: "Lower potential cutoff (V)", type: "number", value: 3.0 },
    ],
  },
  lsv: {
    label: "LSV", status: "desktop", chi: "Not in public 760E libec matrix", ir: false,
    fields: [
      { key: "start_voltage_v", label: "Start potential (V)", type: "number", value: 0.2 },
      { key: "end_voltage_v", label: "End potential (V)", type: "number", value: -0.8 },
      { key: "scan_rate_v_s", label: "Scan rate (V/s)", type: "number", value: 0.01, min: 0.000001 },
      { key: "step_size_v", label: "Potential step (V)", type: "number", value: 0.001, min: 0.000001 },
    ],
  },
  geis: {
    label: "Galvanostatic EIS", status: "verify", chi: "IMP mode to verify", ir: false,
    fields: [
      { key: "initial_frequency_hz", label: "Initial frequency (Hz)", type: "number", value: 100000, min: 0.000001 },
      { key: "final_frequency_hz", label: "Final frequency (Hz)", type: "number", value: 1, min: 0.000001 },
      { key: "ac_current_a", label: "AC current RMS (A)", type: "number", value: 0.0001, min: 0.000000001 },
      { key: "dc_current_a", label: "DC current (A)", type: "number", value: 0 },
      { key: "points_per_decade", label: "Points per decade", type: "number", value: 10, min: 1, integer: true },
    ],
  },
};

const presets = {
  levich: {
    name: "Levich CA RPM sweep",
    steps: [{ kind: "levich_rpm_sweep_ca", name: "Levich CA RPM sweep" }],
  },
  "ocp-eis-cv": {
    name: "OCP-EIS-CV",
    steps: [
      { kind: "ocp", name: "OCP before" },
      { kind: "eis", name: "EIS before" },
      { kind: "cv", name: "CV" },
    ],
  },
  "ca-forward-backward": {
    name: "Bulk electrode CA steps with backward",
    steps: [
      { kind: "ocp", name: "OCP before" },
      { kind: "eis", name: "EIS before" },
      { kind: "ca_range", name: "CA forward", values: { start_voltage_v: -0.1, end_voltage_v: -1.6, step_voltage_v: -0.1 } },
      { kind: "ca_range", name: "CA backward", values: { start_voltage_v: -1.6, end_voltage_v: -0.1, step_voltage_v: 0.1 } },
      { kind: "ocp", name: "OCP after" },
      { kind: "eis", name: "EIS after" },
    ],
  },
  "orr-lsv": {
    name: "ORR OCP-LSV",
    steps: [{ kind: "ocp", name: "OCP before" }, { kind: "lsv", name: "ORR LSV" }],
  },
  blank: { name: "Custom CHI 760E protocol", steps: [] },
};

let steps = [];

function newStep(kind, overrides = {}) {
  const definition = stepDefinitions[kind];
  if (!definition) throw new TypeError(`Unknown protocol step kind: ${kind}`);
  if (Object.hasOwn(overrides, "name") && typeof overrides.name !== "string") {
    throw new TypeError("Protocol step name must be a string");
  }
  if (Object.hasOwn(overrides, "values")
      && (overrides.values === null || typeof overrides.values !== "object" || Array.isArray(overrides.values))) {
    throw new TypeError("Protocol step parameters must be an object");
  }
  const values = Object.fromEntries(definition.fields.map((field) => [field.key, field.value]));
  return {
    id: globalThis.crypto?.randomUUID ? globalThis.crypto.randomUUID() : `${Date.now()}-${Math.random()}`,
    kind,
    name: typeof overrides.name === "string" ? overrides.name : definition.label,
    values: { ...values, ...(overrides.values || {}) },
  };
}

function badgeLabel(status) {
  return { libec: "760E libec", derived: "Derived", desktop: "Desktop only", verify: "Verify SDK", orchestration: "Scheduler" }[status];
}

function escapeHtml(value) {
  return String(value).replace(/[&<>'"]/g, (character) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;",
  }[character]));
}

function renderSteps() {
  const list = document.querySelector("#step-list");
  list.innerHTML = steps.map((step, index) => {
    const definition = stepDefinitions[step.kind];
    const fields = definition.fields.map((field) => `
      <label class="field compact-field">
        <span>${field.label}</span>
        <input data-index="${index}" data-key="${field.key}" type="${field.type}" value="${escapeHtml(step.values[field.key])}"
          ${field.min !== undefined ? `min="${field.min}"` : ""} ${field.integer ? 'step="1"' : 'step="any"'} />
      </label>`).join("");
    return `<article class="protocol-step" data-step-id="${step.id}">
      <div class="step-index">${String(index + 1).padStart(2, "0")}</div>
      <div class="step-body">
        <div class="step-heading">
          <div>
            <input class="step-name" data-index="${index}" data-key="name" value="${escapeHtml(step.name)}" aria-label="Step name" />
            <span class="step-mapping">${definition.label} → ${definition.chi || "local action"}</span>
          </div>
          <div class="step-actions">
            <span class="badge ${definition.status}">${badgeLabel(definition.status)}</span>
            ${definition.ir ? '<span class="badge ir">iR planned · verify SDK</span>' : ""}
            <button type="button" data-action="up" data-index="${index}" aria-label="Move step up">↑</button>
            <button type="button" data-action="down" data-index="${index}" aria-label="Move step down">↓</button>
            <button type="button" data-action="duplicate" data-index="${index}" aria-label="Duplicate step">⧉</button>
            <button type="button" data-action="remove" data-index="${index}" aria-label="Remove step">×</button>
          </div>
        </div>
        <div class="step-fields">${fields}</div>
      </div>
    </article>`;
  }).join("") || '<div class="empty-state"><h3>No steps yet</h3><p>Add a CHI technique or load an RDE-derived preset.</p></div>';
  document.querySelector("#step-count").textContent = `${steps.length} ${steps.length === 1 ? "step" : "steps"}`;
  refreshPreview();
}

function finiteNumber(value) {
  if (value === null || value === undefined || (typeof value === "string" && value.trim() === "")) return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function inputNumber(id) {
  return finiteNumber(document.querySelector(`#${id}`).value);
}

function buildPlan() {
  const irEnabled = document.querySelector("#ir-enabled").checked;
  const planSteps = steps.map((step, index) => {
    const definition = stepDefinitions[step.kind];
    const parameters = Object.fromEntries(definition.fields.map((field) => {
      const rawValue = step.values[field.key];
      return [field.key, field.type === "number" ? finiteNumber(rawValue) : String(rawValue ?? "")];
    }));
    return {
      index: index + 1,
      name: step.name,
      source_technique: step.kind,
      chi_technique: definition.chi,
      adaptation_status: definition.status,
      ir_compensation_eligible: definition.ir,
      derived_outputs: definition.derivedOutputs || (["ca", "ca_range", "levich_rpm_sweep_ca"].includes(step.kind) ? ["chronocoulometry_C"] : []),
      parameters,
    };
  });
  const executionSequence = planSteps.flatMap((step) => {
    const actions = [];
    if (irEnabled && step.ir_compensation_eligible) {
      actions.push({ action: "prepare_ir_compensation", for_step: step.index, execution_enabled: false, requires_connection_verification: true });
    }
    actions.push({ action: step.source_technique === "wait" ? "wait" : "run_experiment", for_step: step.index, execution_enabled: false });
    if (irEnabled && step.ir_compensation_eligible) {
      actions.push({ action: "disable_ir_compensation", for_step: step.index, execution_enabled: false, required_even_after_failure: true });
    }
    return actions;
  });
  return {
    schema_version: "0.3",
    protocol_name: document.querySelector("#protocol-name").value.trim(),
    source_reference: "https://github.com/ZJYang-96485/RDE",
    source_platform: "Gamry",
    target_platform: "CHI 760E",
    execution_enabled: false,
    mapping_review_required: true,
    raman_sync: {
      policy: document.querySelector("#raman-sync").value,
      timing_quality: "software_best_effort",
      hardware_trigger_enabled: false,
    },
    ir_compensation: {
      enabled: irEnabled,
      mode: document.querySelector("#ir-mode").value,
      target_compensation_fraction: 0.95,
      max_compensation_trials: inputNumber("ir-max-trials"),
      stop_condition: "confirmed_target_or_trial_ceiling",
      trial_ceiling_behavior: "accept_final_valid_value",
      ru_retry_count: inputNumber("ir-retries"),
      ru_repeatability_limit: inputNumber("ir-repeatability") === null ? null : inputNumber("ir-repeatability") / 100,
      ocp_stabilization_s: inputNumber("ir-ocp-min"),
      ocp_stabilization_timeout_s: inputNumber("ir-ocp-timeout"),
      ocp_sample_interval_s: inputNumber("ir-ocp-sample"),
      ocp_stability_window: inputNumber("ir-ocp-window"),
      ocp_stability_limit_v: inputNumber("ir-ocp-limit") === null ? null : inputNumber("ir-ocp-limit") / 1000,
      ocp_abs_limit_v: inputNumber("ir-ocp-abs"),
      ru_frequency_hz: inputNumber("ir-ru-frequency"),
      ru_ac_amplitude_v: inputNumber("ir-ru-amplitude") === null ? null : inputNumber("ir-ru-amplitude") / 1000,
      ru_settle_s: inputNumber("ir-ru-settle"),
      continue_without_ir_on_ru_failure: document.querySelector("#ir-fallback").checked,
      require_parameter_readback: true,
      parameter_origin: "user-defined 95%/10-trial policy; remaining preparation defaults adapted from ZJYang-96485/RDE",
      prepare_each_eligible_trial: true,
      cleanup: "disable_ir_compensation_and_cell_off",
      requires_installed_sdk_parameter_discovery: true,
      requested_mode_not_hardware_confirmed: true,
    },
    steps: planSteps,
    execution_sequence: executionSequence,
  };
}

function validatePlan(plan) {
  const errors = [];
  const warnings = [];
  if (!plan.protocol_name) errors.push("Add a protocol name.");
  if (!plan.steps.length) errors.push("Add at least one step.");
  if (!["after_equilibration", "before_and_after_experiment", "none"].includes(plan.raman_sync?.policy)) {
    errors.push("Choose a recognized Raman synchronization policy.");
  }
  if (plan.steps.some((step) => step.adaptation_status === "desktop")) {
    warnings.push("LSV is retained from the RDE workflow but is not listed for 760E in the public libec matrix.");
  }
  if (plan.steps.some((step) => step.adaptation_status === "verify")) {
    warnings.push("At least one step requires installed-SDK parameter verification.");
  }
  const ir = plan.ir_compensation;
  if (ir.target_compensation_fraction !== 0.95) errors.push("iR target compensation must remain fixed at 95%.");
  if (ir.max_compensation_trials !== 10) errors.push("The compensation trial ceiling must remain fixed at 10.");
  if (!Number.isInteger(ir.ru_retry_count) || ir.ru_retry_count < 3 || ir.ru_retry_count > 20) errors.push("Ru attempts per trial must be an integer from 3 to 20.");
  if (!Number.isFinite(ir.ru_repeatability_limit) || !(ir.ru_repeatability_limit > 0 && ir.ru_repeatability_limit < 1)) errors.push("Ru repeatability must be greater than 0% and less than 100%.");
  if (!Number.isFinite(ir.ocp_stabilization_s) || ir.ocp_stabilization_s < 0) errors.push("OCP minimum time must be non-negative.");
  if (!Number.isFinite(ir.ocp_stabilization_timeout_s) || !Number.isFinite(ir.ocp_stabilization_s) || ir.ocp_stabilization_timeout_s < ir.ocp_stabilization_s) errors.push("OCP timeout must be at least the OCP minimum time.");
  if (!Number.isFinite(ir.ocp_sample_interval_s) || !Number.isFinite(ir.ocp_stabilization_timeout_s) || !(ir.ocp_sample_interval_s > 0 && ir.ocp_sample_interval_s <= ir.ocp_stabilization_timeout_s)) errors.push("OCP sample period must be positive and no greater than the timeout.");
  if (!Number.isInteger(ir.ocp_stability_window) || ir.ocp_stability_window < 2) errors.push("OCP stability window must be an integer of at least 2.");
  if (!Number.isFinite(ir.ocp_stability_limit_v) || !Number.isFinite(ir.ocp_abs_limit_v) || !(ir.ocp_stability_limit_v > 0 && ir.ocp_abs_limit_v > 0)) errors.push("OCP stability and absolute limits must be positive.");
  if (!Number.isFinite(ir.ru_frequency_hz) || !Number.isFinite(ir.ru_ac_amplitude_v) || !Number.isFinite(ir.ru_settle_s) || !(ir.ru_frequency_hz > 0 && ir.ru_ac_amplitude_v > 0 && ir.ru_settle_s >= 0)) errors.push("Ru frequency/amplitude must be positive and settle time non-negative.");
  if (!["automatic", "positive_feedback", "current_interrupt"].includes(ir.mode)) errors.push("Choose a recognized iR compensation strategy.");
  plan.steps.forEach((step, index) => {
    const kind = step.source_technique;
    const definition = stepDefinitions[kind];
    if (!definition) {
      errors.push(`Step ${index + 1}: unrecognized CHI technique.`);
      return;
    }
    if (!String(step.name ?? "").trim()) errors.push(`Step ${index + 1}: add a step name.`);
    definition.fields.forEach((field) => {
      if (field.type !== "number") return;
      const value = step.parameters[field.key];
      if (!Number.isFinite(value)) errors.push(`Step ${index + 1}: ${field.label} is required and must be numeric.`);
      else if (field.min !== undefined && value < field.min) errors.push(`Step ${index + 1}: ${field.label} must be at least ${field.min}.`);
      else if (field.integer && !Number.isInteger(value)) errors.push(`Step ${index + 1}: ${field.label} must be an integer.`);
    });
    if (kind === "ca_range") {
      const { start_voltage_v: start, end_voltage_v: end, step_voltage_v: increment } = step.parameters;
      if (Number.isFinite(start) && Number.isFinite(end) && Number.isFinite(increment)) {
        if (increment === 0 || (end > start && increment < 0) || (end < start && increment > 0)) {
          errors.push(`Step ${index + 1}: CA increment must point from the start potential toward the end potential.`);
        } else {
          const intervalCount = Math.abs((end - start) / increment);
          if (Math.abs(intervalCount - Math.round(intervalCount)) > 1e-9) {
            errors.push(`Step ${index + 1}: CA increment must land exactly on the end potential.`);
          } else if (Math.round(intervalCount) + 1 > 1000) {
            errors.push(`Step ${index + 1}: CA range cannot expand beyond 1000 potential holds.`);
          }
        }
      }
    }
    if (kind === "levich_rpm_sweep_ca") {
      const tokens = String(step.parameters.rpm_values ?? "").split(",").map((value) => value.trim());
      const rpmValues = tokens.map((value) => finiteNumber(value));
      if (tokens.length < 2 || tokens.length > 50
          || tokens.some((value) => value === "")
          || rpmValues.some((value) => !Number.isInteger(value) || value <= 0)
          || new Set(rpmValues).size !== rpmValues.length) {
        errors.push(`Step ${index + 1}: RPM staircase must contain 2–50 unique, positive whole-number commands.`);
      }
    }
    const durationKey = kind === "step" ? "step_time_s" : kind === "levich_rpm_sweep_ca" ? "collection_s" : "duration_s";
    const duration = step.parameters[durationKey];
    const samplePeriod = step.parameters.sample_period_s;
    if (Number.isFinite(duration) && Number.isFinite(samplePeriod) && samplePeriod > duration) {
      errors.push(`Step ${index + 1}: sample period cannot exceed the relevant duration.`);
    }
    if (["eis", "geis"].includes(kind)
        && Number.isFinite(step.parameters.initial_frequency_hz)
        && Number.isFinite(step.parameters.final_frequency_hz)
        && step.parameters.initial_frequency_hz <= step.parameters.final_frequency_hz) {
      errors.push(`Step ${index + 1}: initial frequency must be greater than final frequency.`);
    }
    if (["swv", "impe"].includes(kind)
        && step.parameters.initial_voltage_v === step.parameters.final_voltage_v) {
      errors.push(`Step ${index + 1}: initial and final potentials cannot be equal.`);
    }
    if (kind === "lsv" && step.parameters.start_voltage_v === step.parameters.end_voltage_v) {
      errors.push(`Step ${index + 1}: start and end potentials cannot be equal.`);
    }
    if (kind === "cv"
        && Number.isFinite(step.parameters.apex1_voltage_v)
        && Number.isFinite(step.parameters.apex2_voltage_v)
        && step.parameters.apex1_voltage_v <= step.parameters.apex2_voltage_v) {
      errors.push(`Step ${index + 1}: high vertex must be greater than low vertex.`);
    }
    if (kind === "cp"
        && Number.isFinite(step.parameters.voltage_limit_low_v)
        && Number.isFinite(step.parameters.voltage_limit_high_v)
        && step.parameters.voltage_limit_low_v >= step.parameters.voltage_limit_high_v) {
      errors.push(`Step ${index + 1}: lower potential limit must be below the upper limit.`);
    }
  });
  return { errors: [...new Set(errors)], warnings: [...new Set(warnings)] };
}

function buildValidatedPlan() {
  const plan = buildPlan();
  const validation = validatePlan(plan);
  return {
    ...plan,
    validation: {
      valid: validation.errors.length === 0,
      errors: validation.errors,
      warnings: validation.warnings,
    },
  };
}

function refreshPreview() {
  const plan = buildValidatedPlan();
  document.querySelector("#protocol-preview").textContent = JSON.stringify(plan, null, 2);
  const issuePanel = document.querySelector("#protocol-warnings");
  issuePanel.classList.toggle("has-errors", !plan.validation.valid);
  const errorMarkup = plan.validation.errors.length
    ? `<strong>Fix before saving or exporting</strong><ul>${plan.validation.errors.map((issue) => `<li>${issue}</li>`).join("")}</ul>`
    : "";
  const warningMarkup = plan.validation.warnings.length
    ? `<strong>Review required</strong><ul>${plan.validation.warnings.map((issue) => `<li>${issue}</li>`).join("")}</ul>`
    : "";
  issuePanel.innerHTML = `${errorMarkup}${warningMarkup}`;
}

function loadPreset(key) {
  const preset = presets[key];
  steps = preset.steps.map((step) => newStep(step.kind, step));
  document.querySelector("#protocol-name").value = preset.name;
  renderSteps();
}

function exportPlan() {
  const plan = buildValidatedPlan();
  if (!plan.validation.valid) {
    const button = document.querySelector("#export-protocol");
    button.textContent = "Fix errors first";
    setTimeout(() => { button.textContent = "Export JSON"; }, 1600);
    refreshPreview();
    return;
  }
  const blob = new Blob([`${JSON.stringify(plan, null, 2)}\n`], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `${plan.protocol_name.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "") || "chi760e-protocol"}.json`;
  link.click();
  URL.revokeObjectURL(url);
}

function loadSavedPlan() {
  const button = document.querySelector("#load-protocol");
  const raw = localStorage.getItem("spectraloop-chi760e-protocol");
  if (!raw) {
    button.textContent = "No saved plan";
    setTimeout(() => { button.textContent = "Load saved"; }, 1200);
    return;
  }
  try {
    const plan = JSON.parse(raw);
    const restoredSteps = restoreSavedSteps(plan);
    if (typeof plan.protocol_name !== "string") throw new Error("saved protocol name is invalid");
    const ir = plan.ir_compensation || {};
    if (ir.enabled !== undefined && typeof ir.enabled !== "boolean") throw new Error("saved iR enabled flag is invalid");
    if (ir.continue_without_ir_on_ru_failure !== undefined && typeof ir.continue_without_ir_on_ru_failure !== "boolean") throw new Error("saved iR fallback flag is invalid");
    steps = restoredSteps;
    document.querySelector("#protocol-name").value = plan.protocol_name || "Saved CHI 760E protocol";
    if (plan.raman_sync?.policy) document.querySelector("#raman-sync").value = plan.raman_sync.policy;
    document.querySelector("#ir-enabled").checked = ir.enabled ?? false;
    const valueMap = {
      "ir-mode": ir.mode,
      "ir-max-trials": ir.max_compensation_trials,
      "ir-retries": ir.ru_retry_count,
      "ir-repeatability": Number.isFinite(ir.ru_repeatability_limit) ? ir.ru_repeatability_limit * 100 : null,
      "ir-ocp-min": ir.ocp_stabilization_s,
      "ir-ocp-timeout": ir.ocp_stabilization_timeout_s,
      "ir-ocp-sample": ir.ocp_sample_interval_s,
      "ir-ocp-window": ir.ocp_stability_window,
      "ir-ocp-limit": Number.isFinite(ir.ocp_stability_limit_v) ? ir.ocp_stability_limit_v * 1000 : null,
      "ir-ocp-abs": ir.ocp_abs_limit_v,
      "ir-ru-frequency": ir.ru_frequency_hz,
      "ir-ru-amplitude": Number.isFinite(ir.ru_ac_amplitude_v) ? ir.ru_ac_amplitude_v * 1000 : null,
      "ir-ru-settle": ir.ru_settle_s,
    };
    Object.entries(valueMap).forEach(([id, value]) => {
      if (value !== undefined && value !== null) document.querySelector(`#${id}`).value = value;
    });
    document.querySelector("#ir-fallback").checked = ir.continue_without_ir_on_ru_failure ?? false;
    document.querySelector("#protocol-preset").value = "blank";
    renderSteps();
    button.textContent = "Loaded";
    setTimeout(() => { button.textContent = "Load saved"; }, 1200);
  } catch (error) {
    button.textContent = "Saved plan invalid";
    setTimeout(() => { button.textContent = "Load saved"; }, 1600);
  }
}

function restoreSavedSteps(plan) {
  if (!Array.isArray(plan?.steps)) throw new Error("saved steps are missing");
  return plan.steps.map((step, index) => {
    if (!step || typeof step !== "object" || !stepDefinitions[step.source_technique]) {
      throw new Error(`saved step ${index + 1} has an unknown technique`);
    }
    if (typeof step.name !== "string") throw new Error(`saved step ${index + 1} has an invalid name`);
    if (!step.parameters || typeof step.parameters !== "object" || Array.isArray(step.parameters)) {
      throw new Error(`saved step ${index + 1} has invalid parameters`);
    }
    return newStep(step.source_technique, { name: step.name, values: step.parameters });
  });
}

function initializeProtocolBuilder() {
  const stepSelect = document.querySelector("#new-step-kind");
  stepSelect.innerHTML = Object.entries(stepDefinitions).map(([value, definition]) => `<option value="${value}">${definition.label} · ${badgeLabel(definition.status)}</option>`).join("");

  document.querySelector("#protocol-preset").addEventListener("change", (event) => loadPreset(event.target.value));
  document.querySelector("#add-step").addEventListener("click", () => { steps.push(newStep(stepSelect.value)); renderSteps(); });
  document.querySelector("#step-list").addEventListener("input", (event) => {
    const index = Number(event.target.dataset.index);
    const key = event.target.dataset.key;
    if (!Number.isInteger(index) || !key) return;
    if (key === "name") steps[index].name = event.target.value;
    else steps[index].values[key] = event.target.value;
    refreshPreview();
  });
  document.querySelector("#step-list").addEventListener("click", (event) => {
    const button = event.target.closest("button[data-action]");
    if (!button) return;
    const index = Number(button.dataset.index);
    const action = button.dataset.action;
    if (action === "remove") steps.splice(index, 1);
    if (action === "duplicate") steps.splice(index + 1, 0, newStep(steps[index].kind, { name: `${steps[index].name} copy`, values: steps[index].values }));
    if (action === "up" && index > 0) [steps[index - 1], steps[index]] = [steps[index], steps[index - 1]];
    if (action === "down" && index < steps.length - 1) [steps[index + 1], steps[index]] = [steps[index], steps[index + 1]];
    renderSteps();
  });
  [
    "protocol-name", "raman-sync", "ir-enabled", "ir-mode", "ir-fraction", "ir-max-trials", "ir-retries", "ir-repeatability", "ir-fallback",
    "ir-ocp-min", "ir-ocp-timeout", "ir-ocp-sample", "ir-ocp-window", "ir-ocp-limit", "ir-ocp-abs",
    "ir-ru-frequency", "ir-ru-amplitude", "ir-ru-settle",
  ].forEach((id) => document.querySelector(`#${id}`).addEventListener("input", refreshPreview));
  document.querySelector("#save-protocol").addEventListener("click", () => {
    const plan = buildValidatedPlan();
    const button = document.querySelector("#save-protocol");
    if (!plan.validation.valid) {
      button.textContent = "Fix errors first";
      setTimeout(() => { button.textContent = "Save locally"; }, 1600);
      refreshPreview();
      return;
    }
    localStorage.setItem("spectraloop-chi760e-protocol", JSON.stringify(plan));
    button.textContent = "Saved";
    setTimeout(() => { button.textContent = "Save locally"; }, 1200);
  });
  document.querySelector("#load-protocol").addEventListener("click", loadSavedPlan);
  document.querySelector("#export-protocol").addEventListener("click", exportPlan);

  loadPreset("ocp-eis-cv");
}

const protocolCore = { buildValidatedPlan, finiteNumber, restoreSavedSteps, stepDefinitions, validatePlan };

if (typeof globalThis !== "undefined") globalThis.SpectraLoopProtocolCore = protocolCore;

if (typeof document !== "undefined" && document.querySelector("#protocol-preset")) {
  initializeProtocolBuilder();
}

if (typeof module !== "undefined" && module.exports) {
  module.exports = protocolCore;
}

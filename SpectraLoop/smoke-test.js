const IR_TARGET_FRACTION = 0.95;
const IR_TRIAL_CEILING = 10;

function requireCondition(condition, message) {
  if (!condition) throw new Error(message);
}

function normalizedFraction(raw) {
  if (raw === null || raw === undefined || typeof raw === "boolean") return null;
  const value = Number(raw);
  return Number.isFinite(value) && value >= 0 && value <= 1 ? value : null;
}

function evaluateIRTrials(observedFractions) {
  const observations = [];
  for (const raw of observedFractions) {
    if (observations.length >= IR_TRIAL_CEILING) break;
    const value = normalizedFraction(raw);
    observations.push(value);
    if (value !== null && value >= IR_TARGET_FRACTION) {
      return {
        observations,
        reached_target: true,
        accepted_fraction: value,
        accepted_trial: observations.length,
        accepted_at_ceiling: false,
        next_trial: null,
        failure_reason: null,
      };
    }
  }

  if (observations.length < IR_TRIAL_CEILING) {
    return {
      observations,
      reached_target: false,
      accepted_fraction: null,
      accepted_trial: null,
      accepted_at_ceiling: false,
      next_trial: observations.length + 1,
      failure_reason: null,
    };
  }

  const finalValue = observations[IR_TRIAL_CEILING - 1];
  return {
    observations,
    reached_target: false,
    accepted_fraction: finalValue,
    accepted_trial: finalValue === null ? null : IR_TRIAL_CEILING,
    accepted_at_ceiling: finalValue !== null,
    next_trial: null,
    failure_reason: finalValue === null ? "Final trial produced no valid value" : null,
  };
}

function integrateCharge(timeS, currentA, initialChargeC = 0) {
  requireCondition(Array.isArray(timeS) && Array.isArray(currentA), "time and current must be arrays");
  requireCondition(timeS.length > 0 && timeS.length === currentA.length, "time and current arrays must be non-empty and equal in length");
  requireCondition(typeof initialChargeC !== "boolean" && Number.isFinite(Number(initialChargeC)), "initial charge must be finite");
  const time = timeS.map((value) => {
    requireCondition(typeof value !== "boolean" && Number.isFinite(Number(value)), "time values must be finite numbers");
    return Number(value);
  });
  const current = currentA.map((value) => {
    requireCondition(typeof value !== "boolean" && Number.isFinite(Number(value)), "current values must be finite numbers");
    return Number(value);
  });
  const charge = [Number(initialChargeC)];
  for (let index = 1; index < time.length; index += 1) {
    requireCondition(time[index] > time[index - 1], "time values must be strictly increasing");
    charge.push(charge[index - 1] + 0.5 * (current[index - 1] + current[index]) * (time[index] - time[index - 1]));
  }
  return charge;
}

function irSettings() {
  return {
    enabled: true,
    mode: "automatic",
    target_compensation_fraction: IR_TARGET_FRACTION,
    max_compensation_trials: IR_TRIAL_CEILING,
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
  };
}

function buildDefaultProtocolPlan() {
  const core = globalThis.SpectraLoopProtocolCore;
  requireCondition(core, "protocol validation core is unavailable");
  const steps = Object.entries(core.stepDefinitions).map(([kind, definition], index) => ({
    index: index + 1,
    name: definition.label,
    source_technique: kind,
    chi_technique: definition.chi,
    adaptation_status: definition.status,
    ir_compensation_eligible: definition.ir,
    parameters: Object.fromEntries(definition.fields.map((field) => [field.key, field.value])),
  }));
  return {
    schema_version: "0.3",
    protocol_name: "Browser smoke-test protocol",
    execution_enabled: false,
    raman_sync: { policy: "after_equilibration", timing_quality: "software_best_effort" },
    ir_compensation: irSettings(),
    steps,
  };
}

function resolveProtocol({ useSaved = false, savedPlanRaw = null } = {}) {
  if (!useSaved || !savedPlanRaw) {
    return {
      plan: buildDefaultProtocolPlan(),
      source: "built_in_all_techniques",
      note: useSaved ? "No locally saved protocol was found; the built-in all-techniques plan was tested." : "Built-in all-techniques plan tested.",
      load_error: null,
    };
  }
  try {
    const plan = JSON.parse(savedPlanRaw);
    globalThis.SpectraLoopProtocolCore.restoreSavedSteps(plan);
    return { plan, source: "locally_saved_protocol", note: "Locally saved protocol tested.", load_error: null };
  } catch (error) {
    return {
      plan: null,
      source: "locally_saved_protocol",
      note: "The locally saved protocol could not be loaded safely.",
      load_error: error instanceof Error ? error.message : String(error),
    };
  }
}

function simulateTrial({ observedFractions, failAcquisition = false, failCleanup = false, continueUncompensated = true }) {
  const events = [];
  const progress = evaluateIRTrials(observedFractions);
  let runError = null;
  let cleanupError = null;
  let compensationState = "withheld";
  let cleanupAttempted = false;
  try {
    events.push({ type: "ir_preparation_started" });
    if (progress.accepted_fraction !== null) {
      compensationState = "accepted_request_not_hardware_applied";
      events.push({ type: "ir_value_accepted", fraction: progress.accepted_fraction, trial: progress.accepted_trial });
    } else if (progress.failure_reason) {
      events.push({ type: "ir_preparation_failed", reason: progress.failure_reason });
      if (!continueUncompensated) throw new Error(progress.failure_reason);
    }
    events.push({ type: "simulated_acquisition_started" });
    if (failAcquisition) throw new Error("Injected acquisition failure");
    events.push({ type: "simulated_acquisition_completed" });
  } catch (error) {
    runError = error instanceof Error ? error.message : String(error);
    events.push({ type: "simulated_acquisition_failed", reason: runError });
  } finally {
    cleanupAttempted = true;
    events.push({ type: "cleanup_started" });
    if (failCleanup) {
      cleanupError = "Injected cleanup failure";
      events.push({ type: "cleanup_failed", reason: cleanupError });
    } else {
      compensationState = "disabled";
      events.push({ type: "ir_disabled" }, { type: "cell_off" });
    }
  }
  return {
    execution_mode: "simulated",
    hardware_calls: 0,
    progress,
    compensation_state: compensationState,
    cleanup_attempted: cleanupAttempted,
    run_error: runError,
    cleanup_error: cleanupError,
    events,
  };
}

function smokeCases() {
  return [
    {
      id: "offline-boundary",
      group: "Safety boundary",
      title: "No hardware execution surface",
      run: (context) => {
        requireCondition(context.execution_mode === "simulated" && context.hardware_calls === 0, "hardware boundary was not preserved");
        requireCondition(context.protocol.execution_enabled === false, "protocol execution must remain disabled");
        return "Simulation mode confirmed; hardware calls: 0.";
      },
    },
    {
      id: "protocol-validation",
      group: "Protocol",
      title: "Protocol schema and required fields",
      run: (context) => {
        requireCondition(!context.protocol_load_error, context.protocol_load_error || "protocol failed to load");
        const validation = globalThis.SpectraLoopProtocolCore.validatePlan(context.protocol);
        requireCondition(validation.errors.length === 0, validation.errors.join(" "));
        return `${context.protocol.steps.length} steps validated; ${validation.warnings.length} review warning(s) retained.`;
      },
    },
    {
      id: "technique-coverage",
      group: "Protocol",
      title: "CHI 760E offline technique coverage",
      run: () => {
        const expected = ["cv", "it", "ca", "swv", "eis", "impe", "ocp", "step", "cp"];
        const missing = expected.filter((kind) => !globalThis.SpectraLoopProtocolCore.stepDefinitions[kind]);
        requireCondition(missing.length === 0, `missing technique definitions: ${missing.join(", ")}`);
        return "CV, i-t, CA, SWV, EIS, IMPE, OCP, STEP, and ISTEP/CP are represented.";
      },
    },
    {
      id: "ir-early-target",
      group: "iR compensation",
      title: "Stop when 95% is confirmed before trial 10",
      run: () => {
        const result = evaluateIRTrials([0.72, 0.90, 0.95, 0.99]);
        requireCondition(result.reached_target && result.accepted_trial === 3 && result.observations.length === 3, "95% stop condition failed");
        return "95% accepted at trial 3; later observations were ignored.";
      },
    },
    {
      id: "ir-trial-ceiling",
      group: "iR compensation",
      title: "Accept trial 10's final valid value",
      run: () => {
        const result = evaluateIRTrials([...Array(9).fill(0.90), 0.92, 0.99]);
        requireCondition(!result.reached_target && result.accepted_at_ceiling && result.accepted_trial === 10 && result.accepted_fraction === 0.92, "trial-10 acceptance failed");
        return "Trial 10 accepted at 92%; trial 11 was not evaluated.";
      },
    },
    {
      id: "ir-invalid-final",
      group: "iR compensation",
      title: "Invalid trial 10 follows fallback",
      run: () => {
        const result = evaluateIRTrials([...Array(9).fill(0.90), true]);
        requireCondition(result.accepted_fraction === null && result.failure_reason, "invalid final value was silently accepted");
        return "Boolean trial-10 data was rejected and produced an explicit failure reason.";
      },
    },
    {
      id: "cleanup-after-error",
      group: "Failure handling",
      title: "Cleanup executes after acquisition failure",
      run: () => {
        const result = simulateTrial({ observedFractions: [0.95], failAcquisition: true });
        requireCondition(result.run_error && result.cleanup_attempted && result.compensation_state === "disabled", "cleanup did not complete after failure");
        requireCondition(result.events.some((event) => event.type === "cell_off"), "cell-off event is missing");
        return "Injected acquisition failure recorded; iR disable and cell-off cleanup completed.";
      },
    },
    {
      id: "cleanup-failure-visible",
      group: "Failure handling",
      title: "Cleanup failure cannot appear successful",
      run: () => {
        const result = simulateTrial({ observedFractions: [0.95], failCleanup: true });
        requireCondition(result.cleanup_attempted && result.cleanup_error && result.compensation_state !== "disabled", "cleanup failure was hidden");
        return "Injected cleanup failure remained visible and the state was not reported as disabled.";
      },
    },
    {
      id: "cc-integration",
      group: "Data integrity",
      title: "CC is derived from CA without replacing raw current",
      run: () => {
        const charge = integrateCharge([0, 1, 2], [2, 2, 2]);
        requireCondition(charge.length === 3 && charge[2] === 4, "trapezoidal charge result is incorrect");
        return "Known CA trace integrated to 4 C; raw current and derived charge remain separate.";
      },
    },
    {
      id: "synchronized-contract",
      group: "Data integrity",
      title: "Synchronized export preserves timing provenance",
      run: () => {
        const payload = globalThis.SpectraLoopMonitorCore.buildSessionPayload();
        requireCondition(payload.hardware_connected === false && payload.timing_quality === "simulated_unverified", "preview timing was overstated");
        requireCondition(payload.frame_alignments.every((link) => Number.isFinite(link.delta_t_s)), "signed timing offsets are missing");
        requireCondition(payload.electrochemistry.every((record) => Number.isFinite(record.source_timestamp_s)), "electrochemistry source timestamps are missing");
        return `${payload.electrochemistry.length} EChem points and ${payload.raman.length} Raman frames retained with explicit alignment offsets.`;
      },
    },
    {
      id: "rde-separation",
      group: "Optional RDE",
      title: "Commanded RPM is never reported as measured RPM",
      run: (context) => {
        const records = globalThis.SpectraLoopMonitorCore.buildEchemSeries(context.include_rde);
        requireCondition(records.every((record) => record.rde_measured_rpm === null), "commanded RPM leaked into measured RPM");
        if (context.include_rde) requireCondition(records.some((record) => record.rde_commanded_rpm > 0), "RDE demo commands are missing");
        else requireCondition(records.every((record) => record.rde_commanded_rpm === 0), "RDE commands appeared while the option was off");
        return context.include_rde ? "Optional disk-only RDE commands tested; measured RPM remained null." : "RDE option off; all commanded RPM values remained zero.";
      },
    },
    {
      id: "corrupt-plan-rejection",
      group: "Input integrity",
      title: "Corrupt saved steps are rejected",
      run: () => {
        let rejected = false;
        try {
          globalThis.SpectraLoopProtocolCore.restoreSavedSteps({ steps: [{ source_technique: "unknown", name: "bad", parameters: {} }] });
        } catch (_error) {
          rejected = true;
        }
        requireCondition(rejected, "unknown saved technique was silently discarded");
        return "Unknown saved technique produced a blocking error.";
      },
    },
  ];
}

function runSmokeSuite(options = {}) {
  const startedAt = new Date();
  const timer = typeof performance !== "undefined" ? performance : { now: () => Date.now() };
  const startMs = timer.now();
  const resolved = resolveProtocol(options);
  const context = {
    execution_mode: "simulated",
    hardware_calls: 0,
    include_rde: Boolean(options.includeRde),
    protocol: resolved.plan || { execution_enabled: false, steps: [] },
    protocol_load_error: resolved.load_error,
  };
  const results = smokeCases().map((testCase) => {
    const caseStart = timer.now();
    try {
      const detail = testCase.run(context);
      return { id: testCase.id, group: testCase.group, title: testCase.title, passed: true, detail, duration_ms: timer.now() - caseStart };
    } catch (error) {
      return {
        id: testCase.id,
        group: testCase.group,
        title: testCase.title,
        passed: false,
        detail: error instanceof Error ? error.message : String(error),
        duration_ms: timer.now() - caseStart,
      };
    }
  });
  const passed = results.filter((result) => result.passed).length;
  return {
    schema_version: "0.1-smoke-report",
    generated_at: startedAt.toISOString(),
    execution_mode: "simulated",
    hardware_connected: false,
    hardware_calls: 0,
    target_platform: "CHI 760E offline automation",
    protocol_source: resolved.source,
    protocol_note: resolved.note,
    options: { include_optional_disk_rde: context.include_rde },
    status: passed === results.length ? "passed" : "failed",
    summary: { passed, failed: results.length - passed, total: results.length, duration_ms: timer.now() - startMs },
    results,
  };
}

function escapeSmokeHtml(value) {
  return String(value).replace(/[&<>'"]/g, (character) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;",
  }[character]));
}

function renderPending() {
  const list = document.querySelector("#smoke-results");
  list.innerHTML = smokeCases().map((testCase) => `
    <article class="smoke-result pending">
      <span class="smoke-state">PENDING</span>
      <div><small>${escapeSmokeHtml(testCase.group)}</small><h3>${escapeSmokeHtml(testCase.title)}</h3><p>Waiting to run.</p></div>
    </article>`).join("");
}

function renderReport(report) {
  document.querySelector("#smoke-status").textContent = report.status === "passed" ? "All offline checks passed" : "Smoke test found blocking failures";
  document.querySelector("#smoke-status-panel").classList.toggle("failed", report.status !== "passed");
  document.querySelector("#smoke-passed").textContent = String(report.summary.passed);
  document.querySelector("#smoke-failed").textContent = String(report.summary.failed);
  document.querySelector("#smoke-duration").textContent = `${report.summary.duration_ms.toFixed(1)} ms`;
  document.querySelector("#smoke-hardware").textContent = String(report.hardware_calls);
  document.querySelector("#smoke-source").textContent = report.protocol_note;
  document.querySelector("#smoke-results").innerHTML = report.results.map((result) => `
    <article class="smoke-result ${result.passed ? "passed" : "failed"}">
      <span class="smoke-state">${result.passed ? "PASS" : "FAIL"}</span>
      <div>
        <small>${escapeSmokeHtml(result.group)} · ${result.duration_ms.toFixed(2)} ms</small>
        <h3>${escapeSmokeHtml(result.title)}</h3>
        <p>${escapeSmokeHtml(result.detail)}</p>
      </div>
    </article>`).join("");
  document.querySelector("#export-smoke").disabled = false;
}

let lastSmokeReport = null;

function initializeSmokeTest() {
  renderPending();
  const runButton = document.querySelector("#run-smoke");
  runButton.addEventListener("click", () => {
    runButton.disabled = true;
    runButton.textContent = "Running…";
    document.querySelector("#smoke-status").textContent = "Running offline checks";
    setTimeout(() => {
      const useSaved = document.querySelector("#use-saved-protocol").checked;
      lastSmokeReport = runSmokeSuite({
        includeRde: document.querySelector("#smoke-rde").checked,
        useSaved,
        savedPlanRaw: useSaved ? localStorage.getItem("spectraloop-chi760e-protocol") : null,
      });
      renderReport(lastSmokeReport);
      runButton.disabled = false;
      runButton.textContent = "Run smoke test";
    }, 0);
  });
  document.querySelector("#reset-smoke").addEventListener("click", () => {
    lastSmokeReport = null;
    renderPending();
    document.querySelector("#smoke-status").textContent = "Ready to run";
    document.querySelector("#smoke-status-panel").classList.remove("failed");
    document.querySelector("#smoke-passed").textContent = "—";
    document.querySelector("#smoke-failed").textContent = "—";
    document.querySelector("#smoke-duration").textContent = "—";
    document.querySelector("#smoke-hardware").textContent = "0";
    document.querySelector("#smoke-source").textContent = "No smoke test has run yet.";
    document.querySelector("#export-smoke").disabled = true;
  });
  document.querySelector("#export-smoke").addEventListener("click", () => {
    if (!lastSmokeReport) return;
    const url = URL.createObjectURL(new Blob([`${JSON.stringify(lastSmokeReport, null, 2)}\n`], { type: "application/json" }));
    const link = document.createElement("a");
    link.href = url;
    link.download = `spectraloop-smoke-${lastSmokeReport.status}.json`;
    link.click();
    URL.revokeObjectURL(url);
  });
}

const smokeCore = { buildDefaultProtocolPlan, evaluateIRTrials, integrateCharge, runSmokeSuite, simulateTrial };
if (typeof globalThis !== "undefined") globalThis.SpectraLoopSmokeCore = smokeCore;
if (typeof document !== "undefined" && document.querySelector("#run-smoke")) initializeSmokeTest();
if (typeof module !== "undefined" && module.exports) module.exports = smokeCore;

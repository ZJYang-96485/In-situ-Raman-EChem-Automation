const SIMULATOR_VERSION = "0.1";
const MAX_SIMULATION_POINTS = 50000;
const IR_TARGET_FRACTION = 0.95;
const IR_TRIAL_CEILING = 10;

const scenarioDefinitions = {
  standard: {
    label: "Standard · reaches 95%",
    irFractions: [0.72, 0.84, 0.91, 0.95],
  },
  trial_10: {
    label: "iR · accept trial 10",
    irFractions: [0.70, 0.76, 0.81, 0.84, 0.87, 0.89, 0.90, 0.91, 0.92, 0.93],
  },
  ru_failure: {
    label: "Fault · Ru unavailable",
    irFractions: [null, null, null, null, null, null, null, null, null, null],
  },
  acquisition_failure: {
    label: "Fault · acquisition stops",
    irFractions: [0.72, 0.84, 0.91, 0.95],
    acquisitionFailure: true,
  },
  cleanup_failure: {
    label: "Fault · cleanup fails",
    irFractions: [0.72, 0.84, 0.91, 0.95],
    cleanupFailure: true,
  },
};

function requireCondition(condition, message) {
  if (!condition) throw new Error(message);
}

function getProtocolCore() {
  if (typeof globalThis !== "undefined" && globalThis.SpectraLoopProtocolCore) return globalThis.SpectraLoopProtocolCore;
  if (typeof require !== "undefined") return require("./protocols.js");
  return null;
}

function rounded(value, digits = 12) {
  return Number(value.toFixed(digits));
}

function clamp(value, minimum, maximum) {
  return Math.min(maximum, Math.max(minimum, value));
}

function sampleTimes(durationS, samplePeriodS) {
  requireCondition(Number.isFinite(durationS) && durationS >= 0, "simulation duration must be finite and non-negative");
  if (durationS === 0) return [0];
  requireCondition(Number.isFinite(samplePeriodS) && samplePeriodS > 0, "simulation sample period must be positive");
  const intervalCount = Math.floor(durationS / samplePeriodS);
  const values = Array.from({ length: intervalCount + 1 }, (_, index) => rounded(index * samplePeriodS));
  if (Math.abs(values[values.length - 1] - durationS) > 1e-9) values.push(durationS);
  else values[values.length - 1] = durationS;
  return values;
}

function linearRange(start, end, increment) {
  requireCondition(increment !== 0, "range increment cannot be zero");
  const intervalCount = Math.round((end - start) / increment);
  requireCondition(intervalCount >= 0 && intervalCount <= 1000, "range expansion is outside simulator limits");
  return Array.from({ length: intervalCount + 1 }, (_, index) => rounded(start + index * increment));
}

function logFrequencies(initialHz, finalHz, pointsPerDecade) {
  const decades = Math.log10(initialHz / finalHz);
  const count = Math.max(2, Math.ceil(decades * pointsPerDecade) + 1);
  return Array.from({ length: count }, (_, index) => initialHz * ((finalHz / initialHz) ** (index / (count - 1))));
}

function deterministicNoise(index, salt = 0) {
  return Math.sin((index + 1) * 1.61803398875 + salt * 0.731) * 0.0000025;
}

function evaluateIRFractions(rawFractions) {
  const observations = [];
  for (const raw of rawFractions) {
    if (observations.length >= IR_TRIAL_CEILING) break;
    const value = typeof raw === "number" && Number.isFinite(raw) && raw >= 0 && raw <= 1 ? raw : null;
    observations.push(value);
    if (value !== null && value >= IR_TARGET_FRACTION) {
      return {
        observations,
        reached_target: true,
        accepted_fraction: value,
        accepted_trial: observations.length,
        accepted_at_ceiling: false,
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
      failure_reason: "The simulated iR sequence ended before a value could be accepted",
    };
  }
  const finalValue = observations[IR_TRIAL_CEILING - 1];
  return {
    observations,
    reached_target: false,
    accepted_fraction: finalValue,
    accepted_trial: finalValue === null ? null : IR_TRIAL_CEILING,
    accepted_at_ceiling: finalValue !== null,
    failure_reason: finalValue === null ? "Final iR trial produced no valid value" : null,
  };
}

function simulateIRPreparation(settings, scenario, stepIndex, startS) {
  const ruBaseOhm = 17.5 + stepIndex * 0.65;
  const trials = [];
  for (const [index, rawFraction] of scenario.irFractions.slice(0, IR_TRIAL_CEILING).entries()) {
    const fraction = typeof rawFraction === "number" && Number.isFinite(rawFraction) && rawFraction >= 0 && rawFraction <= 1 ? rawFraction : null;
    const attemptJitterOhm = Math.min(0.018, ruBaseOhm * settings.ru_repeatability_limit / 4);
    const ruAttemptsOhm = fraction === null ? [] : Array.from({ length: settings.ru_retry_count }, (_, attemptIndex) => (
      rounded(ruBaseOhm + 0.08 * Math.sin(index + stepIndex) + attemptJitterOhm * Math.sin((attemptIndex + 1) * 1.7 + index), 6)
    ));
    const selectedRuOhm = ruAttemptsOhm.length
      ? rounded(ruAttemptsOhm.reduce((sum, value) => sum + value, 0) / ruAttemptsOhm.length, 6)
      : null;
    const relativeSpread = selectedRuOhm === null
      ? null
      : rounded((Math.max(...ruAttemptsOhm) - Math.min(...ruAttemptsOhm)) / selectedRuOhm, 9);
    const repeatabilityPassed = relativeSpread !== null && relativeSpread <= settings.ru_repeatability_limit;
    const trial = {
      trial: index + 1,
      elapsed_s: rounded(startS + settings.ocp_stabilization_s + (index + 1) * settings.ru_settle_s),
      observed_fraction: repeatabilityPassed ? fraction : null,
      ru_attempts_ohm: ruAttemptsOhm,
      selected_ru_ohm: repeatabilityPassed ? selectedRuOhm : null,
      relative_spread: relativeSpread,
      repeatability_limit: settings.ru_repeatability_limit,
      repeatability_passed: repeatabilityPassed,
      valid: fraction !== null && repeatabilityPassed,
    };
    trials.push(trial);
    if (trial.valid && trial.observed_fraction >= IR_TARGET_FRACTION) break;
  }
  const evaluated = evaluateIRFractions(trials.map((trial) => trial.observed_fraction));
  const acceptedTrial = evaluated.accepted_trial ? trials[evaluated.accepted_trial - 1] : null;
  return {
    ...evaluated,
    target_fraction: IR_TARGET_FRACTION,
    max_trials: IR_TRIAL_CEILING,
    trials,
    selected_ru_ohm: acceptedTrial?.selected_ru_ohm ?? null,
    requested_compensation_ohm: acceptedTrial
      ? rounded(acceptedTrial.ru_ohm * evaluated.accepted_fraction, 6)
      : null,
    duration_s: rounded(settings.ocp_stabilization_s + trials.length * settings.ru_settle_s),
    state: acceptedTrial ? "simulated_applied" : "simulated_uncompensated",
    simulation_only: true,
    hardware_applied: false,
  };
}

function pathAtTime(path, scanRate, timeS) {
  let remaining = timeS;
  for (let index = 0; index < path.length - 1; index += 1) {
    const start = path[index];
    const end = path[index + 1];
    const duration = Math.abs(end - start) / scanRate;
    if (remaining <= duration || index === path.length - 2) {
      const progress = duration === 0 ? 1 : clamp(remaining / duration, 0, 1);
      return { potential: start + (end - start) * progress, direction: Math.sign(end - start) || 1 };
    }
    remaining -= duration;
  }
  return { potential: path[path.length - 1], direction: 1 };
}

function caCurrent(voltageV, timeS, rpm, pointIndex) {
  const polarity = voltageV === 0 ? -1 : Math.sign(voltageV);
  const transient = polarity * 0.00018 * Math.exp(-timeS / 7);
  const steady = polarity * (0.000018 + Math.abs(voltageV) * 0.000055);
  const rotation = rpm > 0 ? -0.0000054 * Math.sqrt(rpm) : 0;
  return transient + steady + rotation + deterministicNoise(pointIndex, voltageV * 10);
}

function simulateStepSamples(step) {
  const p = step.parameters;
  const kind = step.source_technique;
  if (kind === "wait") {
    return { duration_s: p.duration_s, samples: sampleTimes(p.duration_s, Math.max(p.duration_s, 1)).map((time) => ({ offset_s: time, potential_v: null, current_a: null })) };
  }
  if (["ca", "cc_from_ca", "it"].includes(kind)) {
    const voltage = kind === "it" ? p.potential_v : p.voltage_v;
    const samples = sampleTimes(p.duration_s, p.sample_period_s).map((time, index) => ({
      offset_s: time,
      potential_v: voltage,
      current_a: caCurrent(voltage, time, 0, index),
    }));
    return { duration_s: p.duration_s, samples };
  }
  if (kind === "ocp") {
    const samples = sampleTimes(p.duration_s, p.sample_period_s).map((time, index) => ({
      offset_s: time,
      potential_v: 0.16 + 0.028 * Math.exp(-time / 45) + 0.0015 * Math.sin(time / 9),
      current_a: deterministicNoise(index, 2) * 0.03,
    }));
    return { duration_s: p.duration_s, samples };
  }
  if (["cv", "lsv"].includes(kind)) {
    const scanRate = p.scan_rate_v_s;
    const paths = kind === "cv"
      ? Array.from({ length: p.cycles }, () => [p.initial_voltage_v, p.apex1_voltage_v, p.apex2_voltage_v, p.final_voltage_v]).flatMap((path, index) => index ? path.slice(1) : path)
      : [p.start_voltage_v, p.end_voltage_v];
    const duration = paths.slice(1).reduce((sum, end, index) => sum + Math.abs(end - paths[index]) / scanRate, 0);
    const samplePeriod = p.step_size_v / scanRate;
    const samples = sampleTimes(duration, samplePeriod).map((time, index) => {
      const position = pathAtTime(paths, scanRate, time);
      const oxidation = 0.00022 * Math.exp(-((position.potential - 0.08) ** 2) / 0.006);
      const reduction = -0.00019 * Math.exp(-((position.potential + 0.08) ** 2) / 0.008);
      return {
        offset_s: time,
        potential_v: position.potential,
        current_a: position.direction * 0.000012 + oxidation + reduction + deterministicNoise(index, 3),
      };
    });
    return { duration_s: duration, samples };
  }
  if (kind === "ca_range") {
    const voltages = linearRange(p.start_voltage_v, p.end_voltage_v, p.step_voltage_v);
    const samples = [];
    voltages.forEach((voltage, holdIndex) => {
      sampleTimes(p.duration_s, p.sample_period_s).forEach((time, index) => {
        if (holdIndex > 0 && index === 0) return;
        samples.push({
          offset_s: holdIndex * p.duration_s + time,
          potential_v: voltage,
          current_a: caCurrent(voltage, time, 0, index + holdIndex * 17),
          expanded_hold_index: holdIndex + 1,
        });
      });
    });
    return { duration_s: voltages.length * p.duration_s, samples };
  }
  if (kind === "step") {
    const samples = [];
    for (let hold = 0; hold < p.step_count; hold += 1) {
      const voltage = p.start_voltage_v + hold * p.step_voltage_v;
      sampleTimes(p.step_time_s, p.sample_period_s).forEach((time, index) => {
        if (hold > 0 && index === 0) return;
        samples.push({
          offset_s: hold * p.step_time_s + time,
          potential_v: voltage,
          current_a: caCurrent(voltage, time, 0, index + hold * 13),
          expanded_hold_index: hold + 1,
        });
      });
    }
    return { duration_s: p.step_count * p.step_time_s, samples };
  }
  if (kind === "levich_rpm_sweep_ca") {
    const rpms = String(p.rpm_values).split(",").map((value) => Number(value.trim()));
    const samples = [];
    let offset = p.pre_stabilization_s;
    sampleTimes(p.pre_stabilization_s, p.sample_period_s).forEach((time, index) => {
      samples.push({ offset_s: time, potential_v: p.voltage_v, current_a: caCurrent(p.voltage_v, time, 0, index), rde_commanded_rpm: 0 });
    });
    rpms.forEach((rpm, rpmIndex) => {
      const stageDuration = p.stabilization_s + p.collection_s;
      sampleTimes(stageDuration, p.sample_period_s).forEach((time, index) => {
        if (index === 0 && samples.length) return;
        samples.push({
          offset_s: offset + time,
          potential_v: p.voltage_v,
          current_a: caCurrent(p.voltage_v, time, rpm, index + rpmIndex * 19),
          rde_commanded_rpm: rpm,
          rde_stage: time < p.stabilization_s ? "stabilizing" : "collecting",
        });
      });
      offset += stageDuration;
    });
    return { duration_s: offset, samples, rpm_values: rpms, rpm_stage_s: p.stabilization_s + p.collection_s, rpm_start_s: p.pre_stabilization_s };
  }
  if (["eis", "geis"].includes(kind)) {
    const frequencies = logFrequencies(p.initial_frequency_hz, p.final_frequency_hz, p.points_per_decade);
    let elapsed = 0;
    const samples = frequencies.map((frequency, index) => {
      if (index > 0) elapsed += clamp(3 / frequency, 0.05, 5);
      const omegaTau = 2 * Math.PI * frequency * 0.004;
      const zReal = 6 + 22 / (1 + omegaTau ** 2);
      const zImag = -22 * omegaTau / (1 + omegaTau ** 2);
      const current = kind === "geis" ? p.dc_current_a : (p.dc_voltage_v || 0) / Math.max(zReal, 1);
      const potential = kind === "geis" ? current * zReal : p.dc_voltage_v;
      return { offset_s: elapsed, potential_v: potential, current_a: current, frequency_hz: frequency, z_real_ohm: zReal, z_imag_ohm: zImag };
    });
    return { duration_s: elapsed, samples };
  }
  if (kind === "swv") {
    const direction = Math.sign(p.final_voltage_v - p.initial_voltage_v);
    const count = Math.ceil(Math.abs(p.final_voltage_v - p.initial_voltage_v) / p.increment_v) + 1;
    const samples = Array.from({ length: count }, (_, index) => {
      const potential = index === count - 1 ? p.final_voltage_v : p.initial_voltage_v + direction * p.increment_v * index;
      return {
        offset_s: index / p.frequency_hz,
        potential_v: potential,
        current_a: -0.00012 * Math.exp(-((potential + 0.35) ** 2) / 0.018) + deterministicNoise(index, 4),
      };
    });
    return { duration_s: samples[samples.length - 1].offset_s, samples };
  }
  if (kind === "impe") {
    const direction = Math.sign(p.final_voltage_v - p.initial_voltage_v);
    const count = Math.ceil(Math.abs(p.final_voltage_v - p.initial_voltage_v) / p.potential_step_v) + 1;
    const samples = Array.from({ length: count }, (_, index) => {
      const potential = index === count - 1 ? p.final_voltage_v : p.initial_voltage_v + direction * p.potential_step_v * index;
      const zReal = 12 + 18 / (1 + Math.exp((potential - 0.25) * 8));
      return { offset_s: index, potential_v: potential, current_a: potential / zReal, frequency_hz: p.frequency_hz, z_real_ohm: zReal, z_imag_ohm: -4 - 2 * Math.sin(potential * 3) };
    });
    return { duration_s: samples[samples.length - 1].offset_s, samples };
  }
  if (["cp", "cc_charge", "cc_discharge"].includes(kind)) {
    const signedCurrent = kind === "cc_discharge" ? -Math.abs(p.current_a) : p.current_a;
    const samples = sampleTimes(p.duration_s, p.sample_period_s).map((time) => {
      const progress = p.duration_s === 0 ? 1 : time / p.duration_s;
      let potential;
      if (kind === "cc_charge") potential = 3.2 + (p.voltage_cutoff_v - 3.2) * progress;
      else if (kind === "cc_discharge") potential = 4.1 + (p.voltage_cutoff_v - 4.1) * progress;
      else potential = clamp(0.12 + signedCurrent * 1400 + 0.25 * progress * Math.sign(signedCurrent || 1), p.voltage_limit_low_v, p.voltage_limit_high_v);
      return { offset_s: time, potential_v: potential, current_a: signedCurrent };
    });
    return { duration_s: p.duration_s, samples };
  }
  throw new Error(`No simulation model exists for ${kind}`);
}

function buildRamanFrame(midpointS, index, sessionId) {
  const shiftCm1 = Array.from({ length: 301 }, (_, point) => 300 + point * 5);
  const peak = (x, center, width, height) => height * Math.exp(-((x - center) ** 2) / (2 * width ** 2));
  const intensity = shiftCm1.map((shift) => {
    const state = 1 + index * 0.08;
    return 140 + 0.035 * shift + peak(shift, 520, 24, 260) + peak(shift, 1005, 34, 190 * state) + peak(shift, 1350, 48, 125 / state) + 6 * Math.sin(shift / 27 + index);
  });
  return {
    session_id: sessionId,
    source: "raman_simulator",
    sequence: index,
    frame_id: `R${String(index + 1).padStart(3, "0")}`,
    acquisition_start_elapsed_s: Math.max(0, midpointS - 1),
    acquisition_end_elapsed_s: midpointS + 1,
    acquisition_midpoint_elapsed_s: midpointS,
    source_timestamp_s: Math.max(0, midpointS - 1),
    host_receipt_timestamp_s: midpointS + 1.027,
    shift_cm_1: shiftCm1,
    shift_unit: "cm^-1",
    intensity_au: intensity,
    intensity_unit: "a.u.",
    exposure_s: 2,
    accumulations: 1,
    trigger_mode: "software_simulated",
    quality_flags: ["simulated", "timing_unverified"],
  };
}

function buildSimulationSession(plan, options = {}) {
  const scenarioKey = options.scenario || "standard";
  const scenario = scenarioDefinitions[scenarioKey];
  requireCondition(scenario, `Unknown simulation scenario: ${scenarioKey}`);
  const core = getProtocolCore();
  requireCondition(core, "protocol validation core is unavailable");
  const validation = core.validatePlan(plan);
  requireCondition(validation.errors.length === 0, validation.errors.join(" "));

  const sessionId = options.sessionId || `sim-${Date.now().toString(36)}`;
  const records = [];
  const events = [{ elapsed_s: 0, type: "simulation_started", label: "Simulation started", detail: `${plan.protocol_name} · no device connection` }];
  const irResults = [];
  const stepEnds = [];
  let cursorS = 0;
  let cumulativeChargeC = 0;
  let previousRecord = null;
  let previousIntegrationRecord = null;
  let terminalState = "simulated_complete";
  let runError = null;

  const appendSample = (sample, step, stepStartS, irResult) => {
    const elapsedS = rounded(stepStartS + sample.offset_s);
    if (previousRecord && elapsedS <= previousRecord.elapsed_s) return;
    const currentA = Number.isFinite(sample.current_a) ? sample.current_a : null;
    if (previousIntegrationRecord && currentA !== null) {
      cumulativeChargeC += 0.5 * (previousIntegrationRecord.current_a + currentA) * (elapsedS - previousIntegrationRecord.elapsed_s);
    }
    const record = {
      session_id: sessionId,
      source: "chi760e_connection_free_simulator",
      sequence: records.length,
      technique: step.chi_technique || step.source_technique,
      source_technique: step.source_technique,
      protocol_step_id: `step-${String(step.index).padStart(3, "0")}`,
      protocol_step_name: step.name,
      step_index: step.index,
      elapsed_s: elapsedS,
      step_elapsed_s: sample.offset_s,
      source_timestamp_s: elapsedS,
      host_receipt_timestamp_s: rounded(elapsedS + 0.018),
      potential_v: Number.isFinite(sample.potential_v) ? sample.potential_v : null,
      potential_unit: "V",
      current_a: currentA,
      current_unit: "A",
      chronocoulometry_c: cumulativeChargeC,
      rde_commanded_rpm: sample.rde_commanded_rpm || 0,
      rde_measured_rpm: null,
      ir_compensation: irResult ? {
        requested: true,
        preparation_result_id: irResult.result_id,
        target_fraction: IR_TARGET_FRACTION,
        accepted_fraction: irResult.accepted_fraction,
        accepted_trial: irResult.accepted_trial,
        selected_ru_ohm: irResult.selected_ru_ohm,
        requested_compensation_ohm: irResult.requested_compensation_ohm,
        state: irResult.state,
        simulation_only: true,
        hardware_applied: false,
      } : { requested: false, state: "not_requested", simulation_only: true, hardware_applied: false },
      quality_flags: ["simulated", "timing_unverified", "no_hardware_io"],
    };
    ["frequency_hz", "z_real_ohm", "z_imag_ohm", "expanded_hold_index", "rde_stage"].forEach((key) => {
      if (sample[key] !== undefined) record[key] = sample[key];
    });
    records.push(record);
    previousRecord = record;
    previousIntegrationRecord = currentA === null ? null : record;
  };

  for (const step of plan.steps) {
    let irResult = null;
    if (plan.ir_compensation.enabled && step.ir_compensation_eligible) {
      events.push({ elapsed_s: cursorS, type: "ir_preparation_started", label: `iR preparation · ${step.name}`, detail: "Simulated OCP stabilization and Ru trials" });
      irResult = simulateIRPreparation(plan.ir_compensation, scenario, step.index, cursorS);
      irResult.result_id = `ir-step-${String(step.index).padStart(3, "0")}`;
      irResult.step_index = step.index;
      irResult.step_name = step.name;
      irResults.push(irResult);
      irResult.trials.forEach((trial) => events.push({
        elapsed_s: trial.elapsed_s,
        type: "ir_trial",
        label: `iR trial ${trial.trial}`,
        detail: trial.valid ? `${(trial.observed_fraction * 100).toFixed(0)}% · Ru ${trial.selected_ru_ohm.toFixed(2)} Ω from ${trial.ru_attempts_ohm.length} attempts` : "No valid repeatable Ru value",
      }));
      cursorS += irResult.duration_s;
      if (irResult.accepted_trial) {
        events.push({ elapsed_s: cursorS, type: "ir_value_accepted", label: `iR value accepted · trial ${irResult.accepted_trial}`, detail: `${(irResult.accepted_fraction * 100).toFixed(0)}% requested in simulation only` });
      } else {
        events.push({ elapsed_s: cursorS, type: "ir_preparation_failed", label: "iR preparation failed", detail: irResult.failure_reason });
        if (!plan.ir_compensation.continue_without_ir_on_ru_failure) {
          terminalState = "simulated_failed";
          runError = irResult.failure_reason;
          break;
        }
      }
    }

    const stepStartS = cursorS;
    previousIntegrationRecord = null;
    events.push({ elapsed_s: stepStartS, type: "step_started", label: `${step.index}. ${step.name}`, detail: `${step.source_technique.toUpperCase()} simulation started` });
    const result = simulateStepSamples(step);
    requireCondition(records.length + result.samples.length <= MAX_SIMULATION_POINTS, `Simulation exceeds the ${MAX_SIMULATION_POINTS.toLocaleString()}-point limit`);
    let samples = result.samples;
    if (scenario.acquisitionFailure) {
      const keep = Math.max(1, Math.min(samples.length, Math.ceil(samples.length * 0.25)));
      samples = samples.slice(0, keep);
    }
    samples.forEach((sample) => appendSample(sample, step, stepStartS, irResult));

    if (result.rpm_values) {
      result.rpm_values.forEach((rpm, index) => events.push({
        elapsed_s: rounded(stepStartS + result.rpm_start_s + index * result.rpm_stage_s),
        type: "rde_setpoint",
        label: "RDE setpoint",
        detail: `${rpm} rpm commanded · measured RPM unavailable`,
      }));
    }

    if (scenario.acquisitionFailure) {
      cursorS = records.length ? records[records.length - 1].elapsed_s : stepStartS;
      events.push({ elapsed_s: cursorS, type: "acquisition_failed", label: "Injected acquisition failure", detail: `${step.name} stopped early; failure remains visible` });
      terminalState = "simulated_failed";
      runError = "Injected acquisition failure";
      break;
    }

    cursorS = rounded(stepStartS + result.duration_s);
    stepEnds.push(cursorS);
    events.push({ elapsed_s: cursorS, type: "step_completed", label: `${step.index}. ${step.name} complete`, detail: `${result.samples.length} simulated points` });
  }

  events.push({ elapsed_s: cursorS, type: "cleanup_started", label: "Cleanup started", detail: "Simulated iR disable and cell-off sequence" });
  let cleanupState = "simulated_complete";
  let cleanupError = null;
  if (scenario.cleanupFailure) {
    cleanupState = "simulated_failed";
    cleanupError = "Injected cleanup failure";
    terminalState = "simulated_failed";
    events.push({ elapsed_s: cursorS, type: "cleanup_failed", label: "Injected cleanup failure", detail: "Cleanup is not reported as successful" });
  } else {
    events.push({ elapsed_s: cursorS, type: "cleanup_completed", label: "Cleanup complete", detail: "Simulated iR disabled · simulated cell off" });
  }
  events.push({ elapsed_s: cursorS, type: "simulation_finished", label: terminalState === "simulated_complete" ? "Simulation complete" : "Simulation ended with a visible failure", detail: "Hardware calls: 0" });

  if (!records.length) {
    records.push({
      session_id: sessionId, source: "chi760e_connection_free_simulator", sequence: 0, technique: "IDLE", source_technique: "wait",
      protocol_step_id: null, protocol_step_name: null, step_index: null, elapsed_s: cursorS, step_elapsed_s: 0,
      source_timestamp_s: cursorS, host_receipt_timestamp_s: rounded(cursorS + 0.018), potential_v: null, potential_unit: "V",
      current_a: null, current_unit: "A", chronocoulometry_c: 0, rde_commanded_rpm: 0, rde_measured_rpm: null,
      ir_compensation: { requested: false, state: "not_requested", simulation_only: true, hardware_applied: false },
      quality_flags: ["simulated", "timing_unverified", "no_hardware_io"],
    });
  }

  const ramanLimit = 20;
  const requestedRamanTimes = plan.raman_sync.policy === "none"
    ? []
    : plan.raman_sync.policy === "before_and_after_experiment"
      ? [...new Set([0, cursorS])]
      : [...new Set(stepEnds.length ? stepEnds : [cursorS])];
  const simulationWarnings = [];
  if (requestedRamanTimes.length > ramanLimit) {
    simulationWarnings.push(`Raman frame generation was limited to ${ramanLimit} frames from ${requestedRamanTimes.length} requested step-end frames.`);
    events.push({ elapsed_s: cursorS, type: "simulation_limit", label: "Raman frame limit reached", detail: simulationWarnings[0] });
  }
  const ramanTimes = requestedRamanTimes.slice(0, ramanLimit);
  const raman = ramanTimes.map((time, index) => buildRamanFrame(time, index, sessionId));
  const hasRde = records.some((record) => record.rde_commanded_rpm > 0);

  return {
    schema_version: "0.2-simulation",
    session_id: sessionId,
    generated_at: new Date().toISOString(),
    terminal_state: terminalState,
    execution_mode: "connection_free_simulation",
    hardware_connected: false,
    hardware_calls: 0,
    timing_quality: "simulated_unverified",
    simulator: { version: SIMULATOR_VERSION, scenario: scenarioKey, deterministic: true, max_points: MAX_SIMULATION_POINTS, warnings: simulationWarnings },
    protocol_plan: JSON.parse(JSON.stringify(plan)),
    instruments: {
      electrochemistry: { model: "CHI 760E", connection: "not_opened", simulated: true },
      raman: { connection: "not_opened", simulated: true },
      rde: { connection: "not_opened", simulated: true, included: hasRde },
    },
    run_error: runError,
    cleanup_state: cleanupState,
    cleanup_error: cleanupError,
    optional_disk_rde_demo_enabled: hasRde,
    ir_compensation: {
      requested: Boolean(plan.ir_compensation.enabled),
      target_fraction: IR_TARGET_FRACTION,
      max_trials: IR_TRIAL_CEILING,
      per_step_results: irResults,
      hardware_applied: false,
      simulation_only: true,
    },
    derived_channels: {
      chronocoulometry_c: { method: "trapezoidal", source_channel: "current_a", initial_charge_c: 0, interval: "consecutive finite-current samples" },
    },
    electrochemistry: records,
    raman,
    events: events.sort((first, second) => first.elapsed_s - second.elapsed_s),
  };
}

const simulatorCore = { buildSimulationSession, evaluateIRFractions, scenarioDefinitions, simulateStepSamples };
if (typeof globalThis !== "undefined") globalThis.SpectraLoopSimulatorCore = simulatorCore;
if (typeof module !== "undefined" && module.exports) module.exports = simulatorCore;

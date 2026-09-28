const durationS = 120;
const samplePeriodS = 0.5;
const sessionId = "preview-chi760e-raman";
let rdePreviewEnabled = false;

function rpmAt(timeS) {
  if (timeS < 20) return 0;
  if (timeS < 45) return 400;
  if (timeS < 70) return 900;
  if (timeS < 95) return 1600;
  return 2500;
}

function buildEchemSeries(withRde) {
  const records = Array.from({ length: Math.floor(durationS / samplePeriodS) + 1 }, (_, index) => {
    const elapsedS = index * samplePeriodS;
    const rpm = withRde ? rpmAt(elapsedS) : 0;
    const potentialV = elapsedS < 12 ? 0.17 + 0.003 * Math.sin(elapsedS / 2.8) : 0.05;
    const rotationTerm = rpm ? -0.0000054 * Math.sqrt(rpm) : 0;
    const transient = elapsedS >= 12 ? -0.00016 * Math.exp(-(elapsedS - 12) / 8) : 0;
    const currentA = rotationTerm + transient + 0.000004 * Math.sin(elapsedS / 2.4);
    return {
      session_id: sessionId,
      source: "chi760e_simulated",
      sequence: index,
      technique: "CA",
      protocol_step_id: "preview-ca-001",
      cycle_index: 1,
      step_index: 1,
      elapsed_s: elapsedS,
      source_timestamp_s: elapsedS,
      host_receipt_timestamp_s: elapsedS + 0.018,
      potential_v: potentialV,
      potential_unit: "V",
      current_a: currentA,
      current_unit: "A",
      rde_commanded_rpm: rpm,
      rde_measured_rpm: null,
      ir_compensation: {
        requested: true,
        requested_mode: "automatic",
        ru_attempts_ohm: [],
        selected_ru_ohm: null,
        requested_compensation_ohm: null,
        resistance_readback_ohm: null,
        state: "withheld",
      },
      quality_flags: ["simulated", "timing_unverified"],
    };
  });
  records.forEach((record, index) => {
    if (index === 0) {
      record.chronocoulometry_c = 0;
      return;
    }
    const previous = records[index - 1];
    record.chronocoulometry_c = previous.chronocoulometry_c
      + 0.5 * (previous.current_a + record.current_a) * (record.elapsed_s - previous.elapsed_s);
  });
  return records;
}

let echem = buildEchemSeries(rdePreviewEnabled);

const ramanTimes = [18, 38, 63, 88, 113];
const raman = ramanTimes.map((midpointS, frameIndex) => {
  const shiftCm1 = Array.from({ length: 301 }, (_, index) => 300 + index * 5);
  const peak = (x, center, width, height) => height * Math.exp(-((x - center) ** 2) / (2 * width ** 2));
  const intensity = shiftCm1.map((shift) => {
    const state = 1 + frameIndex * 0.12;
    return 140 + 0.035 * shift + peak(shift, 520, 24, 260) + peak(shift, 1005, 34, 190 * state) + peak(shift, 1350, 48, 125 / state) + 6 * Math.sin(shift / 27 + frameIndex);
  });
  return {
    session_id: sessionId,
    source: "raman_simulated",
    sequence: frameIndex,
    frame_id: `R${String(frameIndex + 1).padStart(3, "0")}`,
    acquisition_start_elapsed_s: midpointS - 1,
    acquisition_end_elapsed_s: midpointS + 1,
    acquisition_midpoint_elapsed_s: midpointS,
    source_timestamp_s: midpointS - 1,
    host_receipt_timestamp_s: midpointS + 1.027,
    shift_cm_1: shiftCm1,
    shift_unit: "cm^-1",
    intensity_au: intensity,
    intensity_unit: "a.u.",
    exposure_s: 2,
    accumulations: 1,
    excitation_wavelength_nm: null,
    preprocessing: ["simulated_baseline"],
    calibration_reference: null,
    trigger_mode: "software_simulated",
    quality_flags: ["simulated", "timing_unverified"],
  };
});

const baseEvents = [
  { elapsed_s: 0, label: "Preview session created", detail: "No device connection" },
  { elapsed_s: 3, label: "iR loop planned", detail: "Target 95%; accept the 10th trial's valid value if needed" },
  { elapsed_s: 8, label: "iR application withheld", detail: "No parameter discovery or readback in preview mode" },
  { elapsed_s: 12, label: "Simulated CA begins", detail: "0.050 V target" },
  { elapsed_s: 120, label: "Simulated run complete", detail: "Cleanup would disable iR" },
];

const rdeEvents = [
  { elapsed_s: 20, label: "RDE setpoint", detail: "400 rpm" },
  { elapsed_s: 45, label: "RDE setpoint", detail: "900 rpm" },
  { elapsed_s: 70, label: "RDE setpoint", detail: "1600 rpm" },
  { elapsed_s: 95, label: "RDE setpoint", detail: "2500 rpm" },
];

function activeEvents() {
  return [...baseEvents, ...(rdePreviewEnabled ? rdeEvents : [])]
    .sort((first, second) => first.elapsed_s - second.elapsed_s);
}

let selectedTimeS = 0;
let playing = false;
let animationFrame = null;
let previousAnimationMs = null;

function nearestByTime(records, timeKey, targetS) {
  return records.reduce((best, record) => Math.abs(record[timeKey] - targetS) < Math.abs(best[timeKey] - targetS) ? record : best);
}

function formatCurrent(currentA) {
  const valueMa = currentA * 1000;
  return `${valueMa >= 0 ? "+" : ""}${valueMa.toFixed(3)} mA`;
}

function canvasPoint(event, canvas) {
  const rectangle = canvas.getBoundingClientRect();
  return {
    x: (event.clientX - rectangle.left) * (canvas.width / rectangle.width),
    y: (event.clientY - rectangle.top) * (canvas.height / rectangle.height),
  };
}

function clearCanvas(canvas) {
  const context = canvas.getContext("2d");
  context.clearRect(0, 0, canvas.width, canvas.height);
  context.fillStyle = "#ffffff";
  context.fillRect(0, 0, canvas.width, canvas.height);
  return context;
}

function drawAxes(context, bounds, xTicks, yTicks, xLabel, yLabel) {
  context.strokeStyle = "#d6dee4";
  context.fillStyle = "#667887";
  context.lineWidth = 1;
  context.font = "12px Arial";
  xTicks.forEach(({ value, x }) => {
    context.beginPath();
    context.moveTo(x, bounds.top);
    context.lineTo(x, bounds.bottom);
    context.stroke();
    context.textAlign = "center";
    context.fillText(value, x, bounds.bottom + 19);
  });
  yTicks.forEach(({ value, y }) => {
    context.beginPath();
    context.moveTo(bounds.left, y);
    context.lineTo(bounds.right, y);
    context.stroke();
    context.textAlign = "right";
    context.fillText(value, bounds.left - 8, y + 4);
  });
  context.fillStyle = "#314958";
  context.textAlign = "center";
  context.fillText(xLabel, (bounds.left + bounds.right) / 2, bounds.bottom + 40);
  context.save();
  context.translate(16, (bounds.top + bounds.bottom) / 2);
  context.rotate(-Math.PI / 2);
  context.fillText(yLabel, 0, 0);
  context.restore();
}

function drawTimeline() {
  const canvas = document.querySelector("#timeline-canvas");
  const context = clearCanvas(canvas);
  const panels = [
    { top: 22, bottom: 112, key: "potential_v", min: 0, max: 0.2, color: "#275f88", label: "Ewe (V)" },
    { top: 137, bottom: 227, key: "current_a", min: -0.00032, max: 0.00004, color: "#d65e24", label: "Disk I (A)" },
    { top: 252, bottom: 342, key: "rde_commanded_rpm", min: 0, max: 2700, color: "#20735d", label: "RPM" },
  ];
  const left = 78;
  const right = canvas.width - 24;
  panels.forEach((panel) => {
    const bounds = { left, right, top: panel.top, bottom: panel.bottom };
    drawAxes(
      context,
      bounds,
      [0, 30, 60, 90, 120].map((value) => ({ value, x: left + (value / durationS) * (right - left) })),
      [panel.min, (panel.min + panel.max) / 2, panel.max].map((value) => ({
        value: panel.key === "rde_commanded_rpm" ? Math.round(value) : value.toPrecision(2),
        y: panel.bottom - ((value - panel.min) / (panel.max - panel.min)) * (panel.bottom - panel.top),
      })),
      panel === panels[panels.length - 1] ? "Elapsed time (s)" : "",
      panel.label,
    );
    context.strokeStyle = panel.color;
    context.lineWidth = 2;
    context.beginPath();
    echem.forEach((record, index) => {
      const x = left + (record.elapsed_s / durationS) * (right - left);
      const y = panel.bottom - ((record[panel.key] - panel.min) / (panel.max - panel.min)) * (panel.bottom - panel.top);
      if (index === 0) context.moveTo(x, y); else context.lineTo(x, y);
    });
    context.stroke();
  });
  const cursorX = left + (selectedTimeS / durationS) * (right - left);
  context.strokeStyle = "#7a4fa1";
  context.lineWidth = 2;
  context.beginPath();
  context.moveTo(cursorX, panels[0].top);
  context.lineTo(cursorX, panels[panels.length - 1].bottom);
  context.stroke();
}

function drawSpectrum(frame) {
  const canvas = document.querySelector("#spectrum-canvas");
  const context = clearCanvas(canvas);
  const bounds = { left: 70, right: canvas.width - 24, top: 25, bottom: canvas.height - 52 };
  const minX = frame.shift_cm_1[0];
  const maxX = frame.shift_cm_1[frame.shift_cm_1.length - 1];
  const minY = Math.min(...frame.intensity_au) * 0.95;
  const maxY = Math.max(...frame.intensity_au) * 1.05;
  drawAxes(
    context,
    bounds,
    [300, 600, 900, 1200, 1500, 1800].map((value) => ({ value, x: bounds.left + ((value - minX) / (maxX - minX)) * (bounds.right - bounds.left) })),
    [minY, (minY + maxY) / 2, maxY].map((value) => ({ value: Math.round(value), y: bounds.bottom - ((value - minY) / (maxY - minY)) * (bounds.bottom - bounds.top) })),
    "Raman shift (cm⁻¹)",
    "Intensity (a.u.)",
  );
  context.strokeStyle = "#7a4fa1";
  context.lineWidth = 2;
  context.beginPath();
  frame.shift_cm_1.forEach((shift, index) => {
    const x = bounds.left + ((shift - minX) / (maxX - minX)) * (bounds.right - bounds.left);
    const y = bounds.bottom - ((frame.intensity_au[index] - minY) / (maxY - minY)) * (bounds.bottom - bounds.top);
    if (index === 0) context.moveTo(x, y); else context.lineTo(x, y);
  });
  context.stroke();
}

function renderEvents() {
  const eventList = document.querySelector("#event-list");
  eventList.innerHTML = activeEvents().map((event) => {
    const state = event.elapsed_s <= selectedTimeS ? "past" : "future";
    return `<li class="${state}"><button type="button" data-time="${event.elapsed_s}"><time>${event.elapsed_s.toFixed(1)} s</time><strong>${event.label}</strong><span>${event.detail}</span></button></li>`;
  }).join("");
}

function updateSelection(timeS) {
  selectedTimeS = Math.max(0, Math.min(durationS, timeS));
  const sample = nearestByTime(echem, "elapsed_s", selectedTimeS);
  const frame = nearestByTime(raman, "acquisition_midpoint_elapsed_s", selectedTimeS);
  const offsetS = frame.acquisition_midpoint_elapsed_s - selectedTimeS;
  document.querySelector("#time-slider").value = selectedTimeS;
  document.querySelector("#time-output").textContent = `${selectedTimeS.toFixed(1)} / ${durationS.toFixed(1)} s`;
  document.querySelector("#metric-time").textContent = `${selectedTimeS.toFixed(1)} s`;
  document.querySelector("#metric-potential").textContent = `${sample.potential_v.toFixed(3)} V`;
  document.querySelector("#metric-current").textContent = formatCurrent(sample.current_a);
  document.querySelector("#metric-charge").textContent = `${(sample.chronocoulometry_c * 1000).toFixed(3)} mC`;
  document.querySelector("#metric-rpm").textContent = rdePreviewEnabled ? `${sample.rde_commanded_rpm} rpm` : "Off";
  document.querySelector("#metric-frame").textContent = frame.frame_id;
  document.querySelector("#metric-ir").textContent = "95% target · withheld";
  document.querySelector("#metric-ru").textContent = "0 / 10 trials · 10th valid value is final";
  document.querySelector("#spectrum-time").textContent = `${frame.acquisition_midpoint_elapsed_s.toFixed(1)} s`;
  document.querySelector("#spectrum-offset").textContent = `Δt ${offsetS >= 0 ? "+" : ""}${offsetS.toFixed(1)} s`;
  drawTimeline();
  drawSpectrum(frame);
  renderEvents();
}

function setPlaying(nextPlaying) {
  playing = nextPlaying;
  document.querySelector("#play-toggle").textContent = playing ? "Pause" : "Play";
  previousAnimationMs = null;
  if (playing) animationFrame = requestAnimationFrame(animate);
  else if (animationFrame !== null) cancelAnimationFrame(animationFrame);
}

function animate(nowMs) {
  if (!playing) return;
  if (previousAnimationMs === null) previousAnimationMs = nowMs;
  const deltaS = (nowMs - previousAnimationMs) / 1000;
  previousAnimationMs = nowMs;
  const nextTime = selectedTimeS + deltaS * 4;
  if (nextTime >= durationS) {
    updateSelection(durationS);
    setPlaying(false);
    return;
  }
  updateSelection(nextTime);
  animationFrame = requestAnimationFrame(animate);
}

function exportSession() {
  const payload = buildSessionPayload();
  const url = URL.createObjectURL(new Blob([`${JSON.stringify(payload, null, 2)}\n`], { type: "application/json" }));
  const link = document.createElement("a");
  link.href = url;
  link.download = "spectraloop-synchronized-preview.json";
  link.click();
  URL.revokeObjectURL(url);
}

function buildSessionPayload() {
  const selectedSample = nearestByTime(echem, "elapsed_s", selectedTimeS);
  const selectedFrame = nearestByTime(raman, "acquisition_midpoint_elapsed_s", selectedTimeS);
  const frameAlignments = raman.map((frame) => {
    const sample = nearestByTime(echem, "elapsed_s", frame.acquisition_midpoint_elapsed_s);
    return {
      raman_frame_id: frame.frame_id,
      echem_sequence: sample.sequence,
      echem_elapsed_s: sample.elapsed_s,
      delta_t_s: frame.acquisition_midpoint_elapsed_s - sample.elapsed_s,
      method: "nearest_echem_sample_to_raman_midpoint",
    };
  });
  return {
    schema_version: "0.1-preview",
    session_id: sessionId,
    terminal_state: "simulated_complete",
    execution_mode: "simulated",
    hardware_connected: false,
    timing_quality: "simulated_unverified",
    protocol_plan: {
      schema_version: "0.3",
      identifier: "preview-ca-001",
      hash: null,
      hash_status: "not_computed_preview",
    },
    instruments: {
      electrochemistry: { model: "CHI 760E", serial_number: null, firmware_version: null },
      raman: { model: null, serial_number: null, firmware_version: null },
      rde: { model: null, serial_number: null, firmware_version: null },
    },
    software: { interface: "SpectraLoop preview", version: "offline-prototype" },
    optional_disk_rde_demo_enabled: rdePreviewEnabled,
    alignment_method: "nearest_raman_acquisition_midpoint_on_shared_elapsed_time",
    view_selection: {
      selected_elapsed_s: selectedTimeS,
      echem_sequence: selectedSample.sequence,
      echem_elapsed_s: selectedSample.elapsed_s,
      raman_frame_id: selectedFrame.frame_id,
      raman_midpoint_elapsed_s: selectedFrame.acquisition_midpoint_elapsed_s,
      delta_t_s: selectedFrame.acquisition_midpoint_elapsed_s - selectedTimeS,
    },
    frame_alignments: frameAlignments,
    ir_compensation: {
      requested: true,
      target_fraction: 0.95,
      max_trials: 10,
      stop_condition: "confirmed_target_or_trial_ceiling",
      trial_ceiling_behavior: "accept_final_valid_value",
      applied: false,
      ru_ohm: null,
      reason: "installed SDK parameter discovery and hardware readback not performed",
    },
    derived_channels: {
      chronocoulometry_c: {
        method: "trapezoidal",
        source_channel: "current_a",
        initial_charge_c: 0,
        interval: "consecutive elapsed_s samples",
      },
    },
    electrochemistry: echem,
    raman,
    events: activeEvents(),
  };
}

function initializeMonitor() {
  document.querySelector("#time-slider").addEventListener("input", (event) => updateSelection(Number(event.target.value)));
  document.querySelector("#play-toggle").addEventListener("click", () => setPlaying(!playing));
  document.querySelector("#timeline-canvas").addEventListener("click", (event) => {
    const canvas = event.currentTarget;
    const point = canvasPoint(event, canvas);
    const left = 78;
    const right = canvas.width - 24;
    updateSelection(((point.x - left) / (right - left)) * durationS);
  });
  document.querySelector("#event-list").addEventListener("click", (event) => {
    const button = event.target.closest("button[data-time]");
    if (button) updateSelection(Number(button.dataset.time));
  });
  document.querySelector("#export-session").addEventListener("click", exportSession);
  document.querySelector("#rde-preview-enabled").addEventListener("change", (event) => {
    rdePreviewEnabled = event.target.checked;
    echem = buildEchemSeries(rdePreviewEnabled);
    updateSelection(selectedTimeS);
  });
  window.addEventListener("resize", () => updateSelection(selectedTimeS));

  updateSelection(0);
}

const monitorCore = { buildEchemSeries, buildSessionPayload, nearestByTime, raman };

if (typeof globalThis !== "undefined") globalThis.SpectraLoopMonitorCore = monitorCore;

if (typeof document !== "undefined" && document.querySelector("#timeline-canvas")) {
  initializeMonitor();
}

if (typeof module !== "undefined" && module.exports) {
  module.exports = monitorCore;
}

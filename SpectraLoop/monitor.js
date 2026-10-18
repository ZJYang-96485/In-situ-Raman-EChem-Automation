const previewDurationS = 120;
const previewSamplePeriodS = 0.5;
const previewSessionId = "preview-chi760e-ec-only";

function rpmAt(timeS) {
  if (timeS < 20) return 0;
  if (timeS < 45) return 400;
  if (timeS < 70) return 900;
  if (timeS < 95) return 1600;
  return 2500;
}

function buildEchemSeries(withRde) {
  const records = Array.from({ length: Math.floor(previewDurationS / previewSamplePeriodS) + 1 }, (_, index) => {
    const elapsedS = index * previewSamplePeriodS;
    const rpm = withRde ? rpmAt(elapsedS) : 0;
    const potentialV = elapsedS < 12 ? 0.17 + 0.003 * Math.sin(elapsedS / 2.8) : 0.05;
    const rotationTerm = rpm ? -0.0000054 * Math.sqrt(rpm) : 0;
    const transient = elapsedS >= 12 ? -0.00016 * Math.exp(-(elapsedS - 12) / 8) : 0;
    const currentA = rotationTerm + transient + 0.000004 * Math.sin(elapsedS / 2.4);
    return {
      session_id: previewSessionId,
      source: "chi760e_simulated",
      sequence: index,
      technique: "CA",
      source_technique: "ca",
      protocol_step_id: "preview-ca-001",
      protocol_step_name: "Preview CA",
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
        accepted_fraction: null,
        accepted_trial: null,
        selected_ru_ohm: null,
        requested_compensation_ohm: null,
        state: "withheld",
        simulation_only: true,
        hardware_applied: false,
      },
      quality_flags: ["simulated", "timing_unverified", "no_hardware_io"],
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

const raman = [];

function buildPreviewSession(withRde = false) {
  const baseEvents = [
    { elapsed_s: 0, type: "preview_created", label: "Preview session created", detail: "No device connection" },
    { elapsed_s: 3, type: "ir_planned", label: "iR loop planned", detail: "Target 95%; accept trial 10's valid value if needed" },
    { elapsed_s: 8, type: "ir_withheld", label: "iR application withheld", detail: "Static preview only" },
    { elapsed_s: 12, type: "step_started", label: "Simulated CA begins", detail: "0.050 V target" },
    { elapsed_s: 120, type: "preview_complete", label: "Simulated preview complete", detail: "Hardware calls: 0" },
  ];
  const rdeEvents = [20, 45, 70, 95].map((elapsedS) => ({ elapsed_s: elapsedS, type: "rde_setpoint", label: "RDE setpoint", detail: `${rpmAt(elapsedS)} rpm commanded` }));
  return {
    schema_version: "0.1-preview",
    session_id: previewSessionId,
    terminal_state: "simulated_complete",
    execution_mode: "static_preview",
    hardware_connected: false,
    hardware_calls: 0,
    timing_quality: "simulated_unverified",
    protocol_plan: { schema_version: "0.3", identifier: "preview-ca-001", hash: null, hash_status: "not_computed_preview" },
    instruments: {
      electrochemistry: { model: "CHI 760E", serial_number: null, firmware_version: null },
      raman: { connection: "not_configured", simulated: false },
      rde: { model: null, serial_number: null, firmware_version: null },
    },
    optional_disk_rde_demo_enabled: withRde,
    ir_compensation: {
      requested: true,
      target_fraction: 0.95,
      max_trials: 10,
      applied: false,
      hardware_applied: false,
      simulation_only: true,
      reason: "static preview",
    },
    derived_channels: {
      chronocoulometry_c: { method: "trapezoidal", source_channel: "current_a", initial_charge_c: 0, interval: "consecutive elapsed_s samples" },
    },
    electrochemistry: buildEchemSeries(withRde),
    raman,
    events: [...baseEvents, ...(withRde ? rdeEvents : [])].sort((first, second) => first.elapsed_s - second.elapsed_s),
  };
}

let currentSession = buildPreviewSession(false);
let echem = currentSession.electrochemistry;
let durationS = previewDurationS;
let selectedTimeS = 0;
let playing = false;
let playbackRate = 10;
let animationFrame = null;
let previousAnimationMs = null;

function nearestByTime(records, timeKey, targetS) {
  if (!records.length) return null;
  return records.reduce((best, record) => Math.abs(record[timeKey] - targetS) < Math.abs(best[timeKey] - targetS) ? record : best);
}

function formatElapsed(timeS) {
  if (timeS >= 3600) return `${(timeS / 3600).toFixed(1)} h`;
  if (timeS >= 600) return `${(timeS / 60).toFixed(1)} min`;
  return `${timeS.toFixed(timeS < 10 ? 1 : 0)} s`;
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

function extentFor(key, fallback) {
  const values = echem.map((record) => record[key]).filter((value) => Number.isFinite(value));
  if (!values.length) return fallback;
  let minimum = Infinity;
  let maximum = -Infinity;
  values.forEach((value) => {
    minimum = Math.min(minimum, value);
    maximum = Math.max(maximum, value);
  });
  if (minimum === maximum) {
    const padding = Math.max(Math.abs(minimum) * 0.1, 0.01);
    minimum -= padding;
    maximum += padding;
  } else {
    const padding = (maximum - minimum) * 0.08;
    minimum -= padding;
    maximum += padding;
  }
  return [minimum, maximum];
}

function drawTimeline() {
  const canvas = document.querySelector("#timeline-canvas");
  const context = clearCanvas(canvas);
  const potentialExtent = extentFor("potential_v", [-0.1, 0.2]);
  const currentExtent = extentFor("current_a", [-0.0002, 0.0002]);
  const panels = [
    { top: 22, bottom: 142, key: "potential_v", min: potentialExtent[0], max: potentialExtent[1], color: "#275f88", label: "Potential (V)" },
    { top: 172, bottom: 292, key: "current_a", min: currentExtent[0], max: currentExtent[1], color: "#d65e24", label: "Current (A)" },
  ];
  const left = 72;
  const right = canvas.width - 24;
  const safeDuration = Math.max(durationS, 0.001);
  panels.forEach((panel) => {
    const bounds = { left, right, top: panel.top, bottom: panel.bottom };
    drawAxes(
      context,
      bounds,
      [0, 0.25, 0.5, 0.75, 1].map((fraction) => ({ value: formatElapsed(durationS * fraction), x: left + fraction * (right - left) })),
      [panel.min, (panel.min + panel.max) / 2, panel.max].map((value) => ({
        value: Number(value).toPrecision(2),
        y: panel.bottom - ((value - panel.min) / (panel.max - panel.min)) * (panel.bottom - panel.top),
      })),
      panel === panels[panels.length - 1] ? "Elapsed time" : "",
      panel.label,
    );
    context.strokeStyle = panel.color;
    context.lineWidth = 2;
    context.beginPath();
    let drawing = false;
    echem.forEach((record) => {
      const value = record[panel.key];
      if (!Number.isFinite(value)) {
        drawing = false;
        return;
      }
      const x = left + (record.elapsed_s / safeDuration) * (right - left);
      const y = panel.bottom - ((value - panel.min) / (panel.max - panel.min)) * (panel.bottom - panel.top);
      if (!drawing) context.moveTo(x, y); else context.lineTo(x, y);
      drawing = true;
    });
    context.stroke();
  });
  const cursorX = left + (selectedTimeS / safeDuration) * (right - left);
  context.strokeStyle = "#7a4fa1";
  context.lineWidth = 2;
  context.beginPath();
  context.moveTo(cursorX, panels[0].top);
  context.lineTo(cursorX, panels[panels.length - 1].bottom);
  context.stroke();
}

function updateSelection(timeS) {
  selectedTimeS = Math.max(0, Math.min(durationS, Number.isFinite(timeS) ? timeS : 0));
  document.querySelector("#time-slider").value = selectedTimeS;
  document.querySelector("#time-output").textContent = `${formatElapsed(selectedTimeS)} / ${formatElapsed(durationS)}`;
  drawTimeline();
}

function setPlaying(nextPlaying) {
  playing = Boolean(nextPlaying) && durationS > 0;
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
  const nextTime = selectedTimeS + deltaS * playbackRate;
  if (nextTime >= durationS) {
    updateSelection(durationS);
    setPlaying(false);
    return;
  }
  updateSelection(nextTime);
  animationFrame = requestAnimationFrame(animate);
}

function buildSessionPayload() {
  const selectedSample = nearestByTime(echem, "elapsed_s", selectedTimeS);
  return {
    ...currentSession,
    raman: [],
    view_selection: {
      selected_elapsed_s: selectedTimeS,
      echem_sequence: selectedSample?.sequence ?? null,
      echem_elapsed_s: selectedSample?.elapsed_s ?? null,
    },
  };
}

function exportSession() {
  const payload = buildSessionPayload();
  const url = URL.createObjectURL(new Blob([`${JSON.stringify(payload, null, 2)}\n`], { type: "application/json" }));
  const link = document.createElement("a");
  link.href = url;
  link.download = `spectraloop-${payload.session_id}.json`;
  link.click();
  URL.revokeObjectURL(url);
}

function sessionDuration(session) {
  const times = [
    ...session.electrochemistry.map((record) => record.elapsed_s),
    ...session.events.map((event) => event.elapsed_s),
  ].filter(Number.isFinite);
  return Math.max(0, ...times);
}

function renderSessionMeta() {
  const title = document.querySelector("#simulation-session-title");
  const status = document.querySelector("#simulation-session-status");
  const state = document.querySelector("#simulation-session-state");
  const protocolName = currentSession.protocol_plan?.protocol_name || "Static preview";
  title.textContent = protocolName;
  const warningCount = currentSession.simulator?.warnings?.length || 0;
  status.textContent = `${echem.length} EChem points · 0 hardware calls${warningCount ? ` · ${warningCount} simulator warning${warningCount === 1 ? "" : "s"}` : ""}`;
  state.textContent = currentSession.terminal_state === "simulated_complete" ? "Complete" : "Failure visible";
  state.classList.toggle("failed", currentSession.terminal_state !== "simulated_complete");
  state.classList.remove("stale");
  document.querySelector("#timeline-title").textContent = `${protocolName} · electrochemistry`;
}

function loadSimulationSession(session, options = {}) {
  if (!session || session.hardware_connected !== false || session.hardware_calls !== 0) throw new Error("Only connection-free sessions can be loaded");
  if (!Array.isArray(session.electrochemistry) || !session.electrochemistry.length || !Array.isArray(session.events)) {
    throw new Error("Simulation session is incomplete");
  }
  session.electrochemistry.slice(1).forEach((record, index) => {
    if (!(record.elapsed_s > session.electrochemistry[index].elapsed_s)) throw new Error("Simulation timestamps must be strictly increasing");
  });
  setPlaying(false);
  currentSession = session;
  echem = session.electrochemistry;
  durationS = sessionDuration(session);
  const slider = document.querySelector("#time-slider");
  slider.max = durationS;
  slider.step = Math.max(0.01, durationS / 2000);
  selectedTimeS = 0;
  renderSessionMeta();
  updateSelection(0);
  if (options.autoplay) setPlaying(true);
}

function initializeMonitor() {
  document.querySelector("#time-slider").addEventListener("input", (event) => updateSelection(Number(event.target.value)));
  document.querySelector("#play-toggle").addEventListener("click", () => setPlaying(!playing));
  document.querySelector("#timeline-canvas").addEventListener("click", (event) => {
    const canvas = event.currentTarget;
    const point = canvasPoint(event, canvas);
    const left = 72;
    const right = canvas.width - 24;
    updateSelection(((point.x - left) / (right - left)) * durationS);
  });
  document.querySelector("#export-session").addEventListener("click", exportSession);
  document.querySelector("#playback-speed").addEventListener("change", (event) => { playbackRate = Number(event.target.value); });
  document.querySelector("#replay-simulation").addEventListener("click", () => { updateSelection(0); setPlaying(true); });
  window.addEventListener("resize", () => updateSelection(selectedTimeS));
  renderSessionMeta();
  updateSelection(0);
}

const monitorCore = { buildEchemSeries, buildSessionPayload, buildPreviewSession, loadSimulationSession, nearestByTime, raman };
if (typeof globalThis !== "undefined") globalThis.SpectraLoopMonitorCore = monitorCore;
if (typeof document !== "undefined" && document.querySelector("#timeline-canvas")) initializeMonitor();
if (typeof module !== "undefined" && module.exports) module.exports = monitorCore;

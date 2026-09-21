const capabilityProfiles = {
  "760B": ["CV", "i-t"],
  "760C": ["CV", "i-t", "EIS"],
  "760D": ["CV", "i-t", "LSV", "EIS", "OCP"],
  "760E": ["CV", "i-t", "EIS", "OCP"],
};

const allTechniques = ["CV", "i-t", "LSV", "EIS", "OCP"];
const defaultFormState = {
  chiModel: "760B",
  chiBackend: "mock",
  ramanBackend: "mock",
  exposure: "0.1",
  accumulations: "1",
  spectraCount: "1",
  interDelay: "0",
  excitation: "",
  despike: "",
  smoothing: "1",
  baseline: "none",
  normalization: "none",
  projectName: "operando-raman-study",
  analysisTask: "exploratory",
  targetName: "",
  validationFraction: "0.2",
};

const fieldIds = Object.keys(defaultFormState);
const formStatus = document.querySelector("#form-status");
const preview = document.querySelector("#config-preview");
const targetField = document.querySelector("#target-field");
const tabs = document.querySelectorAll(".tab");
const sections = document.querySelectorAll(".setup-section");

function readForm() {
  return Object.fromEntries(fieldIds.map((id) => [id, document.querySelector(`#${toKebab(id)}`).value]));
}

function toKebab(value) {
  return value.replace(/[A-Z]/g, (character) => `-${character.toLowerCase()}`);
}

function asNumber(value) {
  return value === "" ? null : Number(value);
}

function buildConfiguration() {
  const state = readForm();
  const supervised = ["regression", "classification"].includes(state.analysisTask);
  return {
    application: {
      name: "SpectraLoop - Adaptive Operando Raman Spectroscopy Platform",
      schema_version: "0.1",
      mode: "configuration_only",
      generated_at: new Date().toISOString(),
    },
    potentiostat: {
      family: "CHI 760 series",
      model: state.chiModel,
      backend: state.chiBackend,
      connection_enabled: false,
      supported_automation_techniques: capabilityProfiles[state.chiModel],
    },
    raman: {
      backend: state.ramanBackend,
      connection_enabled: false,
      hardware_verified: false,
      trigger_mode: "software",
      laser_control_enabled: false,
      acquisition: {
        exposure_time_s: asNumber(state.exposure),
        accumulations: asNumber(state.accumulations),
        spectra_count: asNumber(state.spectraCount),
        inter_spectrum_delay_s: asNumber(state.interDelay),
        excitation_wavelength_nm: asNumber(state.excitation),
      },
      preprocessing: {
        owner: "Raman Spectroscopy",
        despike_threshold: asNumber(state.despike),
        smoothing_window_points: asNumber(state.smoothing),
        baseline_mode: state.baseline,
        normalization: state.normalization,
      },
    },
    analysis: {
      workspace: "Machine Learning Platform",
      accepts: "preprocessed_raman_features_with_provenance",
      preprocessing_owner: "Raman Spectroscopy",
      project_name: state.projectName.trim(),
      task: state.analysisTask,
      target_name: supervised ? state.targetName.trim() || null : null,
      validation_fraction: asNumber(state.validationFraction),
    },
  };
}

function validate() {
  const state = readForm();
  const numericChecks = [
    ["Exposure time", Number(state.exposure) > 0],
    ["Accumulations", Number.isInteger(Number(state.accumulations)) && Number(state.accumulations) >= 1],
    ["Spectra per capture", Number.isInteger(Number(state.spectraCount)) && Number(state.spectraCount) >= 1],
    ["Inter-spectrum delay", Number(state.interDelay) >= 0],
    ["Smoothing window", Number.isInteger(Number(state.smoothing)) && Number(state.smoothing) >= 1 && Number(state.smoothing) % 2 === 1],
    ["Validation fraction", Number(state.validationFraction) > 0 && Number(state.validationFraction) < 1],
  ];
  if (state.despike && Number(state.despike) <= 0) numericChecks.push(["Despike threshold", false]);
  if (state.excitation && Number(state.excitation) <= 0) numericChecks.push(["Excitation wavelength", false]);
  if (!state.projectName.trim()) numericChecks.push(["Analysis project name", false]);
  if (["regression", "classification"].includes(state.analysisTask) && !state.targetName.trim()) {
    numericChecks.push(["Target name", false]);
  }
  const failed = numericChecks.filter(([, isValid]) => !isValid).map(([label]) => label);
  return failed;
}

function refreshCapabilities() {
  const model = document.querySelector("#chi-model").value;
  const available = capabilityProfiles[model];
  document.querySelector("#profile-title").textContent = `CHI ${model} automation surface`;
  document.querySelector("#chi-capabilities").innerHTML = allTechniques
    .map((technique) => `<li class="${available.includes(technique) ? "available" : ""}">${available.includes(technique) ? "✓" : "—"} ${technique}</li>`)
    .join("");
  document.querySelector("#profile-note").textContent =
    "Capabilities are model-profile gates for the project’s documented automation surface. They are not a live connection check or a complete hardware specification.";
}

function refreshTaskFields() {
  const supervised = ["regression", "classification"].includes(document.querySelector("#analysis-task").value);
  targetField.hidden = !supervised;
  document.querySelector("#target-name").required = supervised;
}

function refreshPreview() {
  preview.textContent = JSON.stringify(buildConfiguration(), null, 2);
}

function openSection(targetId) {
  sections.forEach((section) => {
    const active = section.id === targetId;
    section.hidden = !active;
    section.classList.toggle("active", active);
  });
  tabs.forEach((tab) => tab.classList.toggle("active", tab.dataset.target === targetId));
  if (targetId === "review") refreshPreview();
}

function storeSetup() {
  const failed = validate();
  if (failed.length) {
    formStatus.textContent = `Fix: ${failed.join(", ")}.`;
    formStatus.style.color = "var(--danger)";
    return null;
  }
  const setup = buildConfiguration();
  localStorage.setItem("spectraloop-setup", JSON.stringify(setup));
  formStatus.textContent = "Setup saved locally in this browser. No hardware was contacted.";
  formStatus.style.color = "var(--safe)";
  return setup;
}

function exportSetup() {
  const setup = storeSetup();
  if (!setup) return;
  const content = JSON.stringify(setup, null, 2);
  const url = URL.createObjectURL(new Blob([content], { type: "application/json" }));
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = "spectraloop-setup.json";
  anchor.click();
  URL.revokeObjectURL(url);
  formStatus.textContent = "Setup JSON exported. It contains configuration only; no device state.";
}

function restoreDefaults() {
  Object.entries(defaultFormState).forEach(([id, value]) => {
    document.querySelector(`#${toKebab(id)}`).value = value;
  });
  refreshCapabilities();
  refreshTaskFields();
  refreshPreview();
  formStatus.textContent = "Defaults restored. Offline mode remains active.";
  formStatus.style.color = "var(--muted)";
}

tabs.forEach((tab) => tab.addEventListener("click", () => openSection(tab.dataset.target)));
document.querySelector("#chi-model").addEventListener("change", () => { refreshCapabilities(); refreshPreview(); });
document.querySelector("#analysis-task").addEventListener("change", () => { refreshTaskFields(); refreshPreview(); });
fieldIds.forEach((id) => document.querySelector(`#${toKebab(id)}`).addEventListener("input", refreshPreview));
document.querySelector("#save-button").addEventListener("click", storeSetup);
document.querySelector("#export-button").addEventListener("click", exportSetup);
document.querySelector("#reset-button").addEventListener("click", restoreDefaults);

refreshCapabilities();
refreshTaskFields();
refreshPreview();

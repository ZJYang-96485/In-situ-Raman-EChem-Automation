const capabilityProfiles = {
  "760B": { direct: ["CV", "i-t"] },
  "760C": { direct: ["CV", "i-t", "EIS"] },
  "760D": { direct: ["CV", "i-t", "LSV", "EIS", "OCP"] },
  "760E": {
    direct: ["CV", "i-t", "CA", "SWV", "EIS", "IMPE", "OCP", "STEP", "ISTEP/CPCS"],
    derived: ["Chronocoulometry (CC) = ∫I dt from CA"],
    desktop: ["LSV"],
    verify: ["GEIS", "iR compensation"],
  },
};

const allTechniques = ["CV", "i-t", "CA", "SWV", "EIS", "IMPE", "OCP", "STEP", "ISTEP/CPCS", "Chronocoulometry (CC) = ∫I dt from CA", "LSV", "GEIS", "iR compensation"];
const defaultFormState = {
  chiModel: "760E",
  chiBackend: "local_bridge",
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
const bridgeSummary = document.querySelector("#bridge-summary");
const bridgeStateElement = document.querySelector("#bridge-state");
const bridgeDetail = document.querySelector("#bridge-detail");
const storageState = document.querySelector("#storage-state");
const storageDetail = document.querySelector("#storage-detail");
const instrumentState = document.querySelector("#instrument-state");
const instrumentDetail = document.querySelector("#instrument-detail");
const storageButton = document.querySelector("#select-storage-button");
const refreshBridgeButton = document.querySelector("#refresh-bridge-button");
const discoveryButton = document.querySelector("#discover-instrument-button");
const confirmationFieldset = document.querySelector("#identity-confirmations");
const confirmationInputs = Array.from(document.querySelectorAll("[data-confirmation]"));
const bridgeActionStatus = document.querySelector("#bridge-action-status");
let bridgeClient = null;
let bridgeSnapshot = null;

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
      name: "SpectraLoop - Adaptive Operando Raman Electrochemistry and Decision Automation Platform",
      schema_version: "0.2",
      mode: "local_bridge_ready_configuration",
      generated_at: new Date().toISOString(),
    },
    potentiostat: {
      family: "CHI 760 series",
      model: state.chiModel,
      backend: state.chiBackend,
      connection_enabled: false,
      identity_connection_enabled: state.chiBackend === "local_bridge"
        && Boolean(bridgeSnapshot?.instrument?.discovery_enabled),
      experiment_control_enabled: false,
      automation_capabilities: capabilityProfiles[state.chiModel],
      live_capabilities_verified: false,
    },
    storage: {
      managed_by: "local_bridge",
      configured: Boolean(bridgeSnapshot?.storage?.configured),
      available: Boolean(bridgeSnapshot?.storage?.available),
      folder_name: bridgeSnapshot?.storage?.folder_name || null,
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
  const profile = capabilityProfiles[model];
  const statusFor = (technique) => Object.entries(profile).find(([, techniques]) => techniques.includes(technique))?.[0] || null;
  const labelFor = (status) => ({ direct: "documented libec", derived: "derived", desktop: "desktop only", verify: "verify SDK" }[status]);
  const iconFor = (status) => ({ direct: "✓", derived: "ƒ", desktop: "↗", verify: "?" }[status] || "—");
  document.querySelector("#profile-title").textContent = `CHI ${model} automation surface`;
  document.querySelector("#chi-capabilities").innerHTML = allTechniques
    .map((technique) => {
      const status = statusFor(technique);
      return `<li class="${status || "unavailable"}">${iconFor(status)} ${technique}${status ? ` · ${labelFor(status)}` : ""}</li>`;
    })
    .join("");
  document.querySelector("#profile-note").textContent =
    "Documented libec entries come from the public model matrix. Derived, desktop-only, and verify-SDK entries are intentionally separate. None is a live connection check.";
}

function refreshTaskFields() {
  const supervised = ["regression", "classification"].includes(document.querySelector("#analysis-task").value);
  targetField.hidden = !supervised;
  document.querySelector("#target-name").required = supervised;
}

function refreshPreview() {
  preview.textContent = JSON.stringify(buildConfiguration(), null, 2);
}

function statusDot(kind) {
  const dot = document.createElement("span");
  dot.className = `status-dot ${kind}`;
  return dot;
}

function setLabeledStatus(element, text, kind) {
  element.replaceChildren(statusDot(kind), document.createTextNode(text));
}

function selectedConfirmations() {
  return Object.fromEntries(
    confirmationInputs.map((input) => [input.dataset.confirmation, input.checked]),
  );
}

function updateDiscoveryButton() {
  const allConfirmed = confirmationInputs.every((input) => input.checked);
  discoveryButton.disabled = !bridgeClient
    || !bridgeSnapshot?.instrument?.discovery_enabled
    || !allConfirmed;
}

function showBridgeUnavailable(message) {
  bridgeSnapshot = null;
  setLabeledStatus(bridgeStateElement, "Not connected", "amber");
  bridgeDetail.textContent = message;
  storageState.textContent = "Unavailable";
  storageDetail.textContent = "Start the local bridge before choosing a folder.";
  instrumentState.textContent = "Unavailable";
  instrumentDetail.textContent = "No instrument request was made.";
  setLabeledStatus(bridgeSummary, "Local bridge not connected", "amber");
  storageButton.disabled = true;
  confirmationFieldset.disabled = true;
  updateDiscoveryButton();
  refreshPreview();
}

function renderBridgeStatus(snapshot) {
  bridgeSnapshot = snapshot;
  setLabeledStatus(bridgeStateElement, "Connected locally", "safe");
  bridgeDetail.textContent = `${snapshot.service.name} ${snapshot.service.version} · loopback only`;
  setLabeledStatus(bridgeSummary, "Local bridge connected", "safe");
  storageButton.disabled = false;

  if (snapshot.storage.configured) {
    storageState.textContent = snapshot.storage.available
      ? snapshot.storage.folder_name
      : `${snapshot.storage.folder_name} (unavailable)`;
    storageDetail.textContent = snapshot.storage.available
      ? "The full path stays in the local bridge and is not exposed to the public site."
      : "Choose an available folder before saving experiment data.";
  } else {
    storageState.textContent = "Not selected";
    storageDetail.textContent = "Choose a folder using the normal Windows folder picker.";
  }

  const instrument = snapshot.instrument;
  if (instrument.discovery_enabled) {
    instrumentState.textContent = `${instrument.target} - SDK check ready`;
    instrumentDetail.textContent = instrument.detail
      || "The persistent worker is ready; physical instrument identity is not confirmed.";
    confirmationFieldset.disabled = false;
  } else {
    instrumentState.textContent = `${instrument.target} · adapter unavailable`;
    instrumentDetail.textContent = instrument.blocker || "A verified local adapter is required.";
    confirmationFieldset.disabled = true;
  }
  updateDiscoveryButton();
  refreshPreview();
}

function bridgeBaseUrl() {
  return window.location.hostname === "127.0.0.1"
    ? window.location.origin
    : SpectraLoopBridge.DEFAULT_BRIDGE_URL;
}

async function refreshBridgeStatus() {
  if (typeof SpectraLoopBridge === "undefined") {
    bridgeClient = null;
    showBridgeUnavailable("The local bridge client did not load. Refresh this page after the site update is deployed.");
    return;
  }
  const token = SpectraLoopBridge.consumeBridgeToken();
  const localCookieAuth = window.location.hostname === "127.0.0.1";
  if (!token && !localCookieAuth) {
    bridgeClient = null;
    showBridgeUnavailable("Double-click Start SpectraLoop.cmd on the instrument computer, then use the page it opens.");
    return;
  }
  try {
    bridgeClient = new SpectraLoopBridge.BridgeClient({
      token,
      baseUrl: bridgeBaseUrl(),
      cookieAuth: !token && localCookieAuth,
    });
    renderBridgeStatus(await bridgeClient.status());
    bridgeActionStatus.textContent = "Bridge verified. No hardware request has been made.";
    bridgeActionStatus.style.color = "var(--safe)";
  } catch (error) {
    bridgeClient = null;
    showBridgeUnavailable(error.message);
    bridgeActionStatus.textContent = error.message;
    bridgeActionStatus.style.color = "var(--danger)";
  }
}

async function selectStorageFolder() {
  if (!bridgeClient) return;
  storageButton.disabled = true;
  bridgeActionStatus.textContent = "Waiting for the Windows folder picker…";
  bridgeActionStatus.style.color = "var(--muted)";
  try {
    const result = await bridgeClient.selectStorageFolder();
    if (result.storage.cancelled) {
      bridgeActionStatus.textContent = "Folder selection cancelled; the previous setting was preserved.";
    } else {
      bridgeActionStatus.textContent = `Data folder selected: ${result.storage.folder_name}.`;
      bridgeActionStatus.style.color = "var(--safe)";
    }
    renderBridgeStatus(await bridgeClient.status());
  } catch (error) {
    bridgeActionStatus.textContent = error.message;
    bridgeActionStatus.style.color = "var(--danger)";
    storageButton.disabled = false;
  }
}

async function discoverInstrumentIdentity() {
  if (!bridgeClient || discoveryButton.disabled) return;
  discoveryButton.disabled = true;
  bridgeActionStatus.textContent = "Running the read-only SDK capability check…";
  bridgeActionStatus.style.color = "var(--warning)";
  try {
    const result = await bridgeClient.discoverInstrument(selectedConfirmations());
    const identity = result.discovery.identity;
    bridgeActionStatus.textContent = result.discovery.physical_connection_confirmed
      ? `Verified ${identity.model}; serial ${identity.serial_number}; firmware ${identity.firmware_version}.`
      : `${identity.model} SDK capabilities read successfully; physical instrument identity is not confirmed.`;
    bridgeActionStatus.style.color = "var(--safe)";
    renderBridgeStatus(await bridgeClient.status());
  } catch (error) {
    bridgeActionStatus.textContent = error.message;
    bridgeActionStatus.style.color = "var(--danger)";
    updateDiscoveryButton();
  }
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
  formStatus.textContent = "Setup saved in this browser. Instrument and storage settings remain managed by the local bridge.";
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
  formStatus.textContent = "Defaults restored. Hardware safety gates remain active.";
  formStatus.style.color = "var(--muted)";
}

tabs.forEach((tab) => tab.addEventListener("click", () => openSection(tab.dataset.target)));
document.querySelector("#chi-model").addEventListener("change", () => { refreshCapabilities(); refreshPreview(); });
document.querySelector("#analysis-task").addEventListener("change", () => { refreshTaskFields(); refreshPreview(); });
fieldIds.forEach((id) => document.querySelector(`#${toKebab(id)}`).addEventListener("input", refreshPreview));
document.querySelector("#save-button").addEventListener("click", storeSetup);
document.querySelector("#export-button").addEventListener("click", exportSetup);
document.querySelector("#reset-button").addEventListener("click", restoreDefaults);
refreshBridgeButton.addEventListener("click", refreshBridgeStatus);
storageButton.addEventListener("click", selectStorageFolder);
discoveryButton.addEventListener("click", discoverInstrumentIdentity);
confirmationInputs.forEach((input) => input.addEventListener("change", updateDiscoveryButton));

refreshCapabilities();
refreshTaskFields();
refreshPreview();
refreshBridgeStatus();

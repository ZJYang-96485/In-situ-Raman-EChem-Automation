(function exposeEchemBridge(root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  root.SpectraLoopEchemBridgeCore = api;
  if (typeof document !== "undefined" && document.querySelector("#echem-bridge-state")) {
    api.initialize(document, window, root.SpectraLoopBridge);
  }
})(typeof globalThis === "object" ? globalThis : this, function buildEchemBridge() {
  "use strict";

  function describeSnapshot(snapshot) {
    const storage = snapshot.storage || {};
    const instrument = snapshot.instrument || {};
    const desktop760d = snapshot.desktop_760d || {};
    const dummyReady = desktop760d.experiment_control_enabled === true;
    return {
      header: dummyReady
        ? "Local bridge connected - 760D dummy test ready"
        : instrument.discovery_enabled
        ? "Local bridge connected - SDK worker ready"
        : "Local bridge connected · CHI control locked",
      storageLabel: storage.configured
        ? `${storage.folder_name || "Selected folder"}${storage.available ? "" : " (unavailable)"}`
        : "Not selected",
      storageDetail: storage.configured && storage.available
        ? "The full path remains inside the local bridge."
        : storage.configured
          ? "Choose an available folder before recording data."
          : "Choose a folder using the normal Windows folder picker.",
      instrumentLabel: instrument.discovery_enabled
        ? `${instrument.target || "Instrument"} - SDK check ready`
        : `${instrument.target || "Instrument"} · adapter unavailable`,
      instrumentDetail: instrument.discovery_enabled
        ? instrument.detail || "The worker is ready; physical instrument identity is not confirmed."
        : instrument.blocker || "A verified local vendor adapter is required.",
      discoveryEnabled: instrument.discovery_enabled === true,
      dummyReady,
      dummyState: desktop760d.state || "adapter_unavailable",
      dummyDetail: desktop760d.blocker
        || (desktop760d.active?.running
          ? `Run ${desktop760d.active.run_label} is active in the CHI desktop.`
          : "The audited CHI 760D executable is ready for an internal-dummy CV."),
    };
  }

  function initialize(doc, browserWindow, bridgeApi) {
    const elements = {
      summary: doc.querySelector("#echem-bridge-summary"),
      bridgeState: doc.querySelector("#echem-bridge-state"),
      bridgeDetail: doc.querySelector("#echem-bridge-detail"),
      storageState: doc.querySelector("#echem-storage-state"),
      storageDetail: doc.querySelector("#echem-storage-detail"),
      instrumentState: doc.querySelector("#echem-instrument-state"),
      instrumentDetail: doc.querySelector("#echem-instrument-detail"),
      actionStatus: doc.querySelector("#echem-bridge-action-status"),
      checkStatus: doc.querySelector("#echem-bridge-check-status"),
      refreshButton: doc.querySelector("#echem-refresh-bridge"),
      storageButton: doc.querySelector("#echem-select-storage"),
      discoveryButton: doc.querySelector("#echem-discover-instrument"),
      confirmationFieldset: doc.querySelector("#echem-identity-confirmations"),
      confirmationInputs: Array.from(doc.querySelectorAll("[data-echem-confirmation]")),
      runnerState: doc.querySelector("#chi760d-runner-state"),
      runnerDetail: doc.querySelector("#chi760d-runner-detail"),
      runnerActionStatus: doc.querySelector("#chi760d-run-action-status"),
      runnerFieldset: doc.querySelector("#chi760d-run-confirmations"),
      runnerInputs: Array.from(doc.querySelectorAll("[data-chi760d-confirmation]")),
      prepareButton: doc.querySelector("#chi760d-prepare-run"),
      startButton: doc.querySelector("#chi760d-start-run"),
    };
    let client = null;
    let snapshot = null;
    let preparationToken = null;

    function dot(kind) {
      const marker = doc.createElement("span");
      marker.className = `status-dot ${kind}`;
      return marker;
    }

    function labeledStatus(element, text, kind) {
      element.replaceChildren(dot(kind), doc.createTextNode(text));
    }

    function checkMessage(text, kind = "") {
      elements.checkStatus.textContent = text;
      elements.checkStatus.className = `bridge-check-status${kind ? ` ${kind}` : ""}`;
    }

    function confirmations() {
      return Object.fromEntries(
        elements.confirmationInputs.map((input) => [input.dataset.echemConfirmation, input.checked]),
      );
    }

    function runnerConfirmations() {
      return Object.fromEntries(
        elements.runnerInputs.map((input) => [input.dataset.chi760dConfirmation, input.checked]),
      );
    }

    function updateDiscoveryButton() {
      elements.discoveryButton.disabled = !client
        || snapshot?.instrument?.discovery_enabled !== true
        || !elements.confirmationInputs.every((input) => input.checked);
    }

    function updateRunnerButtons() {
      const ready = Boolean(client)
        && snapshot?.desktop_760d?.experiment_control_enabled === true
        && snapshot?.storage?.available === true
        && snapshot?.desktop_760d?.active?.running !== true;
      elements.prepareButton.disabled = !ready;
      elements.startButton.disabled = !ready
        || !preparationToken
        || !elements.runnerInputs.every((input) => input.checked);
    }

    function showUnavailable(message) {
      snapshot = null;
      labeledStatus(elements.summary, "Local bridge not connected · no hardware I/O", "amber");
      labeledStatus(elements.bridgeState, "Not connected", "amber");
      elements.bridgeDetail.textContent = message;
      elements.storageState.textContent = "Unavailable";
      elements.storageDetail.textContent = "Start the local bridge before choosing a folder.";
      elements.instrumentState.textContent = "Not connected";
      elements.instrumentDetail.textContent = "No request was sent to the CHI 760E.";
      elements.storageButton.disabled = true;
      elements.confirmationFieldset.disabled = true;
      labeledStatus(elements.runnerState, "Not connected", "amber");
      elements.runnerDetail.textContent = "Start SpectraLoop 760D.cmd on the instrument computer.";
      elements.runnerFieldset.disabled = true;
      preparationToken = null;
      updateDiscoveryButton();
      updateRunnerButtons();
    }

    function renderStatus(nextSnapshot) {
      snapshot = nextSnapshot;
      const view = describeSnapshot(snapshot);
      labeledStatus(elements.summary, view.header, view.discoveryEnabled ? "safe" : "amber");
      labeledStatus(elements.bridgeState, "Connected to local service", "safe");
      elements.bridgeDetail.textContent = `${snapshot.service.name} ${snapshot.service.version} · loopback only`;
      elements.storageState.textContent = view.storageLabel;
      elements.storageDetail.textContent = view.storageDetail;
      elements.instrumentState.textContent = view.instrumentLabel;
      elements.instrumentDetail.textContent = view.instrumentDetail;
      elements.storageButton.disabled = false;
      elements.confirmationFieldset.disabled = !view.discoveryEnabled;
      labeledStatus(
        elements.runnerState,
        view.dummyReady ? "Internal-dummy CV ready" : "760D execution locked",
        view.dummyReady ? "safe" : "amber",
      );
      elements.runnerDetail.textContent = view.dummyDetail;
      elements.runnerDetail.className = `bridge-check-status ${view.dummyReady ? "safe" : "warning"}`;
      elements.runnerFieldset.disabled = !view.dummyReady;
      updateDiscoveryButton();
      updateRunnerButtons();
    }

    function bridgeBaseUrl() {
      return browserWindow.location.hostname === "127.0.0.1"
        ? browserWindow.location.origin
        : bridgeApi.DEFAULT_BRIDGE_URL;
    }

    async function refresh() {
      elements.refreshButton.disabled = true;
      elements.refreshButton.textContent = "Checking…";
      checkMessage("Checking the authenticated bridge at 127.0.0.1:8765…", "warning");
      if (!bridgeApi) {
        client = null;
        showUnavailable("The bridge client is not present in this deployed site version.");
        checkMessage("Bridge check failed: this deployed page does not include the local bridge client.", "failed");
        elements.refreshButton.disabled = false;
        elements.refreshButton.textContent = "Check bridge";
        return;
      }
      const token = bridgeApi.consumeBridgeToken();
      const localCookieAuth = browserWindow.location.hostname === "127.0.0.1";
      if (!token && !localCookieAuth) {
        client = null;
        showUnavailable("A bridge session token is missing. The webpage cannot start a Windows program by itself.");
        checkMessage("Bridge not checked: double-click Start SpectraLoop.cmd on this computer and use the page that it opens. Keep its console window open.", "failed");
        elements.refreshButton.disabled = false;
        elements.refreshButton.textContent = "Check bridge";
        return;
      }
      try {
        client = new bridgeApi.BridgeClient({
          token,
          baseUrl: bridgeBaseUrl(),
          cookieAuth: !token && localCookieAuth,
        });
        renderStatus(await client.status());
        checkMessage("Local bridge responded and authentication succeeded.", "safe");
        elements.actionStatus.textContent = "Bridge verified. No CHI hardware request has been made.";
        elements.actionStatus.style.color = "var(--safe)";
      } catch (error) {
        client = null;
        showUnavailable(error.message);
        checkMessage(`Bridge check failed: ${error.message}`, "failed");
        elements.actionStatus.textContent = error.message;
        elements.actionStatus.style.color = "var(--danger)";
      } finally {
        elements.refreshButton.disabled = false;
        elements.refreshButton.textContent = "Check bridge";
      }
    }

    async function selectStorage() {
      if (!client) return;
      elements.storageButton.disabled = true;
      elements.actionStatus.textContent = "Waiting for the Windows folder picker…";
      elements.actionStatus.style.color = "var(--muted)";
      try {
        const result = await client.selectStorageFolder();
        elements.actionStatus.textContent = result.storage.cancelled
          ? "Folder selection cancelled; the previous setting was preserved."
          : `Data folder selected: ${result.storage.folder_name}.`;
        elements.actionStatus.style.color = result.storage.cancelled ? "var(--muted)" : "var(--safe)";
        renderStatus(await client.status());
      } catch (error) {
        elements.actionStatus.textContent = error.message;
        elements.actionStatus.style.color = "var(--danger)";
        elements.storageButton.disabled = false;
      }
    }

    async function discoverIdentity() {
      if (!client || elements.discoveryButton.disabled) return;
      elements.discoveryButton.disabled = true;
      elements.actionStatus.textContent = "Waiting for local Windows approval, then checking SDK capabilities…";
      elements.actionStatus.style.color = "var(--warning)";
      try {
        const result = await client.discoverInstrument(confirmations());
        const identity = result.discovery.identity;
        renderStatus(await client.status());
        elements.instrumentState.textContent = result.discovery.physical_connection_confirmed
          ? `${identity.model} - physical identity verified`
          : `${identity.model} - SDK capabilities checked`;
        elements.actionStatus.textContent = result.discovery.physical_connection_confirmed
          ? `Serial ${identity.serial_number}; firmware ${identity.firmware_version}; software ${identity.software_version}.`
          : "The persistent 32-bit worker responded, but the physical instrument is not yet confirmed.";
        elements.actionStatus.style.color = "var(--safe)";
      } catch (error) {
        elements.actionStatus.textContent = error.message;
        elements.actionStatus.style.color = "var(--danger)";
        updateDiscoveryButton();
      }
    }

    async function prepare760DRun() {
      if (!client || elements.prepareButton.disabled) return;
      const protocolCore = browserWindow.SpectraLoopProtocolCore;
      if (!protocolCore || typeof protocolCore.buildValidatedPlan !== "function") {
        elements.runnerActionStatus.textContent = "The protocol builder is unavailable.";
        elements.runnerActionStatus.style.color = "var(--danger)";
        return;
      }
      elements.prepareButton.disabled = true;
      elements.runnerActionStatus.textContent = "Validating the bounded protocol and reserving a unique run folder...";
      elements.runnerActionStatus.style.color = "var(--warning)";
      try {
        const result = await client.prepare760DDummyCV(protocolCore.buildValidatedPlan());
        preparationToken = result.preparation.preparation_token;
        const summary = result.preparation.summary;
        elements.runnerActionStatus.textContent = `Prepared ${result.preparation.run_label}: ${summary.low_v} to ${summary.high_v} V at ${summary.scan_rate_v_s} V/s. Check every confirmation to start.`;
        elements.runnerActionStatus.style.color = "var(--safe)";
      } catch (error) {
        preparationToken = null;
        elements.runnerActionStatus.textContent = error.message;
        elements.runnerActionStatus.style.color = "var(--danger)";
      } finally {
        updateRunnerButtons();
      }
    }

    async function start760DRun() {
      if (!client || !preparationToken || elements.startButton.disabled) return;
      elements.startButton.disabled = true;
      elements.runnerActionStatus.textContent = "Waiting for approval in the local Windows dialog...";
      elements.runnerActionStatus.style.color = "var(--warning)";
      try {
        const result = await client.run760DDummyCV(preparationToken, runnerConfirmations());
        preparationToken = null;
        elements.runnerInputs.forEach((input) => { input.checked = false; });
        elements.runnerActionStatus.textContent = `${result.run.run_label} started in CHI 760D. Keep the CHI window visible and use its Stop button if needed.`;
        elements.runnerActionStatus.style.color = "var(--safe)";
        renderStatus(await client.status());
      } catch (error) {
        elements.runnerActionStatus.textContent = error.message;
        elements.runnerActionStatus.style.color = "var(--danger)";
        updateRunnerButtons();
      }
    }

    elements.refreshButton.addEventListener("click", refresh);
    elements.storageButton.addEventListener("click", selectStorage);
    elements.discoveryButton.addEventListener("click", discoverIdentity);
    elements.confirmationInputs.forEach((input) => input.addEventListener("change", updateDiscoveryButton));
    elements.prepareButton.addEventListener("click", prepare760DRun);
    elements.startButton.addEventListener("click", start760DRun);
    elements.runnerInputs.forEach((input) => input.addEventListener("change", updateRunnerButtons));
    refresh();

    return { refresh };
  }

  return { describeSnapshot, initialize };
});

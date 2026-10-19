(function exposeEchemBridge(root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  root.SpectraLoopEchemBridgeCore = api;
  if (typeof document !== "undefined" && document.querySelector("#echem-bridge-state")) {
    api.initialize(document, window, root.SpectraLoopBridge);
  }
})(typeof globalThis === "object" ? globalThis : this, function buildEchemBridge() {
  "use strict";

  let activeClient = null;

  function describeSnapshot(snapshot, selectedModel = "760E") {
    const storage = snapshot.storage || {};
    const instrument = snapshot.instrument || {};
    const desktop760d = snapshot.desktop_760d || {};
    const model = ["760B", "760D", "760E"].includes(selectedModel) ? selectedModel : "760E";
    const dummyReady = model === "760D" && desktop760d.experiment_control_enabled === true;
    const sdkReady = model === "760E" && instrument.discovery_enabled === true;
    const commissioning760EReady = model === "760E"
      && instrument.experiment_control_enabled === true;
    let instrumentLabel;
    let instrumentDetail;
    if (model === "760B") {
      instrumentLabel = "CHI 760B - measurement protected";
      instrumentDetail = "Offline CV and i-t planning only. No live 760B adapter is configured, and the active measurement remains untouched.";
    } else if (model === "760D") {
      instrumentLabel = dummyReady
        ? "CHI 760D - internal-dummy adapter ready"
        : "CHI 760D - desktop adapter unavailable";
      instrumentDetail = desktop760d.blocker
        || (desktop760d.active?.running
          ? `Run ${desktop760d.active.run_label} is active in the CHI desktop.`
          : "The audited desktop adapter is limited to an explicitly approved internal-dummy CV/wait series.");
    } else {
      instrumentLabel = commissioning760EReady
        ? `${instrument.target || "CHI 760E"} - bounded CV control ready`
        : sdkReady
        ? `${instrument.target || "CHI 760E"} - SDK check ready`
        : `${instrument.target || "CHI 760E"} - adapter unavailable`;
      instrumentDetail = instrument.blocker || (commissioning760EReady
        ? "The verified 32-bit worker can run one bounded internal-dummy CV after browser and local approval."
        : sdkReady
        ? instrument.detail || "The worker is ready; physical instrument identity is not confirmed."
        : "A verified local vendor adapter is required.");
    }
    return {
      header: commissioning760EReady
        ? "Local bridge connected - 760E dummy CV ready"
        : dummyReady
        ? "Local bridge connected - 760D dummy test ready"
        : sdkReady
        ? "Local bridge connected - SDK worker ready"
        : "Local bridge connected · CHI control locked",
      storageLabel: storage.configured
        ? `${storage.folder_name || "Selected folder"}${storage.available ? "" : " (unavailable)"}`
        : "Not selected",
      storageDetail: storage.configured && storage.available
        ? storage.source === "repository_default"
          ? "Using the repository data folder automatically. The full path remains inside the local bridge."
          : "The full path remains inside the local bridge."
        : storage.configured
          ? "Choose an available folder before recording data."
          : "Choose a folder using the normal Windows folder picker.",
      instrumentLabel,
      instrumentDetail,
      discoveryEnabled: sdkReady,
      commissioning760EReady,
      commissioning760EState: instrument.state || "adapter_unavailable",
      commissioning760EDetail: instrument.blocker
        || (instrument.active?.state === "starting"
          || instrument.active?.state === "running"
          || instrument.active?.state === "stopping"
          ? `Run ${instrument.active.run_label || instrument.active.job_id} is ${instrument.active.state}.`
          : instrument.active?.state === "completed"
            ? `Run ${instrument.active.run_label} completed and saved ${instrument.active.data_points || 0} data points.`
            : instrument.active?.state === "error"
              ? `Run ${instrument.active.run_label} ended with an error: ${instrument.active.error || "review the saved run record"}.`
              : "The verified 32-bit worker is ready for one bounded internal-dummy CV."),
      dummyReady,
      dummyState: desktop760d.state || "adapter_unavailable",
      dummyDetail: desktop760d.blocker
        || (desktop760d.active?.running
          ? `Run ${desktop760d.active.run_label} is active in the CHI desktop.`
          : desktop760d.active?.state === "completed"
            ? `Run ${desktop760d.active.run_label} completed with ${desktop760d.active.text_outputs_detected}/${desktop760d.active.expected_output_count} text outputs.`
            : desktop760d.active?.state === "error"
              ? `Run ${desktop760d.active.run_label} ended without every expected output; review the local run folder and CHI window.`
          : "The audited CHI 760D executable is ready for an internal-dummy CV/wait series."),
    };
  }

  function bounded760EPlan(protocol) {
    if (!protocol || protocol.target_model !== "760E") {
      throw new Error("Select CHI 760E before preparing the real CV.");
    }
    if (protocol.validation?.valid !== true) {
      throw new Error("Resolve every protocol validation error before preparing the real CV.");
    }
    if (protocol.ir_compensation?.enabled !== false) {
      throw new Error("Disable iR compensation for the first real 760E commissioning CV.");
    }
    if (!Array.isArray(protocol.steps) || protocol.steps.length !== 1
        || protocol.steps[0]?.source_technique !== "cv") {
      throw new Error("The 760E commissioning protocol must contain exactly one CV step.");
    }
    const parameters = protocol.steps[0].parameters || {};
    if (parameters.cycles !== 1) {
      throw new Error("The 760E commissioning CV must use exactly one cycle.");
    }
    if (Math.abs(parameters.final_voltage_v - parameters.initial_voltage_v) > 1e-9) {
      throw new Error("Final potential must equal initial potential for the two-sweep commissioning CV.");
    }
    return {
      target_model: "760E",
      initial_potential_v: parameters.initial_voltage_v,
      high_potential_v: parameters.apex1_voltage_v,
      low_potential_v: parameters.apex2_voltage_v,
      initial_scan_direction: "positive",
      scan_rate_v_s: parameters.scan_rate_v_s,
      potential_step_v: parameters.step_size_v,
      quiet_time_s: 0,
      sweep_segments: 2,
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
      modelSelect: doc.querySelector("#protocol-model"),
      instrumentLabel: doc.querySelector("#echem-instrument-label"),
      sdkDetails: doc.querySelector("#echem-sdk-discovery-details"),
      executionLockTitle: doc.querySelector("#echem-execution-lock-title"),
      executionLockDetail: doc.querySelector("#echem-execution-lock-detail"),
      runner760EPanel: doc.querySelector("#chi760e-runner-panel"),
      runner760EState: doc.querySelector("#chi760e-runner-state"),
      runner760EDetail: doc.querySelector("#chi760e-runner-detail"),
      runner760EActionStatus: doc.querySelector("#chi760e-run-action-status"),
      runner760EFieldset: doc.querySelector("#chi760e-run-confirmations"),
      runner760EInputs: Array.from(doc.querySelectorAll("[data-chi760e-confirmation]")),
      prepare760EButton: doc.querySelector("#chi760e-prepare-run"),
      start760EButton: doc.querySelector("#chi760e-start-run"),
      stop760EButton: doc.querySelector("#chi760e-stop-run"),
      runnerPanel: doc.querySelector("#chi760d-runner-panel"),
      runnerState: doc.querySelector("#chi760d-runner-state"),
      runnerDetail: doc.querySelector("#chi760d-runner-detail"),
      runnerActionStatus: doc.querySelector("#chi760d-run-action-status"),
      runnerFieldset: doc.querySelector("#chi760d-run-confirmations"),
      runnerInputs: Array.from(doc.querySelectorAll("[data-chi760d-confirmation]")),
      prepareButton: doc.querySelector("#chi760d-prepare-run"),
      startButton: doc.querySelector("#chi760d-start-run"),
      benchState: doc.querySelector("#protocol-bench-state"),
    };
    let client = null;
    let snapshot = null;
    let preparation760DToken = null;
    let preparation760EToken = null;
    let active760EJobId = null;
    let runner760EPoll = null;
    let runner760EPollBusy = false;
    let runnerPoll = null;
    let selectedModel = ["760B", "760D", "760E"].includes(elements.modelSelect?.value)
      ? elements.modelSelect.value
      : "760E";

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

    function runner760EConfirmations() {
      return Object.fromEntries(
        elements.runner760EInputs.map((input) => [input.dataset.chi760eConfirmation, input.checked]),
      );
    }

    function updateDiscoveryButton() {
      elements.discoveryButton.disabled = !client
        || selectedModel !== "760E"
        || snapshot?.instrument?.discovery_enabled !== true
        || !elements.confirmationInputs.every((input) => input.checked);
    }

    function updateRunnerButtons() {
      const ready = Boolean(client)
        && selectedModel === "760D"
        && snapshot?.desktop_760d?.experiment_control_enabled === true
        && snapshot?.storage?.available === true
        && snapshot?.desktop_760d?.active?.running !== true
        && elements.benchState?.value === "available";
      elements.prepareButton.disabled = !ready;
      elements.startButton.disabled = !ready
        || !preparation760DToken
        || !elements.runnerInputs.every((input) => input.checked);
    }

    function update760ERunnerButtons() {
      const activeState = snapshot?.instrument?.active?.state;
      const running = ["starting", "running", "stopping"].includes(activeState)
        || Boolean(active760EJobId);
      const ready = Boolean(client)
        && selectedModel === "760E"
        && snapshot?.instrument?.experiment_control_enabled === true
        && snapshot?.storage?.available === true
        && !running
        && elements.benchState?.value === "available";
      elements.prepare760EButton.disabled = !ready || Boolean(preparation760EToken);
      elements.start760EButton.disabled = !ready
        || !preparation760EToken
        || !elements.runner760EInputs.every((input) => input.checked);
      elements.stop760EButton.disabled = !client
        || selectedModel !== "760E"
        || !active760EJobId
        || !["starting", "running"].includes(activeState);
    }

    function stopRunnerPolling() {
      if (runnerPoll !== null) {
        browserWindow.clearInterval(runnerPoll);
        runnerPoll = null;
      }
    }

    function syncRunnerPolling() {
      const running = selectedModel === "760D"
        && snapshot?.desktop_760d?.active?.running === true;
      if (!running) {
        stopRunnerPolling();
        return;
      }
      if (runnerPoll !== null) return;
      runnerPoll = browserWindow.setInterval(async () => {
        if (!client) {
          stopRunnerPolling();
          return;
        }
        try {
          renderStatus(await client.status());
        } catch (error) {
          stopRunnerPolling();
          checkMessage(`Run status check failed: ${error.message}`, "failed");
        }
      }, 2500);
    }

    function stop760ERunnerPolling() {
      if (runner760EPoll !== null) {
        browserWindow.clearInterval(runner760EPoll);
        runner760EPoll = null;
      }
      runner760EPollBusy = false;
    }

    async function poll760ERun() {
      if (!client || !active760EJobId || runner760EPollBusy) return;
      runner760EPollBusy = true;
      try {
        const result = await client.status760EDummyCV(active760EJobId);
        const run = result.run || {};
        if (["completed", "stopped", "error"].includes(run.state)) {
          stop760ERunnerPolling();
          active760EJobId = null;
          renderStatus(await client.status());
          if (run.state === "error") {
            elements.runner760EActionStatus.textContent = `The 760E CV ended with an error: ${run.error || "review the saved run record"}.`;
            elements.runner760EActionStatus.style.color = "var(--danger)";
          } else {
            elements.runner760EActionStatus.textContent = `${run.run_label} ${run.state}; ${run.data_points || 0} data points saved in the local run folder.`;
            elements.runner760EActionStatus.style.color = "var(--safe)";
          }
        } else {
          elements.runner760EActionStatus.textContent = `${run.run_label || "760E CV"} is ${run.state}.`;
          elements.runner760EActionStatus.style.color = "var(--warning)";
          renderStatus(await client.status());
        }
      } catch (error) {
        stop760ERunnerPolling();
        elements.runner760EActionStatus.textContent = `760E status check failed: ${error.message}`;
        elements.runner760EActionStatus.style.color = "var(--danger)";
      } finally {
        runner760EPollBusy = false;
        update760ERunnerButtons();
      }
    }

    function sync760ERunnerPolling() {
      const active = snapshot?.instrument?.active;
      if (["starting", "running", "stopping"].includes(active?.state)
          && typeof active?.job_id === "string") {
        active760EJobId = active.job_id;
      }
      if (selectedModel !== "760E" || !active760EJobId) {
        stop760ERunnerPolling();
        return;
      }
      if (runner760EPoll !== null) return;
      runner760EPoll = browserWindow.setInterval(poll760ERun, 1500);
    }

    function showUnavailable(message) {
      snapshot = null;
      labeledStatus(elements.summary, "Local bridge not connected · no hardware I/O", "amber");
      labeledStatus(elements.bridgeState, "Not connected", "amber");
      elements.bridgeDetail.textContent = message;
      elements.storageState.textContent = "Unavailable";
      elements.storageDetail.textContent = "Start the local bridge before choosing a folder.";
      elements.instrumentState.textContent = selectedModel === "760B"
        ? "Measurement protected - offline planning only"
        : "Not connected";
      elements.instrumentDetail.textContent = selectedModel === "760B"
        ? "No live 760B adapter is configured. The active measurement remains untouched."
        : `No request was sent to the CHI ${selectedModel}.`;
      elements.storageButton.disabled = true;
      elements.confirmationFieldset.disabled = true;
      elements.executionLockTitle.textContent = "Protocol execution is still locked.";
      elements.executionLockDetail.textContent = "Start an authenticated local bridge before checking any hardware-control capability.";
      labeledStatus(elements.runner760EState, "Not connected", "amber");
      elements.runner760EDetail.textContent = "Start SpectraLoop.cmd on the 760E instrument computer.";
      elements.runner760EFieldset.disabled = true;
      labeledStatus(elements.runnerState, "Not connected", "amber");
      elements.runnerDetail.textContent = "Start SpectraLoop 760D.cmd on the instrument computer.";
      elements.runnerFieldset.disabled = true;
      preparation760DToken = null;
      preparation760EToken = null;
      active760EJobId = null;
      stop760ERunnerPolling();
      stopRunnerPolling();
      updateDiscoveryButton();
      updateRunnerButtons();
      update760ERunnerButtons();
    }

    function renderStatus(nextSnapshot) {
      snapshot = nextSnapshot;
      const view = describeSnapshot(snapshot, selectedModel);
      const benchAvailable = elements.benchState?.value === "available";
      const selectedAdapterReady = view.discoveryEnabled
        || (view.commissioning760EReady && benchAvailable)
        || (view.dummyReady && benchAvailable);
      labeledStatus(elements.summary, view.header, selectedAdapterReady ? "safe" : "amber");
      labeledStatus(elements.bridgeState, "Connected to local service", "safe");
      elements.bridgeDetail.textContent = `${snapshot.service.name} ${snapshot.service.version} · loopback only`;
      elements.storageState.textContent = view.storageLabel;
      elements.storageDetail.textContent = view.storageDetail;
      elements.instrumentState.textContent = view.instrumentLabel;
      elements.instrumentDetail.textContent = view.instrumentDetail;
      elements.storageButton.disabled = false;
      elements.confirmationFieldset.disabled = !view.discoveryEnabled;
      const active760E = snapshot.instrument?.active;
      const active760EState = active760E?.state;
      const runner760ELabel = ["starting", "running", "stopping"].includes(active760EState)
        ? `CV ${active760EState}`
        : active760EState === "completed"
          ? "Last CV completed"
          : active760EState === "stopped"
            ? "Last CV stopped"
            : active760EState === "error"
              ? "Last CV needs review"
              : view.commissioning760EReady && benchAvailable
                ? "Bounded CV ready"
                : "760E execution locked";
      labeledStatus(
        elements.runner760EState,
        runner760ELabel,
        active760EState === "error" ? "amber" : view.commissioning760EReady && benchAvailable ? "safe" : "amber",
      );
      elements.runner760EDetail.textContent = benchAvailable
        ? view.commissioning760EDetail
        : "Bench is marked measurement in progress. Hardware preparation and execution are disabled.";
      elements.runner760EDetail.className = `bridge-check-status ${view.commissioning760EReady && benchAvailable ? "safe" : "warning"}`;
      elements.runner760EFieldset.disabled = !view.commissioning760EReady || !benchAvailable;
      const controlEnabled = snapshot.safety?.mode === "chi760e_internal_dummy"
        && snapshot.safety?.experiments_enabled === true;
      elements.executionLockTitle.textContent = controlEnabled
        ? "One bounded 760E hardware workflow is enabled."
        : "Protocol execution is still locked.";
      elements.executionLockDetail.textContent = controlEnabled
        ? "Only the separately approved internal-dummy CV panel can issue experiment commands; all other protocol techniques, iR compensation, Raman, RDE, and automated decisions remain locked."
        : "Connecting the bridge or checking SDK capabilities does not authorize OCP, EIS, CV, iR compensation, cell control, Raman, RDE, or any other experiment.";
      const active = snapshot.desktop_760d?.active;
      const runnerLabel = active?.running
        ? "Series running"
        : active?.state === "completed"
          ? "Last series completed"
          : active?.state === "error"
            ? "Last series needs review"
            : view.dummyReady && benchAvailable
              ? "Internal-dummy series ready"
              : "760D execution locked";
      labeledStatus(elements.runnerState, runnerLabel, active?.state === "error" ? "amber" : view.dummyReady && benchAvailable ? "safe" : "amber");
      elements.runnerDetail.textContent = benchAvailable
        ? view.dummyDetail
        : "Bench is marked measurement in progress. Hardware preparation and execution are disabled.";
      elements.runnerDetail.className = `bridge-check-status ${view.dummyReady && benchAvailable ? "safe" : "warning"}`;
      elements.runnerFieldset.disabled = !view.dummyReady || !benchAvailable;
      updateDiscoveryButton();
      updateRunnerButtons();
      update760ERunnerButtons();
      syncRunnerPolling();
      sync760ERunnerPolling();
    }

    function applyModelScope(nextModel) {
      selectedModel = ["760B", "760D", "760E"].includes(nextModel) ? nextModel : "760E";
      elements.instrumentLabel.textContent = `CHI ${selectedModel} adapter`;
      elements.sdkDetails.hidden = selectedModel !== "760E";
      elements.runner760EPanel.hidden = selectedModel !== "760E";
      elements.runnerPanel.hidden = selectedModel !== "760D";
      if (selectedModel !== "760D") stopRunnerPolling();
      if (selectedModel !== "760E") stop760ERunnerPolling();
      if (selectedModel !== "760E") {
        elements.confirmationInputs.forEach((input) => { input.checked = false; });
      }
      preparation760DToken = null;
      preparation760EToken = null;
      if (snapshot) renderStatus(snapshot);
      else showUnavailable("Start the local bridge on the selected instrument computer.");
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
        activeClient = null;
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
        activeClient = null;
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
        activeClient = client;
        renderStatus(await client.status());
        checkMessage("Local bridge responded and authentication succeeded.", "safe");
        elements.actionStatus.textContent = "Bridge verified. No CHI hardware request has been made.";
        elements.actionStatus.style.color = "var(--safe)";
      } catch (error) {
        client = null;
        activeClient = null;
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
      if (!client || selectedModel !== "760E" || elements.discoveryButton.disabled) return;
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

    async function prepare760ERun() {
      if (!client || selectedModel !== "760E" || elements.prepare760EButton.disabled) return;
      const protocolCore = browserWindow.SpectraLoopProtocolCore;
      if (!protocolCore || typeof protocolCore.buildValidatedPlan !== "function") {
        elements.runner760EActionStatus.textContent = "The protocol builder is unavailable.";
        elements.runner760EActionStatus.style.color = "var(--danger)";
        return;
      }
      elements.prepare760EButton.disabled = true;
      elements.runner760EActionStatus.textContent = "Validating the bounded CV and reserving a unique run folder...";
      elements.runner760EActionStatus.style.color = "var(--warning)";
      try {
        const protocol = protocolCore.buildValidatedPlan();
        const plan = bounded760EPlan(protocol);
        const result = await client.prepare760EDummyCV(plan, protocol.protocol_name);
        preparation760EToken = result.preparation.preparation_token;
        const summary = result.preparation.summary;
        elements.runner760EActionStatus.textContent = `Prepared ${result.preparation.run_label}: ${summary.low_potential_v} to ${summary.high_potential_v} V at ${summary.scan_rate_v_s} V/s. Check every confirmation to start.`;
        elements.runner760EActionStatus.style.color = "var(--safe)";
      } catch (error) {
        preparation760EToken = null;
        elements.runner760EActionStatus.textContent = error.message;
        elements.runner760EActionStatus.style.color = "var(--danger)";
      } finally {
        update760ERunnerButtons();
      }
    }

    async function start760ERun() {
      if (!client || selectedModel !== "760E" || !preparation760EToken
          || elements.start760EButton.disabled) return;
      elements.start760EButton.disabled = true;
      elements.runner760EActionStatus.textContent = "Waiting for approval in the local Windows dialog...";
      elements.runner760EActionStatus.style.color = "var(--warning)";
      try {
        const result = await client.start760EDummyCV(
          preparation760EToken,
          runner760EConfirmations(),
        );
        preparation760EToken = null;
        active760EJobId = result.run.job_id;
        elements.runner760EInputs.forEach((input) => { input.checked = false; });
        elements.runner760EActionStatus.textContent = `${result.run.run_label} started through the CHI 760E SDK. The Stop CV button is available while it runs.`;
        elements.runner760EActionStatus.style.color = "var(--safe)";
        renderStatus(await client.status());
        await poll760ERun();
        sync760ERunnerPolling();
      } catch (error) {
        elements.runner760EActionStatus.textContent = error.message;
        elements.runner760EActionStatus.style.color = "var(--danger)";
        update760ERunnerButtons();
      }
    }

    async function stop760ERun() {
      if (!client || !active760EJobId || elements.stop760EButton.disabled) return;
      elements.stop760EButton.disabled = true;
      elements.runner760EActionStatus.textContent = "Sending the documented CHI stop request...";
      elements.runner760EActionStatus.style.color = "var(--warning)";
      try {
        const result = await client.stop760EDummyCV(active760EJobId);
        elements.runner760EActionStatus.textContent = `${result.run.run_label || "760E CV"} stop requested; waiting for cell-off cleanup.`;
        renderStatus(await client.status());
      } catch (error) {
        elements.runner760EActionStatus.textContent = error.message;
        elements.runner760EActionStatus.style.color = "var(--danger)";
      } finally {
        update760ERunnerButtons();
      }
    }

    async function prepare760DRun() {
      if (!client || selectedModel !== "760D" || elements.prepareButton.disabled) return;
      const protocolCore = browserWindow.SpectraLoopProtocolCore;
      if (!protocolCore || typeof protocolCore.buildValidatedPlan !== "function") {
        elements.runnerActionStatus.textContent = "The protocol builder is unavailable.";
        elements.runnerActionStatus.style.color = "var(--danger)";
        return;
      }
      elements.prepareButton.disabled = true;
      elements.runnerActionStatus.textContent = "Validating the bounded series and reserving a unique run folder...";
      elements.runnerActionStatus.style.color = "var(--warning)";
      try {
        const result = await client.prepare760DDummyCV(protocolCore.buildValidatedPlan());
        preparation760DToken = result.preparation.preparation_token;
        const summary = result.preparation.summary;
        elements.runnerActionStatus.textContent = `Prepared ${result.preparation.run_label}: ${summary.step_count} steps, ${summary.cv_count} bounded CV runs, approximately ${summary.estimated_duration_s} s. Check every confirmation to start.`;
        elements.runnerActionStatus.style.color = "var(--safe)";
      } catch (error) {
        preparation760DToken = null;
        elements.runnerActionStatus.textContent = error.message;
        elements.runnerActionStatus.style.color = "var(--danger)";
      } finally {
        updateRunnerButtons();
      }
    }

    async function start760DRun() {
      if (!client || selectedModel !== "760D" || !preparation760DToken || elements.startButton.disabled) return;
      elements.startButton.disabled = true;
      elements.runnerActionStatus.textContent = "Waiting for approval in the local Windows dialog...";
      elements.runnerActionStatus.style.color = "var(--warning)";
      try {
        const result = await client.run760DDummyCV(preparation760DToken, runnerConfirmations());
        preparation760DToken = null;
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
    elements.prepare760EButton.addEventListener("click", prepare760ERun);
    elements.start760EButton.addEventListener("click", start760ERun);
    elements.stop760EButton.addEventListener("click", stop760ERun);
    elements.runner760EInputs.forEach((input) => input.addEventListener("change", update760ERunnerButtons));
    elements.prepareButton.addEventListener("click", prepare760DRun);
    elements.startButton.addEventListener("click", start760DRun);
    elements.runnerInputs.forEach((input) => input.addEventListener("change", updateRunnerButtons));
    elements.benchState?.addEventListener("change", () => {
      if (snapshot) renderStatus(snapshot);
      else {
        updateRunnerButtons();
        update760ERunnerButtons();
      }
    });
    doc.addEventListener("spectraloop:protocol-scope-changed", (event) => {
      applyModelScope(event.detail?.targetModel);
    });
    applyModelScope(elements.modelSelect?.value);
    refresh();

    return { refresh };
  }

  return {
    bounded760EPlan,
    describeSnapshot,
    getClient: () => activeClient,
    initialize,
  };
});

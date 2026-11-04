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
    const sdkModel = ["760B", "760E"].includes(model);
    const adapterTarget = instrument.commissioning_target_model || null;
    const adapterMatches = sdkModel && adapterTarget === model;
    const sdkReady = adapterMatches && instrument.discovery_enabled === true;
    const commissioning760EReady = adapterMatches
      && instrument.experiment_control_enabled === true;
    let instrumentLabel;
    let instrumentDetail;
    if (model === "760D") {
      instrumentLabel = dummyReady
        ? "CHI 760D - internal-dummy adapter ready"
        : "CHI 760D - desktop adapter unavailable";
      instrumentDetail = desktop760d.blocker
        || (desktop760d.active?.running
          ? `Run ${desktop760d.active.run_label} is active in the CHI desktop.`
          : "The audited desktop adapter is limited to an explicitly approved internal-dummy CV/wait series.");
    } else if (adapterMatches) {
      instrumentLabel = commissioning760EReady
        ? model === "760B"
          ? `${instrument.target || "CHI 760B"} - protocol control ready`
          : `${instrument.target || `CHI ${model}`} - bounded CV control ready`
        : sdkReady
        ? `${instrument.target || `CHI ${model}`} - SDK check ready`
        : `${instrument.target || `CHI ${model}`} - adapter unavailable`;
      instrumentDetail = instrument.blocker || (commissioning760EReady
        ? model === "760B"
          ? "The verified 32-bit worker can run validated Wait, CV, and Amperometric i-t sequences after browser and local approval."
          : "The verified 32-bit worker can run one bounded internal-dummy CV after browser and local approval."
        : sdkReady
        ? instrument.detail || "The worker is ready; physical instrument identity is not confirmed."
        : "A verified local vendor adapter is required.");
    } else {
      instrumentLabel = `CHI ${model} - selected bridge does not match`;
      instrumentDetail = adapterTarget
        ? `This local bridge is configured for CHI ${adapterTarget}. Start the CHI ${model} launcher instead.`
        : `Start the dedicated CHI ${model} SDK launcher on this instrument computer.`;
    }
    return {
      header: commissioning760EReady
        ? model === "760B"
          ? "Local bridge connected - 760B protocol runner ready"
          : `Local bridge connected - ${model} dummy CV ready`
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
              : model === "760B"
                ? "The verified 32-bit 760B worker is ready for the current Wait/CV/Amperometric i-t protocol."
                : `The verified 32-bit ${model} worker is ready for one bounded internal-dummy CV.`),
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

  function boundedSDKPlan(protocol, targetModel = protocol?.target_model) {
    const model = String(targetModel || "").toUpperCase();
    if (!["760B", "760E"].includes(model)) {
      throw new Error("Select CHI 760B or CHI 760E before preparing the real CV.");
    }
    if (!protocol || protocol.target_model !== model) {
      throw new Error(`Select CHI ${model} before preparing the real CV.`);
    }
    if (protocol.validation?.valid !== true) {
      throw new Error("Resolve every protocol validation error before preparing the real CV.");
    }
    if (protocol.ir_compensation?.enabled !== false) {
      throw new Error(`Disable iR compensation for the first real ${model} commissioning CV.`);
    }
    if (!Array.isArray(protocol.steps) || protocol.steps.length !== 1
        || protocol.steps[0]?.source_technique !== "cv") {
      throw new Error(`The ${model} commissioning protocol must contain exactly one CV step.`);
    }
    const parameters = protocol.steps[0].parameters || {};
    if (parameters.cycles !== 1) {
      throw new Error(`The ${model} commissioning CV must use exactly one cycle.`);
    }
    if (Math.abs(parameters.final_voltage_v - parameters.initial_voltage_v) > 1e-9) {
      throw new Error("Final potential must equal initial potential for the two-sweep commissioning CV.");
    }
    return {
      target_model: model,
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

  function bounded760EPlan(protocol) {
    return boundedSDKPlan(protocol, "760E");
  }

  function direct760BSequencePlan(protocol) {
    if (!protocol || protocol.target_model !== "760B") {
      throw new Error("Select CHI 760B before preparing the real experiment sequence.");
    }
    if (protocol.validation?.valid !== true) {
      throw new Error("Resolve every protocol validation error before preparing the real experiment.");
    }
    if (protocol.ir_compensation?.enabled !== false) {
      throw new Error("The iR settings are preserved, but direct 760B execution requires iR disabled until its installed SDK parameter mapping is verified.");
    }
    if (!Array.isArray(protocol.steps) || protocol.steps.length === 0) {
      throw new Error("Add at least one Wait, CV, or Amperometric i-t step.");
    }
    const steps = protocol.steps.map((step, index) => {
      const parameters = step?.parameters || {};
      if (step?.source_technique === "wait") {
        return { kind: "wait", duration_s: parameters.duration_s };
      }
      if (step?.source_technique === "cv") {
        return {
          kind: "cv",
          initial_potential_v: parameters.initial_voltage_v,
          high_potential_v: parameters.apex1_voltage_v,
          low_potential_v: parameters.apex2_voltage_v,
          final_potential_v: parameters.final_voltage_v,
          initial_scan_direction: "positive",
          scan_rate_v_s: parameters.scan_rate_v_s,
          potential_step_v: parameters.step_size_v,
          quiet_time_s: 0,
          cycles: parameters.cycles,
        };
      }
      if (step?.source_technique === "it") {
        return {
          kind: "it",
          potential_v: parameters.potential_v,
          duration_s: parameters.duration_s,
          sample_period_s: parameters.sample_period_s,
          area_cm2: parameters.area_cm2,
          quiet_time_s: 0,
        };
      }
      throw new Error(`Step ${index + 1}: ${step?.source_technique || "unknown"} is not available for direct 760B execution.`);
    });
    return {
      target_model: "760B",
      protocol_name: protocol.protocol_name,
      ir_compensation: { ...protocol.ir_compensation },
      steps,
    };
  }

  function initialize(doc, browserWindow, bridgeApi) {
    const elements = {
      summary: doc.querySelector("#echem-bridge-summary"),
      pageModelLabel: doc.querySelector("#echem-page-model-label"),
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
      runnerSDKEyebrow: doc.querySelector("#chi-sdk-runner-eyebrow"),
      runnerSDKNote: doc.querySelector("#chi-sdk-runner-note"),
      runnerSDKInstructions: doc.querySelector("#chi-sdk-runner-instructions"),
      runnerSDKTargetLabel: doc.querySelector("#chi-sdk-target-confirmation-label"),
      runnerSDKCellLabel: doc.querySelector("#chi-sdk-cell-confirmation-label"),
      runnerSDKProtocolLabel: doc.querySelector("#chi-sdk-protocol-confirmation-label"),
      runner760EState: doc.querySelector("#chi760e-runner-state"),
      runner760EDetail: doc.querySelector("#chi760e-runner-detail"),
      runner760EActionStatus: doc.querySelector("#chi760e-run-action-status"),
      runner760EFieldset: doc.querySelector("#chi760e-run-confirmations"),
      runner760EInputs: Array.from(doc.querySelectorAll("[data-chi-sdk-confirmation]")),
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
      return Object.fromEntries(elements.runner760EInputs.map((input) => {
        const sourceName = input.dataset.chiSdkConfirmation;
        let name = sourceName === "target_is_selected_model"
          ? `target_is_${selectedModel.toLowerCase()}`
          : sourceName;
        if (selectedModel === "760E" && sourceName === "cell_setup_reviewed") {
          name = "internal_dummy_cell_connected";
        }
        if (selectedModel === "760E" && sourceName === "protocol_parameters_reviewed") {
          name = "external_sample_disconnected";
        }
        return [name, input.checked];
      }));
    }

    function updateDiscoveryButton() {
      elements.discoveryButton.disabled = !client
        || !["760B", "760E"].includes(selectedModel)
        || snapshot?.instrument?.commissioning_target_model !== selectedModel
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
        && ["760B", "760E"].includes(selectedModel)
        && snapshot?.instrument?.commissioning_target_model === selectedModel
        && snapshot?.instrument?.experiment_control_enabled === true
        && snapshot?.storage?.available === true
        && !running
        && elements.benchState?.value === "available";
      elements.prepare760EButton.disabled = !ready || Boolean(preparation760EToken);
      elements.start760EButton.disabled = !ready
        || !preparation760EToken
        || (selectedModel === "760E" && !elements.runner760EInputs.every((input) => input.checked));
      elements.stop760EButton.disabled = !client
        || !["760B", "760E"].includes(selectedModel)
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
        const result = await client.statusSDKDummyCV(selectedModel, active760EJobId);
        const run = result.run || {};
        if (["completed", "stopped", "error"].includes(run.state)) {
          stop760ERunnerPolling();
          active760EJobId = null;
          renderStatus(await client.status());
          if (run.state === "error") {
            elements.runner760EActionStatus.textContent = `The ${selectedModel} experiment ended with an error: ${run.error || "review the saved run record"}.`;
            elements.runner760EActionStatus.style.color = "var(--danger)";
          } else {
            elements.runner760EActionStatus.textContent = `${run.run_label} ${run.state}; ${run.data_points || 0} data points saved in ${run.folder || "data/runs"}.`;
            elements.runner760EActionStatus.style.color = "var(--safe)";
            await globalThis.SpectraLoopMonitorCore?.loadLatestRealRun?.();
          }
        } else {
          elements.runner760EActionStatus.textContent = `${run.run_label || `${selectedModel} experiment`} is ${run.state}.`;
          elements.runner760EActionStatus.style.color = "var(--warning)";
          renderStatus(await client.status());
        }
      } catch (error) {
        stop760ERunnerPolling();
        elements.runner760EActionStatus.textContent = `${selectedModel} status check failed: ${error.message}`;
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
      if (!["760B", "760E"].includes(selectedModel)
          || snapshot?.instrument?.commissioning_target_model !== selectedModel
          || !active760EJobId) {
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
      elements.instrumentState.textContent = "Not connected";
      elements.instrumentDetail.textContent = `No request was sent to the CHI ${selectedModel}.`;
      elements.storageButton.disabled = true;
      elements.confirmationFieldset.disabled = true;
      elements.executionLockTitle.textContent = "Protocol execution is still locked.";
      elements.executionLockDetail.textContent = "Start an authenticated local bridge before checking any hardware-control capability.";
      labeledStatus(elements.runner760EState, "Not connected", "amber");
      elements.runner760EDetail.textContent = `Start the CHI ${selectedModel} SDK launcher on the instrument computer.`;
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
      const runNoun = selectedModel === "760B" ? "Experiment" : "CV";
      const runner760ELabel = ["starting", "running", "stopping"].includes(active760EState)
        ? `${runNoun} ${active760EState}`
        : active760EState === "completed"
          ? `Last ${runNoun.toLowerCase()} completed`
          : active760EState === "stopped"
            ? `Last ${runNoun.toLowerCase()} stopped`
            : active760EState === "error"
              ? `Last ${runNoun.toLowerCase()} needs review`
              : view.commissioning760EReady && benchAvailable
                ? selectedModel === "760B" ? "Protocol runner ready" : "Bounded CV ready"
                : `${selectedModel} execution locked`;
      labeledStatus(
        elements.runner760EState,
        runner760ELabel,
        active760EState === "error" ? "amber" : view.commissioning760EReady && benchAvailable ? "safe" : "amber",
      );
      elements.runner760EDetail.textContent = benchAvailable
        ? view.commissioning760EDetail
        : "Bench is marked measurement in progress. Hardware preparation and execution are disabled.";
      elements.runner760EDetail.className = `bridge-check-status ${view.commissioning760EReady && benchAvailable ? "safe" : "warning"}`;
      elements.runner760EFieldset.disabled = selectedModel === "760E"
        && (!view.commissioning760EReady || !benchAvailable);
      const controlEnabled = snapshot.instrument?.commissioning_target_model === selectedModel
        && snapshot.safety?.experiments_enabled === true;
      elements.executionLockTitle.textContent = controlEnabled
        ? selectedModel === "760B"
          ? "Direct CHI 760B protocol execution is enabled."
          : `One bounded ${selectedModel} hardware workflow is enabled.`
        : "Protocol execution is still locked.";
      elements.executionLockDetail.textContent = controlEnabled
        ? selectedModel === "760B"
          ? "The existing protocol runner can execute verified Wait, CV, and Amperometric i-t steps. iR compensation and unsupported techniques fail preflight before any instrument call."
          : "Only the separately approved internal-dummy CV can issue experiment commands; all other protocol techniques remain locked."
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
      elements.pageModelLabel.textContent = `CHI ${selectedModel} · ELECTROCHEMISTRY`;
      elements.instrumentLabel.textContent = `CHI ${selectedModel} adapter`;
      const sdkSelected = ["760B", "760E"].includes(selectedModel);
      elements.sdkDetails.hidden = !sdkSelected;
      elements.runner760EPanel.hidden = !sdkSelected;
      elements.runnerPanel.hidden = selectedModel !== "760D";
      if (selectedModel !== "760D") stopRunnerPolling();
      if (!sdkSelected) stop760ERunnerPolling();
      if (!sdkSelected) {
        elements.confirmationInputs.forEach((input) => { input.checked = false; });
      }
      if (sdkSelected) {
        elements.runnerSDKEyebrow.textContent = `CHI ${selectedModel} SDK CONTROL`;
        elements.runnerSDKNote.textContent = selectedModel === "760B"
          ? "Execute the displayed Wait, CV, and Amperometric i-t steps in order. Results are saved under data/runs/date/task/trial."
          : "One two-sweep CV, within +/-0.25 V, using the current single-CV protocol. Results are saved in the local data folder.";
        elements.runnerSDKInstructions.textContent = selectedModel === "760B"
          ? "Mark the bench available, then prepare and run the current sequence. Preparing reserves a unique run folder without contacting the instrument."
          : `Select CHI ${selectedModel}, mark the bench available, build exactly one one-cycle CV, and disable iR compensation. Preparing validates the plan and reserves a unique run folder; it does not contact the instrument.`;
        elements.runner760EFieldset.hidden = selectedModel === "760B";
        elements.runnerSDKTargetLabel.lastChild.textContent = ` The connected instrument and installed SDK are for CHI ${selectedModel}.`;
        elements.runnerSDKCellLabel.lastChild.textContent = " The CHI internal dummy cell is selected and connected.";
        elements.runnerSDKProtocolLabel.lastChild.textContent = " Every external sample is disconnected.";
        elements.prepare760EButton.textContent = selectedModel === "760B" ? "Prepare current protocol" : "Prepare bounded CV";
        elements.start760EButton.textContent = selectedModel === "760B" ? "Run on CHI 760B" : "Start approved CV";
        elements.stop760EButton.textContent = selectedModel === "760B" ? "Stop experiment" : "Stop CV";
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
      if (!client || !["760B", "760E"].includes(selectedModel) || elements.discoveryButton.disabled) return;
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
      if (!client || !["760B", "760E"].includes(selectedModel)
          || elements.prepare760EButton.disabled) return;
      const protocolCore = browserWindow.SpectraLoopProtocolCore;
      if (!protocolCore || typeof protocolCore.buildValidatedPlan !== "function") {
        elements.runner760EActionStatus.textContent = "The protocol builder is unavailable.";
        elements.runner760EActionStatus.style.color = "var(--danger)";
        return;
      }
      elements.prepare760EButton.disabled = true;
      elements.runner760EActionStatus.textContent = selectedModel === "760B"
        ? "Validating the current sequence and reserving a unique run folder..."
        : "Validating the bounded CV and reserving a unique run folder...";
      elements.runner760EActionStatus.style.color = "var(--warning)";
      try {
        const protocol = protocolCore.buildValidatedPlan();
        const plan = selectedModel === "760B"
          ? direct760BSequencePlan(protocol)
          : boundedSDKPlan(protocol, selectedModel);
        const result = await client.prepareSDKDummyCV(
          selectedModel,
          plan,
          protocol.protocol_name,
        );
        preparation760EToken = result.preparation.preparation_token;
        const summary = result.preparation.summary;
        elements.runner760EActionStatus.textContent = selectedModel === "760B"
          ? `Prepared ${result.preparation.run_label}: ${summary.steps.length} steps, approximately ${summary.estimated_duration_s} s. Ready to run.`
          : `Prepared ${result.preparation.run_label}: ${summary.low_potential_v} to ${summary.high_potential_v} V at ${summary.scan_rate_v_s} V/s. Check every confirmation to start.`;
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
      if (!client || !["760B", "760E"].includes(selectedModel) || !preparation760EToken
          || elements.start760EButton.disabled) return;
      elements.start760EButton.disabled = true;
      elements.runner760EActionStatus.textContent = "Waiting for approval in the local Windows dialog...";
      elements.runner760EActionStatus.style.color = "var(--warning)";
      try {
        const result = await client.startSDKDummyCV(
          selectedModel,
          preparation760EToken,
          selectedModel === "760B" ? {} : runner760EConfirmations(),
        );
        preparation760EToken = null;
        active760EJobId = result.run.job_id;
        elements.runner760EInputs.forEach((input) => { input.checked = false; });
        elements.runner760EActionStatus.textContent = `${result.run.run_label} started through the CHI ${selectedModel} SDK. The stop button is available while it runs.`;
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
        const result = await client.stopSDKDummyCV(selectedModel, active760EJobId);
        elements.runner760EActionStatus.textContent = `${result.run.run_label || `${selectedModel} experiment`} stop requested; waiting for cell-off cleanup.`;
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
    function invalidatePreparedSDKRun(event) {
      if (!preparation760EToken || event.target.closest("#chi760e-runner-panel, #offline-checks")) return;
      preparation760EToken = null;
      elements.runner760EActionStatus.textContent = "The protocol changed. Prepare the current protocol again before starting.";
      elements.runner760EActionStatus.style.color = "var(--warning)";
      update760ERunnerButtons();
    }
    const protocolView = doc.querySelector("#protocol-view");
    protocolView?.addEventListener("input", invalidatePreparedSDKRun);
    protocolView?.addEventListener("change", invalidatePreparedSDKRun);
    protocolView?.addEventListener("click", (event) => {
      if (event.target.closest("#add-step, #load-protocol, button[data-action]")) {
        invalidatePreparedSDKRun(event);
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
    boundedSDKPlan,
    bounded760EPlan,
    direct760BSequencePlan,
    describeSnapshot,
    getClient: () => activeClient,
    initialize,
  };
});

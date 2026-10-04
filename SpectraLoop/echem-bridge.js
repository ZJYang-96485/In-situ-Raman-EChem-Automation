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
    return {
      header: instrument.discovery_enabled
        ? "Local bridge connected · identity only"
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
        ? `${instrument.target || "Instrument"} · identity check ready`
        : `${instrument.target || "Instrument"} · adapter unavailable`,
      instrumentDetail: instrument.discovery_enabled
        ? "Only the verified, read-only identity sequence is available."
        : instrument.blocker || "A verified local vendor adapter is required.",
      discoveryEnabled: instrument.discovery_enabled === true,
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
    };
    let client = null;
    let snapshot = null;

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

    function updateDiscoveryButton() {
      elements.discoveryButton.disabled = !client
        || snapshot?.instrument?.discovery_enabled !== true
        || !elements.confirmationInputs.every((input) => input.checked);
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
      updateDiscoveryButton();
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
      updateDiscoveryButton();
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
      elements.actionStatus.textContent = "Waiting for local Windows approval, then reading identity only…";
      elements.actionStatus.style.color = "var(--warning)";
      try {
        const result = await client.discoverInstrument(confirmations());
        const identity = result.discovery.identity;
        renderStatus(await client.status());
        elements.instrumentState.textContent = `${identity.model} · identity verified`;
        elements.actionStatus.textContent = `Serial ${identity.serial_number}; firmware ${identity.firmware_version}; software ${identity.software_version}.`;
        elements.actionStatus.style.color = "var(--safe)";
      } catch (error) {
        elements.actionStatus.textContent = error.message;
        elements.actionStatus.style.color = "var(--danger)";
        updateDiscoveryButton();
      }
    }

    elements.refreshButton.addEventListener("click", refresh);
    elements.storageButton.addEventListener("click", selectStorage);
    elements.discoveryButton.addEventListener("click", discoverIdentity);
    elements.confirmationInputs.forEach((input) => input.addEventListener("change", updateDiscoveryButton));
    refresh();

    return { refresh };
  }

  return { describeSnapshot, initialize };
});

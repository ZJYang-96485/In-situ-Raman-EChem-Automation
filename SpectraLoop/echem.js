const echemViews = [...document.querySelectorAll("[data-echem-view]")];
const echemSwitches = [...document.querySelectorAll("[data-view-target]")];
let simulatorRecoveryPromise = null;

function ensureSimulationCore() {
  const existing = globalThis.SpectraLoopSimulatorCore;
  if (existing && typeof existing.buildSimulationSession === "function") {
    return Promise.resolve(existing);
  }
  if (simulatorRecoveryPromise) return simulatorRecoveryPromise;

  simulatorRecoveryPromise = new Promise((resolve, reject) => {
    const source = new URL("simulator.js", window.location.href);
    source.searchParams.set("v", "echem-simulator-4");
    source.searchParams.set("recovery", Date.now().toString());
    const script = document.createElement("script");
    script.src = source.href;
    script.onload = () => {
      const recovered = globalThis.SpectraLoopSimulatorCore;
      if (recovered && typeof recovered.buildSimulationSession === "function") {
        resolve(recovered);
        return;
      }
      simulatorRecoveryPromise = null;
      reject(new Error("The simulator module loaded without its required function."));
    };
    script.onerror = () => {
      simulatorRecoveryPromise = null;
      reject(new Error("The simulator module could not be downloaded."));
    };
    document.head.append(script);
  });
  return simulatorRecoveryPromise;
}

function showEchemView(name, updateUrl = true) {
  const target = name === "data" ? "data" : "protocol";
  echemViews.forEach((view) => { view.hidden = view.dataset.echemView !== target; });
  echemSwitches.forEach((button) => {
    const selected = button.dataset.viewTarget === target;
    button.classList.toggle("active", selected);
    button.setAttribute("aria-selected", String(selected));
    button.tabIndex = selected ? 0 : -1;
  });
  if (updateUrl) {
    const url = new URL(window.location.href);
    url.searchParams.set("view", target);
    window.history.replaceState({}, "", url);
  }
}

async function runConnectionFreeSimulation() {
  const button = document.querySelector("#run-simulation");
  const status = document.querySelector("#simulation-builder-status");
  const plan = globalThis.SpectraLoopProtocolCore.buildValidatedPlan();
  if (!plan.validation.valid) {
    status.textContent = `Fix ${plan.validation.errors.length} protocol error${plan.validation.errors.length === 1 ? "" : "s"} before simulation.`;
    document.querySelector("#protocol-warnings")?.scrollIntoView({ behavior: "smooth", block: "center" });
    return;
  }
  button.disabled = true;
  button.textContent = "Simulating…";
  status.textContent = "Generating deterministic EChem data…";
  try {
    const simulator = await ensureSimulationCore();
    const scenario = document.querySelector("#simulation-scenario").value;
    const session = simulator.buildSimulationSession(plan, { scenario });
    globalThis.SpectraLoopMonitorCore.loadSimulationSession(session, { autoplay: true });
    showEchemView("data");
    const bridgeClient = globalThis.SpectraLoopEchemBridgeCore?.getClient?.();
    if (!bridgeClient) {
      status.textContent = `${session.electrochemistry.length} EChem points generated · 0 hardware calls · not saved: check the local bridge and choose a storage folder.`;
      document.querySelector("#simulation-session-status").textContent = "Not saved · check the local bridge and choose a storage folder";
    } else {
      try {
        const result = await bridgeClient.saveSimulation(session);
        status.textContent = `${session.electrochemistry.length} EChem points generated · saved in ${result.simulation.folder}.`;
        document.querySelector("#simulation-session-status").textContent = `Saved in ${result.simulation.folder}`;
      } catch (saveError) {
        status.textContent = `${session.electrochemistry.length} EChem points generated · simulation complete but not saved: ${saveError instanceof Error ? saveError.message : String(saveError)}`;
        document.querySelector("#simulation-session-status").textContent = `Not saved · ${saveError instanceof Error ? saveError.message : String(saveError)}`;
      }
    }
  } catch (error) {
    status.textContent = `Simulation stopped: ${error instanceof Error ? error.message : String(error)}`;
  } finally {
    button.disabled = false;
    button.textContent = "Run simulation";
  }
}

function markSimulationStale() {
  document.querySelector("#simulation-builder-status").textContent = "Protocol or scenario changed · run again to refresh EChem data.";
  document.querySelector("#simulation-session-status").textContent = "Previous preview/session · current builder values have not been simulated";
  const state = document.querySelector("#simulation-session-state");
  state.textContent = "Rerun needed";
  state.classList.remove("failed");
  state.classList.add("stale");
}

echemSwitches.forEach((button) => {
  button.addEventListener("click", () => showEchemView(button.dataset.viewTarget));
  button.addEventListener("keydown", (event) => {
    if (!["ArrowLeft", "ArrowRight"].includes(event.key)) return;
    event.preventDefault();
    const currentIndex = echemSwitches.indexOf(button);
    const direction = event.key === "ArrowRight" ? 1 : -1;
    const next = echemSwitches[(currentIndex + direction + echemSwitches.length) % echemSwitches.length];
    showEchemView(next.dataset.viewTarget);
    next.focus();
  });
});

showEchemView(new URLSearchParams(window.location.search).get("view"), false);

document.querySelector("#run-simulation").addEventListener("click", runConnectionFreeSimulation);
document.querySelector("#protocol-view").addEventListener("input", (event) => {
  if (!event.target.closest("#offline-checks")) markSimulationStale();
});
document.querySelector("#protocol-view").addEventListener("change", (event) => {
  if (!event.target.closest("#offline-checks")) markSimulationStale();
});
document.querySelector("#protocol-view").addEventListener("click", (event) => {
  if (event.target.closest("#add-step, #load-protocol, button[data-action]")) markSimulationStale();
});

globalThis.SpectraLoopEchemCore = {
  ensureSimulationCore,
  markSimulationStale,
  runConnectionFreeSimulation,
  showEchemView,
};

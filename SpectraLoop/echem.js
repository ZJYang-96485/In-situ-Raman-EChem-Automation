const echemViews = [...document.querySelectorAll("[data-echem-view]")];
const echemSwitches = [...document.querySelectorAll("[data-view-target]")];

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

function runConnectionFreeSimulation() {
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
  status.textContent = "Generating deterministic synchronized data…";
  try {
    const scenario = document.querySelector("#simulation-scenario").value;
    const session = globalThis.SpectraLoopSimulatorCore.buildSimulationSession(plan, { scenario });
    globalThis.SpectraLoopMonitorCore.loadSimulationSession(session, { autoplay: true });
    status.textContent = `${session.electrochemistry.length} EChem points and ${session.raman.length} Raman frames generated · 0 hardware calls.`;
    showEchemView("data");
  } catch (error) {
    status.textContent = `Simulation stopped: ${error instanceof Error ? error.message : String(error)}`;
  } finally {
    button.disabled = false;
    button.textContent = "Run simulation";
  }
}

function markSimulationStale() {
  document.querySelector("#simulation-builder-status").textContent = "Protocol or scenario changed · run again to refresh synchronized data.";
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

globalThis.SpectraLoopEchemCore = { markSimulationStale, runConnectionFreeSimulation, showEchemView };

# SpectraLoop

SpectraLoop is a dependency-free browser interface for planning coordinated CHI
760E and operando Raman experiments, with disk-only RDE available as an option.
The static pages remain safe when opened by themselves. On the instrument PC,
an authenticated loopback bridge can provide native storage-folder selection
and, once a verified vendor adapter exists, an identity-only CHI connection.

## Pages

- `index.html` — public concept and I-Corps introduction.
- `setup.html` — model-profiled instrument, local-bridge/storage, Raman, and
  analysis configuration.
- `echem.html` — the single electrochemistry workspace. Switch between the CHI
  760E protocol builder and synchronized electrochemistry/Raman data without
  leaving the page. The builder includes offline checks and a connection-free
  protocol execution simulator.

The older `protocols.html`, `monitor.html`, and `smoke-test.html` routes redirect
to the corresponding view on `echem.html`.

The protocol builder distinguishes documented public-libec mappings, derived
calculations, desktop-only workflows, and installed-SDK verification items.
Chronocoulometry (CC) is derived from CA by integrating current over time.
Automatic iR preparation and cleanup appear in the exported plan. Trials 1–9
target confirmed 95% compensation; the 10th trial's valid value is accepted if
the target has not been reached. Execution remains locked until the installed
760E SDK exposes verified parameters/modes and application readback passes on a
test cell.

The execution simulator uses the current protocol rather than a fixed example.
It generates deterministic technique-specific CHI data, simulated Raman
frames, explicit iR trials, derived CC, and commanded-only RDE values. Standard,
trial-10, Ru-failure, acquisition-failure, and cleanup-failure scenarios remain
entirely in the browser and always report zero hardware calls.

The synchronized-data view places only the electrochemistry plot and Raman plot
side by side on desktop, using a shared time cursor. RDE disk/RPM data and the
run log are intentionally not displayed there. “Synchronized” means software
alignment on a simulated shared elapsed-time axis; it does not claim measured
device timing.

The compact offline check validates the current builder values. Every result is
available on demand, and the exported report always records simulation mode and
zero hardware calls.

See [the synchronized data contract](synchronized-data-contract.md) for the
planned record fields and alignment rules.

## Local instrument-computer use

Double-click `Start SpectraLoop.cmd` in the repository root. It starts the
dependency-free Python bridge on `127.0.0.1:8765` and opens
`https://spectraloop.org/echem.html` with a new, temporary authentication
token. The page can then open the normal
Windows folder picker and persist the chosen data root in the current user's
local application settings. Users do not need to open VS Code or type a path.
Until the updated public site has been deployed, double-click
`Start SpectraLoop Local.cmd` instead; it opens the same bundled interface from
the loopback service and requires no internet connection.

The bridge:

- binds only to loopback and rejects non-local Host headers;
- accepts only the deployed `https://spectraloop.org` origins and its own local
  UI origins;
- requires an unguessable bearer token delivered in a URL fragment and removed
  from the visible URL after loading;
- returns only the chosen folder's name to the web page, keeping the full path
  inside the local service;
- exposes no experiment endpoint and reports experiment control disabled;
- requires four web confirmations plus a separate Windows confirmation before
  any future identity query.

The current CHI adapter status is intentionally `adapter_unavailable`, because
the installed CHI 760E package does not document a non-energizing identity API.
Consequently the bridge makes zero CHI hardware calls today. A matching,
verified discovery transport can later be injected through
`CHI760EDiscoveryGateway` without changing the browser or storage workflow.

For command-line development without the deployed site, start the bridge from
the `CHI760 Potentiostat` directory without `--web-url`; it serves and opens
the bundled UI. The static interface can also be served directly:

Serve from the repository root:

```sh
python -m http.server 8000 --directory SpectraLoop
```

Then open `http://localhost:8000`.

## GitHub Pages

The repository's **Deploy SpectraLoop to GitHub Pages** workflow publishes the
`SpectraLoop/` directory after GitHub Pages is configured to use GitHub Actions.
Publishing the static interface makes the bridge controls available at the
public site, but it does not itself enable hardware I/O. The local bridge must
be running on the instrument PC with a valid session token, and its local
vendor adapter must separately report ready.

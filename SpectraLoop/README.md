# SpectraLoop

SpectraLoop is a dependency-free static interface for planning coordinated CHI
760E and operando Raman experiments, with disk-only RDE available as an option. Every current page is offline: it can
save or export JSON but cannot contact instruments.

## Pages

- `index.html` — public concept and I-Corps introduction.
- `setup.html` — model-profiled instrument, Raman, and analysis configuration.
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

The synchronized-data view uses those generated records for interface
development. “Synchronized” means software alignment on a simulated shared
elapsed-time axis; it does not claim measured device timing.

The compact offline check validates the current builder values. Every result is
available on demand, and the exported report always records simulation mode and
zero hardware calls.

See [the synchronized data contract](synchronized-data-contract.md) for the
planned record fields and alignment rules.

## Local use

Serve from the repository root:

```sh
python -m http.server 8000 --directory SpectraLoop
```

Then open `http://localhost:8000`.

## GitHub Pages

The repository's **Deploy SpectraLoop to GitHub Pages** workflow publishes the
`SpectraLoop/` directory after GitHub Pages is configured to use GitHub Actions.
Publishing this static interface does not enable local laboratory hardware I/O.

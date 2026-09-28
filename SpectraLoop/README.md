# SpectraLoop

SpectraLoop is a dependency-free static interface for planning coordinated CHI
760E and operando Raman experiments, with disk-only RDE available as an option. Every current page is offline: it can
save or export JSON but cannot contact instruments.

## Pages

- `index.html` — public concept and I-Corps introduction.
- `setup.html` — model-profiled instrument, Raman, and analysis configuration.
- `protocols.html` — editable CHI 760E protocol builder adapted from the
  [`ZJYang-96485/RDE`](https://github.com/ZJYang-96485/RDE) workflow.
- `monitor.html` — simulated synchronized electrochemistry/Raman screen with an
  optional disk-only RDE overlay, one shared cursor, and preserved source timestamps.
- `smoke-test.html` — one-click, connection-free acceptance checks for protocol
  validation, iR trial behavior, failure cleanup, CC integration, synchronized
  records, and optional disk-only RDE commands.

The protocol builder distinguishes documented public-libec mappings, derived
calculations, desktop-only workflows, and installed-SDK verification items.
Chronocoulometry (CC) is derived from CA by integrating current over time.
Automatic iR preparation and cleanup appear in the exported plan. Trials 1–9
target confirmed 95% compensation; the 10th trial's valid value is accepted if
the target has not been reached. Execution remains locked until the installed
760E SDK exposes verified parameters/modes and application readback passes on a
test cell.

The monitor uses generated data for interface development. “Synchronized” on
that page means software alignment on a simulated shared elapsed-time axis; it
does not claim measured device timing.

The browser smoke test may validate the protocol saved by `protocols.html` or
use its built-in all-techniques protocol. Every result is displayed separately,
and the exported report always records simulation mode and zero hardware calls.

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

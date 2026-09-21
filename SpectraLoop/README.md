# SpectraLoop — Adaptive Operando Raman Spectroscopy Platform

## GitHub Pages deployment

This static application is deployed from the `SpectraLoop/` directory by the
repository's **Deploy SpectraLoop to GitHub Pages** workflow. On GitHub, enable
**Settings → Pages → Build and deployment → Source: GitHub Actions**, then push
to `main` (or run the workflow manually).

The deployed page keeps all hardware settings in the browser and does not make
network calls to laboratory instruments. It is suitable for setup,
documentation, and configuration export, but not live instrument control.

SpectraLoop is the first user-facing setup console for this project. It is a
dependency-free static web app that configures three areas:

1. a model-profiled CHI 760-series potentiostat;
2. Raman acquisition and Raman-owned preprocessing; and
3. a downstream Machine Learning Platform workspace.

It runs entirely in the browser and only saves/exports JSON configuration. It
does not connect to hardware, control the laser, issue a trigger, or execute an
experiment.

`introduction.html` is a separate I-Corps introduction and customer-discovery
page. It is deliberately marked **under construction** and is not part of the
experiment setup console.

Serve it locally from the repository root:

```sh
python -m http.server 8000 --directory SpectraLoop
```

Then open `http://localhost:8000` in a browser.

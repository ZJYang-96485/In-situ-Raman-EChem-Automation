# In-situ Raman Electrochemistry Automation

This project supports model-profiled CH Instruments CHI 760-series
potentiostats with a current focus on the 760E, a connection-safe Raman acquisition scaffold, and a separate
post-experimental Machine Learning Platform that forms the data foundation for
future safety-gated decision automation.

## License

This project is [proprietary and protected — all rights reserved](LICENSE).
No use, copying, modification, or distribution is permitted without prior
written permission from the copyright holder.

## CHI 760-series potentiostat module

The controller and parameter models live in
[`CHI760 Potentiostat/chi760`](CHI760%20Potentiostat/chi760). The included
`MockCHI760` and the traceable `DryRunCHI760E` backend exercise the automation
workflow without connecting to an instrument. Select `760B`, `760C`, `760D`, or `760E` when creating
`CHI760Controller`; each profile gates the techniques that this project exposes.
This repository does not yet include a verified live hardware driver.

For the 760E, the offline surface includes the techniques listed in the public
libec model matrix: CV, i-t, CA, SWV, IMP/EIS, IMPE, OCPT/OCP, STEP, and
ISTEP/CPCS. Chronocoulometry (CC) is calculated from a CA current trace as
charge in coulombs; it is not claimed as a separate libec technique. LSV is
marked desktop-only for 760E, and GEIS requires installed-SDK verification.
The project profiles follow the
[vendor's 7xx libec automation matrix](https://www.chinstruments.com/software/libec/libec.shtml);
this is an automation-interface constraint, not a claim about every capability
of the physical instrument or its desktop software.

A production backend, including the exact automatic iR-compensation parameter
mapping and readback, must be implemented and validated against the
vendor-supported CHI 760 interface before it is used with hardware. It must
be validated separately for every selected model profile.

The Windows execution-node boundary is now default-deny. The live 760E backend
accepts only a fully evidenced discovery adapter and otherwise raises before
any vendor transport call. All experiment and non-electrochemistry hardware
domains remain blocked; simulation, replay, import, display, and post-processing
remain available.

The current connection boundary keeps all unverified vendor entry points and
parameter identifiers unresolved. On macOS it can inspect copied SDK DLLs
without loading them, exercise all nine profiled 760E libec technique paths and
the iR policy with zero hardware calls, save the command trace, and replay it
while rejecting parameter drift.
See the [CHI 760E module guide](CHI760%20Potentiostat/README.md#connection-free-backend-and-mac-checks).

Example:

```python
from chi760 import CHI760Controller, MockCHI760

potentiostat = CHI760Controller(MockCHI760(), model="760E")
potentiostat.connect()
```

## Raman module

[`Raman Spectroscopy`](Raman%20Spectroscopy) now contains a mock-first,
connection-safe structure for the pictured Raman setup. It records a
provisional Andor/Solis hardware profile, models plans and raw CCD frames, and
provides a deterministic mock backend for development. The future
`AndorSolisBackend` intentionally raises before any SDK or hardware access.

Laser and TTL trigger control are deliberately out of scope until the physical
wiring, interlocks, and vendor interfaces are verified. See the
[Raman pre-connection checklist](Raman%20Spectroscopy/docs/pre-connection-checklist.md)
before a live integration.

## Machine Learning Platform

[`Machine Learning Platform`](Machine%20Learning%20Platform) is reserved for
post-experimental analysis and ML. Raman diagnostics, despiking, smoothing,
baseline correction, normalization, and calibration remain in the Raman
module; the ML workspace requires preprocessing provenance rather than creating
a second cleaning pipeline.

## SpectraLoop app

[`SpectraLoop`](SpectraLoop) is the user-friendly first setup app for a
coordinated electrochemistry/Raman workflow and a future safety-gated
decision-automation layer. It runs in a browser and exports
configuration, protocol, check-report, and simulated-session JSON. Its single electrochemistry page switches
between a CHI 760E protocol builder and synchronized data, with optional
disk-only RDE planning, a compact offline check, and a connection-free
execution simulator driven by the current protocol. The simulator generates
deterministic synchronized data and explicit fault states with zero hardware
calls. No hardware, laser, trigger, physical iR action, or automated decision
action is available from the app. A loopback-only local bridge now lets the
setup page select a data folder using the Windows folder picker and provides
the secured boundary for a future verified CHI identity adapter. No experiment
endpoint is enabled.

On the instrument computer, double-click `Start SpectraLoop.cmd`; no VS Code
session or Python package installation is required. The launcher resolves the
repository location at runtime, starts the bridge only on `127.0.0.1`, and opens
`spectraloop.org` with a temporary authentication token. The same bridge can
serve the bundled interface when working offline by double-clicking
`Start SpectraLoop Local.cmd`.

### GitHub Pages

The same app is prepared for GitHub Pages through the repository workflow
`Deploy SpectraLoop to GitHub Pages`. GitHub Pages hosts the static interface;
all storage and future potentiostat access remain local to the instrument
computer and require the authenticated bridge.

# In-situ Raman Electrochemistry Automation

This project supports model-profiled CH Instruments CHI 760-series
potentiostats, a connection-safe Raman acquisition scaffold, and a separate
post-experimental Machine Learning Platform that forms the data foundation for
future safety-gated decision automation.

## License

This project is [proprietary and protected — all rights reserved](LICENSE).
No use, copying, modification, or distribution is permitted without prior
written permission from the copyright holder.

## CHI 760-series potentiostat module

The controller and parameter models live in
[`CHI760 Potentiostat/chi760`](CHI760%20Potentiostat/chi760). The included
`MockCHI760` backend exercises the automation workflow without connecting to
an instrument. Select `760B`, `760C`, `760D`, or `760E` when creating
`CHI760Controller`; each profile gates the techniques that this project exposes.
This repository does not yet include a live hardware driver.

The public surface includes CV, amperometric i-t, LSV, EIS, and OCP only when
the selected model profile allows them. The project profiles follow the
[vendor's 7xx libec automation matrix](https://www.chinstruments.com/software/libec/libec.shtml);
this is an automation-interface constraint, not a claim about every capability
of the physical instrument or its desktop software.

A production backend must be implemented and validated against the
vendor-supported CHI 760 interface before it is used with hardware. It must
be validated separately for every selected model profile.

Example:

```python
from chi760 import CHI760Controller, MockCHI760

potentiostat = CHI760Controller(MockCHI760(), model="760B")
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
decision-automation layer. It runs locally in a browser and exports
configuration JSON only—no hardware, laser, trigger, or automated decision
action is available from the app.

### GitHub Pages

The same app is prepared for GitHub Pages through the repository workflow
`Deploy SpectraLoop to GitHub Pages`. GitHub Pages hosts the static interface;
live Raman and potentiostat control remain local to the instrument computer.

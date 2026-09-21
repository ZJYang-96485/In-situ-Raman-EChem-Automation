# Raman Spectroscopy module

This is a mock-first Raman acquisition structure for the unconnected setup.
It does not load vendor software, enumerate devices, operate the Andor camera
or spectrograph, change detector settings, send TTL signals, or control the
Ondax laser hardware.

## What is included

- Immutable hardware, acquisition-plan, raw-frame, and result models.
- `RamanController`, which owns connection state and allows only software
  triggering.
- `MockRamanBackend`, which generates deterministic synthetic CCD-like frames
  for development.
- `AndorSolisBackend`, an intentionally disabled boundary for a future live
  Andor SDK/Solis implementation.
- A pure wavelength/Raman-shift calibration helper; it requires a verified
  calibration record and cannot alter instrument settings.
- Raman-owned diagnostics, despiking, smoothing, baseline correction, and
  normalization. Downstream analysis receives their recorded outputs rather
  than owning raw-spectrum cleanup.
- A JSON hardware inventory template, initially set to `mock` and
  `connection_enabled: false`.

The example inventory transcribes visible identifiers from the supplied photos
as provisional information: an Andor detector (`DU420A-BEX2-DD`, `CCD-15119`),
an Andor spectrograph (`SR-303i-A-SIL`), Solis for Spectroscopy, and an Ondax
laser controller. Confirm every item at the bench before treating it as a
hardware record.

## Development example

Run from this directory:

```python
from raman import (
    MockRamanBackend,
    RamanAcquisitionParameters,
    RamanAcquisitionPlan,
    RamanController,
)

controller = RamanController(MockRamanBackend())
controller.connect()
result = controller.acquire(
    RamanAcquisitionPlan(RamanAcquisitionParameters(exposure_time_s=0.1)),
    correlation_metadata={"electrochemistry_run_id": "planned-run-001"},
)
controller.disconnect()
```

`result.frames` contains raw pixel-axis/counts data. It deliberately does not
pretend to be wavelength- or Raman-shift-calibrated.

`create_raman_backend(load_raman_configuration(...))` can select the mock
backend from the JSON template. Selecting `andor_solis` only constructs the
disabled adapter; it still cannot connect to equipment. A future live attempt
must pass both safeguards: `connection_enabled: true` and a verified hardware
profile. Those gates still do not replace the adapter's own hardware checks.

Run the checks with:

```sh
python -B -m unittest discover -s tests -v
```

See [the pre-connection checklist](docs/pre-connection-checklist.md) before a
live integration is started.

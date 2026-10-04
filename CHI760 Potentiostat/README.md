# CHI 760-series Potentiostat

This module provides a connection-free, model-profiled planning surface for CH
Instruments 760-series automation. The current development target is the CHI
760E.

## Electrochemistry-only Windows node

The default `ELECTROCHEMISTRY_ONLY` runtime profile permits only a verified CHI
discovery transport. Experiment execution, cell control, iR application, Raman
acquisition, laser and TTL control, RDE motor control, ML actions, and automated
decisions raise before a hardware callback can run. Simulation, replay, data
display/import, and derived calculations remain available.

`CHI760ELiveBackend` is discovery-only and contains no guessed DLL, COM, serial,
or executable binding. It can use an adapter only when matching vendor evidence
supplies exact open, identity, capability, and close identifiers. Missing
values, missing return codes, failures, and timeouts are errors and close the
logical session. Every experiment method remains blocked even when a fake
discovery adapter is present.

The installed CHI 760E help on the audited Windows computer documents a desktop
command-line macro runner. That path includes experiment, cell, trigger, and
RDE commands but no read-only identity query. It is therefore recorded as
evidence and is not invoked. A connected USB/serial cable does not change this
gate.

`RunDataStore` reserves unique timestamped run directories, refuses overwrite,
keeps raw and processed files separate, flushes append-only records, and uses
atomic metadata/protocol writes. Until an experiment is configured and
authorized, the real `data/runs/` directory remains empty; read-only inspection
records belong under `data/discovery/` and simulations under
`data/simulations/`.

`chi760.web_bridge` exposes the same fail-closed boundary to the SpectraLoop
browser UI. It listens only on loopback, requires a per-launch bearer token,
restricts browser origins, and exposes storage selection plus identity
discovery only. Its default gateway is unavailable and makes zero hardware
calls. A future ready adapter also requires a local Windows approval immediately
before discovery. There is deliberately no experiment-control HTTP endpoint.

```python
from chi760 import CHI760Controller, MockCHI760

potentiostat = CHI760Controller(MockCHI760(), model="760E")
```

## CHI 760E capability distinctions

The 760E profile includes the techniques listed for 7xxE in the public CH
Instruments libec matrix:

| Project name | Public libec name | Status in this repository |
| --- | --- | --- |
| CV | CV | Profiled; mock and zero-hardware dry run |
| Amperometric i-t | i-t | Profiled; mock and zero-hardware dry run |
| Chronoamperometry | CA | Profiled; mock and zero-hardware dry run |
| Square-wave voltammetry | SWV | Profiled; mock and zero-hardware dry run |
| Potentiostatic EIS | IMP | Profiled; mock and zero-hardware dry run |
| Impedance versus potential | IMPE | Profiled; mock and zero-hardware dry run |
| Open-circuit potential | OCPT | Profiled; mock and zero-hardware dry run |
| Multi-potential steps | STEP | Profiled; mock and zero-hardware dry run |
| Current steps / chronopotentiometry | ISTEP/CPCS | Profiled; mock and zero-hardware dry run |
| Chronocoulometry (CC) | CA + integration of current over time | Derived locally; no separate CC capability claimed |
| LSV | LSV in the desktop workflow | Not listed for 7xxE in the public libec matrix |
| Galvanostatic EIS | IMP mode | Installed-SDK verification required |
| iR compensation | Installed-SDK parameters/mode | Installed-SDK and device verification required |

“Profiled” means parameter models, controller gates, protocol mapping, and mock
methods exist. It does not mean a physical device has been connected or that a
live vendor call has been validated.

CC is represented as chronocoulometry derived from a CA current/time record:

```python
from chi760 import chronocoulometry_from_ca_C

charge_C = chronocoulometry_from_ca_C(
    time_s=[0, 1, 2],
    current_A=[0.002, 0.002, 0.002],
)
```

The reference repository also names constant-current battery steps
`cc_charge`/`cc_discharge`. Those remain clearly separate: they map to a
current-step/chronopotentiometry plan plus capacity integration and are not
called chronocoulometry in this project.

## RDE protocol adaptation

`adapt_rde_protocol()` translates protocol JSON from
[`ZJYang-96485/RDE`](https://github.com/ZJYang-96485/RDE) into an
execution-disabled CHI 760E plan. It preserves source parameters and records one
of four explicit outcomes instead of silently substituting techniques:

- documented 760E libec mapping;
- local orchestration or derived calculation;
- desktop-only workflow;
- installed-SDK verification required.

The optional disk-only RDE builder supports commanded rotation sequences, equilibration,
electrochemical trials, Raman capture markers, and mandatory final RDE stop.
Actual RDE control remains connection-dependent because the controller and its
communication interface have not been identified in this repository.

## Automated iR compensation plan

The offline policy supports fresh Ru measurement attempts for every eligible
trial, repeatability/range validation, and iterative application/readback toward
a 95% compensation target. Trials 1–9 stop when the target is confirmed; at the
10th trial, its valid value is accepted even below 95%. An invalid final value
uses the configured failure/fallback policy. Cleanup always disables
compensation.

The 95% target and 10-trial ceiling are the default policy. Other numerical
preparation defaults are copied from the referenced RDE project for editability
and parity. General electrochemistry limits are supplied by the global protocol
configuration; the installed CHI interface still has to establish the exact
write, readback, disable, and cell-off bindings.

This is a plan, not working 760E control. Positive-feedback, current-interrupt,
and automatic mode names describe the requested strategies. The exact
automation identifiers will be populated from the installed CHI SDK, then the
first connected smoke test will verify parameter write, readback, and cleanup
on a dummy/test setup.

See [the pre-connection checklist](docs/pre-connection-checklist.md) for the
information and acceptance tests needed before a live adapter can be enabled.

## Connection-free backend and Mac checks

`DryRunCHI760E` implements the same controller boundary without loading a
vendor library or contacting a device. It records every intended operation in a
JSON-safe trace, reports zero hardware calls, and supports exact replay that
rejects command or parameter drift.

Run these commands from this directory on macOS:

```sh
python -m chi760 mapping
python -m chi760 preflight
python -m chi760 dry-run-smoke --output /tmp/chi760e-dry-run.json
python -m chi760 replay /tmp/chi760e-dry-run.json
```

`mapping` shows unresolved vendor entry points and parameter identifiers.
`preflight` is read-only: when SDK files are supplied, it hashes them and parses
Windows PE architecture and export names without loading a DLL. `dry-run-smoke`
exercises all nine currently profiled 760E libec technique paths, the
95%/10-trial iR policy, compensation disable, and cell-off planning. It never
performs a device call. LSV remains desktop-only, GEIS remains an unresolved
installed-SDK item, and the optional disk RDE requires a separate controller.
`replay` validates the trace schema, UTC and monotonic timestamps, finite numeric
values, operation order, and every recorded parameter before reporting success.

When the installed 760E package is available, copy only the relevant SDK DLLs,
headers, and matching vendor documentation to an inspection location and pass
the DLL paths to `preflight`. Do not guess `--required-export` names; add those
only after an installed header, sample, or manual identifies them.

## Tests

Run from this directory:

```sh
python -B -m unittest discover -s tests -v
python -m mypy chi760 tests
```

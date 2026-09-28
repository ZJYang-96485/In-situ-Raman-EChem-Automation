# CHI 760-series Potentiostat

This module provides a connection-free, model-profiled planning surface for CH
Instruments 760-series automation. The current development target is the CHI
760E.

```python
from chi760 import CHI760Controller, MockCHI760

potentiostat = CHI760Controller(MockCHI760(), model="760E")
```

## CHI 760E capability distinctions

The 760E profile includes the techniques listed for 7xxE in the public CH
Instruments libec matrix:

| Project name | Public libec name | Status in this repository |
| --- | --- | --- |
| CV | CV | Profiled; mock only |
| Amperometric i-t | i-t | Profiled; mock only |
| Chronoamperometry | CA | Profiled; mock only |
| Square-wave voltammetry | SWV | Profiled; mock only |
| Potentiostatic EIS | IMP | Profiled; mock only |
| Impedance versus potential | IMPE | Profiled; mock only |
| Open-circuit potential | OCPT | Profiled; mock only |
| Multi-potential steps | STEP | Profiled; mock only |
| Current steps / chronopotentiometry | ISTEP/CPCS | Profiled; mock only |
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

The 95% target and 10-trial ceiling are the current user-defined policy. Other
numerical preparation defaults are copied from the referenced RDE project for
editability and parity. Live use remains unapproved until the chemistry is
reviewed and the settings are mapped to the installed CHI interface.

This is a plan, not working 760E control. Positive-feedback, current-interrupt,
and automatic mode names are requested strategies only. The installed CHI SDK
must first confirm which modes and parameter identifiers are actually available.
Live execution stays disabled until a parameter write and readback test passes
on an approved test cell.

See [the pre-connection checklist](docs/pre-connection-checklist.md) for the
information and acceptance tests needed before a live adapter can be enabled.

## Tests

Run from this directory:

```sh
python -B -m unittest discover -s tests -v
```

# CHI 760B commissioning

## Verified preparation state

The 760B has a dedicated repository-local 32-bit worker runtime and launcher:

- `.runtime/chi760b-worker/libec760b.dll` with its required Qt runtime files;
- `.runtime/python-x86/python.exe` for the isolated worker process;
- `Start SpectraLoop 760B.cmd` for the deployed or bundled web interface.

Static inspection and read-only SDK discovery established an x86 7B library
with the required CV worker exports. The SDK reports CV and amperometric i-t as
the supported 760B automation techniques. It exposes no serial-number or
firmware getter, so the SDK model-series result is not independent proof of the
specific physical instrument connected to the USB cable.

The bridge and browser support only one real 760B operation: a bounded
internal-dummy CV. Amperometric i-t remains planning-only. It is not presented
as chronoamperometry because the validated 760B SDK surface does not expose a
native CA technique.

## First-run boundary

The first physical run must use the CHI internal dummy cell, not an external
sample. The protocol is constrained to:

- exactly one CV and one cycle (two sweeps);
- positive initial scan;
- all potentials within +/-0.25 V;
- scan rate 0.01-0.2 V/s;
- potential step 0.001-0.01 V;
- quiet time no longer than 10 seconds;
- iR compensation and Raman disabled.

Preparation reserves `data/runs/<date>/<task>/trial-NNN/` and writes the
validated protocol without calling the worker. Start requires all browser
confirmations and a separate Windows approval on the instrument computer. The
worker checks model series 7B, writes and reads back every CV parameter, provides
remote Stop, requests `CHI_Stop` during cleanup, turns the cell off, retrieves
the result, and saves raw data and metadata locally.

## Remaining physical acceptance

The software path, route isolation, model mismatch lock, storage selection,
worker preflight, Stop route, and cleanup code are covered by automated tests.
The first real internal-dummy CV has not yet been completed. External-sample
experiments remain out of scope until that run confirms:

- the connected unit accepts the 7B SDK session;
- saved potential/current data are complete and parseable;
- Stop and cell-off cleanup behave as expected;
- the operator verifies the instrument returns to a safe idle state.

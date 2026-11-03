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

The bridge and the existing Protocol Builder now support direct ordered 760B
sequences containing Wait, CV, and Amperometric i-t steps. Amperometric i-t is
not presented as chronoamperometry because the validated 760B SDK surface does
not expose a native CA technique.

## Direct protocol behavior

The prepared cell and electrode setup remains the operator's selected setup.
The direct protocol accepts ordered Wait, CV, and Amperometric i-t steps. For
CV, SpectraLoop applies no commissioning voltage ceiling and no maximum cycle
count. It checks only that numeric values are finite, cycles are a positive
integer, and rate/step values are positive, then leaves the operating range to
the CHI SDK and instrument.

The installed DLL documents `m_inpcl` as sweep segments, each one half-cycle,
so the worker sends two sweep segments per requested cycle. It exposes no
independent Final E parameter. A final value equal to Initial E enables
`m_bFullCycle` and adds the return segment; any other final value is retained in
the saved protocol while the SDK determines the physical endpoint from its
sweep segments. iR compensation remains visible and saved, but enabled iR
fails preflight because its 760B SDK parameter mapping is not yet verified.

Preparation reserves `data/runs/<date>/<task>/trial-NNN/` and writes the
validated protocol without calling the worker. The 760B browser confirmation
checklist has been removed; start retains the separate Windows approval on the instrument computer. The
worker checks model series 7B, writes and reads back every CV/i-t parameter, provides
remote Stop, requests `CHI_Stop` during cleanup, turns the cell off, retrieves
the results, and saves a step-aware CSV plus metadata locally.

## Remaining physical acceptance

The software path, route isolation, model mismatch lock, storage selection,
worker preflight, Stop route, and cleanup code are covered by automated tests.
The first real direct 760B sequence has not yet been completed. It remains a
physical acceptance step that must confirm:

- the connected unit accepts the 7B SDK session;
- saved potential/current data are complete and parseable;
- Stop and cell-off cleanup behave as expected;
- the operator verifies the instrument returns to a safe idle state.

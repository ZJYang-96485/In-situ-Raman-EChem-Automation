# CHI 760B offline commissioning

## Current safety state

The connected CHI 760B is running a measurement. Treat the instrument computer,
the CHI desktop application, its configuration files, its COM/USB connection,
and its output directory as read-only operational state. Do not start another
CHI process, send a discovery command, change the serial port, restart the local
bridge, or copy mutable configuration files while the measurement is active.

The repository currently has model-profile evidence for only these 760B
automation techniques:

- cyclic voltammetry (CV);
- amperometric i-t.

That evidence is a planning gate based on the documented public libec matrix.
It is not proof that the installed 760B application exposes a compatible SDK or
desktop command-line interface. There is no 760B executable, SDK library,
header, help file, approved hash, or physical identity result in this
repository, so live 760B control remains unavailable.

## Work allowed during the measurement

- Build and validate offline CV and i-t protocol JSON.
- Run mock, simulation, schema, and model-gating tests.
- Review repository source and already-copied documentation.
- Prepare a post-measurement inspection checklist.

These activities must report zero hardware calls and must not enumerate or open
instrument ports.

## After the measurement has ended

1. Save and export the measurement in the CHI application.
2. Confirm with the operator that the cell output is off and the application
   may be closed.
3. Copy, rather than move, the 760B program's executable, help file, and any SDK
   documentation into a new repository-local inspection folder. Do not reuse
   the `chi760d` directory.
4. Hash and parse those copies without loading an executable or DLL. Record the
   product version, PE architecture, documented command-line switches, SDK
   exports, and model limitations.
5. Select an automation route only from that evidence. Do not rename or reuse a
   760D/760E adapter for the 760B.
6. Add a separate approved executable/library hash and a default-disabled local
   bridge adapter.
7. Commission first with disconnected external leads and the vendor's internal
   dummy cell, using a bounded one-cycle protocol and a local Windows approval.
8. Confirm saved output, cell-off cleanup, and an operator-accessible Stop path
   before considering an external sample.

## Acceptance criteria for live readiness

Live 760B experiments are not ready until all of the following are recorded:

- physical model and communication identity confirmed after the current run;
- vendor-supported automation entry point documented for this installed build;
- executable or library hash pinned and architecture matched;
- CV/i-t parameter mapping validated without silent unit conversion;
- unique non-overwriting output directory verified;
- bounded internal-dummy run completed and parsed;
- cell output and application cleanup confirmed;
- stop/recovery behavior tested with an operator present.


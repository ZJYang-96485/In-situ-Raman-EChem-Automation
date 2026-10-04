# CHI 760E pre-connection checklist

This checklist separates work that can be completed offline from facts that
must come from the installed CHI software or the physical system. Completing it
does not itself authorize energizing a cell, rotating an electrode, or enabling
a Raman laser.

## Already possible without a device

- Validate protocol schemas and parameter ranges.
- Translate the existing RDE protocol vocabulary to explicit CHI plan statuses.
- Generate CA voltage ranges and RDE speed schedules.
- Derive chronocoulometry (CC) by integrating CA current over time.
- Test Ru retry, range, repeatability, fallback, and cleanup logic with mock data.
- Run all nine profiled 760E libec technique paths plus the iR policy and replay
  the exact command trace with an asserted hardware-call count of zero.
- Hash candidate SDK files and inspect their PE architecture and exported names
  without loading a DLL or contacting a device.
- Exercise synchronized-screen behavior with simulated timestamps.
- Export provenance-rich protocol and data JSON.

## Information needed from the instrument computer

- Exact potentiostat model reported by the installed software.
- CHI software version and installed libec/SDK version.
- Library architecture and language binding available to the application.
- Vendor sample-program result on that computer, without a live cell first if
  the vendor permits it.
- Exact computer-to-instrument interface and operating-system device identity.
- Local path to the vendor headers/manuals that match the installed library.
- Whether the installed API reports technique and parameter availability at
  runtime, and the resulting report for this 760E.

Do not infer missing parameter identifiers or units from technique names. Store
the discovered identifier, type, units, limits, and readback behavior together.

## iR compensation verification gate

Before automatic iR compensation can be enabled, confirm all of the following:

1. The installed interface exposes an Ru-measurement path suitable for the
   intended experiment.
2. The available compensation mode or modes are identified by the installed
   SDK; do not assume positive feedback or current interrupt from the offline
   plan.
3. Compensation amount units and permitted range are confirmed.
4. The applied state and amount can be read back, or an equivalent vendor-
   documented confirmation is available.
5. Failed measurement, failed write, failed readback, abort, and disconnect all
   lead to compensation disable and a safe cell state.
6. The fixed default policy is preserved: test trials in order, stop when 95% is
   confirmed, and otherwise accept the 10th trial's valid value. Global
   electrochemistry limits remain external configuration.
7. When lab access is available, verify the mapped operations first with an
   appropriate dummy/test cell, then with the intended experimental setup.

Record every Ru attempt, rejected value, selected Ru, requested compensated Ru,
readback, mode, timestamp, and fallback/abort decision.

Items 1–5 can be checked automatically against supplied installed-SDK artifacts
and later against a connected test setup. The current Mac checks validate the
automation logic and inspect files only; they do not claim that a vendor symbol
exists or that a setting was written or read back. Item 7 necessarily waits for
lab access.

## Optional disk-only RDE and Raman information still needed

- If RDE will be used: controller make/model, control interface, RPM limits, ramp behavior, and
  whether actual speed feedback is available. Until feedback is verified, label
  RPM as a commanded setpoint.
- Raman instrument/SDK identity, acquisition timestamp definitions, exposure
  timing, and any trigger input/output behavior.
- Electrical trigger wiring, polarity, pulse-width requirements, and isolation,
  if hardware triggering will be used.
- Interlock ownership and the actions that must remain independent of software.

## Synchronization acceptance tests

- Measure host-clock offset and drift for each device path.
- Measure command-to-acquisition latency and jitter rather than assuming it.
- Preserve each source timestamp and host receipt timestamp; never overwrite
  raw clocks with an aligned time.
- Define whether a Raman frame is represented by acquisition start, midpoint,
  or end, and store all three when available.
- Test start, pause, resume, abort, reconnect, and partial-file behavior.
- Mark timing quality per record and reject downstream claims that exceed the
  measured synchronization accuracy.

## Minimum live-enable evidence

Live execution should remain locked until the repository contains a dated
verification record with the installed versions, discovered capabilities,
dummy-cell test results, iR readback result, cleanup/abort result, and measured
synchronization performance.

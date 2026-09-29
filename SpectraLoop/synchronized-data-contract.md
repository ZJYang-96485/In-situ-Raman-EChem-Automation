# Synchronized electrochemistry–Raman data contract

This is an offline design contract. Field availability and timestamp accuracy
must be verified for each connected device before they are marked as measured.

## Session

Each run has one immutable `session_id`, a monotonic sequence for every source,
the protocol-plan hash/version, instrument and software versions, and an event
log. Aborted and incomplete runs remain valid sessions with an explicit terminal
state.

## Electrochemistry record

Required planned fields:

- `session_id`, `source`, and `sequence`;
- source timestamp when available;
- host receipt timestamp;
- elapsed time derived for display;
- working-electrode potential, disk current, and their units;
- commanded RDE RPM and measured RPM as separate nullable fields;
- technique, protocol-step ID, and cycle/step index;
- iR requested mode, Ru attempts, selected Ru, requested amount, readback, and
  applied/withheld state;
- quality flags, including missing timestamps, reconnects, overranges, and
  unverified timing.

Chronocoulometry is stored as a derived series in coulombs with the integration
method, source current channel, interval bounds, and initial-charge convention.
Raw current is never replaced by integrated charge.

## Raman acquisition record

Required planned fields:

- `session_id`, `source`, `frame_id`, and sequence;
- source timestamp and host receipt timestamp;
- acquisition start, end, and midpoint when available;
- Raman-shift axis, intensity values, and units;
- exposure, accumulations, excitation wavelength, preprocessing provenance, and
  calibration reference;
- quality flags and trigger metadata.

## Alignment

The interface displays a shared elapsed-time axis but preserves all raw clocks.
The nearest Raman frame may be associated with a selected electrochemistry
sample for visualization, with a signed `delta_t_s`; this association does not
imply simultaneity. Hardware triggers, clock-offset correction, and interpolation
must each be recorded as methods rather than hidden transformations.

Timing quality starts as `simulated_unverified`. A connected integration may
upgrade that label only after latency, jitter, offset, and drift are measured.

## Connection-free simulation

Simulator sessions use `execution_mode: connection_free_simulation`,
`hardware_connected: false`, and `hardware_calls: 0`. They retain the current
protocol plan, every iR trial and repeated Ru value, explicit run and cleanup
errors, raw simulated timestamps, and `simulation_only`/`no_hardware_io`
markers. A simulated iR value is never represented as a hardware-applied value.

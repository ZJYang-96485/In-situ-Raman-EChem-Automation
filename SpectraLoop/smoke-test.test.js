const test = require("node:test");
const assert = require("node:assert/strict");

require("./protocols.js");
require("./monitor.js");
const { evaluateIRTrials, integrateCharge, runSmokeSuite, simulateTrial } = require("./smoke-test.js");

test("built-in browser smoke suite passes without hardware calls", () => {
  const report = runSmokeSuite({ includeRde: true });
  assert.equal(report.status, "passed");
  assert.equal(report.summary.failed, 0);
  assert.equal(report.summary.passed, report.summary.total);
  assert.equal(report.hardware_calls, 0);
  assert.equal(report.hardware_connected, false);
});

test("iR evaluator enforces early target, trial-10 acceptance, and invalid-final failure", () => {
  const early = evaluateIRTrials([0.8, 0.95, 0.2]);
  assert.equal(early.accepted_trial, 2);
  assert.deepEqual(early.observations, [0.8, 0.95]);

  const ceiling = evaluateIRTrials([...Array(9).fill(0.9), 0.92, 1]);
  assert.equal(ceiling.accepted_trial, 10);
  assert.equal(ceiling.accepted_fraction, 0.92);
  assert.equal(ceiling.accepted_at_ceiling, true);

  const invalid = evaluateIRTrials([...Array(9).fill(0.9), true]);
  assert.equal(invalid.accepted_fraction, null);
  assert.match(invalid.failure_reason, /no valid value/);
});

test("simulated acquisition and cleanup failures remain separately visible", () => {
  const acquisition = simulateTrial({ observedFractions: [0.95], failAcquisition: true });
  assert.match(acquisition.run_error, /acquisition failure/);
  assert.equal(acquisition.cleanup_attempted, true);
  assert.equal(acquisition.compensation_state, "disabled");

  const cleanup = simulateTrial({ observedFractions: [0.95], failCleanup: true });
  assert.match(cleanup.cleanup_error, /cleanup failure/);
  assert.notEqual(cleanup.compensation_state, "disabled");
});

test("charge integration rejects silent coercion and preserves known result", () => {
  assert.deepEqual(integrateCharge([0, 1, 2], [2, 2, 2]), [0, 2, 4]);
  assert.throws(() => integrateCharge([0, true], [1, 1]), /time values/);
  assert.throws(() => integrateCharge([0, 1], [1, Number.NaN]), /current values/);
});

test("corrupt locally saved plan produces a visible failed assertion", () => {
  const report = runSmokeSuite({
    useSaved: true,
    savedPlanRaw: JSON.stringify({
      protocol_name: "corrupt",
      steps: [{ source_technique: "unknown", name: "bad", parameters: {} }],
    }),
  });
  assert.equal(report.status, "failed");
  const protocolResult = report.results.find((result) => result.id === "protocol-validation");
  assert.equal(protocolResult.passed, false);
  assert.match(protocolResult.detail, /unknown technique/);
});

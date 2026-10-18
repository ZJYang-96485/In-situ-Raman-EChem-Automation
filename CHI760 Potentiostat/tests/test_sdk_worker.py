from __future__ import annotations

from pathlib import Path
import tempfile
import threading
from time import monotonic, sleep
import unittest

from chi760.sdk_worker import (
    CV_COMMISSIONING_CONFIRMATIONS,
    CV_COMMISSIONING_LIMITS,
    CVCommissioningJobManager,
    CV_DRY_RUN_PARAMETERS,
    REQUIRED_COMMISSIONING_EXPORTS,
    REQUIRED_DISCOVERY_EXPORTS,
    REQUIRED_RUNTIME_DLLS,
    build_parser,
    cv_plan_to_sdk_parameters,
    inspect_runtime,
    main,
    serve_requests,
    validate_cv_commissioning_plan,
)
from contextlib import redirect_stdout
from io import StringIO
import json


def bounded_cv_plan() -> dict[str, object]:
    return {
        "target_model": "760E",
        "initial_potential_v": 0.0,
        "high_potential_v": 0.2,
        "low_potential_v": -0.2,
        "initial_scan_direction": "positive",
        "scan_rate_v_s": 0.05,
        "potential_step_v": 0.002,
        "quiet_time_s": 0.0,
        "sweep_segments": 2,
    }


def commissioning_confirmations() -> dict[str, bool]:
    return {name: True for name in CV_COMMISSIONING_CONFIRMATIONS}


class ImmediateCVRunner:
    def __init__(self) -> None:
        self.plans: list[dict[str, object]] = []
        self.stop_calls = 0
        self.reset_calls = 0

    def reset_stop(self) -> None:
        self.reset_calls += 1

    def run(self, plan: dict[str, object]) -> dict[str, object]:
        self.plans.append(plan)
        return {
            "data_points": 3,
            "x_values": [-0.1, 0.0, 0.1],
            "y_values": [-1e-6, 0.0, 1e-6],
            "units": {"x": "V", "y": "A"},
        }

    def stop(self) -> None:
        self.stop_calls += 1


class BlockingCVRunner(ImmediateCVRunner):
    def __init__(self) -> None:
        super().__init__()
        self.started = threading.Event()
        self.release = threading.Event()

    def run(self, plan: dict[str, object]) -> dict[str, object]:
        self.plans.append(plan)
        self.started.set()
        if not self.release.wait(timeout=2.0):
            raise RuntimeError("fake CV runner timed out")
        return {
            "data_points": 1,
            "x_values": [0.0],
            "y_values": [0.0],
            "units": {"x": "V", "y": "A"},
        }

    def stop(self) -> None:
        super().stop()
        self.release.set()


def wait_for_job_state(
    manager: CVCommissioningJobManager,
    job_id: str,
    expected: set[str],
) -> dict[str, object]:
    deadline = monotonic() + 2.0
    while monotonic() < deadline:
        status = manager.status(job_id)
        if status["state"] in expected:
            return status
        sleep(0.01)
    raise AssertionError(f"job did not reach one of {sorted(expected)}")


class SDKWorkerTests(unittest.TestCase):
    def test_missing_sdk_fails_closed_without_loading_or_calls(self):
        with tempfile.TemporaryDirectory() as directory:
            report = inspect_runtime(directory, directory)

        self.assertFalse(report["ready_to_load"])
        self.assertFalse(report["library_loaded"])
        self.assertEqual(0, report["vendor_functions_called"])
        self.assertFalse(report["device_contacted"])
        self.assertFalse(report["experiments_enabled"])

    def test_required_surface_contains_only_discovery_candidates(self):
        self.assertEqual(
            {
                "CHI_getModelSeries",
                "CHI_getErrorStatus",
                "CHI_hasTechnique",
                "CHI_hasParameter",
            },
            set(REQUIRED_DISCOVERY_EXPORTS),
        )
        self.assertNotIn("CHI_runExperiment", REQUIRED_DISCOVERY_EXPORTS)
        self.assertNotIn("CHI_setParameter", REQUIRED_DISCOVERY_EXPORTS)
        self.assertIn("CHI_runExperiment", REQUIRED_COMMISSIONING_EXPORTS)
        self.assertIn("CHI_Stop", REQUIRED_COMMISSIONING_EXPORTS)
        self.assertIn(
            "CHI_getExperimentDataAndReturnWriteCount",
            REQUIRED_COMMISSIONING_EXPORTS,
        )
        self.assertEqual(4, len(REQUIRED_RUNTIME_DLLS))

    def test_runtime_paths_are_supplied_not_machine_coded(self):
        source = Path(__file__).resolve().parents[1] / "chi760" / "sdk_worker.py"
        text = source.read_text(encoding="utf-8")

        self.assertNotIn("Users\\", text)
        self.assertNotIn("Downloads\\", text)
        self.assertNotIn("C:\\Qt", text)

    def test_discovery_refuses_to_load_without_every_confirmation(self):
        output = StringIO()
        with redirect_stdout(output):
            result = main(
                [
                    "discover",
                    "--sdk-dir",
                    "missing-sdk",
                    "--runtime-dir",
                    "missing-runtime",
                    "--confirm-identity-only",
                ]
            )

        payload = json.loads(output.getvalue())
        self.assertEqual(2, result)
        self.assertFalse(payload["library_loaded"])
        self.assertEqual(0, payload["vendor_functions_called"])
        self.assertFalse(payload["experiments_enabled"])

    def test_sdk_dry_run_refuses_to_load_without_physical_isolation(self):
        output = StringIO()
        with redirect_stdout(output):
            result = main(
                [
                    "dry-run",
                    "--sdk-dir",
                    "missing-sdk",
                    "--runtime-dir",
                    "missing-runtime",
                    "--confirm-no-sample",
                ]
            )

        payload = json.loads(output.getvalue())
        self.assertEqual(2, result)
        self.assertFalse(payload["library_loaded"])
        self.assertEqual(0, payload["vendor_functions_called"])
        self.assertFalse(payload["experiments_enabled"])

    def test_source_requires_positive_run_result_for_dry_run_success(self):
        source = Path(__file__).resolve().parents[1] / "chi760" / "sdk_worker.py"
        text = source.read_text(encoding="utf-8")

        self.assertIn('payload["run_returned"] is not True', text)
        self.assertIn('payload["dry_run_completed"] = False', text)

    def test_connected_dry_run_uses_documented_bounded_cv_parameters(self):
        self.assertEqual(0.2, CV_DRY_RUN_PARAMETERS["m_eh"])
        self.assertEqual(-0.2, CV_DRY_RUN_PARAMETERS["m_el"])
        self.assertGreaterEqual(
            CV_DRY_RUN_PARAMETERS["m_eh"] - CV_DRY_RUN_PARAMETERS["m_el"],
            0.01,
        )
        self.assertEqual(0.05, CV_DRY_RUN_PARAMETERS["m_vv"])
        self.assertEqual(0.002, CV_DRY_RUN_PARAMETERS["m_inpsi"])
        self.assertNotIn("m_bFullCycle", CV_DRY_RUN_PARAMETERS)

    def test_commissioning_cv_is_strictly_bounded_and_maps_to_vendor_fields(self):
        normalized = validate_cv_commissioning_plan(bounded_cv_plan())
        parameters = cv_plan_to_sdk_parameters(normalized)

        self.assertEqual("760E", normalized["target_model"])
        self.assertEqual(2, normalized["sweep_segments"])
        self.assertEqual(
            {
                "m_ei",
                "m_eh",
                "m_el",
                "m_pn",
                "m_vv",
                "m_inpcl",
                "m_inpsi",
                "m_qt",
            },
            set(parameters),
        )
        self.assertEqual(1.0, parameters["m_pn"])
        self.assertEqual(2.0, parameters["m_inpcl"])

    def test_commissioning_cv_rejects_out_of_scope_or_ambiguous_values(self):
        invalid_changes = (
            {"target_model": "760D"},
            {"high_potential_v": CV_COMMISSIONING_LIMITS["potential_abs_max_v"] + 0.01},
            {"scan_rate_v_s": True},
            {"potential_step_v": float("nan")},
            {"sweep_segments": 3},
            {"initial_scan_direction": "negative"},
            {"unexpected": 1},
        )
        for changes in invalid_changes:
            plan = bounded_cv_plan()
            plan.update(changes)
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                validate_cv_commissioning_plan(plan)

    def test_serve_parser_requires_explicit_commissioning_opt_in(self):
        parser = build_parser()
        locked = parser.parse_args(
            ["serve", "--sdk-dir", "sdk", "--runtime-dir", "runtime"]
        )
        enabled = parser.parse_args(
            [
                "serve",
                "--sdk-dir",
                "sdk",
                "--runtime-dir",
                "runtime",
                "--enable-chi760e-commissioning",
            ]
        )

        self.assertFalse(locked.enable_chi760e_commissioning)
        self.assertTrue(enabled.enable_chi760e_commissioning)

    def test_persistent_protocol_serves_status_then_clean_shutdown(self):
        requests = StringIO(
            '{"schema_version":"0.1","id":1,"command":"status"}\n'
            '{"schema_version":"0.1","id":2,"command":"shutdown"}\n'
        )
        responses = StringIO()
        with tempfile.TemporaryDirectory() as directory:
            result = serve_requests(
                directory,
                directory,
                input_stream=requests,
                output_stream=responses,
            )

        payloads = [json.loads(line) for line in responses.getvalue().splitlines()]
        self.assertEqual(0, result)
        self.assertEqual([1, 2], [payload["id"] for payload in payloads])
        self.assertTrue(all(payload["ok"] for payload in payloads))
        self.assertFalse(payloads[0]["result"]["library_loaded"])
        self.assertEqual("shutdown", payloads[1]["result"]["operation"])

    def test_persistent_protocol_rejects_cv_start_when_default_locked(self):
        request = {
            "schema_version": "0.1",
            "id": 7,
            "command": "cv-start",
            "plan": bounded_cv_plan(),
            "confirmations": commissioning_confirmations(),
        }
        requests = StringIO(
            json.dumps(request) + "\n"
        )
        responses = StringIO()
        with tempfile.TemporaryDirectory() as directory:
            serve_requests(
                directory,
                directory,
                input_stream=requests,
                output_stream=responses,
            )

        payload = json.loads(responses.getvalue())
        self.assertFalse(payload["ok"])
        self.assertIn("disabled", payload["error"])

    def test_job_manager_completes_and_pages_simulated_cv_data(self):
        runner = ImmediateCVRunner()
        manager = CVCommissioningJobManager(runner)

        started = manager.start(bounded_cv_plan(), commissioning_confirmations())
        job_id = str(started["job_id"])
        status = wait_for_job_state(manager, job_id, {"completed"})
        first = manager.result_page(job_id, 0, 2)
        second = manager.result_page(job_id, 2, 2)

        self.assertEqual("completed", status["state"])
        self.assertEqual(3, status["data_points"])
        self.assertEqual([-0.1, 0.0], first["x_values"])
        self.assertEqual(2, first["next_offset"])
        self.assertEqual([0.1], second["x_values"])
        self.assertIsNone(second["next_offset"])
        self.assertEqual(1, runner.reset_calls)
        self.assertEqual(1, len(runner.plans))

    def test_job_manager_requires_every_confirmation_before_start(self):
        confirmations = commissioning_confirmations()
        confirmations[CV_COMMISSIONING_CONFIRMATIONS[-1]] = False
        runner = ImmediateCVRunner()
        manager = CVCommissioningJobManager(runner)

        with self.assertRaisesRegex(ValueError, "all local"):
            manager.start(bounded_cv_plan(), confirmations)

        self.assertEqual([], runner.plans)
        self.assertEqual(0, runner.reset_calls)

    def test_job_manager_stop_reaches_simulated_runner(self):
        runner = BlockingCVRunner()
        manager = CVCommissioningJobManager(runner)
        started = manager.start(bounded_cv_plan(), commissioning_confirmations())
        job_id = str(started["job_id"])
        self.assertTrue(runner.started.wait(timeout=1.0))

        manager.stop(job_id)
        status = wait_for_job_state(manager, job_id, {"stopped", "error"})

        self.assertEqual("stopped", status["state"])
        self.assertTrue(status["stop_requested"])
        self.assertEqual(1, runner.stop_calls)

    def test_enabled_protocol_routes_cv_start_only_to_injected_simulator(self):
        runner = ImmediateCVRunner()
        manager = CVCommissioningJobManager(runner)
        request = {
            "schema_version": "0.1",
            "id": 8,
            "command": "cv-start",
            "plan": bounded_cv_plan(),
            "confirmations": commissioning_confirmations(),
        }
        requests = StringIO(json.dumps(request) + "\n")
        responses = StringIO()
        with tempfile.TemporaryDirectory() as directory:
            serve_requests(
                directory,
                directory,
                enable_chi760e_commissioning=True,
                commissioning_jobs=manager,
                input_stream=requests,
                output_stream=responses,
            )

        payload = json.loads(responses.getvalue())
        self.assertTrue(payload["ok"])
        self.assertEqual("760E", payload["result"]["target_model"])
        wait_for_job_state(manager, payload["result"]["job_id"], {"completed"})
        self.assertEqual(1, len(runner.plans))


if __name__ == "__main__":
    unittest.main()

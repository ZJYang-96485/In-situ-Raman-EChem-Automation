from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from chi760.sdk_worker import (
    CV_DRY_RUN_PARAMETERS,
    REQUIRED_DISCOVERY_EXPORTS,
    REQUIRED_RUNTIME_DLLS,
    inspect_runtime,
    main,
)
from contextlib import redirect_stdout
from io import StringIO
import json


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


if __name__ == "__main__":
    unittest.main()

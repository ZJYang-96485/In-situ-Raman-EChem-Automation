import unittest

from machine_learning import (
    AnalysisProjectConfiguration,
    AnalysisTask,
    AutomatedActionBlockedError,
    PreprocessedDatasetManifest,
    request_automated_decision,
    request_ml_action,
    validate_analysis_readiness,
)


class MachineLearningContractsTests(unittest.TestCase):
    def test_ml_and_decision_actions_cannot_reach_callbacks(self):
        calls = 0

        def action():
            nonlocal calls
            calls += 1

        for request in (request_ml_action, request_automated_decision):
            with self.subTest(request=request.__name__):
                with self.assertRaises(AutomatedActionBlockedError):
                    request(action)

        self.assertEqual(0, calls)
    def test_dataset_requires_raman_preprocessing_provenance(self):
        with self.assertRaisesRegex(ValueError, "preprocessing_reference"):
            PreprocessedDatasetManifest(
                dataset_name="run-1",
                source_session_ids=("mock-raman-0001",),
                feature_count=128,
                preprocessing_reference="",
            )

    def test_readiness_keeps_cleaning_outside_this_workspace(self):
        dataset = PreprocessedDatasetManifest(
            dataset_name="run-1",
            source_session_ids=("mock-raman-0001",),
            feature_count=128,
            preprocessing_reference="raman-plan-v1",
            includes_electrochemistry_metadata=False,
        )
        project = AnalysisProjectConfiguration(
            project_name="peak-state-study",
            task=AnalysisTask.EXPLORATORY,
        )

        blockers = validate_analysis_readiness(dataset, project)

        self.assertEqual(
            ("electrochemistry metadata is not attached to this dataset",), blockers
        )


if __name__ == "__main__":
    unittest.main()

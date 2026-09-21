from datetime import datetime, timezone
import unittest

from raman import (
    RamanPreprocessingPlan,
    SpectrumFrame,
    diagnose_frame,
    preprocess_frame,
)


class RamanPreprocessingTests(unittest.TestCase):
    def setUp(self):
        timestamp = datetime.now(timezone.utc)
        self.frame = SpectrumFrame(
            frame_index=0,
            pixel_axis=(0, 1, 2, 3, 4),
            intensity_counts=(10, 10, 100, 10, 10),
            started_at=timestamp,
            completed_at=timestamp,
            monotonic_started_s=1.0,
            monotonic_completed_s=1.0,
        )

    def test_preprocessing_returns_a_copy_and_records_steps(self):
        processed = preprocess_frame(
            self.frame,
            RamanPreprocessingPlan(
                despike_threshold=3.0,
                smoothing_window_points=3,
                baseline_mode="edge_linear",
            ),
        )

        self.assertEqual((10.0, 10.0, 100.0, 10.0, 10.0), self.frame.intensity_counts)
        self.assertNotEqual(self.frame.intensity_counts, processed.intensity_counts)
        self.assertIn("preprocessing", processed.metadata)
        self.assertEqual(
            "median_despike",
            processed.metadata["preprocessing"]["applied_steps"][0]["name"],
        )

    def test_diagnostics_do_not_modify_the_frame(self):
        diagnostics = diagnose_frame(self.frame, saturation_threshold_counts=90)

        self.assertEqual(5, diagnostics.point_count)
        self.assertEqual(1, diagnostics.saturated_point_count)
        self.assertIn("saturation threshold reached", diagnostics.warnings)
        self.assertEqual(100.0, self.frame.intensity_counts[2])


if __name__ == "__main__":
    unittest.main()

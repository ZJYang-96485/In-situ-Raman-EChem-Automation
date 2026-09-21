import unittest

from chi760.models import CVParameters, ITParameters


class ParameterValidationTests(unittest.TestCase):
    def test_cv_requires_a_positive_scan_rate(self):
        with self.assertRaisesRegex(ValueError, "scan_rate must be > 0"):
            CVParameters(
                initial_potential=0.0,
                high_potential=1.0,
                low_potential=-0.2,
                scan_rate=-0.05,
                cycles=3,
            )

    def test_it_sample_interval_cannot_exceed_duration(self):
        with self.assertRaisesRegex(
            ValueError, "sample_interval cannot exceed duration"
        ):
            ITParameters(potential=0.5, duration=1, sample_interval=2)


if __name__ == "__main__":
    unittest.main()

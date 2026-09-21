from datetime import datetime, timezone
import unittest

from raman import (
    RamanAcquisitionParameters,
    RamanAcquisitionPlan,
    RamanAcquisitionResult,
    SpectrumFrame,
    TimingQuality,
    TriggerMode,
)


class RamanModelValidationTests(unittest.TestCase):
    def test_acquisition_parameters_reject_invalid_values(self):
        with self.assertRaisesRegex(ValueError, "exposure_time_s"):
            RamanAcquisitionParameters(exposure_time_s=0)
        with self.assertRaisesRegex(ValueError, "accumulations"):
            RamanAcquisitionParameters(exposure_time_s=0.1, accumulations=0)
        with self.assertRaisesRegex(ValueError, "spectra_count"):
            RamanAcquisitionParameters(exposure_time_s=0.1, spectra_count=False)
        with self.assertRaisesRegex(ValueError, "inter_spectrum_delay_s"):
            RamanAcquisitionParameters(exposure_time_s=0.1, inter_spectrum_delay_s=-1)

    def test_plan_accepts_a_serialized_trigger_value(self):
        plan = RamanAcquisitionPlan(
            RamanAcquisitionParameters(exposure_time_s=0.1),
            trigger_mode="software",
        )
        self.assertEqual(TriggerMode.SOFTWARE, plan.trigger_mode)

    def test_result_requires_sequential_frames_and_freezes_metadata(self):
        timestamp = datetime.now(timezone.utc)
        plan = RamanAcquisitionPlan(
            RamanAcquisitionParameters(exposure_time_s=0.1, spectra_count=1)
        )
        frame = SpectrumFrame(
            frame_index=0,
            pixel_axis=(0, 1),
            intensity_counts=(1, 2),
            started_at=timestamp,
            completed_at=timestamp,
            monotonic_started_s=1.0,
            monotonic_completed_s=1.0,
            metadata={"source": "test"},
        )
        result = RamanAcquisitionResult(
            session_id="session-1",
            plan=plan,
            frames=(frame,),
            started_at=timestamp,
            completed_at=timestamp,
            timing_quality=TimingQuality.SIMULATED,
            metadata={"source": "test"},
        )

        with self.assertRaises(TypeError):
            result.metadata["new"] = "value"


if __name__ == "__main__":
    unittest.main()

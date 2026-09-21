import unittest

from raman import (
    MockRamanBackend,
    RamanAcquisitionParameters,
    RamanAcquisitionPlan,
    RamanController,
    RamanNotConnectedError,
    TimingQuality,
)


class MockRamanAcquisitionTests(unittest.TestCase):
    def test_mock_acquisition_returns_raw_frames_and_correlation_metadata(self):
        controller = RamanController(MockRamanBackend(pixel_count=16))
        plan = RamanAcquisitionPlan(
            RamanAcquisitionParameters(
                exposure_time_s=0.1,
                accumulations=2,
                spectra_count=2,
            ),
            label="electrochemistry-step-1",
        )

        with self.assertRaises(RamanNotConnectedError):
            controller.acquire(plan)

        identity = controller.connect()
        result = controller.acquire(
            plan,
            correlation_metadata={"electrochemistry_run_id": "run-001"},
        )
        controller.disconnect()

        self.assertIn("simulated", identity.manufacturer)
        self.assertEqual("mock-raman-0001", result.session_id)
        self.assertEqual(TimingQuality.SIMULATED, result.timing_quality)
        self.assertEqual(2, len(result.frames))
        self.assertEqual(16, len(result.frames[0].pixel_axis))
        self.assertEqual("raw_pixel", result.frames[0].metadata["axis"])
        self.assertEqual(
            "run-001", result.metadata["correlation"]["electrochemistry_run_id"]
        )
        self.assertFalse(controller.connected)

    def test_mock_uses_virtual_requested_timing_without_sleeping(self):
        controller = RamanController(MockRamanBackend(pixel_count=4))
        plan = RamanAcquisitionPlan(
            RamanAcquisitionParameters(
                exposure_time_s=0.5,
                accumulations=2,
                spectra_count=2,
                inter_spectrum_delay_s=3.0,
            )
        )
        controller.connect()
        result = controller.acquire(plan)
        controller.disconnect()

        first_frame, second_frame = result.frames
        self.assertEqual(
            4.0,
            (second_frame.started_at - first_frame.started_at).total_seconds(),
        )
        self.assertEqual(
            1.0,
            (first_frame.completed_at - first_frame.started_at).total_seconds(),
        )
        self.assertEqual("virtual_requested_duration", result.metadata["timing_model"])

    def test_idle_abort_does_not_cancel_the_next_acquisition(self):
        backend = MockRamanBackend(pixel_count=4)
        backend.abort()
        controller = RamanController(backend)
        controller.connect()
        result = controller.acquire(
            RamanAcquisitionPlan(RamanAcquisitionParameters(exposure_time_s=0.1))
        )
        controller.disconnect()

        self.assertEqual(1, len(result.frames))


if __name__ == "__main__":
    unittest.main()

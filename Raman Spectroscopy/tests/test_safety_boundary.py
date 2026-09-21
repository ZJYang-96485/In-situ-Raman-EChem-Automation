import unittest

from raman import (
    AndorSolisBackend,
    InstrumentIdentity,
    MockRamanBackend,
    RamanAcquisitionParameters,
    RamanAcquisitionPlan,
    RamanController,
    RamanHardwareNotConfiguredError,
    RamanHardwareProfile,
    RamanSafetyError,
    TriggerMode,
)


class RamanSafetyBoundaryTests(unittest.TestCase):
    def test_controller_rejects_unverified_hardware_triggering(self):
        controller = RamanController(MockRamanBackend())
        controller.connect()
        plan = RamanAcquisitionPlan(
            RamanAcquisitionParameters(exposure_time_s=0.1),
            trigger_mode=TriggerMode.EXTERNAL_TTL,
        )

        with self.assertRaises(RamanSafetyError):
            controller.acquire(plan)
        controller.disconnect()

    def test_andor_backend_cannot_connect_before_implementation(self):
        backend = AndorSolisBackend(
            RamanHardwareProfile(
                detector=InstrumentIdentity(manufacturer="Andor"),
                verified=True,
            ),
            connection_enabled=True,
        )

        with self.assertRaises(RamanHardwareNotConfiguredError):
            backend.connect()

    def test_live_controller_requires_explicit_enablement(self):
        backend = AndorSolisBackend(
            RamanHardwareProfile(
                detector=InstrumentIdentity(manufacturer="Andor"),
                verified=True,
            ),
            connection_enabled=True,
        )
        controller = RamanController(backend)

        with self.assertRaises(RamanSafetyError):
            controller.connect()

    def test_andor_backend_requires_a_verified_profile(self):
        backend = AndorSolisBackend(
            RamanHardwareProfile(
                detector=InstrumentIdentity(manufacturer="Andor"),
                verified=False,
            ),
            connection_enabled=True,
        )

        with self.assertRaises(RamanSafetyError):
            backend.connect()


if __name__ == "__main__":
    unittest.main()

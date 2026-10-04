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

    def test_andor_backend_is_blocked_by_electrochemistry_only_profile(self):
        backend = AndorSolisBackend(
            RamanHardwareProfile(
                detector=InstrumentIdentity(manufacturer="Andor"),
                verified=True,
            ),
            connection_enabled=True,
        )

        with self.assertRaisesRegex(RamanSafetyError, "electrochemistry-only"):
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
            electrochemistry_only=False,
        )

        with self.assertRaises(RamanSafetyError):
            backend.connect()

    def test_live_backend_is_not_called_by_controller(self):
        class CountingLiveBackend:
            is_simulated = False
            hardware_verified = True

            def __init__(self):
                self.calls = 0

            def connect(self):
                self.calls += 1
                return InstrumentIdentity(manufacturer="fake")

            def disconnect(self):
                self.calls += 1

            def acquire(self, plan):
                self.calls += 1
                raise AssertionError("must not reach hardware")

            def abort(self):
                self.calls += 1

        backend = CountingLiveBackend()
        controller = RamanController(backend, live_connection_enabled=True)

        with self.assertRaisesRegex(RamanSafetyError, "electrochemistry-only"):
            controller.connect()

        self.assertEqual(0, backend.calls)

    def test_laser_ttl_disconnect_and_abort_are_explicitly_blocked(self):
        backend = AndorSolisBackend(
            RamanHardwareProfile(
                detector=InstrumentIdentity(manufacturer="Andor"),
                verified=True,
            ),
            connection_enabled=True,
        )

        for operation in (
            backend.request_laser_control,
            backend.request_ttl_trigger,
            backend.disconnect,
            backend.abort,
        ):
            with self.subTest(operation=operation.__name__):
                with self.assertRaises(RamanSafetyError):
                    operation()


if __name__ == "__main__":
    unittest.main()

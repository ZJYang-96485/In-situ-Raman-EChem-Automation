from pathlib import Path
import unittest

from raman import (
    InstrumentIdentity,
    MockRamanBackend,
    RamanConfiguration,
    RamanHardwareProfile,
    create_raman_backend,
    create_raman_controller,
    load_raman_configuration,
)


class RamanConfigurationTests(unittest.TestCase):
    def test_example_configuration_is_connection_safe(self):
        config_path = (
            Path(__file__).resolve().parents[1] / "config" / "raman.example.json"
        )
        configuration = load_raman_configuration(config_path)

        self.assertEqual("mock", configuration.backend)
        self.assertFalse(configuration.connection_enabled)
        self.assertFalse(configuration.hardware.verified)
        self.assertEqual("CCD-15119", configuration.hardware.detector.serial_number)
        self.assertIsInstance(create_raman_backend(configuration), MockRamanBackend)
        self.assertIsInstance(
            create_raman_controller(configuration).backend, MockRamanBackend
        )

    def test_configuration_rejects_a_non_boolean_connection_flag(self):
        with self.assertRaisesRegex(ValueError, "connection_enabled"):
            RamanConfiguration(
                hardware=RamanHardwareProfile(
                    detector=InstrumentIdentity(manufacturer="Andor")
                ),
                connection_enabled="false",
            )


if __name__ == "__main__":
    unittest.main()

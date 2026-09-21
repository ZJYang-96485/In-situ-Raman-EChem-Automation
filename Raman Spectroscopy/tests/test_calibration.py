import unittest

from raman import WavelengthCalibration, raman_shift_cm1


class RamanCalibrationTests(unittest.TestCase):
    def test_wavelength_calibration_evaluates_a_polynomial(self):
        calibration = WavelengthCalibration((500.0, 0.05), source="test standard")

        self.assertEqual(500.0, calibration.wavelength_nm(0))
        self.assertEqual((500.0, 500.5), calibration.wavelengths_nm((0, 10)))

    def test_raman_shift_uses_wavelengths_in_nanometres(self):
        shift = raman_shift_cm1(532.0, 562.0)

        self.assertGreater(shift, 0)
        self.assertAlmostEqual(1003.40, shift, places=2)

    def test_calibration_rejects_invalid_values(self):
        with self.assertRaisesRegex(ValueError, "coefficients_nm"):
            WavelengthCalibration(())
        with self.assertRaisesRegex(ValueError, "excitation_wavelength_nm"):
            raman_shift_cm1(0, 562.0)
        with self.assertRaisesRegex(ValueError, "non-finite"):
            WavelengthCalibration((1e308, 1e308)).wavelength_nm(1e308)
        with self.assertRaisesRegex(ValueError, "non-finite"):
            raman_shift_cm1(5e-324, 562.0)


if __name__ == "__main__":
    unittest.main()

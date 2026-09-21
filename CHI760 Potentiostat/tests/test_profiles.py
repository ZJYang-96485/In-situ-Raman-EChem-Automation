import unittest

from chi760.profiles import CHI760Model, Technique, profile_for


class CHI760ProfileTests(unittest.TestCase):
    def test_profiles_gate_techniques_by_model(self):
        profile_c = profile_for("760C")
        profile_e = profile_for(CHI760Model.E)

        self.assertTrue(profile_c.supports(Technique.EIS))
        self.assertFalse(profile_c.supports(Technique.LSV))
        self.assertTrue(profile_e.supports(Technique.OCP))
        self.assertFalse(profile_e.supports(Technique.LSV))

    def test_unknown_model_is_rejected_with_available_choices(self):
        with self.assertRaisesRegex(ValueError, "760B"):
            profile_for("760Z")


if __name__ == "__main__":
    unittest.main()

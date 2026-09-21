import unittest

from chi760.controller import CHI760Controller
from chi760.errors import UnsupportedTechniqueError
from chi760.mock_backend import MockCHI760
from chi760.models import (
    CVParameters,
    EISParameters,
    ITParameters,
    LSVParameters,
    OCPParameters,
)


class SupportedTechniqueTests(unittest.TestCase):
    def test_760b_runs_only_cv_and_it(self):
        chi = CHI760Controller(MockCHI760(), model="760B")
        cv = CVParameters(
            initial_potential=0.0,
            high_potential=1.0,
            low_potential=-0.2,
            scan_rate=0.05,
            cycles=3,
        )
        it = ITParameters(potential=0.5, duration=120)

        self.assertEqual(("CV", "i-t"), chi.supported_techniques)
        self.assertTrue(chi.connect())
        cv_result = chi.run_cv(cv)
        it_result = chi.run_it(it)
        chi.disconnect()

        self.assertEqual("CV", cv_result["technique"])
        self.assertEqual("i-t", it_result["technique"])

    def test_760d_unlocks_lsv_eis_and_ocp(self):
        chi = CHI760Controller(MockCHI760(), model="CHI760D")
        lsv = LSVParameters(0.0, 1.0, 0.01)
        eis = EISParameters(0.5, 0.01, 100000, 0.1)
        ocp = OCPParameters(duration=60)

        self.assertEqual(("CV", "i-t", "LSV", "EIS", "OCP"), chi.supported_techniques)
        chi.connect()
        lsv_result = chi.run_lsv(lsv)
        eis_result = chi.run_eis(eis)
        ocp_result = chi.run_ocp(ocp)
        chi.disconnect()

        self.assertEqual("LSV", lsv_result["technique"])
        self.assertEqual("EIS", eis_result["technique"])
        self.assertEqual("OCP", ocp_result["technique"])

    def test_profile_rejects_unsupported_760b_techniques(self):
        chi = CHI760Controller(MockCHI760(), model="760B")

        with self.assertRaises(UnsupportedTechniqueError):
            chi.run_lsv(LSVParameters(0.0, 1.0, 0.01))


if __name__ == "__main__":
    unittest.main()

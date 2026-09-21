import unittest

from chi760.controller import CHI760Controller
from chi760.mock_backend import MockCHI760
from chi760.models import CVParameters


class CHI760ControllerTests(unittest.TestCase):
    def test_runs_cv_with_the_mock_backend(self):
        chi = CHI760Controller(MockCHI760(), model="760B")
        params = CVParameters(
            initial_potential=0.0,
            high_potential=1.0,
            low_potential=-0.2,
            scan_rate=0.05,
            cycles=3,
        )

        self.assertTrue(chi.connect())
        result = chi.run_cv(params)
        chi.disconnect()

        self.assertEqual("CV", result["technique"])
        self.assertEqual(vars(params), result["parameters"])


if __name__ == "__main__":
    unittest.main()

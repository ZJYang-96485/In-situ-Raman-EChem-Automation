class MockCHI760:
    """Test backend that can stand in for any profiled CHI 760 controller."""

    def connect(self):
        print("Mock CHI760 connected")
        return True

    def disconnect(self):
        print("Mock CHI760 disconnected")

    def run_cv(self, **params):
        print("Running mock CV:", params)
        return {
            "technique": "CV",
            "parameters": params,
            "potential_V": [],
            "current_A": []
        }

    def run_it(self, **params):
        print("Running mock i-t:", params)
        return {
            "technique": "i-t",
            "parameters": params,
            "time_s": [],
            "current_A": []
        }

    def run_lsv(self, **params):
        print("Running mock LSV:", params)
        return {
            "technique": "LSV",
            "parameters": params,
            "potential_V": [],
            "current_A": [],
        }

    def run_eis(self, **params):
        print("Running mock EIS:", params)
        return {
            "technique": "EIS",
            "parameters": params,
            "frequency_Hz": [],
            "z_real_ohm": [],
            "z_imag_ohm": [],
        }

    def run_ocp(self, **params):
        print("Running mock OCP:", params)
        return {
            "technique": "OCP",
            "parameters": params,
            "time_s": [],
            "potential_V": [],
        }


class MockCHI760B(MockCHI760):
    """Compatibility name for tests configured specifically for a CHI 760B."""

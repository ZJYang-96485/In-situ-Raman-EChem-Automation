class MockCHI760D:
    def connect(self):
        print("Mock CHI760D connected")
        return True

    def disconnect(self):
        print("Mock CHI760D disconnected")

    def run_cv(self, **params):
        print("Running mock CV:", params)
        return {
            "technique": "CV",
            "parameters": params,
            "potential_V": [],
            "current_A": []
        }

    def run_lsv(self, **params):
        print("Running mock LSV:", params)
        return {
            "technique": "LSV",
            "parameters": params,
            "potential_V": [],
            "current_A": []
        }

    def run_ocp(self, **params):
        print("Running mock OCP:", params)
        return {
            "technique": "OCP",
            "parameters": params,
            "time_s": [],
            "potential_V": []
        }

    def run_it(self, **params):
        print("Running mock i-t:", params)
        return {
            "technique": "i-t",
            "parameters": params,
            "time_s": [],
            "current_A": []
        }

    def run_eis(self, **params):
        print("Running mock EIS:", params)
        return {
            "technique": "EIS",
            "parameters": params,
            "frequency_Hz": [],
            "z_real_ohm": [],
            "z_imag_ohm": []
        }
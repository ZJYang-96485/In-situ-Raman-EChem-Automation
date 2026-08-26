class CHI760DController:
    def __init__(self, backend):
        self.backend = backend

    def connect(self):
        return self.backend.connect()

    def disconnect(self):
        return self.backend.disconnect()

    def run_cv(self, params):
        return self.backend.run_cv(**vars(params))

    def run_lsv(self, params):
        return self.backend.run_lsv(**vars(params))

    def run_eis(self, params):
        return self.backend.run_eis(**vars(params))

    def run_ocp(self, params):
        return self.backend.run_ocp(**vars(params))

    def run_it(self, params):
        return self.backend.run_it(**vars(params))
"""Model-profiled control surface for CH Instruments 760-series automation."""

from .errors import UnsupportedTechniqueError
from .profiles import CHI760Model, CHI760Profile, Technique, profile_for



class CHI760Controller:
    """Delegate only profile-supported experiments to an instrument backend."""

    def __init__(
        self,
        backend,
        model: CHI760Model | str = CHI760Model.B,
    ):
        self.backend = backend
        self.profile: CHI760Profile = profile_for(model)

    @property
    def model(self) -> CHI760Model:
        return self.profile.model

    @property
    def supported_techniques(self) -> tuple[str, ...]:
        return tuple(
            technique.value
            for technique in Technique
            if self.profile.supports(technique)
        )

    def connect(self):
        return self.backend.connect()

    def disconnect(self):
        return self.backend.disconnect()

    def run_cv(self, params):
        return self._run(Technique.CV, "run_cv", params)

    def run_it(self, params):
        return self._run(Technique.IT, "run_it", params)

    def run_lsv(self, params):
        return self._run(Technique.LSV, "run_lsv", params)

    def run_eis(self, params):
        return self._run(Technique.EIS, "run_eis", params)

    def run_ocp(self, params):
        return self._run(Technique.OCP, "run_ocp", params)

    def _run(self, technique: Technique, backend_method: str, params):
        if not self.profile.supports(technique):
            raise UnsupportedTechniqueError(
                f"CHI {self.model.value} does not expose {technique.value} "
                "through this automation interface"
            )
        return getattr(self.backend, backend_method)(**vars(params))


class CHI760BController(CHI760Controller):
    """Compatibility controller that fixes the profile to the 760B."""

    def __init__(self, backend):
        super().__init__(backend, CHI760Model.B)

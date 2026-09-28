"""Model-profiled control surface for CH Instruments 760-series automation."""

from .errors import UnsupportedTechniqueError
from .models import (
    CAParameters,
    CVParameters,
    EISParameters,
    IMPEParameters,
    ISTEPParameters,
    ITParameters,
    LSVParameters,
    OCPParameters,
    STEPParameters,
    SWVParameters,
)
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

    def run_cv(self, params: CVParameters):
        return self._run(Technique.CV, "run_cv", params, CVParameters)

    def run_it(self, params: ITParameters):
        return self._run(Technique.IT, "run_it", params, ITParameters)

    def run_lsv(self, params: LSVParameters):
        return self._run(Technique.LSV, "run_lsv", params, LSVParameters)

    def run_eis(self, params: EISParameters):
        return self._run(Technique.EIS, "run_eis", params, EISParameters)

    def run_ocp(self, params: OCPParameters):
        return self._run(Technique.OCP, "run_ocp", params, OCPParameters)

    def run_ca(self, params: CAParameters):
        return self._run(Technique.CA, "run_ca", params, CAParameters)

    def run_swv(self, params: SWVParameters):
        return self._run(Technique.SWV, "run_swv", params, SWVParameters)

    def run_impe(self, params: IMPEParameters):
        return self._run(Technique.IMPE, "run_impe", params, IMPEParameters)

    def run_step(self, params: STEPParameters):
        return self._run(Technique.STEP, "run_step", params, STEPParameters)

    def run_istep(self, params: ISTEPParameters):
        return self._run(Technique.ISTEP, "run_istep", params, ISTEPParameters)

    def _run(self, technique: Technique, backend_method: str, params, expected_type: type):
        if not self.profile.supports(technique):
            raise UnsupportedTechniqueError(
                f"CHI {self.model.value} does not expose {technique.value} "
                "through this automation interface"
            )
        if not isinstance(params, expected_type):
            raise TypeError(
                f"{technique.value} requires {expected_type.__name__}; "
                f"received {type(params).__name__}"
            )
        return getattr(self.backend, backend_method)(**vars(params))


class CHI760BController(CHI760Controller):
    """Compatibility controller that fixes the profile to the 760B."""

    def __init__(self, backend):
        super().__init__(backend, CHI760Model.B)

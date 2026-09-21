"""Model-specific automation profiles for CH Instruments 760-series units."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class CHI760Model(str, Enum):
    """760-series models currently represented by this automation surface."""

    B = "760B"
    C = "760C"
    D = "760D"
    E = "760E"


class Technique(str, Enum):
    """Techniques implemented by the Python controller interface."""

    CV = "CV"
    IT = "i-t"
    LSV = "LSV"
    EIS = "EIS"
    OCP = "OCP"


@dataclass(frozen=True)
class CHI760Profile:
    """A capability gate for one 760-series model.

    These capabilities describe the techniques exposed by this project and are
    based on the vendor's documented 7xx libec automation matrix. They do not
    claim every capability of the physical instrument or desktop software.
    """

    model: CHI760Model
    supported_techniques: frozenset[Technique]
    is_bipotentiostat: bool = True

    def supports(self, technique: Technique) -> bool:
        return technique in self.supported_techniques


PROFILES: dict[CHI760Model, CHI760Profile] = {
    CHI760Model.B: CHI760Profile(
        model=CHI760Model.B,
        supported_techniques=frozenset({Technique.CV, Technique.IT}),
    ),
    CHI760Model.C: CHI760Profile(
        model=CHI760Model.C,
        supported_techniques=frozenset(
            {Technique.CV, Technique.IT, Technique.EIS}
        ),
    ),
    CHI760Model.D: CHI760Profile(
        model=CHI760Model.D,
        supported_techniques=frozenset(
            {
                Technique.CV,
                Technique.IT,
                Technique.LSV,
                Technique.EIS,
                Technique.OCP,
            }
        ),
    ),
    CHI760Model.E: CHI760Profile(
        model=CHI760Model.E,
        supported_techniques=frozenset(
            {Technique.CV, Technique.IT, Technique.EIS, Technique.OCP}
        ),
    ),
}


def profile_for(model: CHI760Model | str) -> CHI760Profile:
    """Return the model profile, accepting either ``760B`` or ``CHI760B``."""

    if isinstance(model, str):
        normalized = model.upper().replace("CHI", "")
        try:
            model = CHI760Model(normalized)
        except ValueError as error:
            choices = ", ".join(candidate.value for candidate in CHI760Model)
            raise ValueError(f"unknown CHI 760 model '{model}'; choose {choices}") from error
    return PROFILES[model]

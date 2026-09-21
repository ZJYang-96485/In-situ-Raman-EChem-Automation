"""Flexible CH Instruments 760-series potentiostat automation interfaces."""

from .controller import CHI760BController, CHI760Controller
from .errors import UnsupportedTechniqueError
from .mock_backend import MockCHI760, MockCHI760B
from .models import CVParameters, EISParameters, ITParameters, LSVParameters, OCPParameters
from .profiles import CHI760Model, CHI760Profile, Technique, profile_for

__all__ = [
    "CHI760BController",
    "CHI760Controller",
    "CHI760Model",
    "CHI760Profile",
    "CVParameters",
    "EISParameters",
    "ITParameters",
    "LSVParameters",
    "MockCHI760",
    "MockCHI760B",
    "OCPParameters",
    "Technique",
    "UnsupportedTechniqueError",
    "profile_for",
]

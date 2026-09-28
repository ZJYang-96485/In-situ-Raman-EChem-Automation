"""Flexible CH Instruments 760-series potentiostat automation interfaces."""

from .controller import CHI760BController, CHI760Controller
from .errors import UnsupportedTechniqueError
from .mock_backend import MockCHI760, MockCHI760B
from .models import (
    CAParameters,
    CVParameters,
    CurrentStep,
    EISParameters,
    IMPEParameters,
    ISTEPParameters,
    ITParameters,
    LSVParameters,
    OCPParameters,
    PotentialStep,
    STEPParameters,
    SWVParameters,
)
from .processing import chronocoulometry_from_ca_C, cumulative_charge_C
from .ir_compensation import (
    IRCompensationProgress,
    IRCompensationMode,
    IRCompensationPlan,
    RuValidationResult,
    evaluate_compensation_trials,
    technique_uses_ir_compensation,
    validate_ru_measurements,
)
from .rde_adapter import (
    AdaptationStatus,
    ProtocolAdaptation,
    TechniqueAdaptation,
    adapt_rde_protocol,
)
from .protocols import (
    EchemProtocol,
    ProtocolAction,
    ProtocolStep,
    RDEExperiment,
    RamanSyncPolicy,
    build_rde_protocol,
)
from .profiles import CHI760Model, CHI760Profile, Technique, profile_for

__all__ = [
    "CHI760BController",
    "CHI760Controller",
    "CHI760Model",
    "CHI760Profile",
    "AdaptationStatus",
    "CAParameters",
    "CVParameters",
    "CurrentStep",
    "EchemProtocol",
    "EISParameters",
    "IMPEParameters",
    "IRCompensationMode",
    "IRCompensationPlan",
    "IRCompensationProgress",
    "ISTEPParameters",
    "ITParameters",
    "LSVParameters",
    "MockCHI760",
    "MockCHI760B",
    "OCPParameters",
    "PotentialStep",
    "ProtocolAction",
    "ProtocolAdaptation",
    "ProtocolStep",
    "RDEExperiment",
    "RamanSyncPolicy",
    "RuValidationResult",
    "STEPParameters",
    "SWVParameters",
    "Technique",
    "TechniqueAdaptation",
    "UnsupportedTechniqueError",
    "build_rde_protocol",
    "adapt_rde_protocol",
    "cumulative_charge_C",
    "chronocoulometry_from_ca_C",
    "evaluate_compensation_trials",
    "profile_for",
    "technique_uses_ir_compensation",
    "validate_ru_measurements",
]

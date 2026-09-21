"""Connection-safe Raman acquisition scaffolding."""

from .andor_solis_backend import AndorSolisBackend
from .calibration import WavelengthCalibration, raman_shift_cm1
from .configuration import RamanConfiguration, load_raman_configuration
from .controller import RamanController
from .diagnostics import SpectrumDiagnostics, diagnose_frame
from .errors import (
    RamanAcquisitionAbortedError,
    RamanError,
    RamanHardwareNotConfiguredError,
    RamanNotConnectedError,
    RamanSafetyError,
)
from .factory import create_raman_backend, create_raman_controller
from .mock_backend import MockRamanBackend
from .preprocessing import RamanPreprocessingPlan, preprocess_frame
from .models import (
    ConnectionState,
    InstrumentIdentity,
    RamanAcquisitionParameters,
    RamanAcquisitionPlan,
    RamanAcquisitionResult,
    RamanHardwareProfile,
    SpectrumFrame,
    TimingQuality,
    TriggerMode,
)

__all__ = [
    "AndorSolisBackend",
    "ConnectionState",
    "InstrumentIdentity",
    "MockRamanBackend",
    "RamanPreprocessingPlan",
    "RamanAcquisitionAbortedError",
    "RamanAcquisitionParameters",
    "RamanAcquisitionPlan",
    "RamanAcquisitionResult",
    "RamanConfiguration",
    "RamanController",
    "RamanError",
    "RamanHardwareNotConfiguredError",
    "RamanHardwareProfile",
    "RamanNotConnectedError",
    "RamanSafetyError",
    "SpectrumFrame",
    "SpectrumDiagnostics",
    "TimingQuality",
    "TriggerMode",
    "WavelengthCalibration",
    "create_raman_backend",
    "create_raman_controller",
    "diagnose_frame",
    "load_raman_configuration",
    "raman_shift_cm1",
    "preprocess_frame",
]

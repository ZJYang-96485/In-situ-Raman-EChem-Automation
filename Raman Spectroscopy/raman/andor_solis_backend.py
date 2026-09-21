"""Safe placeholder for a future Andor iDus/Shamrock/Solis integration."""

from __future__ import annotations

from .errors import RamanHardwareNotConfiguredError, RamanSafetyError
from .models import (
    InstrumentIdentity,
    RamanAcquisitionPlan,
    RamanAcquisitionResult,
    RamanHardwareProfile,
)


class AndorSolisBackend:
    """Define the future live-backend boundary without touching hardware.

    This class intentionally does not load an Andor SDK, enumerate USB devices,
    open a camera or spectrograph, change detector settings, or interact with
    laser/trigger lines. It makes accidental instrument access impossible while
    the exact SDK mapping and physical wiring are still unverified.
    """

    is_simulated = False

    def __init__(self, profile: RamanHardwareProfile, *, connection_enabled: bool = False):
        self.profile = profile
        self.connection_enabled = connection_enabled

    @property
    def hardware_verified(self) -> bool:
        return self.profile.verified

    def connect(self) -> InstrumentIdentity:
        if not self.connection_enabled:
            raise RamanSafetyError(
                "live Andor/Solis connection is disabled in the Raman configuration"
            )
        if not self.profile.verified:
            raise RamanSafetyError(
                "live Andor/Solis connection requires a verified hardware profile"
            )
        raise RamanHardwareNotConfiguredError(
            "The Andor/Solis backend is a connection-safe scaffold. Verify the "
            "camera, spectrograph, SDK, trigger wiring, and laser interlocks "
            "before implementing a live connection."
        )

    def disconnect(self) -> None:
        """No-op: this scaffold never opens a hardware connection."""

    def acquire(self, plan: RamanAcquisitionPlan) -> RamanAcquisitionResult:
        raise RamanHardwareNotConfiguredError(
            "No live Andor/Solis acquisition is implemented; use MockRamanBackend "
            "until the hardware integration is validated."
        )

    def abort(self) -> None:
        """No-op: this scaffold never starts a hardware acquisition."""

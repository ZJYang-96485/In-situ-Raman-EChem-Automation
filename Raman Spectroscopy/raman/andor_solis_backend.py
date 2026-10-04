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

    def __init__(
        self,
        profile: RamanHardwareProfile,
        *,
        connection_enabled: bool = False,
        electrochemistry_only: bool = True,
    ):
        self.profile = profile
        self.connection_enabled = connection_enabled
        self.electrochemistry_only = electrochemistry_only

    @property
    def hardware_verified(self) -> bool:
        return self.profile.verified

    def connect(self) -> InstrumentIdentity:
        self._require_electrochemistry_scope("live Andor/Solis connection")
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
        raise RamanSafetyError(
            "Andor/Solis disconnect is blocked; this scaffold never opens a session"
        )

    def acquire(self, plan: RamanAcquisitionPlan) -> RamanAcquisitionResult:
        self._require_electrochemistry_scope("live Raman acquisition")
        raise RamanHardwareNotConfiguredError(
            "No live Andor/Solis acquisition is implemented; use MockRamanBackend "
            "until the hardware integration is validated."
        )

    def abort(self) -> None:
        raise RamanSafetyError(
            "Andor/Solis abort is blocked; this scaffold never starts acquisition"
        )

    def request_laser_control(self) -> None:
        raise RamanSafetyError(
            "laser control is blocked by the electrochemistry-only runtime profile"
        )

    def request_ttl_trigger(self) -> None:
        raise RamanSafetyError(
            "TTL triggering is blocked by the electrochemistry-only runtime profile"
        )

    def _require_electrochemistry_scope(self, operation: str) -> None:
        if self.electrochemistry_only:
            raise RamanSafetyError(
                f"{operation} is blocked by the electrochemistry-only runtime profile"
            )

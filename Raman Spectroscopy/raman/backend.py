"""Backend boundary for Raman acquisition hardware."""

from typing import Protocol

from .models import (
    InstrumentIdentity,
    RamanAcquisitionPlan,
    RamanAcquisitionResult,
)


class RamanBackend(Protocol):
    """Minimum contract required by :class:`RamanController`.

    Every non-simulated backend must enforce its own live-connection and
    verified-hardware safeguards as well; controller checks are an additional
    boundary, not a replacement for backend-level protection.
    """

    is_simulated: bool
    hardware_verified: bool

    def connect(self) -> InstrumentIdentity:
        """Open a connection and return the detected instrument identity."""

    def disconnect(self) -> None:
        """Close a connection without changing optical hardware state."""

    def acquire(self, plan: RamanAcquisitionPlan) -> RamanAcquisitionResult:
        """Acquire raw detector frames for a software-triggered plan."""

    def abort(self) -> None:
        """Request that an active acquisition stop safely."""

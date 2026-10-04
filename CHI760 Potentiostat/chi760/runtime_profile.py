"""Default-deny runtime scope for the electrochemistry execution node."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Callable, TypeVar

from .errors import HardwareOperationBlockedError


class HardwareOperation(str, Enum):
    """Hardware-capable operation classes that must be authorized explicitly."""

    CHI_DISCOVERY = "chi_discovery"
    CHI_EXPERIMENT = "chi_experiment"
    IR_COMPENSATION = "ir_compensation"
    RAMAN_ACQUISITION = "raman_acquisition"
    LASER_CONTROL = "laser_control"
    TTL_TRIGGER = "ttl_trigger"
    RDE_MOTOR_CONTROL = "rde_motor_control"
    ML_ACTION = "ml_action"
    AUTOMATED_DECISION = "automated_decision"


_T = TypeVar("_T")


@dataclass(frozen=True)
class RuntimeProfile:
    """Whitelist hardware domains while leaving simulation and import untouched."""

    name: str
    allowed_hardware_operations: frozenset[HardwareOperation]

    def require(self, operation: HardwareOperation, action: str) -> None:
        if operation not in self.allowed_hardware_operations:
            raise HardwareOperationBlockedError(
                f"{action} is blocked by runtime profile {self.name!r} "
                f"({operation.value})"
            )

    def dispatch(
        self,
        operation: HardwareOperation,
        action: str,
        callback: Callable[[], _T],
    ) -> _T:
        """Call a hardware boundary only after the profile check succeeds."""

        self.require(operation, action)
        return callback()


ELECTROCHEMISTRY_ONLY = RuntimeProfile(
    name="electrochemistry_only",
    allowed_hardware_operations=frozenset({HardwareOperation.CHI_DISCOVERY}),
)

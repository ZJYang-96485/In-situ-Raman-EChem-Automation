"""Load a descriptive Raman hardware profile without connecting to it."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Mapping

from .models import InstrumentIdentity, RamanHardwareProfile


@dataclass(frozen=True)
class RamanConfiguration:
    """Static configuration used to select a development backend later."""

    hardware: RamanHardwareProfile
    backend: str = "mock"
    connection_enabled: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.backend, str):
            raise ValueError("backend must be a string")
        if self.backend not in {"mock", "andor_solis"}:
            raise ValueError("backend must be 'mock' or 'andor_solis'")
        if not isinstance(self.connection_enabled, bool):
            raise ValueError("connection_enabled must be a boolean")


def load_raman_configuration(path: str | Path) -> RamanConfiguration:
    """Read a JSON configuration file; this function performs no I/O to hardware."""

    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, Mapping):
        raise ValueError("Raman configuration must be a JSON object")

    hardware = raw.get("hardware")
    if not isinstance(hardware, Mapping):
        raise ValueError("Raman configuration requires a 'hardware' object")

    return RamanConfiguration(
        backend=_required_string(raw.get("backend", "mock"), "backend"),
        connection_enabled=_required_bool(
            raw.get("connection_enabled", False), "connection_enabled"
        ),
        hardware=RamanHardwareProfile(
            detector=_load_identity(hardware.get("detector"), "detector"),
            spectrograph=_load_optional_identity(
                hardware.get("spectrograph"), "spectrograph"
            ),
            laser_controller=_load_optional_identity(
                hardware.get("laser_controller"), "laser_controller"
            ),
            excitation_wavelength_nm=_optional_number(
                hardware.get("excitation_wavelength_nm"), "excitation_wavelength_nm"
            ),
            verified=_required_bool(hardware.get("verified", False), "verified"),
        ),
    )


def _load_identity(value: Any, name: str) -> InstrumentIdentity:
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be an object")
    return InstrumentIdentity(
        manufacturer=_required_string(value.get("manufacturer"), f"{name}.manufacturer"),
        model=_optional_string(value.get("model"), f"{name}.model"),
        serial_number=_optional_string(
            value.get("serial_number"), f"{name}.serial_number"
        ),
        software=_optional_string(value.get("software"), f"{name}.software"),
    )


def _load_optional_identity(value: Any, name: str) -> InstrumentIdentity | None:
    if value is None:
        return None
    return _load_identity(value, name)


def _required_string(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value


def _optional_string(value: Any, name: str) -> str | None:
    if value is None:
        return None
    return _required_string(value, name)


def _required_bool(value: Any, name: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{name} must be a boolean")
    return value


def _optional_number(value: Any, name: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a number or null")
    return float(value)

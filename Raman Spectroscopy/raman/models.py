"""Vendor-neutral data models for Raman acquisition planning and results."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from math import isfinite
from types import MappingProxyType
from typing import Any, Mapping, Sequence


class TriggerMode(str, Enum):
    """Requested source for starting an acquisition.

    Only ``SOFTWARE`` is usable in this connection-free scaffold. The other
    values describe future integration requirements; they never activate a
    physical output in the current implementation.
    """

    SOFTWARE = "software"
    EXTERNAL_TTL = "external_ttl"
    INTERNAL = "internal"


class TimingQuality(str, Enum):
    """How trustworthy acquisition timing is for cross-instrument alignment."""

    SIMULATED = "simulated"
    SOFTWARE_BEST_EFFORT = "software_best_effort"


class ConnectionState(str, Enum):
    """The controller's best-known state of its backend connection."""

    DISCONNECTED = "disconnected"
    CONNECTED = "connected"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class InstrumentIdentity:
    """Inventory information for one physical or simulated component."""

    manufacturer: str
    model: str | None = None
    serial_number: str | None = None
    software: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.manufacturer, str) or not self.manufacturer.strip():
            raise ValueError("manufacturer must be provided")


@dataclass(frozen=True)
class RamanHardwareProfile:
    """Inventory record; it does not create a hardware connection.

    Laser fields are descriptive metadata only. No laser control is modeled or
    exposed until interlocks, wiring, and the vendor interface are verified.
    """

    detector: InstrumentIdentity
    spectrograph: InstrumentIdentity | None = None
    laser_controller: InstrumentIdentity | None = None
    excitation_wavelength_nm: float | None = None
    verified: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.verified, bool):
            raise ValueError("verified must be a boolean")
        if self.excitation_wavelength_nm is not None:
            _require_positive_finite(
                self.excitation_wavelength_nm, "excitation_wavelength_nm"
            )


@dataclass(frozen=True)
class RamanAcquisitionParameters:
    """Acquisition settings that can be mapped to a future detector backend."""

    exposure_time_s: float
    accumulations: int = 1
    spectra_count: int = 1
    inter_spectrum_delay_s: float = 0.0
    center_wavelength_nm: float | None = None
    grating_grooves_per_mm: float | None = None

    def __post_init__(self) -> None:
        _require_positive_finite(self.exposure_time_s, "exposure_time_s")
        _require_positive_int(self.accumulations, "accumulations")
        _require_positive_int(self.spectra_count, "spectra_count")
        _require_nonnegative_finite(
            self.inter_spectrum_delay_s, "inter_spectrum_delay_s"
        )

        if self.center_wavelength_nm is not None:
            _require_positive_finite(
                self.center_wavelength_nm, "center_wavelength_nm"
            )
        if self.grating_grooves_per_mm is not None:
            _require_positive_finite(
                self.grating_grooves_per_mm, "grating_grooves_per_mm"
            )


@dataclass(frozen=True)
class RamanAcquisitionPlan:
    """One logical Raman capture request, including its trigger contract."""

    parameters: RamanAcquisitionParameters
    trigger_mode: TriggerMode = TriggerMode.SOFTWARE
    label: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.trigger_mode, TriggerMode):
            object.__setattr__(self, "trigger_mode", TriggerMode(self.trigger_mode))
        if self.label is not None and (
            not isinstance(self.label, str) or not self.label.strip()
        ):
            raise ValueError("label cannot be blank")


@dataclass(frozen=True)
class SpectrumFrame:
    """One raw detector frame with a pixel axis and uncalibrated counts."""

    frame_index: int
    pixel_axis: Sequence[float]
    intensity_counts: Sequence[float]
    started_at: datetime
    completed_at: datetime
    monotonic_started_s: float
    monotonic_completed_s: float
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if (
            isinstance(self.frame_index, bool)
            or not isinstance(self.frame_index, int)
            or self.frame_index < 0
        ):
            raise ValueError("frame_index must be an integer >= 0")

        pixel_axis = tuple(float(value) for value in self.pixel_axis)
        intensity_counts = tuple(float(value) for value in self.intensity_counts)
        if not pixel_axis:
            raise ValueError("pixel_axis cannot be empty")
        if len(pixel_axis) != len(intensity_counts):
            raise ValueError("pixel_axis and intensity_counts must have equal length")
        if not all(isfinite(value) for value in pixel_axis):
            raise ValueError("pixel_axis values must be finite")
        if not all(isfinite(value) for value in intensity_counts):
            raise ValueError("intensity_counts values must be finite")
        if not isinstance(self.started_at, datetime) or not isinstance(
            self.completed_at, datetime
        ):
            raise ValueError("frame timestamps must be datetime values")
        if self.started_at.tzinfo is None or self.completed_at.tzinfo is None:
            raise ValueError("frame timestamps must be timezone-aware")
        if self.completed_at < self.started_at:
            raise ValueError("completed_at cannot precede started_at")
        _require_finite(self.monotonic_started_s, "monotonic_started_s")
        _require_finite(self.monotonic_completed_s, "monotonic_completed_s")
        if self.monotonic_completed_s < self.monotonic_started_s:
            raise ValueError(
                "monotonic_completed_s cannot precede monotonic_started_s"
            )

        object.__setattr__(self, "pixel_axis", pixel_axis)
        object.__setattr__(self, "intensity_counts", intensity_counts)
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))


@dataclass(frozen=True)
class RamanAcquisitionResult:
    """The raw frames and timing record returned for one acquisition plan."""

    session_id: str
    plan: RamanAcquisitionPlan
    frames: Sequence[SpectrumFrame]
    started_at: datetime
    completed_at: datetime
    timing_quality: TimingQuality
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.session_id, str) or not self.session_id.strip():
            raise ValueError("session_id must be provided")
        if not isinstance(self.timing_quality, TimingQuality):
            object.__setattr__(
                self, "timing_quality", TimingQuality(self.timing_quality)
            )

        frames = tuple(self.frames)
        if len(frames) != self.plan.parameters.spectra_count:
            raise ValueError("frame count must match plan.parameters.spectra_count")
        if not all(isinstance(frame, SpectrumFrame) for frame in frames):
            raise ValueError("frames must contain SpectrumFrame values")
        if tuple(frame.frame_index for frame in frames) != tuple(range(len(frames))):
            raise ValueError("frame indexes must be sequential and start at zero")
        if not isinstance(self.started_at, datetime) or not isinstance(
            self.completed_at, datetime
        ):
            raise ValueError("result timestamps must be datetime values")
        if self.started_at.tzinfo is None or self.completed_at.tzinfo is None:
            raise ValueError("result timestamps must be timezone-aware")
        if self.completed_at < self.started_at:
            raise ValueError("completed_at cannot precede started_at")
        if any(
            frame.started_at < self.started_at
            or frame.completed_at > self.completed_at
            for frame in frames
        ):
            raise ValueError("frame timestamps must fall within the result interval")

        object.__setattr__(self, "frames", frames)
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))


def _require_positive_finite(value: float, name: str) -> None:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not isfinite(value)
        or value <= 0
    ):
        raise ValueError(f"{name} must be finite and > 0")


def _require_finite(value: float, name: str) -> None:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not isfinite(value)
    ):
        raise ValueError(f"{name} must be finite")


def _require_nonnegative_finite(value: float, name: str) -> None:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not isfinite(value)
        or value < 0
    ):
        raise ValueError(f"{name} must be finite and >= 0")


def _require_positive_int(value: int, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{name} must be an integer >= 1")

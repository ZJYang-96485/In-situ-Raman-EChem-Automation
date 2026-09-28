from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Sequence


@dataclass
class CVParameters:
    initial_potential: float
    high_potential: float
    low_potential: float
    scan_rate: float
    cycles: int = 1

    def __post_init__(self):
        _require_finite(self.initial_potential, "initial_potential")
        _require_finite(self.high_potential, "high_potential")
        _require_finite(self.low_potential, "low_potential")
        if self.high_potential <= self.low_potential:
            raise ValueError("high_potential must be greater than low_potential")
        _require_positive_finite(self.scan_rate, "scan_rate")
        _require_positive_int(self.cycles, "cycles")


@dataclass
class LSVParameters:
    initial_potential: float
    final_potential: float
    scan_rate: float

    def __post_init__(self):
        _require_finite(self.initial_potential, "initial_potential")
        _require_finite(self.final_potential, "final_potential")
        _require_positive_finite(self.scan_rate, "scan_rate")
        if self.initial_potential == self.final_potential:
            raise ValueError(
                "initial_potential and final_potential cannot be equal"
            )


@dataclass
class ITParameters:
    potential: float
    duration: float
    sample_interval: float = 1.0

    def __post_init__(self):
        _require_finite(self.potential, "potential")
        _require_positive_finite(self.duration, "duration")
        _require_positive_finite(self.sample_interval, "sample_interval")
        if self.sample_interval > self.duration:
            raise ValueError("sample_interval cannot exceed duration")


@dataclass
class OCPParameters:
    duration: float
    sample_interval: float = 1.0

    def __post_init__(self):
        _require_positive_finite(self.duration, "duration")
        _require_positive_finite(self.sample_interval, "sample_interval")
        if self.sample_interval > self.duration:
            raise ValueError("sample_interval cannot exceed duration")


@dataclass
class EISParameters:
    dc_potential: float
    ac_amplitude: float
    start_frequency: float
    end_frequency: float
    points_per_decade: int = 10

    def __post_init__(self):
        _require_finite(self.dc_potential, "dc_potential")
        _require_positive_finite(self.ac_amplitude, "ac_amplitude")
        _require_positive_finite(self.start_frequency, "start_frequency")
        _require_positive_finite(self.end_frequency, "end_frequency")
        if self.start_frequency <= self.end_frequency:
            raise ValueError(
                "start_frequency must be greater than end_frequency"
            )
        _require_positive_int(self.points_per_decade, "points_per_decade")


@dataclass(frozen=True)
class PotentialStep:
    """One potential hold used by CA and multi-potential-step plans."""

    potential_V: float
    duration_s: float

    def __post_init__(self):
        _require_finite(self.potential_V, "potential_V")
        _require_positive_finite(self.duration_s, "duration_s")


@dataclass(frozen=True)
class CurrentStep:
    """One current hold used by an ISTEP/CPCS plan."""

    current_A: float
    duration_s: float

    def __post_init__(self):
        _require_finite(self.current_A, "current_A")
        _require_positive_finite(self.duration_s, "duration_s")


@dataclass(frozen=True)
class CAParameters:
    """Vendor-neutral chronoamperometry plan.

    Charge is deliberately derived from the returned current/time series rather
    than represented as a separate, unsupported libec CC technique.
    """

    steps: Sequence[PotentialStep]
    sample_interval_s: float = 0.1
    quiet_time_s: float = 0.0
    cycles: int = 1

    def __post_init__(self):
        steps = tuple(self.steps)
        if not steps or not all(isinstance(step, PotentialStep) for step in steps):
            raise ValueError("steps must contain at least one PotentialStep")
        _require_positive_finite(self.sample_interval_s, "sample_interval_s")
        _require_nonnegative_finite(self.quiet_time_s, "quiet_time_s")
        _require_positive_int(self.cycles, "cycles")
        if self.sample_interval_s > min(step.duration_s for step in steps):
            raise ValueError("sample_interval_s cannot exceed the shortest step")
        object.__setattr__(self, "steps", steps)


@dataclass(frozen=True)
class SWVParameters:
    initial_potential_V: float
    final_potential_V: float
    increment_V: float
    amplitude_V: float
    frequency_Hz: float
    quiet_time_s: float = 0.0

    def __post_init__(self):
        _require_finite(self.initial_potential_V, "initial_potential_V")
        _require_finite(self.final_potential_V, "final_potential_V")
        if self.initial_potential_V == self.final_potential_V:
            raise ValueError("initial_potential_V and final_potential_V cannot be equal")
        _require_positive_finite(abs(self.increment_V), "abs(increment_V)")
        _require_positive_finite(self.amplitude_V, "amplitude_V")
        _require_positive_finite(self.frequency_Hz, "frequency_Hz")
        _require_nonnegative_finite(self.quiet_time_s, "quiet_time_s")


@dataclass(frozen=True)
class IMPEParameters:
    initial_potential_V: float
    final_potential_V: float
    potential_step_V: float
    ac_amplitude_V_rms: float
    frequency_Hz: float
    quiet_time_s: float = 0.0

    def __post_init__(self):
        _require_finite(self.initial_potential_V, "initial_potential_V")
        _require_finite(self.final_potential_V, "final_potential_V")
        if self.initial_potential_V == self.final_potential_V:
            raise ValueError("initial_potential_V and final_potential_V cannot be equal")
        _require_positive_finite(abs(self.potential_step_V), "abs(potential_step_V)")
        _require_positive_finite(self.ac_amplitude_V_rms, "ac_amplitude_V_rms")
        _require_positive_finite(self.frequency_Hz, "frequency_Hz")
        _require_nonnegative_finite(self.quiet_time_s, "quiet_time_s")


@dataclass(frozen=True)
class STEPParameters:
    steps: Sequence[PotentialStep]
    sample_interval_s: float = 0.1
    cycles: int = 1

    def __post_init__(self):
        steps = tuple(self.steps)
        if not steps or not all(isinstance(step, PotentialStep) for step in steps):
            raise ValueError("steps must contain at least one PotentialStep")
        _require_positive_finite(self.sample_interval_s, "sample_interval_s")
        _require_positive_int(self.cycles, "cycles")
        if self.sample_interval_s > min(step.duration_s for step in steps):
            raise ValueError("sample_interval_s cannot exceed the shortest step")
        object.__setattr__(self, "steps", steps)


@dataclass(frozen=True)
class ISTEPParameters:
    steps: Sequence[CurrentStep]
    sample_interval_s: float = 0.1
    cycles: int = 1

    def __post_init__(self):
        steps = tuple(self.steps)
        if not steps or not all(isinstance(step, CurrentStep) for step in steps):
            raise ValueError("steps must contain at least one CurrentStep")
        _require_positive_finite(self.sample_interval_s, "sample_interval_s")
        _require_positive_int(self.cycles, "cycles")
        if self.sample_interval_s > min(step.duration_s for step in steps):
            raise ValueError("sample_interval_s cannot exceed the shortest step")
        object.__setattr__(self, "steps", steps)


def _require_finite(value: float, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value):
        raise ValueError(f"{name} must be finite")


def _require_positive_finite(value: float, name: str) -> None:
    _require_finite(value, name)
    if value <= 0:
        raise ValueError(f"{name} must be > 0")


def _require_nonnegative_finite(value: float, name: str) -> None:
    _require_finite(value, name)
    if value < 0:
        raise ValueError(f"{name} must be >= 0")


def _require_positive_int(value: int, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{name} must be an integer >= 1")

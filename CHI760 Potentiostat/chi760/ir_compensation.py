"""Vendor-neutral automatic iR-compensation planning and Ru validation.

The policy follows the per-trial preparation used by the referenced RDE
project, but the eventual CHI backend must discover and verify the installed
760E libec parameter identifiers before it may apply compensation.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from math import isfinite
from statistics import mean
from typing import Iterable

from .profiles import Technique


class IRCompensationMode(str, Enum):
    POSITIVE_FEEDBACK = "positive_feedback"
    CURRENT_INTERRUPT = "current_interrupt"
    AUTOMATIC = "automatic"


IR_ELIGIBLE_TECHNIQUES = frozenset(
    {Technique.CV, Technique.CA}
)


@dataclass(frozen=True)
class IRCompensationPlan:
    enabled: bool = True
    mode: IRCompensationMode = IRCompensationMode.AUTOMATIC
    target_compensation_fraction: float = 0.95
    max_compensation_trials: int = 10
    ru_retry_count: int = 5
    ru_repeatability_limit: float = 0.05
    ru_min_ohm: float = 0.01
    ru_max_ohm: float = 100000.0
    ocp_stabilization_s: float = 5.0
    ocp_stabilization_timeout_s: float = 30.0
    ocp_sample_interval_s: float = 0.25
    ocp_stability_window: int = 5
    ocp_stability_limit_V: float = 0.005
    ocp_abs_limit_V: float = 2.5
    ru_frequency_Hz: float = 100000.0
    ru_ac_amplitude_V: float = 0.005
    ru_settle_s: float = 0.5
    continue_without_ir_on_ru_failure: bool = True
    require_parameter_readback: bool = True
    starting_policy_confirmed: bool = True
    live_use_approved: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.mode, IRCompensationMode):
            object.__setattr__(self, "mode", IRCompensationMode(self.mode))
        if not _is_finite_number(self.target_compensation_fraction) or self.target_compensation_fraction != 0.95:
            raise ValueError("target_compensation_fraction is fixed at 0.95")
        if self.max_compensation_trials != 10 or isinstance(self.max_compensation_trials, bool):
            raise ValueError("max_compensation_trials is fixed at 10")
        if not isinstance(self.ru_retry_count, int) or isinstance(self.ru_retry_count, bool) or not 3 <= self.ru_retry_count <= 20:
            raise ValueError("ru_retry_count must be an integer from 3 to 20")
        if not _is_finite_number(self.ru_repeatability_limit) or not 0 < self.ru_repeatability_limit < 1:
            raise ValueError("ru_repeatability_limit must be > 0 and < 1")
        if not _is_finite_number(self.ru_min_ohm) or not _is_finite_number(self.ru_max_ohm) or not 0 < self.ru_min_ohm < self.ru_max_ohm:
            raise ValueError("Ru limits must be positive and ordered")
        if not _is_finite_number(self.ocp_stabilization_s) or self.ocp_stabilization_s < 0:
            raise ValueError("ocp_stabilization_s must be >= 0")
        if not _is_finite_number(self.ocp_stabilization_timeout_s) or self.ocp_stabilization_timeout_s < self.ocp_stabilization_s:
            raise ValueError("ocp_stabilization_timeout_s must be >= ocp_stabilization_s")
        if not _is_finite_number(self.ocp_sample_interval_s) or not 0 < self.ocp_sample_interval_s <= self.ocp_stabilization_timeout_s:
            raise ValueError("ocp_sample_interval_s must be > 0 and within the timeout")
        if not isinstance(self.ocp_stability_window, int) or isinstance(self.ocp_stability_window, bool) or self.ocp_stability_window < 2:
            raise ValueError("ocp_stability_window must be an integer >= 2")
        for name in (
            "ocp_stability_limit_V",
            "ocp_abs_limit_V",
            "ru_frequency_Hz",
            "ru_ac_amplitude_V",
        ):
            value = getattr(self, name)
            if not _is_finite_number(value) or value <= 0:
                raise ValueError(f"{name} must be finite and > 0")
        if not _is_finite_number(self.ru_settle_s) or self.ru_settle_s < 0:
            raise ValueError("ru_settle_s must be finite and >= 0")
        for name in (
            "enabled",
            "continue_without_ir_on_ru_failure",
            "require_parameter_readback",
            "starting_policy_confirmed",
            "live_use_approved",
        ):
            if not isinstance(getattr(self, name), bool):
                raise ValueError(f"{name} must be a boolean")


@dataclass(frozen=True)
class RuValidationResult:
    attempts_ohm: tuple[float | None, ...]
    selected_ohm: float | None
    repeatability: float | None
    requested_compensation_ohm: float | None
    passed: bool
    continue_uncompensated: bool
    reason: str | None


@dataclass(frozen=True)
class IRCompensationProgress:
    observed_fractions: tuple[float | None, ...]
    target_fraction: float
    reached_target: bool
    exhausted: bool
    accepted_fraction: float | None
    accepted_trial_number: int | None
    accepted_at_ceiling: bool
    next_trial_number: int | None
    reason: str | None


def technique_uses_ir_compensation(technique: Technique | str) -> bool:
    """Return whether the offline RDE plan requests iR for this technique.

    This is intentionally limited to the CV/CA family demonstrated by the
    source RDE workflow. It is not a claim about installed 760E capability.
    """

    if not isinstance(technique, Technique):
        technique = Technique(technique)
    return technique in IR_ELIGIBLE_TECHNIQUES


def validate_ru_measurements(
    attempts_ohm: Iterable[float | None],
    plan: IRCompensationPlan,
) -> RuValidationResult:
    """Select the first repeatable central pair from bounded Ru readings."""

    attempts: list[float | None] = []
    valid: list[float] = []
    last_repeatability = None
    for raw in attempts_ohm:
        if len(attempts) >= plan.ru_retry_count:
            break
        value = None
        if raw is not None and not isinstance(raw, bool):
            try:
                candidate = float(raw)
            except (TypeError, ValueError):
                candidate = None
            if candidate is not None and isfinite(candidate) and plan.ru_min_ohm <= candidate <= plan.ru_max_ohm:
                value = candidate
                valid.append(candidate)
        attempts.append(value)
        if len(valid) < 2:
            continue

        ordered = sorted(valid)
        middle = len(ordered) // 2
        if len(ordered) == 2 or len(ordered) % 2 == 0:
            first, second = ordered[middle - 1], ordered[middle]
            selected = mean((first, second))
        else:
            selected = ordered[middle]
            neighbours = ordered[:middle] + ordered[middle + 1 :]
            second = min(neighbours, key=lambda item: abs(item - selected))
            first = selected
        last_repeatability = abs(first - second) / mean((first, second))
        if last_repeatability <= plan.ru_repeatability_limit:
            return RuValidationResult(
                tuple(attempts),
                selected,
                last_repeatability,
                selected * plan.target_compensation_fraction,
                True,
                False,
                None,
            )

    reason = "Unable to obtain repeatable Ru measurements within configured limits"
    return RuValidationResult(
        tuple(attempts),
        None,
        last_repeatability,
        None,
        False,
        plan.continue_without_ir_on_ru_failure,
        reason,
    )


def evaluate_compensation_trials(
    observed_fractions: Iterable[float | None],
    plan: IRCompensationPlan,
) -> IRCompensationProgress:
    """Evaluate readback-derived compensation fractions against the stop rule.

    The live backend will derive each observed fraction from verified CHI
    readback. This connection-free function stops at 95% during trials 1–9.
    If the target is still unmet, it accepts the tenth trial's valid value.
    """

    observations: list[float | None] = []
    for raw in observed_fractions:
        if len(observations) >= plan.max_compensation_trials:
            break
        value = None
        if raw is not None and not isinstance(raw, bool):
            try:
                candidate = float(raw)
            except (TypeError, ValueError):
                candidate = None
            if candidate is not None and isfinite(candidate) and 0 <= candidate <= 1:
                value = candidate
        observations.append(value)
        if value is not None and value >= plan.target_compensation_fraction:
            return IRCompensationProgress(
                tuple(observations),
                plan.target_compensation_fraction,
                True,
                False,
                value,
                len(observations),
                False,
                None,
                None,
            )

    exhausted = len(observations) >= plan.max_compensation_trials
    final_value = observations[-1] if exhausted and observations else None
    accepted_at_ceiling = final_value is not None
    return IRCompensationProgress(
        tuple(observations),
        plan.target_compensation_fraction,
        False,
        exhausted,
        final_value if accepted_at_ceiling else None,
        len(observations) if accepted_at_ceiling else None,
        accepted_at_ceiling,
        None if exhausted else len(observations) + 1,
        (
            "Accepted final valid value at the 10-trial ceiling"
            if accepted_at_ceiling
            else "Final trial produced no valid value"
            if exhausted
            else None
        ),
    )


def ir_plan_parameters(plan: IRCompensationPlan) -> dict[str, object]:
    """Serialize an iR plan for protocol metadata and the future live backend."""

    return {
        "enabled": plan.enabled,
        "mode": plan.mode.value,
        "target_compensation_fraction": plan.target_compensation_fraction,
        "max_compensation_trials": plan.max_compensation_trials,
        "stop_condition": "confirmed_target_or_trial_ceiling",
        "trial_ceiling_behavior": "accept_final_valid_value",
        "ru_retry_count": plan.ru_retry_count,
        "ru_repeatability_limit": plan.ru_repeatability_limit,
        "ru_min_ohm": plan.ru_min_ohm,
        "ru_max_ohm": plan.ru_max_ohm,
        "ocp_stabilization_s": plan.ocp_stabilization_s,
        "ocp_stabilization_timeout_s": plan.ocp_stabilization_timeout_s,
        "ocp_sample_interval_s": plan.ocp_sample_interval_s,
        "ocp_stability_window": plan.ocp_stability_window,
        "ocp_stability_limit_V": plan.ocp_stability_limit_V,
        "ocp_abs_limit_V": plan.ocp_abs_limit_V,
        "ru_frequency_Hz": plan.ru_frequency_Hz,
        "ru_ac_amplitude_V": plan.ru_ac_amplitude_V,
        "ru_settle_s": plan.ru_settle_s,
        "continue_without_ir_on_ru_failure": plan.continue_without_ir_on_ru_failure,
        "require_parameter_readback": plan.require_parameter_readback,
        "starting_policy_confirmed": plan.starting_policy_confirmed,
        "live_use_approved": plan.live_use_approved,
        "parameter_origin": "user-defined 95%/10-trial policy; remaining preparation defaults adapted from ZJYang-96485/RDE",
        "requested_mode_not_hardware_confirmed": True,
        "requires_installed_sdk_parameter_discovery": True,
        "cleanup": "disable_ir_compensation_and_cell_off",
    }


def _is_finite_number(value: object) -> bool:
    return (
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and isfinite(value)
    )

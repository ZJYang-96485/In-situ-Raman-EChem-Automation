"""Execution-disabled protocol plans for optional disk-only RDE experiments."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from math import isfinite
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from .profiles import Technique
from .ir_compensation import IRCompensationPlan, ir_plan_parameters, technique_uses_ir_compensation


class ProtocolAction(str, Enum):
    MARKER = "marker"
    SET_RDE_SPEED = "set_rde_speed"
    START_RDE = "start_rde"
    WAIT = "wait"
    PREPARE_IR_COMPENSATION = "prepare_ir_compensation"
    RUN_EXPERIMENT = "run_experiment"
    DISABLE_IR_COMPENSATION = "disable_ir_compensation"
    CAPTURE_RAMAN = "capture_raman"
    STOP_RDE = "stop_rde"


class RamanSyncPolicy(str, Enum):
    NONE = "none"
    AFTER_EQUILIBRATION = "after_equilibration"
    BEFORE_AND_AFTER_EXPERIMENT = "before_and_after_experiment"


@dataclass(frozen=True)
class RDEExperiment:
    """Technique request embedded in an RDE protocol.

    Parameters stay vendor-neutral until the reviewed libec mapping layer is
    available. Constructing a protocol never communicates with hardware.
    """

    technique: Technique
    parameters: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.technique, Technique):
            object.__setattr__(self, "technique", Technique(self.technique))
        if not isinstance(self.parameters, Mapping):
            raise ValueError("parameters must be a mapping")
        object.__setattr__(self, "parameters", MappingProxyType(dict(self.parameters)))


@dataclass(frozen=True)
class ProtocolStep:
    step_id: str
    label: str
    action: ProtocolAction
    parameters: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.step_id, str) or not isinstance(self.label, str) or not self.step_id.strip() or not self.label.strip():
            raise ValueError("step_id and label must be provided")
        if not isinstance(self.action, ProtocolAction):
            object.__setattr__(self, "action", ProtocolAction(self.action))
        if not isinstance(self.parameters, Mapping):
            raise ValueError("parameters must be a mapping")
        object.__setattr__(self, "parameters", MappingProxyType(dict(self.parameters)))


@dataclass(frozen=True)
class EchemProtocol:
    name: str
    description: str
    steps: Sequence[ProtocolStep]
    execution_enabled: bool = False
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not isinstance(self.description, str) or not self.name.strip() or not self.description.strip():
            raise ValueError("name and description must be provided")
        steps = tuple(self.steps)
        if not steps or not all(isinstance(step, ProtocolStep) for step in steps):
            raise ValueError("steps must contain at least one ProtocolStep")
        if not isinstance(self.execution_enabled, bool):
            raise ValueError("execution_enabled must be a boolean")
        if self.execution_enabled:
            raise ValueError("RDE protocol execution is disabled before hardware review")
        if len({step.step_id for step in steps}) != len(steps):
            raise ValueError("protocol step_id values must be unique")
        object.__setattr__(self, "steps", steps)
        if not isinstance(self.metadata, Mapping):
            raise ValueError("metadata must be a mapping")
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))


def build_rde_protocol(
    *,
    name: str,
    speeds_rpm: Sequence[float],
    experiment: RDEExperiment,
    equilibration_s: float,
    raman_sync: RamanSyncPolicy = RamanSyncPolicy.AFTER_EQUILIBRATION,
    conditioning: RDEExperiment | None = None,
    ir_compensation: IRCompensationPlan | None = None,
) -> EchemProtocol:
    """Build a reusable disk-only RDE rotation-series plan without executing it."""

    if not isinstance(experiment, RDEExperiment):
        raise ValueError("experiment must be an RDEExperiment")
    if conditioning is not None and not isinstance(conditioning, RDEExperiment):
        raise ValueError("conditioning must be an RDEExperiment or None")
    if ir_compensation is not None and not isinstance(ir_compensation, IRCompensationPlan):
        raise ValueError("ir_compensation must be an IRCompensationPlan or None")
    if isinstance(speeds_rpm, (str, bytes)):
        raise ValueError("speeds_rpm must be a sequence of numeric values")
    try:
        speeds = tuple(_finite_float(speed, "speeds_rpm") for speed in speeds_rpm)
    except TypeError as exc:
        raise ValueError("speeds_rpm must be a sequence of numeric values") from exc
    if not speeds or not all(speed > 0 for speed in speeds):
        raise ValueError("speeds_rpm must contain finite values > 0")
    equilibration = _finite_float(equilibration_s, "equilibration_s")
    if equilibration < 0:
        raise ValueError("equilibration_s must be finite and >= 0")
    if not isinstance(raman_sync, RamanSyncPolicy):
        raman_sync = RamanSyncPolicy(raman_sync)
    ir_plan = ir_compensation or IRCompensationPlan()

    steps: list[ProtocolStep] = [
        ProtocolStep("marker-start", "Protocol start", ProtocolAction.MARKER)
    ]
    if conditioning is not None:
        steps.extend(_prepared_experiment_steps("conditioning", "Electrode conditioning", conditioning, ir_plan))
    for index, speed_rpm in enumerate(speeds, start=1):
        prefix = f"rotation-{index:02d}"
        steps.extend(
            (
                ProtocolStep(
                    f"{prefix}-speed",
                    f"Set rotation to {speed_rpm:g} rpm",
                    ProtocolAction.SET_RDE_SPEED,
                    {"speed_rpm": speed_rpm, "requires_verified_rde": True},
                ),
                ProtocolStep(
                    f"{prefix}-start",
                    "Start rotation",
                    ProtocolAction.START_RDE,
                    {"requires_verified_rde": True},
                ),
                ProtocolStep(
                    f"{prefix}-equilibrate",
                    "Hydrodynamic equilibration",
                    ProtocolAction.WAIT,
                    {"duration_s": equilibration},
                ),
            )
        )
        if raman_sync is RamanSyncPolicy.AFTER_EQUILIBRATION:
            steps.append(_raman_step(f"{prefix}-raman", "Raman capture after equilibration"))
        elif raman_sync is RamanSyncPolicy.BEFORE_AND_AFTER_EXPERIMENT:
            steps.append(_raman_step(f"{prefix}-raman-before", "Raman capture before experiment"))
        steps.extend(
            _prepared_experiment_steps(
                f"{prefix}-experiment", experiment.technique.value, experiment, ir_plan
            )
        )
        if raman_sync is RamanSyncPolicy.BEFORE_AND_AFTER_EXPERIMENT:
            steps.append(_raman_step(f"{prefix}-raman-after", "Raman capture after experiment"))

    steps.extend(
        (
            ProtocolStep(
                "rde-stop",
                "Stop rotation",
                ProtocolAction.STOP_RDE,
                {"requires_verified_rde": True},
            ),
            ProtocolStep("marker-complete", "Protocol complete", ProtocolAction.MARKER),
        )
    )
    return EchemProtocol(
        name=name,
        description="Optional disk-only RDE rotation-series plan; hardware execution is disabled.",
        steps=steps,
        metadata={
            "speeds_rpm": speeds,
            "raman_sync": raman_sync.value,
            "rde_mode": "optional_disk_only",
            "timing_contract": "planned_only",
            "ir_compensation": ir_plan_parameters(ir_plan),
        },
    )


def _experiment_step(step_id: str, label: str, experiment: RDEExperiment) -> ProtocolStep:
    return ProtocolStep(
        step_id,
        label,
        ProtocolAction.RUN_EXPERIMENT,
        {"technique": experiment.technique.value, "parameters": dict(experiment.parameters)},
    )


def _prepared_experiment_steps(
    step_id: str,
    label: str,
    experiment: RDEExperiment,
    ir_plan: IRCompensationPlan,
) -> tuple[ProtocolStep, ...]:
    experiment_step = _experiment_step(step_id, label, experiment)
    if not ir_plan.enabled or not technique_uses_ir_compensation(experiment.technique):
        return (experiment_step,)
    return (
        ProtocolStep(
            f"{step_id}-ir-prepare",
            "Measure Ru and prepare iR compensation",
            ProtocolAction.PREPARE_IR_COMPENSATION,
            ir_plan_parameters(ir_plan),
        ),
        experiment_step,
        ProtocolStep(
            f"{step_id}-ir-disable",
            "Disable iR compensation",
            ProtocolAction.DISABLE_IR_COMPENSATION,
            {"required_even_after_failure": True, "cell_off_on_cleanup_failure": True},
        ),
    )


def _raman_step(step_id: str, label: str) -> ProtocolStep:
    return ProtocolStep(
        step_id,
        label,
        ProtocolAction.CAPTURE_RAMAN,
        {"trigger_mode": "software", "timing_quality": "software_best_effort"},
    )


def _finite_float(value: Any, name: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name} values must be finite numbers, not booleans")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} values must be finite numbers") from exc
    if not isfinite(number):
        raise ValueError(f"{name} values must be finite numbers")
    return number

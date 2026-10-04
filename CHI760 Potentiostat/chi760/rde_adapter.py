"""Adapt protocol JSON from the RDE repository to a CHI 760E plan.

The source project targets Gamry hardware. This module preserves the scientific
intent and parameter names while reporting how each step maps to the documented
760E libec surface. It never performs hardware I/O and never silently replaces
an unsupported technique with a different experiment.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from .profiles import Technique
from .runtime_profile import ELECTROCHEMISTRY_ONLY, HardwareOperation
from .ir_compensation import IRCompensationPlan, ir_plan_parameters, technique_uses_ir_compensation
from .protocols import EchemProtocol, ProtocolAction, ProtocolStep


class AdaptationStatus(str, Enum):
    LIBEC_760E = "libec_760e"
    ORCHESTRATION = "orchestration"
    DERIVED = "derived"
    DESKTOP_ONLY = "desktop_only"
    VERIFY_INSTALLED_SDK = "verify_installed_sdk"


@dataclass(frozen=True)
class TechniqueAdaptation:
    source_technique: str
    chi_technique: Technique | None
    status: AdaptationStatus
    note: str


@dataclass(frozen=True)
class ProtocolAdaptation:
    protocol: EchemProtocol
    techniques: Sequence[TechniqueAdaptation]
    warnings: Sequence[str]

    def __post_init__(self) -> None:
        object.__setattr__(self, "techniques", tuple(self.techniques))
        object.__setattr__(self, "warnings", tuple(self.warnings))


TECHNIQUE_ADAPTATIONS: Mapping[str, TechniqueAdaptation] = MappingProxyType(
    {
        "wait": TechniqueAdaptation(
            "wait", None, AdaptationStatus.ORCHESTRATION, "Local scheduler delay."
        ),
        "ocp": TechniqueAdaptation(
            "ocp", Technique.OCP, AdaptationStatus.LIBEC_760E, "Maps to OCPT."
        ),
        "cv": TechniqueAdaptation(
            "cv", Technique.CV, AdaptationStatus.LIBEC_760E, "Direct CV mapping."
        ),
        "it": TechniqueAdaptation(
            "it", Technique.IT, AdaptationStatus.LIBEC_760E,
            "Direct amperometric i-t mapping.",
        ),
        "ca": TechniqueAdaptation(
            "ca", Technique.CA, AdaptationStatus.LIBEC_760E,
            "Direct CA mapping; chronocoulometry (CC) can be derived by integrating I(t).",
        ),
        "ca_staircase": TechniqueAdaptation(
            "ca_staircase", Technique.STEP, AdaptationStatus.LIBEC_760E,
            "Maps to multi-potential STEP after parameter validation.",
        ),
        "levich_rpm_sweep_ca": TechniqueAdaptation(
            "levich_rpm_sweep_ca", Technique.CA, AdaptationStatus.LIBEC_760E,
            "One continuous CA acquisition plus an external commanded-RPM schedule.",
        ),
        "eis": TechniqueAdaptation(
            "eis", Technique.EIS, AdaptationStatus.LIBEC_760E, "Maps to IMP."
        ),
        "cp": TechniqueAdaptation(
            "cp", Technique.ISTEP, AdaptationStatus.LIBEC_760E,
            "A single signed-current hold maps to ISTEP/CPCS.",
        ),
        "cc_charge": TechniqueAdaptation(
            "cc_charge", Technique.ISTEP, AdaptationStatus.DERIVED,
            "Source constant-current charge (not chronocoulometry CC): run ISTEP/CPCS and derive capacity from I(t).",
        ),
        "cc_discharge": TechniqueAdaptation(
            "cc_discharge", Technique.ISTEP, AdaptationStatus.DERIVED,
            "Source constant-current discharge (not chronocoulometry CC): run ISTEP/CPCS and derive capacity from I(t).",
        ),
        "lsv": TechniqueAdaptation(
            "lsv", Technique.LSV, AdaptationStatus.DESKTOP_ONLY,
            "760E desktop capability; not listed for 7xxE in the public libec matrix.",
        ),
        "geis": TechniqueAdaptation(
            "geis", Technique.EIS, AdaptationStatus.VERIFY_INSTALLED_SDK,
            "Source GEIS intent retained; the installed libec IMP mode and parameter surface must be verified.",
        ),
    }
)


def request_rde_hardware_control() -> None:
    """Reject optional disk-RDE motor control before any controller call."""

    ELECTROCHEMISTRY_ONLY.require(
        HardwareOperation.RDE_MOTOR_CONTROL,
        "RDE motor control",
    )


def adapt_rde_protocol(
    source: Mapping[str, Any],
    *,
    ir_compensation: IRCompensationPlan | None = None,
) -> ProtocolAdaptation:
    """Translate one RDE protocol payload into an execution-disabled CHI plan."""

    if not isinstance(source, Mapping):
        raise ValueError("source protocol must be a mapping")
    if ir_compensation is not None and not isinstance(ir_compensation, IRCompensationPlan):
        raise ValueError("ir_compensation must be an IRCompensationPlan or None")
    name = str(source.get("protocol_name") or source.get("display_name") or "").strip()
    if not name:
        raise ValueError("protocol_name is required")
    raw_steps = source.get("steps")
    if not isinstance(raw_steps, list) or not raw_steps:
        raise ValueError("steps must be a non-empty list")

    protocol_steps: list[ProtocolStep] = []
    reports: list[TechniqueAdaptation] = []
    warnings: list[str] = []
    ir_plan = ir_compensation or IRCompensationPlan()
    output_index = 0
    for source_index, raw_step in enumerate(raw_steps, start=1):
        if not isinstance(raw_step, Mapping):
            raise ValueError(f"step {source_index} must be an object")
        enabled = raw_step.get("enabled", True)
        if not isinstance(enabled, bool):
            raise ValueError(f"step {source_index} enabled must be a boolean")
        if not enabled:
            continue
        expanded = _expand_ca_range(raw_step) if raw_step.get("type") == "ca_range" else [dict(raw_step)]
        for expanded_step in expanded:
            output_index += 1
            source_technique = str(
                expanded_step.get("technique") or expanded_step.get("type") or ""
            ).strip().lower()
            adaptation = TECHNIQUE_ADAPTATIONS.get(source_technique)
            if adaptation is None:
                raise ValueError(f"step {source_index} has unsupported source technique '{source_technique}'")
            reports.append(adaptation)
            label = str(expanded_step.get("name") or f"step_{output_index}").strip()
            parameters = _portable_parameters(expanded_step)
            parameters.update(
                {
                    "source_technique": source_technique,
                    "chi_technique": adaptation.chi_technique.value if adaptation.chi_technique else None,
                    "adaptation_status": adaptation.status.value,
                    "adaptation_note": adaptation.note,
                }
            )
            action = ProtocolAction.WAIT if source_technique == "wait" else ProtocolAction.RUN_EXPERIMENT
            base_id = f"step-{output_index:03d}"
            uses_ir = bool(
                ir_plan.enabled
                and adaptation.chi_technique is not None
                and technique_uses_ir_compensation(adaptation.chi_technique)
            )
            if uses_ir:
                protocol_steps.append(
                    ProtocolStep(
                        f"{base_id}-ir-prepare",
                        "Measure Ru and prepare iR compensation",
                        ProtocolAction.PREPARE_IR_COMPENSATION,
                        ir_plan_parameters(ir_plan),
                    )
                )
            protocol_steps.append(ProtocolStep(base_id, label, action, parameters))
            if uses_ir:
                protocol_steps.append(
                    ProtocolStep(
                        f"{base_id}-ir-disable",
                        "Disable iR compensation",
                        ProtocolAction.DISABLE_IR_COMPENSATION,
                        {"required_even_after_failure": True, "cell_off_on_cleanup_failure": True},
                    )
                )
            if adaptation.status in {
                AdaptationStatus.DESKTOP_ONLY,
                AdaptationStatus.VERIFY_INSTALLED_SDK,
            }:
                warnings.append(f"{label}: {adaptation.note}")

    if not protocol_steps:
        raise ValueError("protocol must contain at least one enabled step")

    protocol = EchemProtocol(
        name=name,
        description=str(source.get("description") or "RDE protocol adapted for CHI 760E planning."),
        steps=protocol_steps,
        metadata={
            "source_repository": "https://github.com/ZJYang-96485/RDE",
            "source_platform": "Gamry",
            "target_platform": "CHI 760E",
            "mapping_review_required": True,
            "ir_compensation": ir_plan_parameters(ir_plan),
        },
    )
    return ProtocolAdaptation(protocol, reports, tuple(dict.fromkeys(warnings)))


def _portable_parameters(step: Mapping[str, Any]) -> dict[str, Any]:
    parameters = {
        str(key): value
        for key, value in step.items()
        if key not in {"name", "technique", "type", "enabled", "editor_mode"}
    }
    raw_output = parameters.pop("output", None)
    if raw_output:
        parameters["source_output"] = Path(str(raw_output)).name
        parameters["output_stem"] = Path(str(raw_output)).stem
    if str(step.get("technique", "")).lower() in {"cc_charge", "cc_discharge"}:
        parameters["derive_cumulative_charge"] = True
    if str(step.get("technique", "")).lower() in {"ca", "levich_rpm_sweep_ca"}:
        parameters["derived_outputs"] = ["chronocoulometry_C"]
    return parameters


def _expand_ca_range(step: Mapping[str, Any]) -> list[dict[str, Any]]:
    try:
        start = Decimal(str(step.get("start_voltage_v")))
        end = Decimal(str(step.get("end_voltage_v")))
        increment = Decimal(str(step.get("step_voltage_v")))
    except (InvalidOperation, TypeError) as exc:
        raise ValueError("CA range voltages must be decimal numbers") from exc
    if increment == 0:
        raise ValueError("CA range step_voltage_v cannot be zero")
    if not all(value.is_finite() for value in (start, end, increment)):
        raise ValueError("CA range voltages must be finite")
    if end > start and increment < 0 or end < start and increment > 0:
        raise ValueError("CA range step_voltage_v points away from end_voltage_v")
    if (end - start) % increment != 0:
        raise ValueError("CA range increment must land exactly on end_voltage_v")

    values: list[Decimal] = []
    value = start
    while (increment > 0 and value <= end) or (increment < 0 and value >= end):
        values.append(value)
        if len(values) > 1000:
            raise ValueError("CA range expands to more than 1000 steps")
        value += increment
    label = str(step.get("direction_label") or step.get("name") or "ca_range")
    prefix = str(step.get("output_prefix") or label)
    expanded = []
    for voltage in values:
        voltage_float = float(voltage)
        token = _voltage_token(voltage)
        item = dict(step)
        item.pop("type", None)
        item.update(
            {
                "name": f"{label}_{token}",
                "technique": "ca",
                "voltage_v": voltage_float,
                "output": f"{prefix}_{token}.DTA",
            }
        )
        expanded.append(item)
    return expanded


def _voltage_token(voltage: Decimal) -> str:
    if voltage == 0:
        return "0p0V"
    prefix = "m" if voltage < 0 else "p"
    magnitude = format(abs(voltage).normalize(), "f")
    if "." not in magnitude:
        magnitude += ".0"
    return f"{prefix}{magnitude.replace('.', 'p')}V"

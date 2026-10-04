"""Connection-boundary mappings for the future CHI 760E SDK backend.

Only public technique names and this project's internal parameter names are
recorded here. Vendor entry points and parameter identifiers remain ``None``
until they are confirmed from the installed SDK package.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .profiles import Technique


class MappingStatus(str, Enum):
    DOCUMENTED_LIBEC = "documented_libec"
    DESKTOP_ONLY = "desktop_only"
    VERIFY_INSTALLED_SDK = "verify_installed_sdk"


@dataclass(frozen=True)
class TechniqueSDKMapping:
    technique: Technique | str
    controller_method: str | None
    public_libec_name: str
    status: MappingStatus
    internal_parameters: tuple[str, ...]
    sdk_entrypoint: str | None = None
    sdk_parameter_identifiers: tuple[tuple[str, str], ...] = ()
    notes: str = ""

    @property
    def live_binding_resolved(self) -> bool:
        identifiers = dict(self.sdk_parameter_identifiers)
        return (
            self.status is MappingStatus.DOCUMENTED_LIBEC
            and self.controller_method is not None
            and self.sdk_entrypoint is not None
            and set(identifiers) == set(self.internal_parameters)
            and all(bool(value) for value in identifiers.values())
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "technique": (
                self.technique.value
                if isinstance(self.technique, Technique)
                else self.technique
            ),
            "controller_method": self.controller_method,
            "public_libec_name": self.public_libec_name,
            "status": self.status.value,
            "internal_parameters": list(self.internal_parameters),
            "sdk_entrypoint": self.sdk_entrypoint,
            "sdk_parameter_identifiers": dict(self.sdk_parameter_identifiers),
            "live_binding_resolved": self.live_binding_resolved,
            "notes": self.notes,
        }


@dataclass(frozen=True)
class IRSDKMapping:
    status: MappingStatus = MappingStatus.VERIFY_INSTALLED_SDK
    measure_ru_entrypoint: str | None = None
    apply_compensation_entrypoint: str | None = None
    readback_entrypoint: str | None = None
    disable_compensation_entrypoint: str | None = None
    cell_off_entrypoint: str | None = None
    mode_parameter_identifier: str | None = None
    resistance_parameter_identifier: str | None = None
    readback_parameter_identifier: str | None = None

    @property
    def live_binding_resolved(self) -> bool:
        values = (
            self.measure_ru_entrypoint,
            self.apply_compensation_entrypoint,
            self.readback_entrypoint,
            self.disable_compensation_entrypoint,
            self.cell_off_entrypoint,
            self.mode_parameter_identifier,
            self.resistance_parameter_identifier,
            self.readback_parameter_identifier,
        )
        return all(bool(value) for value in values)

    def as_dict(self) -> dict[str, object]:
        return {
            "status": self.status.value,
            "measure_ru_entrypoint": self.measure_ru_entrypoint,
            "apply_compensation_entrypoint": self.apply_compensation_entrypoint,
            "readback_entrypoint": self.readback_entrypoint,
            "disable_compensation_entrypoint": self.disable_compensation_entrypoint,
            "cell_off_entrypoint": self.cell_off_entrypoint,
            "mode_parameter_identifier": self.mode_parameter_identifier,
            "resistance_parameter_identifier": self.resistance_parameter_identifier,
            "readback_parameter_identifier": self.readback_parameter_identifier,
            "live_binding_resolved": self.live_binding_resolved,
        }


CHI760E_TECHNIQUE_MAPPINGS: dict[Technique, TechniqueSDKMapping] = {
    Technique.CV: TechniqueSDKMapping(
        Technique.CV, "run_cv", "CV", MappingStatus.DOCUMENTED_LIBEC,
        ("initial_potential", "high_potential", "low_potential", "scan_rate", "cycles"),
    ),
    Technique.IT: TechniqueSDKMapping(
        Technique.IT, "run_it", "i-t", MappingStatus.DOCUMENTED_LIBEC,
        ("potential", "duration", "sample_interval"),
    ),
    Technique.LSV: TechniqueSDKMapping(
        Technique.LSV, "run_lsv", "LSV", MappingStatus.DESKTOP_ONLY,
        ("initial_potential", "final_potential", "scan_rate"),
        notes="The public libec matrix lists LSV for 7xxD, not 7xxE.",
    ),
    Technique.EIS: TechniqueSDKMapping(
        Technique.EIS, "run_eis", "IMP", MappingStatus.DOCUMENTED_LIBEC,
        ("dc_potential", "ac_amplitude", "start_frequency", "end_frequency", "points_per_decade"),
    ),
    Technique.OCP: TechniqueSDKMapping(
        Technique.OCP, "run_ocp", "OCPT", MappingStatus.DOCUMENTED_LIBEC,
        ("duration", "sample_interval"),
    ),
    Technique.CA: TechniqueSDKMapping(
        Technique.CA, "run_ca", "CA", MappingStatus.DOCUMENTED_LIBEC,
        ("steps", "sample_interval_s", "quiet_time_s", "cycles"),
        notes="Chronocoulometry is derived from the returned CA current trace.",
    ),
    Technique.SWV: TechniqueSDKMapping(
        Technique.SWV, "run_swv", "SWV", MappingStatus.DOCUMENTED_LIBEC,
        ("initial_potential_V", "final_potential_V", "increment_V", "amplitude_V", "frequency_Hz", "quiet_time_s"),
    ),
    Technique.IMPE: TechniqueSDKMapping(
        Technique.IMPE, "run_impe", "IMPE", MappingStatus.DOCUMENTED_LIBEC,
        ("initial_potential_V", "final_potential_V", "potential_step_V", "ac_amplitude_V_rms", "frequency_Hz", "quiet_time_s"),
    ),
    Technique.STEP: TechniqueSDKMapping(
        Technique.STEP, "run_step", "STEP", MappingStatus.DOCUMENTED_LIBEC,
        ("steps", "sample_interval_s", "cycles"),
    ),
    Technique.ISTEP: TechniqueSDKMapping(
        Technique.ISTEP, "run_istep", "ISTEP/CPCS", MappingStatus.DOCUMENTED_LIBEC,
        ("steps", "sample_interval_s", "cycles"),
    ),
}

CHI760E_IR_MAPPING = IRSDKMapping()

CHI760E_UNVERIFIED_TECHNIQUE_MAPPINGS: dict[str, TechniqueSDKMapping] = {
    "GEIS": TechniqueSDKMapping(
        "GEIS",
        None,
        "IMP mode to verify",
        MappingStatus.VERIFY_INSTALLED_SDK,
        (
            "initial_frequency_hz",
            "final_frequency_hz",
            "ac_current_a",
            "dc_current_a",
            "points_per_decade",
        ),
        notes=(
            "Galvanostatic EIS is retained as an explicit unresolved mapping; "
            "the installed SDK must establish whether and how IMP exposes it."
        ),
    ),
}

CHI760E_DERIVED_OUTPUTS: dict[str, dict[str, object]] = {
    "chronocoulometry_C": {
        "source_technique": Technique.CA.value,
        "method": "trapezoidal_integral_of_current_over_time",
        "separate_sdk_technique_claimed": False,
    },
    "constant_current_charge": {
        "source_technique": Technique.ISTEP.value,
        "method": "current_step_plus_capacity_integration",
        "separate_sdk_technique_claimed": False,
    },
    "constant_current_discharge": {
        "source_technique": Technique.ISTEP.value,
        "method": "current_step_plus_capacity_integration",
        "separate_sdk_technique_claimed": False,
    },
}


def mapping_for(technique: Technique | str) -> TechniqueSDKMapping:
    if not isinstance(technique, Technique):
        technique = Technique(technique)
    return CHI760E_TECHNIQUE_MAPPINGS[technique]


def unresolved_live_bindings() -> tuple[str, ...]:
    unresolved = [
        f"technique:{technique.value}"
        for technique, mapping in CHI760E_TECHNIQUE_MAPPINGS.items()
        if mapping.status is MappingStatus.DOCUMENTED_LIBEC
        and not mapping.live_binding_resolved
    ]
    unresolved.extend(
        f"technique:{name}"
        for name, mapping in CHI760E_UNVERIFIED_TECHNIQUE_MAPPINGS.items()
        if not mapping.live_binding_resolved
    )
    if not CHI760E_IR_MAPPING.live_binding_resolved:
        unresolved.append("ir_compensation")
    return tuple(unresolved)


def sdk_mapping_manifest() -> dict[str, object]:
    return {
        "schema_version": "0.1",
        "target_model": "760E",
        "source": "public CH Instruments libec 7xxE technique matrix",
        "techniques": {
            technique.value: mapping.as_dict()
            for technique, mapping in CHI760E_TECHNIQUE_MAPPINGS.items()
        },
        "unverified_techniques": {
            name: mapping.as_dict()
            for name, mapping in CHI760E_UNVERIFIED_TECHNIQUE_MAPPINGS.items()
        },
        "derived_outputs": CHI760E_DERIVED_OUTPUTS,
        "optional_rde": {
            "mode": "disk_only_external_controller",
            "sdk_entrypoint": None,
            "measured_rpm_available": False,
        },
        "ir_compensation": CHI760E_IR_MAPPING.as_dict(),
        "unresolved_live_bindings": list(unresolved_live_bindings()),
        "hardware_execution_enabled": False,
    }

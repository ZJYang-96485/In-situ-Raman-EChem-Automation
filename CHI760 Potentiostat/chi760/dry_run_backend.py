"""Zero-hardware CHI 760E backend used to validate the connection boundary."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from .errors import BackendStateError, LiveExecutionUnavailableError
from .ir_compensation import (
    IRCompensationPlan,
    evaluate_compensation_trials,
    ir_plan_parameters,
    validate_ru_measurements,
)
from .profiles import Technique
from .sdk_mapping import CHI760E_IR_MAPPING, mapping_for, sdk_mapping_manifest
from .trace import CommandTrace, json_safe


_EMPTY_RESULT_SERIES: dict[Technique, dict[str, list[float]]] = {
    Technique.CV: {"potential_V": [], "current_A": []},
    Technique.IT: {"time_s": [], "current_A": []},
    Technique.LSV: {"potential_V": [], "current_A": []},
    Technique.EIS: {"frequency_Hz": [], "z_real_ohm": [], "z_imag_ohm": []},
    Technique.OCP: {"time_s": [], "potential_V": []},
    Technique.CA: {"time_s": [], "potential_V": [], "current_A": []},
    Technique.SWV: {
        "potential_V": [],
        "forward_current_A": [],
        "reverse_current_A": [],
        "differential_current_A": [],
    },
    Technique.IMPE: {"potential_V": [], "z_real_ohm": [], "z_imag_ohm": []},
    Technique.STEP: {"time_s": [], "potential_V": [], "current_A": []},
    Technique.ISTEP: {"time_s": [], "current_A": [], "potential_V": []},
}


class DryRunCHI760E:
    """Exercise the future 760E backend contract without loading an SDK.

    ``connect()`` opens only a logical dry-run session. Every result and trace
    explicitly reports that no library was loaded, no device was connected,
    and no hardware call occurred.
    """

    execution_mode = "dry_run"
    hardware_connected = False
    sdk_loaded = False

    def __init__(self, trace: CommandTrace | None = None) -> None:
        self._trace = trace or CommandTrace(execution_mode=self.execution_mode)
        self._logical_session_open = False

    @property
    def hardware_calls(self) -> int:
        return 0

    @property
    def logical_session_open(self) -> bool:
        return self._logical_session_open

    @property
    def trace(self) -> CommandTrace:
        return self._trace

    def connect(self) -> bool:
        if self._logical_session_open:
            raise BackendStateError("dry-run session is already open")
        self._logical_session_open = True
        self._trace.record(
            "connect",
            {},
            {
                "logical_session_open": True,
                "hardware_connected": False,
                "sdk_loaded": False,
                "hardware_calls": 0,
            },
        )
        return True

    def disconnect(self) -> None:
        self._require_open()
        self._trace.record(
            "disconnect",
            {},
            {
                "logical_session_open": False,
                "hardware_connected": False,
                "hardware_calls": 0,
            },
        )
        self._logical_session_open = False

    def run_cv(self, **params: Any) -> dict[str, Any]:
        return self._run(Technique.CV, params)

    def run_it(self, **params: Any) -> dict[str, Any]:
        return self._run(Technique.IT, params)

    def run_lsv(self, **params: Any) -> dict[str, Any]:
        return self._run(Technique.LSV, params)

    def run_eis(self, **params: Any) -> dict[str, Any]:
        return self._run(Technique.EIS, params)

    def run_ocp(self, **params: Any) -> dict[str, Any]:
        return self._run(Technique.OCP, params)

    def run_ca(self, **params: Any) -> dict[str, Any]:
        return self._run(Technique.CA, params)

    def run_swv(self, **params: Any) -> dict[str, Any]:
        return self._run(Technique.SWV, params)

    def run_impe(self, **params: Any) -> dict[str, Any]:
        return self._run(Technique.IMPE, params)

    def run_step(self, **params: Any) -> dict[str, Any]:
        return self._run(Technique.STEP, params)

    def run_istep(self, **params: Any) -> dict[str, Any]:
        return self._run(Technique.ISTEP, params)

    def _run(self, technique: Technique, params: Mapping[str, Any]) -> dict[str, Any]:
        self._require_open()
        mapping = mapping_for(technique)
        if mapping.controller_method is None:
            raise LiveExecutionUnavailableError(
                f"{technique.value} has no controller method mapping"
            )
        result: dict[str, Any] = {
            "technique": mapping.public_libec_name,
            "parameters": json_safe(params),
            "execution_mode": self.execution_mode,
            "hardware_connected": False,
            "hardware_calls": 0,
            "sdk_loaded": False,
            "sdk_entrypoint": mapping.sdk_entrypoint,
            "mapping_status": mapping.status.value,
            "quality_flags": ["dry_run", "no_hardware_io", "sdk_binding_unresolved"],
            **json_safe(_EMPTY_RESULT_SERIES[technique]),
        }
        self._trace.record(
            mapping.controller_method,
            {"parameters": params},
            result,
        )
        return result

    def prepare_ir_compensation(
        self,
        plan: IRCompensationPlan,
        *,
        trial_ru_attempts_ohm: Sequence[Sequence[float | None]],
        observed_fractions: Sequence[float | None],
    ) -> dict[str, Any]:
        self._require_open()
        if not isinstance(plan, IRCompensationPlan):
            raise TypeError("plan must be an IRCompensationPlan")
        if not plan.enabled:
            raise ValueError("cannot prepare iR compensation when the plan is disabled")
        if len(trial_ru_attempts_ohm) != len(observed_fractions):
            raise ValueError("Ru trial data and observed fractions must have equal lengths")
        if not trial_ru_attempts_ohm:
            raise ValueError("at least one iR trial is required")
        if len(trial_ru_attempts_ohm) > plan.max_compensation_trials:
            raise ValueError("iR trial data cannot exceed the 10-trial ceiling")

        trials: list[dict[str, Any]] = []
        effective_fractions: list[float | None] = []
        progress = None
        for index, (attempts, observed_fraction) in enumerate(
            zip(trial_ru_attempts_ohm, observed_fractions),
            start=1,
        ):
            ru = validate_ru_measurements(attempts, plan)
            effective_fraction = observed_fraction if ru.passed else None
            effective_fractions.append(effective_fraction)
            progress = evaluate_compensation_trials(effective_fractions, plan)
            trials.append(
                {
                    "trial": index,
                    "ru": ru,
                    "observed_fraction": effective_fraction,
                    "hardware_applied": False,
                    "readback_source": "provided_dry_run_observation",
                }
            )
            if progress.reached_target or progress.exhausted:
                break
        if progress is None:
            raise ValueError("at least one iR trial is required")

        accepted_trial = progress.accepted_trial_number
        accepted_ru = trials[accepted_trial - 1]["ru"] if accepted_trial else None
        if progress.accepted_fraction is not None:
            state = "planned_not_hardware_applied"
        elif progress.exhausted and plan.continue_without_ir_on_ru_failure:
            state = "planned_uncompensated_fallback"
        elif progress.exhausted:
            state = "blocked"
        else:
            state = "awaiting_next_trial"
        result = {
            "state": state,
            "plan": ir_plan_parameters(plan),
            "progress": progress,
            "trials": trials,
            "accepted_ru_ohm": accepted_ru.selected_ohm if accepted_ru else None,
            "requested_compensation_ohm": (
                accepted_ru.requested_compensation_ohm if accepted_ru else None
            ),
            "mapping": CHI760E_IR_MAPPING.as_dict(),
            "simulation_only": True,
            "hardware_applied": False,
            "hardware_connected": False,
            "hardware_calls": 0,
        }
        self._trace.record(
            "prepare_ir_compensation",
            {
                "plan": plan,
                "trial_ru_attempts_ohm": trial_ru_attempts_ohm,
                "observed_fractions": observed_fractions,
            },
            result,
        )
        return json_safe(result)

    def disable_ir_compensation(self) -> dict[str, Any]:
        self._require_open()
        result = {
            "state": "planned_disabled",
            "hardware_state_changed": False,
            "hardware_connected": False,
            "hardware_calls": 0,
            "sdk_entrypoint": CHI760E_IR_MAPPING.disable_compensation_entrypoint,
        }
        self._trace.record("disable_ir_compensation", {}, result)
        return result

    def cell_off(self) -> dict[str, Any]:
        self._require_open()
        result = {
            "state": "planned_cell_off",
            "hardware_state_changed": False,
            "hardware_connected": False,
            "hardware_calls": 0,
            "sdk_entrypoint": CHI760E_IR_MAPPING.cell_off_entrypoint,
        }
        self._trace.record("cell_off", {}, result)
        return result

    def trace_payload(self) -> dict[str, Any]:
        payload = self._trace.to_payload()
        payload.update(
            {
                "target_model": "760E",
                "sdk_loaded": False,
                "mapping_manifest": sdk_mapping_manifest(),
            }
        )
        return payload

    def request_live_execution(self) -> None:
        raise LiveExecutionUnavailableError(
            "live execution is not implemented; installed-SDK bindings remain unresolved"
        )

    def _require_open(self) -> None:
        if not self._logical_session_open:
            raise BackendStateError("open a dry-run session before requesting operations")

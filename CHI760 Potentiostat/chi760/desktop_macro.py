"""Constrained CHI 760D desktop-macro automation.

This adapter intentionally supports only one short internal-dummy-cell CV.  It
does not accept raw macro text, arbitrary executable paths from the browser, or
external-cell experiments.  The desktop executable is verified against the
audited repository copy before a macro can be prepared or launched.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import math
from pathlib import Path
import secrets
import subprocess
import threading
from typing import Any, Callable, Mapping, Protocol

from .data_store import RunDataStore, RunWriter


CHI760D_APPROVED_SHA256 = (
    "884A32505B8A601A6E6C562323D472511DDEE6882AD06EFC3CEFCDB07C1D3B7D"
)
MAX_DUMMY_ABS_POTENTIAL_V = 0.25
MIN_DUMMY_SCAN_RATE_V_S = 0.01
MAX_DUMMY_SCAN_RATE_V_S = 0.2


class DesktopMacroError(RuntimeError):
    """Raised when the constrained desktop automation cannot proceed safely."""


class ProcessHandle(Protocol):
    pid: int

    def poll(self) -> int | None: ...


ProcessLauncher = Callable[..., ProcessHandle]


def default_chi760d_executable() -> Path:
    """Locate the tracked desktop program without a computer-specific path."""

    return Path(__file__).resolve().parents[1] / "chi760d" / "chi760d.exe"


@dataclass(frozen=True)
class DummyCVPlan:
    protocol_name: str
    initial_v: float
    high_v: float
    low_v: float
    final_v: float
    scan_rate_v_s: float
    step_size_v: float
    cycles: int

    @classmethod
    def from_web_protocol(cls, protocol: Mapping[str, Any]) -> "DummyCVPlan":
        validation = protocol.get("validation")
        if not isinstance(validation, Mapping) or validation.get("valid") is not True:
            raise DesktopMacroError("The browser protocol must pass validation first.")
        name = protocol.get("protocol_name")
        if not isinstance(name, str) or not name.strip() or len(name) > 100:
            raise DesktopMacroError("The protocol name must contain 1-100 characters.")
        steps = protocol.get("steps")
        if not isinstance(steps, list) or len(steps) != 1:
            raise DesktopMacroError("The 760D dummy test requires exactly one CV step.")
        step = steps[0]
        if not isinstance(step, Mapping) or step.get("source_technique") != "cv":
            raise DesktopMacroError("The 760D dummy test supports only a CV step.")
        parameters = step.get("parameters")
        if not isinstance(parameters, Mapping):
            raise DesktopMacroError("The CV parameters are missing.")

        ir = protocol.get("ir_compensation")
        if not isinstance(ir, Mapping) or ir.get("enabled") is not False:
            raise DesktopMacroError("Disable iR compensation for the first 760D dummy test.")
        raman = protocol.get("raman_sync")
        if not isinstance(raman, Mapping) or raman.get("policy") != "none":
            raise DesktopMacroError("Set Raman timing to None for the 760D dummy test.")

        plan = cls(
            protocol_name=name.strip(),
            initial_v=_finite(parameters, "initial_voltage_v"),
            high_v=_finite(parameters, "apex1_voltage_v"),
            low_v=_finite(parameters, "apex2_voltage_v"),
            final_v=_finite(parameters, "final_voltage_v"),
            scan_rate_v_s=_finite(parameters, "scan_rate_v_s"),
            step_size_v=_finite(parameters, "step_size_v"),
            cycles=_integer(parameters, "cycles"),
        )
        plan.validate_bounds()
        return plan

    def validate_bounds(self) -> None:
        potentials = (self.initial_v, self.high_v, self.low_v, self.final_v)
        if any(abs(value) > MAX_DUMMY_ABS_POTENTIAL_V for value in potentials):
            raise DesktopMacroError(
                f"The first dummy test is limited to +/-{MAX_DUMMY_ABS_POTENTIAL_V:g} V."
            )
        if not self.low_v < self.initial_v < self.high_v:
            raise DesktopMacroError(
                "Initial potential must be strictly between the low and high vertices."
            )
        if not math.isclose(self.final_v, self.initial_v, abs_tol=1e-12):
            raise DesktopMacroError(
                "Final and initial potential must match for the bounded 760D CV."
            )
        if not MIN_DUMMY_SCAN_RATE_V_S <= self.scan_rate_v_s <= MAX_DUMMY_SCAN_RATE_V_S:
            raise DesktopMacroError(
                "The first dummy test scan rate must be between 0.01 and 0.2 V/s."
            )
        if not 0.001 <= self.step_size_v <= 0.01:
            raise DesktopMacroError(
                "The first dummy test potential step must be 0.001-0.01 V."
            )
        if self.cycles != 1:
            raise DesktopMacroError("The first 760D dummy test is limited to one cycle.")

    def public_summary(self) -> dict[str, Any]:
        return {
            "technique": "CV",
            "cell": "internal_dummy",
            "initial_v": self.initial_v,
            "high_v": self.high_v,
            "low_v": self.low_v,
            "final_v": self.final_v,
            "scan_rate_v_s": self.scan_rate_v_s,
            "step_size_v": self.step_size_v,
            "cycles": self.cycles,
        }


@dataclass
class PreparedDummyRun:
    token: str
    plan: DummyCVPlan
    writer: RunWriter
    macro_path: Path
    text_output: Path
    binary_output: Path
    prepared_at: datetime


class CHI760DDesktopController:
    """Prepare and launch a single allowlisted CHI 760D internal-dummy CV."""

    def __init__(
        self,
        executable: str | Path | None = None,
        *,
        execution_enabled: bool = False,
        expected_sha256: str = CHI760D_APPROVED_SHA256,
        process_launcher: ProcessLauncher = subprocess.Popen,
    ) -> None:
        self.executable = Path(executable or default_chi760d_executable())
        self.execution_enabled = execution_enabled
        self.expected_sha256 = expected_sha256.upper()
        self.process_launcher = process_launcher
        self.hardware_calls = 0
        self._prepared: dict[str, PreparedDummyRun] = {}
        self._active: tuple[PreparedDummyRun, ProcessHandle] | None = None
        self._lock = threading.Lock()

    def public_status(self) -> dict[str, Any]:
        verified, blocker = self._verify_executable()
        active = self._active_status()
        return {
            "target": "CHI 760D desktop",
            "state": (
                "running_internal_dummy"
                if active is not None and active["running"]
                else "ready_for_internal_dummy"
                if verified and self.execution_enabled
                else "execution_locked"
                if verified
                else "adapter_unavailable"
            ),
            "executable_verified": verified,
            "experiment_control_enabled": verified and self.execution_enabled,
            "scope": "internal_dummy_cv_only",
            "remote_stop_available": False,
            "hardware_calls": self.hardware_calls,
            "blocker": blocker
            or (
                None
                if self.execution_enabled
                else "Start the dedicated 760D launcher to enable the internal-dummy test."
            ),
            "active": active,
        }

    def prepare(
        self, protocol: Mapping[str, Any], data_root: str | Path
    ) -> dict[str, Any]:
        verified, blocker = self._verify_executable()
        if not verified:
            raise DesktopMacroError(blocker or "The CHI 760D executable is not verified.")
        root = Path(data_root)
        if not root.is_absolute() or not root.is_dir():
            raise DesktopMacroError("Choose an available storage folder first.")
        plan = DummyCVPlan.from_web_protocol(protocol)
        with self._lock:
            if self._prepared:
                raise DesktopMacroError(
                    "An unused 760D preparation already exists; restart the bridge to discard it."
                )
            if self._active is not None and self._active[1].poll() is None:
                raise DesktopMacroError("A CHI 760D desktop run is already active.")
            store = RunDataStore(root)
            store.ensure_layout()
            writer = store.create_run()
            writer.write_protocol_once(dict(protocol))
            macro_path = writer.paths.directory / "chi760d_internal_dummy_cv.mcr"
            text_output = writer.paths.directory / "chi760d_internal_dummy_cv.txt"
            binary_output = writer.paths.directory / "chi760d_internal_dummy_cv.bin"
            macro = render_dummy_cv_macro(plan, writer.paths.directory)
            with macro_path.open("x", encoding="ascii", newline="\r\n") as stream:
                stream.write(macro)
            token = secrets.token_urlsafe(24)
            prepared = PreparedDummyRun(
                token=token,
                plan=plan,
                writer=writer,
                macro_path=macro_path,
                text_output=text_output,
                binary_output=binary_output,
                prepared_at=datetime.now(timezone.utc),
            )
            self._prepared[token] = prepared
        return {
            "preparation_token": token,
            "run_label": writer.paths.directory.name,
            "macro_sha256": _sha256(macro_path),
            "summary": plan.public_summary(),
            "requires_local_approval": True,
            "remote_stop_available": False,
        }

    def execute(self, preparation_token: str) -> dict[str, Any]:
        if not self.execution_enabled:
            raise DesktopMacroError("CHI 760D experiment execution is locked.")
        verified, blocker = self._verify_executable()
        if not verified:
            raise DesktopMacroError(blocker or "The CHI 760D executable is not verified.")
        with self._lock:
            prepared = self._prepared.pop(preparation_token, None)
            if prepared is None:
                raise DesktopMacroError("The prepared 760D run is missing or already used.")
            if self._active is not None and self._active[1].poll() is None:
                self._prepared[preparation_token] = prepared
                raise DesktopMacroError("A CHI 760D desktop run is already active.")
            try:
                process = self.process_launcher(
                    [str(self.executable), f"/runmacro:{prepared.macro_path}"],
                    cwd=str(self.executable.parent),
                    shell=False,
                )
            except OSError as error:
                self._prepared[preparation_token] = prepared
                raise DesktopMacroError(
                    "Windows could not start the verified CHI 760D desktop program."
                ) from error
            self.hardware_calls += 1
            self._active = (prepared, process)
        started_at = datetime.now(timezone.utc).isoformat()
        prepared.writer.write_metadata(
            {
                "started_at": started_at,
                "units": {"potential": "V", "scan_rate": "V/s"},
                "technique": "CV",
                "parameters": prepared.plan.public_summary(),
                "software_version": "SpectraLoop-CHI760D-macro-0.1",
                "chi_identity": {
                    "model": "CHI 760D",
                    "verification": "approved_desktop_executable",
                },
                "state": "running",
            }
        )
        prepared.writer.append_instrument_trace(
            {
                "operation": "launch_approved_chi760d_macro",
                "started_at": started_at,
                "scope": "internal_dummy_cv_only",
                "remote_stop_available": False,
            }
        )
        return {
            "started": True,
            "run_label": prepared.writer.paths.directory.name,
            "summary": prepared.plan.public_summary(),
            "remote_stop_available": False,
            "operator_instruction": "Keep the CHI window visible; use its Stop button if needed.",
        }

    def preparation_summary(self, preparation_token: str) -> dict[str, Any]:
        """Return a path-free summary for the local approval dialog."""

        with self._lock:
            prepared = self._prepared.get(preparation_token)
            if prepared is None:
                raise DesktopMacroError("The prepared 760D run is missing or already used.")
            return prepared.plan.public_summary()

    def _active_status(self) -> dict[str, Any] | None:
        with self._lock:
            if self._active is None:
                return None
            prepared, process = self._active
            return_code = process.poll()
            return {
                "run_label": prepared.writer.paths.directory.name,
                "running": return_code is None,
                "process_return_code": return_code,
                "text_output_detected": prepared.text_output.is_file(),
                "binary_output_detected": prepared.binary_output.is_file(),
            }

    def _verify_executable(self) -> tuple[bool, str | None]:
        if not self.executable.is_file():
            return False, "The repository-relative CHI 760D executable is missing."
        try:
            actual = _sha256(self.executable)
        except OSError:
            return False, "The CHI 760D executable cannot be read."
        if actual.upper() != self.expected_sha256:
            return False, "The CHI 760D executable hash does not match the audited v23.01 copy."
        return True, None


def render_dummy_cv_macro(plan: DummyCVPlan, run_directory: Path) -> str:
    """Render only documented CHI commands from typed values."""

    directory = run_directory.resolve()
    text = str(directory)
    if any(character in text for character in "\r\n;#"):
        raise DesktopMacroError("The selected data path contains a macro control character.")
    direction = "p" if plan.high_v - plan.initial_v <= plan.initial_v - plan.low_v else "n"
    lines = [
        "; SpectraLoop generated: CHI 760D internal dummy CV only",
        f"folder:{text}",
        "dummyon",
        "celloff",
        "abortov",
        "tech:cv",
        f"ei:{_number(plan.initial_v)}",
        f"eh:{_number(plan.high_v)}",
        f"el:{_number(plan.low_v)}",
        f"pn:{direction}",
        f"v:{_number(plan.scan_rate_v_s)}",
        "cl:2",
        f"si:{_number(plan.step_size_v)}",
        "qt:1",
        "autosens",
        "run",
        "save:chi760d_internal_dummy_cv.bin",
        "tsave:chi760d_internal_dummy_cv.txt",
        "celloff",
        "dummyoff",
        "beep",
        "end",
    ]
    return "\n".join(lines) + "\n"


def _number(value: float) -> str:
    return format(value, ".12g")


def _finite(parameters: Mapping[str, Any], key: str) -> float:
    value = parameters.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise DesktopMacroError(f"{key} must be numeric.")
    converted = float(value)
    if not math.isfinite(converted):
        raise DesktopMacroError(f"{key} must be finite.")
    return converted


def _integer(parameters: Mapping[str, Any], key: str) -> int:
    value = parameters.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise DesktopMacroError(f"{key} must be an integer.")
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()

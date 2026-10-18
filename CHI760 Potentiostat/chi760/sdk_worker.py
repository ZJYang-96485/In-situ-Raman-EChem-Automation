"""Isolated 32-bit preflight process for the legacy CHI libec runtime.

This module is deliberately executable as a standalone script. The Python
embeddable distribution can therefore run it without importing the rest of the
project. ``status`` only parses files. ``load-check`` loads the DLL but never
calls a vendor function. ``serve`` keeps a private stdin/stdout JSON session
alive for the local SpectraLoop bridge. Commissioning commands exist only
behind an explicit process-start flag and a second set of local confirmations.
"""

from __future__ import annotations

import argparse
import ctypes
from hashlib import sha256
import json
import os
from pathlib import Path
import struct
import sys
import threading
from time import monotonic, sleep
from typing import Any
from uuid import uuid4


SCHEMA_VERSION = "0.1"
MAX_REQUEST_BYTES = 64 * 1024
REQUIRED_RUNTIME_DLLS = (
    "QtCore4.dll",
    "QtGui4.dll",
    "QtSvg4.dll",
    "QtXml4.dll",
)
REQUIRED_DISCOVERY_EXPORTS = (
    "CHI_getModelSeries",
    "CHI_getErrorStatus",
    "CHI_hasTechnique",
    "CHI_hasParameter",
)
REQUIRED_COMMISSIONING_EXPORTS = REQUIRED_DISCOVERY_EXPORTS + (
    "CHI_setTechnique",
    "CHI_getTechnique",
    "CHI_setParameter",
    "CHI_getParameter",
    "CHI_runExperiment",
    "CHI_experimentIsRunning",
    "CHI_getExperimentDataAndReturnWriteCount",
    "CHI_Stop",
)
TECHNIQUE_IDS = {
    "CV": 0,
    "LSV": 1,
    "SCV": 2,
    "TAFEL": 3,
    "CA": 4,
    "CC": 5,
    "DPV": 6,
    "NPV": 7,
    "SWV": 8,
    "ACV": 9,
    "SHACV": 10,
    "IT": 11,
    "BE": 12,
    "HMV": 13,
    "IMP": 14,
    "CP": 15,
    "PSA": 16,
    "IMPT": 17,
    "DPA": 18,
    "TPA": 19,
    "DDPA": 20,
    "CPCR": 21,
    "DNPV": 22,
    "SECM": 23,
    "PAC": 24,
    "PSC": 25,
    "OCPT": 26,
    "SSF": 27,
    "IMPE": 28,
    "STEP": 29,
    "QCM": 30,
    "SSTEP": 31,
    "CPCS": 32,
    "IPAD": 33,
    "SPC": 34,
    "SWG": 35,
    "SONIC": 36,
    "ECN": 37,
    "SMPL": 38,
    "SISECM": 39,
    "LVDT": 40,
    "FTACV": 41,
    "ZCCC": 42,
    "ICHRG": 43,
    "ACTB": 44,
}
CV_DRY_RUN_PARAMETERS = {
    "m_ei": 0.0,
    "m_eh": 0.2,
    "m_el": -0.2,
    "m_pn": 1.0,
    "m_vv": 0.05,
    "m_inpcl": 2.0,
    "m_inpsi": 0.002,
    "m_qt": 0.0,
}
CV_COMMISSIONING_LIMITS = {
    "potential_abs_max_v": 0.25,
    "scan_rate_min_v_s": 0.01,
    "scan_rate_max_v_s": 0.2,
    "potential_step_min_v": 0.001,
    "potential_step_max_v": 0.01,
    "quiet_time_max_s": 10.0,
    "sweep_segments": 2,
    "data_capacity": 65_535,
    "timeout_s": 180.0,
}
CV_COMMISSIONING_CONFIRMATIONS = (
    "commissioning_approved",
    "target_is_760e",
    "no_other_chi_measurement_running",
    "chi_desktop_closed",
    "internal_dummy_cell_connected",
    "external_sample_disconnected",
    "electrode_leads_verified",
    "cell_output_confirmed_off",
)
CV_COMMISSIONING_PLAN_FIELDS = (
    "target_model",
    "initial_potential_v",
    "high_potential_v",
    "low_potential_v",
    "initial_scan_direction",
    "scan_rate_v_s",
    "potential_step_v",
    "quiet_time_s",
    "sweep_segments",
)


def validate_cv_commissioning_plan(plan: Any) -> dict[str, Any]:
    """Normalize the one deliberately small CV supported for commissioning."""

    if not isinstance(plan, dict):
        raise ValueError("CV commissioning plan must be an object")
    unknown = sorted(set(plan) - set(CV_COMMISSIONING_PLAN_FIELDS))
    missing = sorted(set(CV_COMMISSIONING_PLAN_FIELDS) - set(plan))
    if unknown:
        raise ValueError(f"unsupported CV commissioning fields: {', '.join(unknown)}")
    if missing:
        raise ValueError(f"missing CV commissioning fields: {', '.join(missing)}")
    if plan["target_model"] != "760E":
        raise ValueError("CV commissioning target_model must be 760E")
    if plan["initial_scan_direction"] != "positive":
        raise ValueError("the first commissioning CV must use a positive initial scan")

    normalized: dict[str, Any] = {
        "target_model": "760E",
        "initial_scan_direction": "positive",
    }
    for name in (
        "initial_potential_v",
        "high_potential_v",
        "low_potential_v",
        "scan_rate_v_s",
        "potential_step_v",
        "quiet_time_s",
    ):
        normalized[name] = _finite_number(plan[name], name)
    segments = plan["sweep_segments"]
    if isinstance(segments, bool) or not isinstance(segments, int):
        raise ValueError("sweep_segments must be an integer")
    if segments != CV_COMMISSIONING_LIMITS["sweep_segments"]:
        raise ValueError("the first commissioning CV must use exactly two sweeps")
    normalized["sweep_segments"] = segments

    potential_limit = CV_COMMISSIONING_LIMITS["potential_abs_max_v"]
    for name in (
        "initial_potential_v",
        "high_potential_v",
        "low_potential_v",
    ):
        if abs(normalized[name]) > potential_limit:
            raise ValueError(f"{name} must stay within +/-{potential_limit} V")
    if not (
        normalized["low_potential_v"]
        < normalized["initial_potential_v"]
        < normalized["high_potential_v"]
    ):
        raise ValueError("initial potential must be strictly between low and high")
    if not (
        CV_COMMISSIONING_LIMITS["scan_rate_min_v_s"]
        <= normalized["scan_rate_v_s"]
        <= CV_COMMISSIONING_LIMITS["scan_rate_max_v_s"]
    ):
        raise ValueError("scan_rate_v_s is outside the commissioning range")
    if not (
        CV_COMMISSIONING_LIMITS["potential_step_min_v"]
        <= normalized["potential_step_v"]
        <= CV_COMMISSIONING_LIMITS["potential_step_max_v"]
    ):
        raise ValueError("potential_step_v is outside the commissioning range")
    if not 0.0 <= normalized["quiet_time_s"] <= CV_COMMISSIONING_LIMITS["quiet_time_max_s"]:
        raise ValueError("quiet_time_s is outside the commissioning range")
    return normalized


def cv_plan_to_sdk_parameters(plan: Any) -> dict[str, float]:
    """Map a validated plan to the properties listed by the vendor TestSDK."""

    normalized = validate_cv_commissioning_plan(plan)
    return {
        "m_ei": normalized["initial_potential_v"],
        "m_eh": normalized["high_potential_v"],
        "m_el": normalized["low_potential_v"],
        "m_pn": 1.0,
        "m_vv": normalized["scan_rate_v_s"],
        "m_inpcl": float(normalized["sweep_segments"]),
        "m_inpsi": normalized["potential_step_v"],
        "m_qt": normalized["quiet_time_s"],
    }


def _finite_number(value: Any, name: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a finite number")
    try:
        number = float(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{name} must be a finite number") from error
    if not (-float("inf") < number < float("inf")):
        raise ValueError(f"{name} must be a finite number")
    return number


def inspect_runtime(
    sdk_directory: str | Path,
    runtime_directory: str | Path,
    *,
    dll_name: str = "libec760e.dll",
) -> dict[str, Any]:
    """Inspect the worker and SDK without loading a library."""

    sdk_dir = Path(sdk_directory).expanduser().resolve(strict=False)
    runtime_dir = Path(runtime_directory).expanduser().resolve(strict=False)
    library = sdk_dir / dll_name
    runtime_files = {
        name: (runtime_dir / name).is_file() for name in REQUIRED_RUNTIME_DLLS
    }
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "operation": "status",
        "process_bitness": struct.calcsize("P") * 8,
        "platform": sys.platform,
        "sdk_directory_exists": sdk_dir.is_dir(),
        "runtime_directory_exists": runtime_dir.is_dir(),
        "library_exists": library.is_file(),
        "library_path": str(library),
        "runtime_files": runtime_files,
        "required_exports": list(REQUIRED_DISCOVERY_EXPORTS),
        "missing_exports": list(REQUIRED_DISCOVERY_EXPORTS),
        "required_commissioning_exports": list(REQUIRED_COMMISSIONING_EXPORTS),
        "missing_commissioning_exports": list(REQUIRED_COMMISSIONING_EXPORTS),
        "library_architecture": None,
        "library_bitness": None,
        "library_sha256": None,
        "ready_to_load": False,
        "library_loaded": False,
        "vendor_functions_called": 0,
        "device_contacted": False,
        "experiments_enabled": False,
        "error": None,
    }
    if not library.is_file():
        payload["error"] = "CHI SDK DLL is missing"
        return payload
    try:
        data = library.read_bytes()
        architecture, bitness, exports = _inspect_pe_bytes(data)
    except (OSError, ValueError, struct.error) as error:
        payload["error"] = f"Cannot inspect CHI SDK DLL: {error}"
        return payload
    missing = [name for name in REQUIRED_DISCOVERY_EXPORTS if name not in exports]
    missing_commissioning = [
        name for name in REQUIRED_COMMISSIONING_EXPORTS if name not in exports
    ]
    payload.update(
        {
            "library_architecture": architecture,
            "library_bitness": bitness,
            "library_sha256": sha256(data).hexdigest(),
            "missing_exports": missing,
            "missing_commissioning_exports": missing_commissioning,
        }
    )
    problems: list[str] = []
    if payload["process_bitness"] != 32:
        problems.append("worker process is not 32-bit")
    if architecture != "x86" or bitness != 32:
        problems.append("CHI SDK DLL is not 32-bit x86")
    missing_runtime = [name for name, present in runtime_files.items() if not present]
    if missing_runtime:
        problems.append(f"missing runtime DLLs: {', '.join(missing_runtime)}")
    if missing:
        problems.append(f"missing required exports: {', '.join(missing)}")
    payload["ready_to_load"] = not problems
    payload["error"] = "; ".join(problems) if problems else None
    return payload


def load_check(
    sdk_directory: str | Path,
    runtime_directory: str | Path,
    *,
    dll_name: str = "libec760e.dll",
) -> dict[str, Any]:
    """Load the SDK and resolve symbols without calling any vendor function."""

    payload = inspect_runtime(sdk_directory, runtime_directory, dll_name=dll_name)
    payload["operation"] = "load_check"
    if not payload["ready_to_load"]:
        return payload
    if os.name != "nt":
        payload["error"] = "DLL loading is available only on Windows"
        payload["ready_to_load"] = False
        return payload

    library_path = Path(str(payload["library_path"]))
    sdk_dir = library_path.parent
    runtime_dir = Path(runtime_directory).expanduser().resolve(strict=True)
    search_handles = []
    try:
        search_handles.append(os.add_dll_directory(str(runtime_dir)))
        if sdk_dir != runtime_dir:
            search_handles.append(os.add_dll_directory(str(sdk_dir)))
        library = ctypes.CDLL(str(library_path))
        unresolved = [
            name for name in REQUIRED_DISCOVERY_EXPORTS if not hasattr(library, name)
        ]
        payload["library_loaded"] = True
        payload["missing_exports_after_load"] = unresolved
        if unresolved:
            payload["error"] = (
                "required exports did not resolve after loading: "
                + ", ".join(unresolved)
            )
    except (OSError, AttributeError) as error:
        payload["error"] = f"SDK load check failed: {error}"
    finally:
        for handle in reversed(search_handles):
            handle.close()
    return payload


def read_identity_and_capabilities(
    sdk_directory: str | Path,
    runtime_directory: str | Path,
    *,
    dll_name: str = "libec760e.dll",
) -> dict[str, Any]:
    """Call only documented getter functions; never run or configure a test."""

    payload = inspect_runtime(sdk_directory, runtime_directory, dll_name=dll_name)
    payload["operation"] = "read_identity_and_capabilities"
    payload["physical_connection_confirmed"] = False
    payload["serial_number"] = None
    payload["firmware_version"] = None
    if not payload["ready_to_load"]:
        return payload
    if os.name != "nt":
        payload["error"] = "CHI discovery is available only on Windows"
        return payload

    library_path = Path(str(payload["library_path"]))
    sdk_dir = library_path.parent
    runtime_dir = Path(runtime_directory).expanduser().resolve(strict=True)
    search_handles = []
    try:
        search_handles.append(os.add_dll_directory(str(runtime_dir)))
        if sdk_dir != runtime_dir:
            search_handles.append(os.add_dll_directory(str(sdk_dir)))
        library = ctypes.CDLL(str(library_path))
        payload["library_loaded"] = True

        get_model = library.CHI_getModelSeries
        get_model.argtypes = [ctypes.POINTER(ctypes.c_char)]
        get_model.restype = None
        has_technique = library.CHI_hasTechnique
        has_technique.argtypes = [ctypes.c_int]
        has_technique.restype = ctypes.c_bool
        get_error = library.CHI_getErrorStatus
        get_error.argtypes = [ctypes.POINTER(ctypes.c_char), ctypes.c_int]
        get_error.restype = None

        model_buffer = ctypes.create_string_buffer(10)
        payload["vendor_functions_called"] += 1
        get_model(model_buffer)
        model = model_buffer.value.decode("ascii", errors="replace").strip()

        supported = []
        for name, identifier in TECHNIQUE_IDS.items():
            payload["vendor_functions_called"] += 1
            if bool(has_technique(identifier)):
                supported.append({"name": name, "id": identifier})

        error_buffer = ctypes.create_string_buffer(1024)
        payload["vendor_functions_called"] += 1
        get_error(error_buffer, len(error_buffer))
        error_status = error_buffer.value.decode("utf-8", errors="replace").strip()

        payload.update(
            {
                "reported_model_series": model or None,
                "supported_techniques": supported,
                "vendor_error_status": error_status or None,
                "device_contacted": None,
                "note": (
                    "The supplied SDK exposes no serial-number or firmware getter. "
                    "These results describe the loaded model-specific SDK and do not "
                    "by themselves prove physical instrument identity."
                ),
            }
        )
        if not model:
            payload["error"] = "CHI_getModelSeries returned an empty value"
    except (OSError, AttributeError, ValueError) as error:
        payload["error"] = f"Read-only CHI discovery failed: {error}"
    finally:
        for handle in reversed(search_handles):
            handle.close()
    return payload


def run_sdk_dry_run(
    sdk_directory: str | Path,
    runtime_directory: str | Path,
    *,
    dll_name: str = "libec760e.dll",
    timeout_s: float = 5.0,
    physical_hardware_available: bool = False,
) -> dict[str, Any]:
    """Exercise the CV execution pipeline only after dry-run readback succeeds."""

    payload = inspect_runtime(sdk_directory, runtime_directory, dll_name=dll_name)
    payload.update(
        {
            "operation": "sdk_dry_run",
            "dry_run_requested": True,
            "dry_run_readback": None,
            "cell_on_readback": None,
            "run_returned": None,
            "data_points_returned": None,
            "stop_called": False,
            "physical_hardware_available": physical_hardware_available,
            "device_contact_attempted": False,
            "physical_connection_confirmed": False,
            "parameter_readbacks": {},
        }
    )
    if not payload["ready_to_load"]:
        return payload
    if os.name != "nt":
        payload["error"] = "CHI SDK dry-run is available only on Windows"
        return payload

    library_path = Path(str(payload["library_path"]))
    sdk_dir = library_path.parent
    runtime_dir = Path(runtime_directory).expanduser().resolve(strict=True)
    search_handles = []
    try:
        search_handles.append(os.add_dll_directory(str(runtime_dir)))
        if sdk_dir != runtime_dir:
            search_handles.append(os.add_dll_directory(str(sdk_dir)))
        library = ctypes.CDLL(str(library_path))
        payload["library_loaded"] = True

        set_technique = library.CHI_setTechnique
        set_technique.argtypes = [ctypes.c_int]
        set_technique.restype = None
        get_technique = library.CHI_getTechnique
        get_technique.argtypes = []
        get_technique.restype = ctypes.c_int
        has_parameter = library.CHI_hasParameter
        has_parameter.argtypes = [ctypes.c_char_p]
        has_parameter.restype = ctypes.c_bool
        set_parameter = library.CHI_setParameter
        set_parameter.argtypes = [ctypes.c_char_p, ctypes.c_float]
        set_parameter.restype = None
        get_parameter = library.CHI_getParameter
        get_parameter.argtypes = [ctypes.c_char_p]
        get_parameter.restype = ctypes.c_float
        run_experiment = library.CHI_runExperiment
        run_experiment.argtypes = []
        run_experiment.restype = ctypes.c_bool
        is_running = library.CHI_experimentIsRunning
        is_running.argtypes = []
        is_running.restype = ctypes.c_bool
        get_data = library.CHI_getExperimentDataAndReturnWriteCount
        get_data.argtypes = [
            ctypes.POINTER(ctypes.c_float),
            ctypes.POINTER(ctypes.c_float),
            ctypes.c_int,
        ]
        get_data.restype = ctypes.c_int
        stop = library.CHI_Stop
        stop.argtypes = []
        stop.restype = None
        get_error = library.CHI_getErrorStatus
        get_error.argtypes = [ctypes.POINTER(ctypes.c_char), ctypes.c_int]
        get_error.restype = None

        payload["vendor_functions_called"] += 1
        set_technique(TECHNIQUE_IDS["CV"])
        payload["vendor_functions_called"] += 1
        selected_technique = int(get_technique())
        payload["selected_technique"] = selected_technique
        if selected_technique != TECHNIQUE_IDS["CV"]:
            raise ValueError("CV technique readback did not match the request")

        for safety_identifier in (b"m_bDryRun", b"m_bCellOn"):
            payload["vendor_functions_called"] += 1
            if not bool(has_parameter(safety_identifier)):
                raise ValueError(
                    "required safety parameter is unavailable: "
                    f"{safety_identifier.decode()}"
                )

        payload["vendor_functions_called"] += 1
        set_parameter(b"m_bDryRun", ctypes.c_float(1.0))
        payload["vendor_functions_called"] += 1
        dry_run_readback = float(get_parameter(b"m_bDryRun"))
        payload["dry_run_readback"] = dry_run_readback
        if dry_run_readback < 0.5:
            raise ValueError("m_bDryRun did not read back as enabled")

        payload["vendor_functions_called"] += 1
        set_parameter(b"m_bCellOn", ctypes.c_float(0.0))
        payload["vendor_functions_called"] += 1
        cell_on_readback = float(get_parameter(b"m_bCellOn"))
        payload["cell_on_readback"] = cell_on_readback
        if cell_on_readback >= 0.5:
            raise ValueError("m_bCellOn did not read back as disabled")

        parameter_readbacks: dict[str, float] = {}
        for parameter_name, requested in CV_DRY_RUN_PARAMETERS.items():
            encoded = parameter_name.encode("ascii")
            payload["vendor_functions_called"] += 1
            if not bool(has_parameter(encoded)):
                raise ValueError(
                    f"required CV parameter is unavailable: {parameter_name}"
                )
            payload["vendor_functions_called"] += 1
            set_parameter(encoded, ctypes.c_float(requested))
            payload["vendor_functions_called"] += 1
            readback = float(get_parameter(encoded))
            parameter_readbacks[parameter_name] = readback
            tolerance = max(1e-6, abs(requested) * 1e-5)
            if abs(readback - requested) > tolerance:
                raise ValueError(
                    f"CV parameter readback mismatch for {parameter_name}: "
                    f"requested {requested}, received {readback}"
                )
        payload["parameter_readbacks"] = parameter_readbacks

        payload["vendor_functions_called"] += 1
        payload["device_contact_attempted"] = True
        payload["run_returned"] = bool(run_experiment())
        payload["device_contacted"] = bool(
            physical_hardware_available and payload["run_returned"]
        )
        payload["physical_connection_confirmed"] = payload["device_contacted"]
        deadline = monotonic() + timeout_s
        while True:
            payload["vendor_functions_called"] += 1
            running = bool(is_running())
            if not running:
                break
            if monotonic() >= deadline:
                raise TimeoutError("SDK dry-run did not finish before timeout")
            sleep(0.05)

        capacity = 256
        x_values = (ctypes.c_float * capacity)()
        y_values = (ctypes.c_float * capacity)()
        payload["vendor_functions_called"] += 1
        payload["data_points_returned"] = int(
            get_data(x_values, y_values, capacity)
        )

        payload["vendor_functions_called"] += 1
        stop()
        payload["stop_called"] = True
        cleanup_deadline = monotonic() + 1.0
        while monotonic() < cleanup_deadline:
            payload["vendor_functions_called"] += 1
            if not bool(is_running()):
                break
            sleep(0.05)
        sleep(0.25)

        error_buffer = ctypes.create_string_buffer(1024)
        payload["vendor_functions_called"] += 1
        get_error(error_buffer, len(error_buffer))
        error_status = error_buffer.value.decode("utf-8", errors="replace").strip()
        payload["vendor_error_status"] = error_status or None
        if payload["run_returned"] is not True:
            payload["dry_run_completed"] = False
            payload["error"] = (
                "CHI SDK dry-run was rejected"
                + (f": {error_status}" if error_status else "")
            )
        else:
            payload["dry_run_completed"] = True
    except (OSError, AttributeError, TimeoutError, ValueError) as error:
        payload["error"] = f"CHI SDK dry-run failed: {error}"
    finally:
        for handle in reversed(search_handles):
            handle.close()
    return payload


class LiveCVRunner:
    """Run one documented, bounded CV when the worker is explicitly unlocked."""

    def __init__(
        self,
        sdk_directory: str | Path,
        runtime_directory: str | Path,
        *,
        dll_name: str = "libec760e.dll",
    ) -> None:
        self.sdk_directory = sdk_directory
        self.runtime_directory = runtime_directory
        self.dll_name = dll_name
        self._lock = threading.Lock()
        self._stop_function: Any = None
        self._abort_requested = threading.Event()
        self._active = False

    def reset_stop(self) -> None:
        """Prepare a new job without losing a stop requested after it starts."""

        with self._lock:
            if self._active:
                raise RuntimeError("a CHI commissioning run is already active")
            self._abort_requested.clear()

    def run(self, plan: Any) -> dict[str, Any]:
        normalized = validate_cv_commissioning_plan(plan)
        sdk_parameters = cv_plan_to_sdk_parameters(normalized)
        preflight = inspect_runtime(
            self.sdk_directory,
            self.runtime_directory,
            dll_name=self.dll_name,
        )
        if not preflight["ready_to_load"]:
            raise RuntimeError(str(preflight.get("error") or "CHI SDK preflight failed"))
        missing_exports = preflight.get("missing_commissioning_exports")
        if missing_exports:
            raise RuntimeError(
                "CHI SDK is missing commissioning exports: "
                + ", ".join(str(name) for name in missing_exports)
            )
        if os.name != "nt":
            raise RuntimeError("live CHI commissioning is available only on Windows")
        with self._lock:
            if self._active:
                raise RuntimeError("a CHI commissioning run is already active")
            self._active = True
            self._stop_function = None

        library_path = Path(str(preflight["library_path"]))
        sdk_dir = library_path.parent
        runtime_dir = Path(self.runtime_directory).expanduser().resolve(strict=True)
        search_handles = []
        payload: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "operation": "760e_cv_commissioning",
            "target_model": "760E",
            "plan": normalized,
            "sdk_parameters": sdk_parameters,
            "vendor_functions_called": 0,
            "run_returned": None,
            "stop_called": False,
            "cell_on_parameter_readback_after_cleanup": None,
            "data_points": 0,
            "x_values": [],
            "y_values": [],
            "units": {"x": "V", "y": "A"},
            "vendor_error_status": None,
        }
        set_parameter: Any = None
        get_parameter: Any = None
        stop: Any = None
        cleanup_errors: list[str] = []
        try:
            search_handles.append(os.add_dll_directory(str(runtime_dir)))
            if sdk_dir != runtime_dir:
                search_handles.append(os.add_dll_directory(str(sdk_dir)))
            library = ctypes.CDLL(str(library_path))

            get_model = library.CHI_getModelSeries
            get_model.argtypes = [ctypes.POINTER(ctypes.c_char)]
            get_model.restype = None
            set_technique = library.CHI_setTechnique
            set_technique.argtypes = [ctypes.c_int]
            set_technique.restype = None
            get_technique = library.CHI_getTechnique
            get_technique.argtypes = []
            get_technique.restype = ctypes.c_int
            has_parameter = library.CHI_hasParameter
            has_parameter.argtypes = [ctypes.c_char_p]
            has_parameter.restype = ctypes.c_bool
            set_parameter = library.CHI_setParameter
            set_parameter.argtypes = [ctypes.c_char_p, ctypes.c_float]
            set_parameter.restype = None
            get_parameter = library.CHI_getParameter
            get_parameter.argtypes = [ctypes.c_char_p]
            get_parameter.restype = ctypes.c_float
            run_experiment = library.CHI_runExperiment
            run_experiment.argtypes = []
            run_experiment.restype = ctypes.c_bool
            is_running = library.CHI_experimentIsRunning
            is_running.argtypes = []
            is_running.restype = ctypes.c_bool
            get_data = library.CHI_getExperimentDataAndReturnWriteCount
            get_data.argtypes = [
                ctypes.POINTER(ctypes.c_float),
                ctypes.POINTER(ctypes.c_float),
                ctypes.c_int,
            ]
            get_data.restype = ctypes.c_int
            stop = library.CHI_Stop
            stop.argtypes = []
            stop.restype = None
            get_error = library.CHI_getErrorStatus
            get_error.argtypes = [ctypes.POINTER(ctypes.c_char), ctypes.c_int]
            get_error.restype = None
            with self._lock:
                self._stop_function = stop

            model_buffer = ctypes.create_string_buffer(10)
            payload["vendor_functions_called"] += 1
            get_model(model_buffer)
            model = model_buffer.value.decode("ascii", errors="replace").strip()
            payload["reported_model_series"] = model or None
            if model.upper() != "760E":
                raise RuntimeError(
                    f"loaded SDK reported {model or 'no model'} instead of 760E"
                )

            payload["vendor_functions_called"] += 1
            set_technique(TECHNIQUE_IDS["CV"])
            payload["vendor_functions_called"] += 1
            if int(get_technique()) != TECHNIQUE_IDS["CV"]:
                raise RuntimeError("CV technique readback did not match the request")

            required_parameters = ("m_bDryRun", "m_bCellOn", *sdk_parameters)
            for parameter_name in required_parameters:
                payload["vendor_functions_called"] += 1
                if not bool(has_parameter(parameter_name.encode("ascii"))):
                    raise RuntimeError(
                        f"required CV parameter is unavailable: {parameter_name}"
                    )

            self._set_and_verify_parameter(
                set_parameter,
                get_parameter,
                "m_bDryRun",
                0.0,
                payload,
            )
            self._set_and_verify_parameter(
                set_parameter,
                get_parameter,
                "m_bCellOn",
                0.0,
                payload,
            )
            for parameter_name, value in sdk_parameters.items():
                self._set_and_verify_parameter(
                    set_parameter,
                    get_parameter,
                    parameter_name,
                    value,
                    payload,
                )
            if self._abort_requested.is_set():
                raise RuntimeError("CV commissioning was stopped before cell enable")

            self._set_and_verify_parameter(
                set_parameter,
                get_parameter,
                "m_bCellOn",
                1.0,
                payload,
            )
            payload["vendor_functions_called"] += 1
            payload["run_returned"] = bool(run_experiment())
            if payload["run_returned"] is not True:
                raise RuntimeError("CHI SDK rejected the commissioning CV")

            deadline = monotonic() + CV_COMMISSIONING_LIMITS["timeout_s"]
            while True:
                payload["vendor_functions_called"] += 1
                if not bool(is_running()):
                    break
                if monotonic() >= deadline:
                    raise TimeoutError("commissioning CV exceeded its bounded timeout")
                sleep(0.05)

            capacity = int(CV_COMMISSIONING_LIMITS["data_capacity"])
            x_buffer = (ctypes.c_float * capacity)()
            y_buffer = (ctypes.c_float * capacity)()
            payload["vendor_functions_called"] += 1
            count = int(get_data(x_buffer, y_buffer, capacity))
            if count < 0 or count > capacity:
                raise RuntimeError("CHI SDK returned an invalid CV data count")
            x_values = [float(x_buffer[index]) for index in range(count)]
            y_values = [float(y_buffer[index]) for index in range(count)]
            if count == 0 and not self._abort_requested.is_set():
                raise RuntimeError("CHI SDK returned no CV data")
            if any(
                not (-float("inf") < value < float("inf"))
                for value in (*x_values, *y_values)
            ):
                raise RuntimeError("CHI SDK returned non-finite CV data")
            payload["data_points"] = count
            payload["x_values"] = x_values
            payload["y_values"] = y_values

            error_buffer = ctypes.create_string_buffer(1024)
            payload["vendor_functions_called"] += 1
            get_error(error_buffer, len(error_buffer))
            error_status = error_buffer.value.decode("utf-8", errors="replace").strip()
            payload["vendor_error_status"] = error_status or None
            return payload
        finally:
            if stop is not None:
                try:
                    stop()
                    payload["vendor_functions_called"] += 1
                    payload["stop_called"] = True
                except (OSError, ValueError) as error:
                    cleanup_errors.append(f"CHI_Stop failed: {error}")
            if set_parameter is not None and get_parameter is not None:
                try:
                    set_parameter(b"m_bCellOn", ctypes.c_float(0.0))
                    payload["vendor_functions_called"] += 1
                    cell_on = float(get_parameter(b"m_bCellOn"))
                    payload["vendor_functions_called"] += 1
                    payload["cell_on_parameter_readback_after_cleanup"] = cell_on
                    if cell_on >= 0.5:
                        cleanup_errors.append("m_bCellOn did not clear during cleanup")
                except (OSError, ValueError) as error:
                    cleanup_errors.append(f"cell-off parameter cleanup failed: {error}")
            with self._lock:
                self._stop_function = None
                self._active = False
            for handle in reversed(search_handles):
                handle.close()
            if cleanup_errors:
                raise RuntimeError("; ".join(cleanup_errors))

    def stop(self) -> None:
        """Request termination using the vendor's documented stop function."""

        self._abort_requested.set()
        with self._lock:
            stop = self._stop_function
        if stop is not None:
            stop()

    @staticmethod
    def _set_and_verify_parameter(
        set_parameter: Any,
        get_parameter: Any,
        name: str,
        requested: float,
        payload: dict[str, Any],
    ) -> None:
        encoded = name.encode("ascii")
        set_parameter(encoded, ctypes.c_float(requested))
        payload["vendor_functions_called"] += 1
        readback = float(get_parameter(encoded))
        payload["vendor_functions_called"] += 1
        tolerance = max(1e-6, abs(requested) * 1e-5)
        if abs(readback - requested) > tolerance:
            raise RuntimeError(
                f"CV parameter readback mismatch for {name}: "
                f"requested {requested}, received {readback}"
            )


class CVCommissioningJobManager:
    """Own the worker's single asynchronous 760E commissioning job."""

    def __init__(self, runner: Any) -> None:
        self.runner = runner
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._job_id: str | None = None
        self._state = "idle"
        self._plan: dict[str, Any] | None = None
        self._result: dict[str, Any] | None = None
        self._error: str | None = None
        self._stop_requested = False

    def start(self, plan: Any, confirmations: Any) -> dict[str, Any]:
        normalized = validate_cv_commissioning_plan(plan)
        self._validate_confirmations(confirmations)
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                raise ValueError("a 760E commissioning job is already active")
            reset_stop = getattr(self.runner, "reset_stop", None)
            if callable(reset_stop):
                reset_stop()
            self._job_id = uuid4().hex
            self._state = "starting"
            self._plan = normalized
            self._result = None
            self._error = None
            self._stop_requested = False
            job_id = self._job_id
            self._thread = threading.Thread(
                target=self._run,
                name="chi760e-cv-commissioning",
                daemon=True,
            )
            self._thread.start()
        return {"job_id": job_id, "state": "starting", "target_model": "760E"}

    def status(self, job_id: Any = None) -> dict[str, Any]:
        with self._lock:
            self._require_job(job_id)
            data_points = 0
            if self._result is not None:
                value = self._result.get("data_points", 0)
                if isinstance(value, int) and not isinstance(value, bool):
                    data_points = value
            return {
                "job_id": self._job_id,
                "state": self._state,
                "target_model": "760E",
                "plan": dict(self._plan) if self._plan is not None else None,
                "data_points": data_points,
                "result_available": self._result is not None,
                "stop_requested": self._stop_requested,
                "error": self._error,
            }

    def stop(self, job_id: Any) -> dict[str, Any]:
        with self._lock:
            self._require_job(job_id)
            if self._state not in {"starting", "running", "stopping"}:
                raise ValueError("the 760E commissioning job is not active")
            self._stop_requested = True
            self._state = "stopping"
        self.runner.stop()
        return self.status(job_id)

    def result_page(self, job_id: Any, offset: Any, limit: Any) -> dict[str, Any]:
        if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
            raise ValueError("result offset must be a non-negative integer")
        if (
            isinstance(limit, bool)
            or not isinstance(limit, int)
            or not 1 <= limit <= 4096
        ):
            raise ValueError("result limit must be an integer from 1 to 4096")
        with self._lock:
            self._require_job(job_id)
            if self._result is None:
                raise ValueError("CV result data is not available")
            x_values = self._result.get("x_values")
            y_values = self._result.get("y_values")
            if not isinstance(x_values, list) or not isinstance(y_values, list):
                raise ValueError("CV result data is malformed")
            if len(x_values) != len(y_values):
                raise ValueError("CV result channel lengths do not match")
            end = min(len(x_values), offset + limit)
            return {
                "job_id": self._job_id,
                "offset": offset,
                "count": max(0, end - offset),
                "total": len(x_values),
                "next_offset": end if end < len(x_values) else None,
                "x_values": x_values[offset:end],
                "y_values": y_values[offset:end],
                "units": self._result.get("units", {"x": "V", "y": "A"}),
            }

    def close(self, timeout_s: float = 2.0) -> None:
        with self._lock:
            thread = self._thread
            active = self._state in {"starting", "running", "stopping"}
            job_id = self._job_id
        if active and job_id is not None:
            try:
                self.stop(job_id)
            except (OSError, RuntimeError, ValueError):
                pass
        if thread is not None and thread.is_alive():
            thread.join(timeout=max(0.0, timeout_s))

    def _run(self) -> None:
        with self._lock:
            plan = dict(self._plan or {})
            if self._stop_requested:
                self._state = "stopped"
                return
            self._state = "running"
        try:
            result = self.runner.run(plan)
            if not isinstance(result, dict):
                raise RuntimeError("live CV runner returned a non-object result")
            with self._lock:
                self._result = result
                self._state = "stopped" if self._stop_requested else "completed"
        except Exception as error:
            with self._lock:
                self._error = str(error)
                self._state = "error"

    def _require_job(self, job_id: Any) -> None:
        if self._job_id is None:
            raise ValueError("no 760E commissioning job has been started")
        if job_id is not None and job_id != self._job_id:
            raise ValueError("760E commissioning job id does not match")

    @staticmethod
    def _validate_confirmations(confirmations: Any) -> None:
        if not isinstance(confirmations, dict) or not all(
            confirmations.get(name) is True
            for name in CV_COMMISSIONING_CONFIRMATIONS
        ):
            raise ValueError("all local 760E commissioning confirmations are required")


def serve_requests(
    sdk_directory: str | Path,
    runtime_directory: str | Path,
    *,
    dll_name: str = "libec760e.dll",
    enable_chi760e_commissioning: bool = False,
    commissioning_jobs: CVCommissioningJobManager | None = None,
    input_stream: Any = None,
    output_stream: Any = None,
) -> int:
    """Serve private JSON-lines requests until EOF or an explicit shutdown."""

    source = sys.stdin if input_stream is None else input_stream
    destination = sys.stdout if output_stream is None else output_stream
    jobs = commissioning_jobs
    if jobs is None:
        jobs = CVCommissioningJobManager(
            LiveCVRunner(
                sdk_directory,
                runtime_directory,
                dll_name=dll_name,
            )
        )
    for raw_line in source:
        request_id: Any = None
        shutdown = False
        try:
            if len(raw_line.encode("utf-8")) > MAX_REQUEST_BYTES:
                raise ValueError("request exceeds the worker size limit")
            request = json.loads(raw_line)
            if not isinstance(request, dict):
                raise ValueError("request must be a JSON object")
            request_id = request.get("id")
            if request.get("schema_version") != SCHEMA_VERSION:
                raise ValueError("worker protocol version mismatch")
            if not isinstance(request_id, int) or isinstance(request_id, bool):
                raise ValueError("request id must be an integer")
            command = request.get("command")
            if command == "status":
                result = inspect_runtime(
                    sdk_directory, runtime_directory, dll_name=dll_name
                )
                result["commissioning_mode_enabled"] = bool(
                    enable_chi760e_commissioning
                )
                result["experiments_enabled"] = bool(
                    enable_chi760e_commissioning
                    and result["ready_to_load"]
                    and not result["missing_commissioning_exports"]
                )
            elif command == "load-check":
                if request.get("allow_library_load_without_calls") is not True:
                    raise ValueError("explicit library-load acknowledgement is required")
                result = load_check(
                    sdk_directory, runtime_directory, dll_name=dll_name
                )
            elif command == "discover":
                confirmations = request.get("confirmations")
                required = (
                    "identity_only",
                    "no_sample_connected",
                    "electrode_leads_safe",
                    "cell_output_off",
                )
                if not isinstance(confirmations, dict) or not all(
                    confirmations.get(name) is True for name in required
                ):
                    raise ValueError(
                        "all local discovery safety confirmations are required"
                    )
                result = read_identity_and_capabilities(
                    sdk_directory, runtime_directory, dll_name=dll_name
                )
            elif command == "cv-start":
                if not enable_chi760e_commissioning:
                    raise ValueError("760E commissioning is disabled for this worker")
                result = jobs.start(request.get("plan"), request.get("confirmations"))
            elif command == "cv-status":
                if not enable_chi760e_commissioning:
                    raise ValueError("760E commissioning is disabled for this worker")
                result = jobs.status(request.get("job_id"))
            elif command == "cv-stop":
                if not enable_chi760e_commissioning:
                    raise ValueError("760E commissioning is disabled for this worker")
                result = jobs.stop(request.get("job_id"))
            elif command == "cv-result":
                if not enable_chi760e_commissioning:
                    raise ValueError("760E commissioning is disabled for this worker")
                result = jobs.result_page(
                    request.get("job_id"),
                    request.get("offset", 0),
                    request.get("limit", 4096),
                )
            elif command == "shutdown":
                jobs.close()
                result = {
                    "schema_version": SCHEMA_VERSION,
                    "operation": "shutdown",
                    "library_loaded": False,
                    "vendor_functions_called": 0,
                    "device_contacted": False,
                    "experiments_enabled": False,
                    "error": None,
                }
                shutdown = True
            else:
                raise ValueError("unsupported worker command")
            response = {
                "schema_version": SCHEMA_VERSION,
                "id": request_id,
                "ok": True,
                "result": result,
            }
        except (
            OSError,
            RuntimeError,
            TimeoutError,
            TypeError,
            ValueError,
            json.JSONDecodeError,
        ) as error:
            response = {
                "schema_version": SCHEMA_VERSION,
                "id": request_id,
                "ok": False,
                "error": str(error),
            }
        destination.write(json.dumps(response, allow_nan=False, sort_keys=True) + "\n")
        destination.flush()
        if shutdown:
            return 0
    return 0


def start_parent_watchdog(parent_pid: int | None) -> None:
    """Exit the worker if an abruptly terminated bridge cannot close its pipe."""

    if parent_pid is None or parent_pid <= 0 or parent_pid == os.getpid():
        return

    def watch() -> None:
        if os.name == "nt":
            synchronize = 0x00100000
            infinite = 0xFFFFFFFF
            kernel32 = ctypes.windll.kernel32
            handle = kernel32.OpenProcess(synchronize, False, parent_pid)
            if not handle:
                os._exit(0)
            try:
                kernel32.WaitForSingleObject(handle, infinite)
            finally:
                kernel32.CloseHandle(handle)
            os._exit(0)
        while True:
            try:
                os.kill(parent_pid, 0)
            except OSError:
                os._exit(0)
            sleep(1.0)

    threading.Thread(target=watch, name="chi-worker-parent-watch", daemon=True).start()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Inspect the legacy CHI SDK in an isolated 32-bit process."
    )
    commands = parser.add_subparsers(dest="command", required=True)
    for command in ("status", "load-check", "discover", "dry-run", "serve"):
        child = commands.add_parser(command)
        child.add_argument("--sdk-dir", type=Path, required=True)
        child.add_argument("--runtime-dir", type=Path, required=True)
        child.add_argument("--dll-name", default="libec760e.dll")
        if command == "serve":
            child.add_argument("--parent-pid", type=int)
            child.add_argument(
                "--enable-chi760e-commissioning",
                action="store_true",
                help=(
                    "Expose bounded CV job commands; every start still requires "
                    "the complete local safety confirmation set."
                ),
            )
        if command == "load-check":
            child.add_argument(
                "--allow-library-load-without-calls",
                action="store_true",
                help="Required acknowledgement; no exported function is invoked.",
            )
        elif command == "discover":
            child.add_argument("--confirm-identity-only", action="store_true")
            child.add_argument("--confirm-no-sample", action="store_true")
            child.add_argument("--confirm-leads-safe", action="store_true")
            child.add_argument("--confirm-cell-output-off", action="store_true")
        elif command == "dry-run":
            child.add_argument("--confirm-usb-disconnected", action="store_true")
            child.add_argument("--confirm-usb-connected", action="store_true")
            child.add_argument("--confirm-no-sample", action="store_true")
            child.add_argument("--confirm-leads-safe", action="store_true")
            child.add_argument("--confirm-cell-output-off", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    if arguments.command == "serve":
        start_parent_watchdog(arguments.parent_pid)
        return serve_requests(
            arguments.sdk_dir,
            arguments.runtime_dir,
            dll_name=arguments.dll_name,
            enable_chi760e_commissioning=(
                arguments.enable_chi760e_commissioning
            ),
        )
    if arguments.command == "status":
        payload = inspect_runtime(
            arguments.sdk_dir,
            arguments.runtime_dir,
            dll_name=arguments.dll_name,
        )
    elif arguments.command == "load-check" and not arguments.allow_library_load_without_calls:
        payload = {
            "schema_version": SCHEMA_VERSION,
            "operation": "load_check",
            "library_loaded": False,
            "vendor_functions_called": 0,
            "device_contacted": False,
            "experiments_enabled": False,
            "error": "explicit library-load acknowledgement is required",
        }
    elif arguments.command == "load-check":
        payload = load_check(
            arguments.sdk_dir,
            arguments.runtime_dir,
            dll_name=arguments.dll_name,
        )
    elif arguments.command == "discover":
        if not all(
            (
                arguments.confirm_identity_only,
                arguments.confirm_no_sample,
                arguments.confirm_leads_safe,
                arguments.confirm_cell_output_off,
            )
        ):
            payload = {
                "schema_version": SCHEMA_VERSION,
                "operation": "read_identity_and_capabilities",
                "library_loaded": False,
                "vendor_functions_called": 0,
                "device_contacted": False,
                "experiments_enabled": False,
                "error": "all local discovery safety confirmations are required",
            }
        else:
            payload = read_identity_and_capabilities(
                arguments.sdk_dir,
                arguments.runtime_dir,
                dll_name=arguments.dll_name,
            )
    else:
        disconnected_confirmed = (
            arguments.confirm_usb_disconnected
            and not arguments.confirm_usb_connected
            and arguments.confirm_no_sample
        )
        connected_confirmed = all(
            (
                arguments.confirm_usb_connected,
                not arguments.confirm_usb_disconnected,
                arguments.confirm_no_sample,
                arguments.confirm_leads_safe,
                arguments.confirm_cell_output_off,
            )
        )
        if not (disconnected_confirmed or connected_confirmed):
            payload = {
                "schema_version": SCHEMA_VERSION,
                "operation": "sdk_dry_run",
                "library_loaded": False,
                "vendor_functions_called": 0,
                "device_contacted": False,
                "experiments_enabled": False,
                "error": (
                    "confirm either USB-disconnected/no-sample or the complete "
                    "connected dry-run safety set"
                ),
            }
        else:
            payload = run_sdk_dry_run(
                arguments.sdk_dir,
                arguments.runtime_dir,
                dll_name=arguments.dll_name,
                physical_hardware_available=connected_confirmed,
            )
    print(json.dumps(payload, allow_nan=False, sort_keys=True))
    return 0 if payload.get("error") is None else 2


def _inspect_pe_bytes(data: bytes) -> tuple[str, int, tuple[str, ...]]:
    if len(data) < 64 or data[:2] != b"MZ":
        raise ValueError("not a Windows PE file")
    pe_offset = _u32(data, 0x3C)
    if pe_offset + 24 > len(data) or data[pe_offset:pe_offset + 4] != b"PE\x00\x00":
        raise ValueError("invalid PE header")
    machine = _u16(data, pe_offset + 4)
    architecture, machine_bitness = {
        0x014C: ("x86", 32),
        0x8664: ("x86_64", 64),
        0xAA64: ("arm64", 64),
    }.get(machine, (f"unknown_0x{machine:04x}", 0))
    section_count = _u16(data, pe_offset + 6)
    optional_size = _u16(data, pe_offset + 20)
    optional_offset = pe_offset + 24
    magic = _u16(data, optional_offset)
    if magic == 0x10B:
        bitness = 32
        data_directory_offset = optional_offset + 96
    elif magic == 0x20B:
        bitness = 64
        data_directory_offset = optional_offset + 112
    else:
        raise ValueError(f"unsupported PE optional-header magic 0x{magic:04x}")
    if machine_bitness and machine_bitness != bitness:
        raise ValueError("PE machine and optional-header bitness disagree")
    export_rva = _u32(data, data_directory_offset)
    if export_rva == 0:
        return architecture, bitness, ()
    section_offset = optional_offset + optional_size
    sections: list[tuple[int, int, int]] = []
    for index in range(section_count):
        offset = section_offset + index * 40
        virtual_size = _u32(data, offset + 8)
        virtual_address = _u32(data, offset + 12)
        raw_size = _u32(data, offset + 16)
        raw_offset = _u32(data, offset + 20)
        sections.append((virtual_address, max(virtual_size, raw_size), raw_offset))
    export_offset = _rva_to_offset(export_rva, sections, len(data))
    name_count = _u32(data, export_offset + 24)
    names_offset = _rva_to_offset(
        _u32(data, export_offset + 32), sections, len(data)
    )
    if name_count > 10_000:
        raise ValueError("PE export-name count exceeds inspection limit")
    exports = []
    for index in range(name_count):
        name_rva = _u32(data, names_offset + index * 4)
        name_offset = _rva_to_offset(name_rva, sections, len(data))
        exports.append(_read_c_string(data, name_offset))
    return architecture, bitness, tuple(exports)


def _rva_to_offset(
    rva: int,
    sections: list[tuple[int, int, int]],
    data_length: int,
) -> int:
    for virtual_address, span, raw_offset in sections:
        if virtual_address <= rva < virtual_address + span:
            offset = raw_offset + (rva - virtual_address)
            if offset < data_length:
                return offset
    raise ValueError(f"PE RVA 0x{rva:x} is outside file sections")


def _read_c_string(data: bytes, offset: int) -> str:
    end = data.find(b"\x00", offset, min(len(data), offset + 4096))
    if end == -1:
        raise ValueError("unterminated PE export name")
    return data[offset:end].decode("ascii")


def _u16(data: bytes, offset: int) -> int:
    if offset < 0 or offset + 2 > len(data):
        raise ValueError("truncated PE field")
    return struct.unpack_from("<H", data, offset)[0]


def _u32(data: bytes, offset: int) -> int:
    if offset < 0 or offset + 4 > len(data):
        raise ValueError("truncated PE field")
    return struct.unpack_from("<I", data, offset)[0]


if __name__ == "__main__":
    raise SystemExit(main())

"""Isolated 32-bit preflight process for the legacy CHI libec runtime.

This module is deliberately executable as a standalone script. The Python
embeddable distribution can therefore run it without importing the rest of the
project. ``status`` only parses files. ``load-check`` loads the DLL in this
short-lived process but never calls a vendor function.
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
from time import monotonic, sleep
from typing import Any


SCHEMA_VERSION = "0.1"
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
    payload.update(
        {
            "library_architecture": architecture,
            "library_bitness": bitness,
            "library_sha256": sha256(data).hexdigest(),
            "missing_exports": missing,
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

        for identifier in (b"m_bDryRun", b"m_bCellOn"):
            payload["vendor_functions_called"] += 1
            if not bool(has_parameter(identifier)):
                raise ValueError(
                    f"required safety parameter is unavailable: {identifier.decode()}"
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
        for identifier, requested in CV_DRY_RUN_PARAMETERS.items():
            encoded = identifier.encode("ascii")
            payload["vendor_functions_called"] += 1
            if not bool(has_parameter(encoded)):
                raise ValueError(f"required CV parameter is unavailable: {identifier}")
            payload["vendor_functions_called"] += 1
            set_parameter(encoded, ctypes.c_float(requested))
            payload["vendor_functions_called"] += 1
            readback = float(get_parameter(encoded))
            parameter_readbacks[identifier] = readback
            tolerance = max(1e-6, abs(requested) * 1e-5)
            if abs(readback - requested) > tolerance:
                raise ValueError(
                    f"CV parameter readback mismatch for {identifier}: "
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Inspect the legacy CHI SDK in an isolated 32-bit process."
    )
    commands = parser.add_subparsers(dest="command", required=True)
    for command in ("status", "load-check", "discover", "dry-run"):
        child = commands.add_parser(command)
        child.add_argument("--sdk-dir", type=Path, required=True)
        child.add_argument("--runtime-dir", type=Path, required=True)
        child.add_argument("--dll-name", default="libec760e.dll")
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

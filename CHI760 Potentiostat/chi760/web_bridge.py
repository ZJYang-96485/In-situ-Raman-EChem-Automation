"""Loopback-only web bridge for the SpectraLoop browser interface.

The bridge is deliberately small and dependency-free.  It gives a browser UI
an authenticated local boundary for storage selection, read-only discovery,
and explicitly enabled commissioning adapters without exposing the instrument
computer to the network.

The default gateway is unavailable and performs zero hardware calls.  A live
gateway has to be supplied explicitly after the matching vendor interface has
been verified.
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from datetime import datetime, timezone
import hmac
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
import math
import mimetypes
import os
from pathlib import Path
from pathlib import PurePosixPath
import re
import secrets
import subprocess
import threading
from typing import Any, Callable, Mapping, Protocol
from urllib.parse import unquote, urlsplit, urlunsplit
import webbrowser

from .errors import (
    BackendStateError,
    InvalidVendorResponseError,
    VendorCallError,
    VendorCallTimeoutError,
    VendorEvidenceUnavailableError,
)
from .desktop_macro import (
    CHI760DDesktopController,
    DesktopMacroError,
    default_chi760d_executable,
)
from .data_store import RunDataStore, safe_task_folder_name
from .live_backend import CHI760ELiveBackend, LiveConnectionState
from .worker_transport import (
    CHI760ECommissioningError,
    DEFAULT_WORKER_TIMEOUT_S,
    PersistentSDKWorker,
    SDKWorkerCommissioningGateway,
    SDKWorkerDiscoveryGateway,
    WorkerLaunchConfig,
    default_worker_launch_config,
)


BRIDGE_VERSION = "0.6.0"
BRIDGE_COOKIE_NAME = "spectraloop_bridge_session"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
MAX_REQUEST_BYTES = 64 * 1024
MAX_SIMULATION_SAVE_BYTES = 64 * 1024 * 1024
DEFAULT_ALLOWED_ORIGINS = frozenset(
    {"https://spectraloop.org", "https://www.spectraloop.org"}
)
REQUIRED_DISCOVERY_CONFIRMATIONS = frozenset(
    {
        "identity_only",
        "no_sample_connected",
        "electrode_leads_safe",
        "cell_output_off",
    }
)
REQUIRED_760D_RUN_CONFIRMATIONS = frozenset(
    {
        "internal_dummy_only",
        "electrode_leads_disconnected",
        "chi_desktop_closed",
        "limits_reviewed",
        "stop_button_accessible",
    }
)
REQUIRED_760E_RUN_CONFIRMATIONS = frozenset(
    {
        "target_is_760e",
        "no_other_chi_measurement_running",
        "chi_desktop_closed",
        "internal_dummy_cell_connected",
        "external_sample_disconnected",
        "electrode_leads_verified",
        "cell_output_confirmed_off",
    }
)


class BridgeRequestError(ValueError):
    """A safe, user-correctable API request error."""

    def __init__(self, code: str, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.status = status


class DiscoveryGateway(Protocol):
    """Small adapter surface owned by the local bridge, not the website."""

    def public_status(self) -> Mapping[str, Any]: ...

    def discover(self) -> Mapping[str, Any]: ...


class UnavailableDiscoveryGateway:
    """Fail-closed default used until a verified vendor adapter is installed."""

    def __init__(
        self,
        blocker: str = (
            "The installed CHI 760E files do not document a non-energizing "
            "identity interface. No vendor transport is configured."
        ),
        *,
        target: str = "CHI 760E",
    ) -> None:
        self.blocker = blocker
        self.target = target
        self.hardware_calls = 0

    def public_status(self) -> Mapping[str, Any]:
        return {
            "target": self.target,
            "state": "adapter_unavailable",
            "discovery_enabled": False,
            "experiment_control_enabled": False,
            "hardware_calls": self.hardware_calls,
            "blocker": self.blocker,
        }

    def discover(self) -> Mapping[str, Any]:
        raise VendorEvidenceUnavailableError(self.blocker)


class CHI760EDiscoveryGateway:
    """Expose only the verified read-only sequence of ``CHI760ELiveBackend``."""

    def __init__(self, backend: CHI760ELiveBackend) -> None:
        self.backend = backend
        self._lock = threading.Lock()

    def public_status(self) -> Mapping[str, Any]:
        resolved = self.backend.mapping.resolved and self.backend.transport is not None
        return {
            "target": "CHI 760E",
            "state": "ready_for_identity" if resolved else "adapter_unavailable",
            "discovery_enabled": resolved,
            "experiment_control_enabled": False,
            "hardware_calls": self.backend.hardware_calls,
            "blocker": None if resolved else "Verified discovery mapping is unavailable.",
        }

    def discover(self) -> Mapping[str, Any]:
        with self._lock:
            self.backend.connect()
            try:
                identity = self.backend.query_identity()
                capabilities = self.backend.query_capabilities()
                return {
                    "identity": identity,
                    "capabilities": capabilities,
                    "trace": self.backend.trace_payload(),
                }
            finally:
                if self.backend.connection_state is LiveConnectionState.CONNECTED:
                    self.backend.disconnect()


DirectoryPicker = Callable[[Path | None], Path | None]
FolderOpener = Callable[[Path], None]
ApprovalPrompt = Callable[[], bool]
ExperimentApprovalPrompt = Callable[[Mapping[str, Any]], bool]


def native_directory_picker(initial: Path | None = None) -> Path | None:
    """Open the operating system's directory chooser without a web path field."""

    try:
        import tkinter as tk
        from tkinter import filedialog
    except ImportError as error:  # pragma: no cover - platform Python packaging
        raise BridgeRequestError(
            "folder_picker_unavailable",
            "This Python installation does not include the native folder picker.",
            503,
        ) from error

    root = tk.Tk()
    root.withdraw()
    try:
        root.attributes("-topmost", True)
        selected = filedialog.askdirectory(
            parent=root,
            title="Choose SpectraLoop data folder",
            initialdir=str(initial) if initial and initial.is_dir() else None,
            mustexist=True,
        )
    finally:
        root.destroy()
    return Path(selected) if selected else None


def native_folder_opener(directory: Path) -> None:
    """Open one validated saved folder after an explicit browser click."""

    if os.name != "nt":  # pragma: no cover - the production bridge is Windows-only
        raise BridgeRequestError(
            "folder_open_unavailable",
            "Opening the saved folder is available on the Windows instrument computer.",
            503,
        )
    try:
        subprocess.Popen(
            ["explorer.exe", str(directory)],
            shell=False,
            close_fds=True,
        )
    except OSError as error:
        raise BridgeRequestError(
            "folder_open_failed",
            "Windows could not open the saved simulation folder.",
            500,
        ) from error


def native_discovery_approval() -> bool:
    """Require a confirmation owned by the instrument PC, not the web page."""

    try:
        import tkinter as tk
        from tkinter import messagebox
    except ImportError as error:  # pragma: no cover - platform Python packaging
        raise BridgeRequestError(
            "local_confirmation_unavailable",
            "This Python installation cannot display the local safety confirmation.",
            503,
        ) from error

    root = tk.Tk()
    root.withdraw()
    try:
        root.attributes("-topmost", True)
        return bool(
            messagebox.askyesno(
                "Confirm CHI SDK capability check",
                "Allow one read-only CHI SDK capability check?\n\n"
                "Confirm that no sample or electrochemical cell is connected, "
                "the electrode leads are safe, and the CHI cell output is off.\n\n"
                "This does not run an experiment or prove physical instrument identity.",
                parent=root,
                icon="warning",
            )
        )
    finally:
        root.destroy()


def native_760d_experiment_approval(summary: Mapping[str, Any]) -> bool:
    """Require a second, local approval for the bounded internal-dummy series."""

    try:
        import tkinter as tk
        from tkinter import messagebox
    except ImportError as error:  # pragma: no cover - platform Python packaging
        raise BridgeRequestError(
            "local_confirmation_unavailable",
            "This Python installation cannot display the local experiment confirmation.",
            503,
        ) from error

    root = tk.Tk()
    root.withdraw()
    try:
        root.attributes("-topmost", True)
        return bool(
            messagebox.askyesno(
                "Start CHI 760D internal dummy series",
                "Allow one real CHI 760D macro series on the INTERNAL DUMMY CELL?\n\n"
                f"Steps: {summary.get('step_count')}; bounded CV runs: {summary.get('cv_count')}\n"
                f"Estimated duration: {summary.get('estimated_duration_s')} s\n\n"
                "Confirm the electrode leads are disconnected, chi760d.exe is closed, "
                "and you can reach the CHI Stop button. External samples are not allowed.",
                parent=root,
                icon="warning",
            )
        )
    finally:
        root.destroy()


def native_760e_experiment_approval(summary: Mapping[str, Any]) -> bool:
    """Require instrument-computer approval immediately before worker start."""

    try:
        import tkinter as tk
        from tkinter import messagebox
    except ImportError as error:  # pragma: no cover - platform Python packaging
        raise BridgeRequestError(
            "local_confirmation_unavailable",
            "This Python installation cannot display the local experiment confirmation.",
            503,
        ) from error

    root = tk.Tk()
    root.withdraw()
    try:
        root.attributes("-topmost", True)
        return bool(
            messagebox.askyesno(
                "Start CHI 760E internal dummy CV",
                "Allow one real CHI 760E CV on the INTERNAL DUMMY CELL?\n\n"
                f"Initial: {summary.get('initial_potential_v')} V\n"
                f"High: {summary.get('high_potential_v')} V\n"
                f"Low: {summary.get('low_potential_v')} V\n"
                f"Scan rate: {summary.get('scan_rate_v_s')} V/s\n\n"
                "Confirm no other CHI measurement is running, CHI desktop software "
                "is closed, external samples are disconnected, and the cell output "
                "is off before starting.",
                parent=root,
                icon="warning",
            )
        )
    finally:
        root.destroy()


def default_config_path() -> Path:
    """Return a per-user settings path without embedding a computer-specific path."""

    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data) / "SpectraLoop" / "bridge.json"
    xdg_config_home = os.environ.get("XDG_CONFIG_HOME")
    if xdg_config_home:
        return Path(xdg_config_home) / "spectraloop" / "bridge.json"
    return Path.home() / ".config" / "spectraloop" / "bridge.json"


class StorageSettings:
    """Persist the user-selected data root locally and reveal only its label."""

    def __init__(self, config_path: str | Path) -> None:
        self.config_path = Path(config_path)
        self._root: Path | None = None
        self._load_error: str | None = None
        self._load()

    @property
    def root(self) -> Path | None:
        return self._root

    def public_status(self) -> dict[str, Any]:
        available = self._root is not None and self._root.is_dir()
        return {
            "configured": self._root is not None,
            "available": available,
            "folder_name": self._root.name if self._root is not None else None,
            "load_error": self._load_error,
        }

    def select(self, picker: DirectoryPicker) -> dict[str, Any]:
        selected = picker(self._root)
        if selected is None:
            return {**self.public_status(), "cancelled": True}
        self.configure(selected)
        return {**self.public_status(), "cancelled": False}

    def configure(self, selected: str | Path) -> None:
        candidate = Path(selected).expanduser()
        if not candidate.is_absolute():
            raise BridgeRequestError(
                "invalid_storage_folder", "The selected storage folder must be absolute."
            )
        try:
            resolved = candidate.resolve(strict=True)
        except OSError as error:
            raise BridgeRequestError(
                "invalid_storage_folder", "The selected storage folder is unavailable."
            ) from error
        if not resolved.is_dir():
            raise BridgeRequestError(
                "invalid_storage_folder", "The selected storage location is not a folder."
            )
        payload = {
            "schema_version": "0.1",
            "storage_root": str(resolved),
            "selected_at": datetime.now(timezone.utc).isoformat(),
        }
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.config_path.with_name(
            f".{self.config_path.name}.{secrets.token_hex(8)}.tmp"
        )
        try:
            with temporary.open("x", encoding="utf-8", newline="\n") as stream:
                json.dump(payload, stream, indent=2, sort_keys=True, allow_nan=False)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.config_path)
        finally:
            if temporary.exists():
                temporary.unlink()
        self._root = resolved
        self._load_error = None

    def _load(self) -> None:
        if not self.config_path.exists():
            return
        try:
            payload = json.loads(self.config_path.read_text(encoding="utf-8"))
            value = payload.get("storage_root")
            if not isinstance(value, str) or not value:
                raise ValueError("storage_root is missing")
            candidate = Path(value)
            if not candidate.is_absolute():
                raise ValueError("storage_root is not absolute")
            self._root = candidate.resolve(strict=False)
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as error:
            self._root = None
            self._load_error = f"Stored folder setting could not be loaded: {error}"


@dataclass
class BridgeState:
    token: str
    storage: StorageSettings
    gateway: DiscoveryGateway
    directory_picker: DirectoryPicker = native_directory_picker
    folder_opener: FolderOpener = native_folder_opener
    discovery_approval: ApprovalPrompt = native_discovery_approval
    desktop_760d: CHI760DDesktopController | None = None
    experiment_approval: ExperimentApprovalPrompt = native_760d_experiment_approval
    commissioning_760e: SDKWorkerCommissioningGateway | None = None
    chi760e_experiment_approval: ExperimentApprovalPrompt = (
        native_760e_experiment_approval
    )

    def status_payload(self) -> dict[str, Any]:
        instrument_status = dict(self.gateway.public_status())
        desktop_status = (
            self.desktop_760d.public_status()
            if self.desktop_760d is not None
            else {
                "target": "CHI 760D desktop",
                "state": "adapter_unavailable",
                "executable_verified": False,
                "experiment_control_enabled": False,
                "scope": "internal_dummy_cv_only",
                "remote_stop_available": False,
                "hardware_calls": 0,
                "blocker": "The CHI 760D desktop adapter is not configured.",
                "active": None,
            }
        )
        chi760e_enabled = (
            instrument_status.get("experiment_control_enabled") is True
            and self.commissioning_760e is not None
        )
        chi760d_enabled = desktop_status.get("experiment_control_enabled") is True
        return {
            "api_version": "v1",
            "service": {
                "name": "SpectraLoop local bridge",
                "version": BRIDGE_VERSION,
                "binding": "loopback_only",
            },
            "storage": self.storage.public_status(),
            "instrument": instrument_status,
            "desktop_760d": desktop_status,
            "safety": {
                "mode": (
                    "chi760e_internal_dummy"
                    if chi760e_enabled
                    else "chi760d_internal_dummy"
                    if chi760d_enabled
                    else "sdk_discovery_only"
                ),
                "experiments_enabled": chi760e_enabled or chi760d_enabled,
                "experiment_scope": (
                    "internal_dummy_bounded_cv"
                    if chi760e_enabled
                    else "internal_dummy_bounded_cv_series"
                    if chi760d_enabled
                    else None
                ),
                "remote_stop_available": chi760e_enabled,
                "raman_enabled": False,
                "laser_enabled": False,
                "automated_decisions_enabled": False,
                "local_confirmation_required": True,
            },
        }


def _finite_number(
    value: Any, field_name: str, *, nullable: bool = False
) -> float | None:
    if value is None and nullable:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise BridgeRequestError(
            "invalid_simulation", f"{field_name} must be a finite number."
        )
    converted = float(value)
    if not math.isfinite(converted):
        raise BridgeRequestError(
            "invalid_simulation", f"{field_name} must be finite."
        )
    return converted


def _save_simulation_session(storage_root: Path, session: Any) -> dict[str, Any]:
    """Validate and persist one browser-only EChem simulation."""

    if not isinstance(session, Mapping):
        raise BridgeRequestError(
            "invalid_simulation", "A simulation session object is required."
        )
    if session.get("execution_mode") != "connection_free_simulation":
        raise BridgeRequestError(
            "invalid_simulation", "Only connection-free simulations can be saved."
        )
    if (
        session.get("hardware_connected") is not False
        or session.get("hardware_calls") != 0
    ):
        raise BridgeRequestError(
            "invalid_simulation", "Simulation data must report zero hardware I/O."
        )
    if session.get("terminal_state") not in {"simulated_complete", "simulated_failed"}:
        raise BridgeRequestError(
            "invalid_simulation", "Simulation terminal state is invalid."
        )

    protocol = session.get("protocol_plan")
    if not isinstance(protocol, Mapping):
        raise BridgeRequestError(
            "invalid_simulation", "The simulation protocol is missing."
        )
    task_name = protocol.get("protocol_name")
    if not isinstance(task_name, str) or not task_name.strip():
        raise BridgeRequestError(
            "invalid_simulation", "The simulation protocol needs a task name."
        )
    try:
        safe_task_folder_name(task_name)
    except ValueError as error:
        raise BridgeRequestError("invalid_simulation", str(error)) from error
    records = session.get("electrochemistry")
    events = session.get("events")
    if not isinstance(records, list) or not 1 <= len(records) <= 50_000:
        raise BridgeRequestError(
            "invalid_simulation",
            "Simulation must contain 1 to 50,000 EChem records.",
        )
    if not isinstance(events, list) or len(events) > 10_000:
        raise BridgeRequestError(
            "invalid_simulation", "Simulation events are missing or too numerous."
        )
    raman = session.get("raman", [])
    if not isinstance(raman, list) or raman:
        raise BridgeRequestError(
            "invalid_simulation",
            "The current simulator stores EChem only; Raman frames are not accepted.",
        )

    rows: list[list[Any]] = []
    previous_elapsed = -math.inf
    for index, record in enumerate(records):
        if not isinstance(record, Mapping):
            raise BridgeRequestError(
                "invalid_simulation", f"EChem record {index} is invalid."
            )
        elapsed = _finite_number(record.get("elapsed_s"), f"record {index} elapsed_s")
        assert elapsed is not None
        if elapsed <= previous_elapsed:
            raise BridgeRequestError(
                "invalid_simulation",
                "EChem timestamps must be strictly increasing.",
            )
        previous_elapsed = elapsed
        source = record.get("source_technique")
        if not isinstance(source, str) or not re.fullmatch(r"[a-z0-9_-]{1,64}", source):
            raise BridgeRequestError(
                "invalid_simulation",
                f"EChem record {index} has an invalid technique.",
            )
        step_index = _finite_number(
            record.get("step_index"), f"record {index} step_index", nullable=True
        )
        if step_index is not None and not step_index.is_integer():
            raise BridgeRequestError(
                "invalid_simulation",
                f"EChem record {index} step_index must be an integer.",
            )
        rows.append(
            [
                index,
                elapsed,
                int(step_index) if step_index is not None else None,
                source,
                _finite_number(
                    record.get("potential_v"),
                    f"record {index} potential_v",
                    nullable=True,
                ),
                _finite_number(
                    record.get("current_a"),
                    f"record {index} current_a",
                    nullable=True,
                ),
                _finite_number(
                    record.get("chronocoulometry_c"),
                    f"record {index} chronocoulometry_c",
                    nullable=True,
                ),
            ]
        )
    for index, event in enumerate(events):
        if not isinstance(event, Mapping):
            raise BridgeRequestError(
                "invalid_simulation", f"Simulation event {index} is invalid."
            )
        _finite_number(event.get("elapsed_s"), f"event {index} elapsed_s")

    instruments = session.get("instruments")
    electrochemistry_instrument = (
        instruments.get("electrochemistry")
        if isinstance(instruments, Mapping)
        else None
    )
    instrument_model = (
        electrochemistry_instrument.get("model", "CHI 760")
        if isinstance(electrochemistry_instrument, Mapping)
        else "CHI 760"
    )

    try:
        json.dumps(session, allow_nan=False)
        store = RunDataStore(storage_root)
        writer = store.create_simulation_trial(task_name.strip())
        writer.write_protocol_once(protocol)
        writer.write_simulation_session_once(session)
        output = io.StringIO(newline="")
        csv_writer = csv.writer(output, lineterminator="\n")
        csv_writer.writerow(
            [
                "sequence",
                "elapsed_s",
                "step_index",
                "source_technique",
                "potential_v",
                "current_a",
                "chronocoulometry_c",
            ]
        )
        csv_writer.writerows(rows)
        writer.append_raw_output(output.getvalue().encode("utf-8"))
        for event in events:
            writer.append_event(event)
        saved_at = datetime.now(timezone.utc).isoformat()
        failed = session["terminal_state"] == "simulated_failed"
        simulator = session.get("simulator")
        scenario = simulator.get("scenario") if isinstance(simulator, Mapping) else None
        simulator_version = (
            simulator.get("version", "unknown")
            if isinstance(simulator, Mapping)
            else "unknown"
        )
        writer.write_metadata(
            {
                "started_at": session.get("generated_at") or saved_at,
                "completed_at": saved_at,
                "units": {
                    "potential": "V",
                    "current": "A",
                    "time": "s",
                    "charge": "C",
                },
                "technique": "ECHEM_SIMULATION",
                "parameters": {"scenario": scenario},
                "software_version": (
                    f"SpectraLoop browser simulator {simulator_version}"
                ),
                "chi_identity": {"model": instrument_model, "simulated": True},
                "state": "error" if failed else "completed",
                **(
                    {
                        "error": session.get("run_error")
                        or session.get("cleanup_error")
                        or "Simulated failure"
                    }
                    if failed
                    else {}
                ),
            }
        )
    except BridgeRequestError:
        raise
    except (OSError, TypeError, ValueError) as error:
        raise BridgeRequestError(
            "simulation_save_failed",
            f"The simulation could not be saved: {error}",
            500,
        ) from error

    relative_folder = writer.paths.directory.relative_to(storage_root.resolve()).as_posix()
    return {
        "saved": True,
        "folder": relative_folder,
        "task_name": task_name.strip(),
        "trial": writer.paths.directory.name,
        "files": [
            "metadata.json",
            "protocol.json",
            "simulation_session.json",
            "echem_raw.csv",
            "events.jsonl",
        ],
    }


class SpectraLoopHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    # On Windows, HTTPServer's SO_REUSEADDR default can allow two independent
    # bridge processes to share one port and alternate requests/tokens.
    allow_reuse_address = False

    def __init__(
        self,
        server_address: tuple[str, int],
        state: BridgeState,
        *,
        site_directory: Path | None,
        allowed_origins: frozenset[str],
    ) -> None:
        self.bridge_state = state
        self.site_directory = site_directory.resolve() if site_directory else None
        self.allowed_origins = allowed_origins
        super().__init__(server_address, SpectraLoopRequestHandler)


class SpectraLoopRequestHandler(BaseHTTPRequestHandler):
    server: SpectraLoopHTTPServer
    server_version = "SpectraLoopBridge/0.1"

    def do_OPTIONS(self) -> None:  # noqa: N802 - stdlib handler API
        if not self._valid_host():
            self._json_error(HTTPStatus.BAD_REQUEST, "invalid_host", "Invalid Host header.")
            return
        origin = self.headers.get("Origin")
        if not self._origin_allowed(origin):
            self._json_error(HTTPStatus.FORBIDDEN, "origin_not_allowed", "Origin is not allowed.")
            return
        self.send_response(HTTPStatus.NO_CONTENT)
        self._cors_headers(origin)
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
        self.send_header("Access-Control-Max-Age", "600")
        self.send_header("Access-Control-Allow-Private-Network", "true")
        if self.headers.get("Access-Control-Request-Local-Network") == "true":
            self.send_header("Access-Control-Allow-Local-Network", "true")
        self.send_header("Content-Length", "0")
        self.end_headers()
        self.log_message(
            "bridge preflight origin=%r method=%r headers=%r private=%r local=%r",
            origin,
            self.headers.get("Access-Control-Request-Method"),
            self.headers.get("Access-Control-Request-Headers"),
            self.headers.get("Access-Control-Request-Private-Network"),
            self.headers.get("Access-Control-Request-Local-Network"),
        )

    def do_GET(self) -> None:  # noqa: N802 - stdlib handler API
        route = urlsplit(self.path).path
        if route == "/v1/status":
            if not self._authorize_api():
                return
            self._json_response(HTTPStatus.OK, self.server.bridge_state.status_payload())
            return
        self._serve_static(route)

    def do_POST(self) -> None:  # noqa: N802 - stdlib handler API
        if not self._authorize_api():
            return
        try:
            route = urlsplit(self.path).path
            payload = self._read_json(
                max_bytes=(
                    MAX_SIMULATION_SAVE_BYTES
                    if route == "/v1/simulations/save"
                    else MAX_REQUEST_BYTES
                )
            )
            if route == "/v1/storage/select":
                if payload:
                    raise BridgeRequestError(
                        "unexpected_payload", "Storage selection does not accept parameters."
                    )
                result = self.server.bridge_state.storage.select(
                    self.server.bridge_state.directory_picker
                )
                self._json_response(HTTPStatus.OK, {"storage": result})
                return
            if route == "/v1/simulations/save":
                storage_root = self.server.bridge_state.storage.root
                if storage_root is None or not storage_root.is_dir():
                    raise BridgeRequestError(
                        "storage_required", "Choose an available storage folder first."
                    )
                saved = _save_simulation_session(storage_root, payload.get("session"))
                self._json_response(HTTPStatus.OK, {"simulation": saved})
                return
            if route == "/v1/simulations/open-folder":
                storage_root = self.server.bridge_state.storage.root
                if storage_root is None or not storage_root.is_dir():
                    raise BridgeRequestError(
                        "storage_required", "Choose an available storage folder first."
                    )
                relative_value = payload.get("folder")
                if not isinstance(relative_value, str) or len(relative_value) > 500:
                    raise BridgeRequestError(
                        "invalid_simulation_folder",
                        "A saved simulation folder is required.",
                    )
                relative = PurePosixPath(relative_value)
                if (
                    relative.is_absolute()
                    or not relative.parts
                    or relative.parts[0] != "simulations"
                    or any(part in {"", ".", ".."} for part in relative.parts)
                ):
                    raise BridgeRequestError(
                        "invalid_simulation_folder",
                        "The requested folder must be a saved simulation trial.",
                    )
                try:
                    destination = storage_root.joinpath(*relative.parts).resolve(
                        strict=True
                    )
                    destination.relative_to(storage_root.resolve(strict=True))
                except (OSError, ValueError) as error:
                    raise BridgeRequestError(
                        "simulation_folder_unavailable",
                        "The saved simulation folder is no longer available.",
                        404,
                    ) from error
                if not destination.is_dir() or not destination.name.startswith("trial-"):
                    raise BridgeRequestError(
                        "invalid_simulation_folder",
                        "The requested folder is not a saved simulation trial.",
                    )
                self.server.bridge_state.folder_opener(destination)
                self._json_response(
                    HTTPStatus.OK,
                    {"simulation": {"opened": True, "folder": relative_value}},
                )
                return
            if route == "/v1/instrument/760e/prepare":
                controller_760e = self.server.bridge_state.commissioning_760e
                if controller_760e is None:
                    raise BridgeRequestError(
                        "chi760e_commissioning_unavailable",
                        "The CHI 760E commissioning adapter is not configured.",
                        409,
                    )
                plan = payload.get("plan")
                if not isinstance(plan, Mapping):
                    raise BridgeRequestError(
                        "invalid_plan", "A bounded CHI 760E CV plan is required."
                    )
                task_name = payload.get("task_name")
                if not isinstance(task_name, str) or not task_name.strip():
                    raise BridgeRequestError(
                        "task_name_required",
                        "A task name is required to organize the saved trial.",
                    )
                storage_root = self.server.bridge_state.storage.root
                if storage_root is None or not storage_root.is_dir():
                    raise BridgeRequestError(
                        "storage_required", "Choose an available storage folder first."
                    )
                preparation = controller_760e.prepare(
                    plan, storage_root, task_name.strip()
                )
                self._json_response(
                    HTTPStatus.OK, {"preparation": preparation}
                )
                return
            if route == "/v1/instrument/760e/start":
                controller_760e = self.server.bridge_state.commissioning_760e
                if controller_760e is None:
                    raise BridgeRequestError(
                        "chi760e_commissioning_unavailable",
                        "The CHI 760E commissioning adapter is not configured.",
                        409,
                    )
                confirmations = payload.get("confirmations")
                if not isinstance(confirmations, Mapping):
                    raise BridgeRequestError(
                        "confirmations_required",
                        "All 760E internal-dummy safety confirmations are required.",
                    )
                missing = sorted(
                    key
                    for key in REQUIRED_760E_RUN_CONFIRMATIONS
                    if confirmations.get(key) is not True
                )
                if missing:
                    raise BridgeRequestError(
                        "confirmations_required",
                        f"Missing confirmations: {', '.join(missing)}.",
                    )
                preparation_token = payload.get("preparation_token")
                if not isinstance(preparation_token, str) or not preparation_token:
                    raise BridgeRequestError(
                        "preparation_required",
                        "Prepare the 760E run before starting it.",
                    )
                summary = controller_760e.preparation_summary(preparation_token)
                if not self.server.bridge_state.chi760e_experiment_approval(summary):
                    raise BridgeRequestError(
                        "local_approval_declined",
                        "The 760E run was not approved on the instrument computer.",
                        409,
                    )
                result = controller_760e.start(
                    preparation_token,
                    {**dict(confirmations), "commissioning_approved": True},
                )
                self._json_response(HTTPStatus.OK, {"run": result})
                return
            if route == "/v1/instrument/760e/status":
                controller_760e = self.server.bridge_state.commissioning_760e
                if controller_760e is None:
                    raise BridgeRequestError(
                        "chi760e_commissioning_unavailable",
                        "The CHI 760E commissioning adapter is not configured.",
                        409,
                    )
                job_id = payload.get("job_id")
                if not isinstance(job_id, str) or not job_id:
                    raise BridgeRequestError(
                        "job_id_required", "A CHI 760E job id is required."
                    )
                result = controller_760e.job_status(job_id)
                self._json_response(HTTPStatus.OK, {"run": result})
                return
            if route == "/v1/instrument/760e/stop":
                controller_760e = self.server.bridge_state.commissioning_760e
                if controller_760e is None:
                    raise BridgeRequestError(
                        "chi760e_commissioning_unavailable",
                        "The CHI 760E commissioning adapter is not configured.",
                        409,
                    )
                job_id = payload.get("job_id")
                if not isinstance(job_id, str) or not job_id:
                    raise BridgeRequestError(
                        "job_id_required", "A CHI 760E job id is required."
                    )
                result = controller_760e.stop(job_id)
                self._json_response(HTTPStatus.OK, {"run": result})
                return
            if route == "/v1/instrument/760e/result":
                controller_760e = self.server.bridge_state.commissioning_760e
                if controller_760e is None:
                    raise BridgeRequestError(
                        "chi760e_commissioning_unavailable",
                        "The CHI 760E commissioning adapter is not configured.",
                        409,
                    )
                job_id = payload.get("job_id")
                if not isinstance(job_id, str) or not job_id:
                    raise BridgeRequestError(
                        "job_id_required", "A CHI 760E job id is required."
                    )
                offset = payload.get("offset", 0)
                limit = payload.get("limit", 4096)
                result = controller_760e.result_page(job_id, offset, limit)
                self._json_response(HTTPStatus.OK, {"result": result})
                return
            if route == "/v1/instrument/760d/prepare":
                controller_760d = self.server.bridge_state.desktop_760d
                if controller_760d is None:
                    raise BridgeRequestError(
                        "desktop_adapter_unavailable",
                        "The CHI 760D desktop adapter is not configured.",
                        409,
                    )
                protocol = payload.get("protocol")
                if not isinstance(protocol, Mapping):
                    raise BridgeRequestError(
                        "invalid_protocol", "A validated protocol object is required."
                    )
                storage_root = self.server.bridge_state.storage.root
                if storage_root is None or not storage_root.is_dir():
                    raise BridgeRequestError(
                        "storage_required", "Choose an available storage folder first."
                    )
                preparation = controller_760d.prepare(protocol, storage_root)
                self._json_response(
                    HTTPStatus.OK, {"preparation": preparation}
                )
                return
            if route == "/v1/instrument/760d/run":
                controller_760d = self.server.bridge_state.desktop_760d
                if controller_760d is None:
                    raise BridgeRequestError(
                        "desktop_adapter_unavailable",
                        "The CHI 760D desktop adapter is not configured.",
                        409,
                    )
                confirmations = payload.get("confirmations")
                if not isinstance(confirmations, Mapping):
                    raise BridgeRequestError(
                        "confirmations_required",
                        "All 760D internal-dummy safety confirmations are required.",
                    )
                missing = sorted(
                    key
                    for key in REQUIRED_760D_RUN_CONFIRMATIONS
                    if confirmations.get(key) is not True
                )
                if missing:
                    raise BridgeRequestError(
                        "confirmations_required",
                        f"Missing confirmations: {', '.join(missing)}.",
                    )
                preparation_token = payload.get("preparation_token")
                if not isinstance(preparation_token, str) or not preparation_token:
                    raise BridgeRequestError(
                        "preparation_required", "Prepare the 760D run before starting it."
                    )
                summary = controller_760d.preparation_summary(preparation_token)
                if not self.server.bridge_state.experiment_approval(summary):
                    raise BridgeRequestError(
                        "local_approval_declined",
                        "The 760D run was not approved on the instrument computer.",
                        409,
                    )
                result = controller_760d.execute(preparation_token)
                self._json_response(HTTPStatus.OK, {"run": result})
                return
            if route == "/v1/instrument/discover":
                confirmations = payload.get("confirmations")
                if not isinstance(confirmations, Mapping):
                    raise BridgeRequestError(
                        "confirmations_required",
                        "All identity-only safety confirmations are required.",
                    )
                missing = sorted(
                    key
                    for key in REQUIRED_DISCOVERY_CONFIRMATIONS
                    if confirmations.get(key) is not True
                )
                if missing:
                    raise BridgeRequestError(
                        "confirmations_required",
                        f"Missing confirmations: {', '.join(missing)}.",
                    )
                gateway_status = self.server.bridge_state.gateway.public_status()
                if gateway_status.get("discovery_enabled") is not True:
                    blocker = gateway_status.get("blocker")
                    raise VendorEvidenceUnavailableError(
                        str(blocker) if blocker else "Verified discovery adapter is unavailable."
                    )
                if not self.server.bridge_state.discovery_approval():
                    raise BridgeRequestError(
                        "local_approval_declined",
                        "The identity check was not approved on the instrument computer.",
                        409,
                    )
                discovery_result = self.server.bridge_state.gateway.discover()
                self._json_response(
                    HTTPStatus.OK,
                    {
                        "connected": (
                            discovery_result.get("physical_connection_confirmed") is True
                        ),
                        "worker_connected": True,
                        "discovery": dict(discovery_result),
                    },
                )
                return
            self._json_error(HTTPStatus.NOT_FOUND, "not_found", "API route not found.")
        except BridgeRequestError as error:
            self._json_error(error.status, error.code, str(error))
        except VendorEvidenceUnavailableError as error:
            self._json_error(
                HTTPStatus.CONFLICT,
                "vendor_interface_unavailable",
                str(error),
            )
        except DesktopMacroError as error:
            self._json_error(
                HTTPStatus.CONFLICT,
                "chi760d_macro_blocked",
                str(error),
            )
        except CHI760ECommissioningError as error:
            self._json_error(
                HTTPStatus.CONFLICT,
                "chi760e_commissioning_blocked",
                str(error),
            )
        except (BackendStateError, InvalidVendorResponseError, VendorCallError, VendorCallTimeoutError) as error:
            self._json_error(
                HTTPStatus.BAD_GATEWAY,
                "instrument_discovery_failed",
                str(error),
            )
        except Exception:
            self._json_error(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                "bridge_error",
                "The local bridge encountered an unexpected error.",
            )

    def _authorize_api(self) -> bool:
        if not self._valid_host():
            self._json_error(HTTPStatus.BAD_REQUEST, "invalid_host", "Invalid Host header.")
            return False
        origin = self.headers.get("Origin")
        local_cookie_valid = self._local_cookie_valid(origin)
        if not self._origin_allowed(origin) and not local_cookie_valid:
            self._json_error(HTTPStatus.FORBIDDEN, "origin_not_allowed", "Origin is not allowed.")
            return False
        authorization = self.headers.get("Authorization", "")
        prefix = "Bearer "
        supplied = authorization[len(prefix) :] if authorization.startswith(prefix) else ""
        bearer_valid = bool(supplied) and hmac.compare_digest(
            supplied, self.server.bridge_state.token
        )
        if not bearer_valid and not local_cookie_valid:
            self._json_error(HTTPStatus.UNAUTHORIZED, "unauthorized", "Bridge token is missing or invalid.")
            return False
        return True

    def _local_cookie_valid(self, origin: str | None) -> bool:
        port = self.server.server_address[1]
        local_origins = {
            f"http://127.0.0.1:{port}",
            f"http://localhost:{port}",
        }
        same_origin_request = origin in local_origins
        if origin is None:
            fetch_site = self.headers.get("Sec-Fetch-Site", "").lower()
            referer = self.headers.get("Referer", "")
            parsed_referer = urlsplit(referer)
            referer_origin = (
                f"{parsed_referer.scheme}://{parsed_referer.netloc}"
                if parsed_referer.scheme and parsed_referer.netloc
                else ""
            )
            same_origin_request = (
                fetch_site == "same-origin" or referer_origin in local_origins
            )
        if not same_origin_request:
            return False
        cookie = SimpleCookie()
        try:
            cookie.load(self.headers.get("Cookie", ""))
        except Exception:
            return False
        morsel = cookie.get(BRIDGE_COOKIE_NAME)
        return morsel is not None and hmac.compare_digest(
            morsel.value, self.server.bridge_state.token
        )

    def _valid_host(self) -> bool:
        host = self.headers.get("Host", "").lower()
        port = self.server.server_address[1]
        return host in {
            f"127.0.0.1:{port}",
            f"localhost:{port}",
            "127.0.0.1" if port == 80 else "",
            "localhost" if port == 80 else "",
        }

    def _origin_allowed(self, origin: str | None) -> bool:
        return origin is not None and origin in self.server.allowed_origins

    def _read_json(self, *, max_bytes: int = MAX_REQUEST_BYTES) -> dict[str, Any]:
        content_type = self.headers.get("Content-Type", "")
        if content_type.split(";", 1)[0].strip().lower() != "application/json":
            raise BridgeRequestError(
                "invalid_content_type", "Content-Type must be application/json."
            )
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as error:
            raise BridgeRequestError("invalid_request", "Invalid Content-Length.") from error
        if length < 0 or length > max_bytes:
            raise BridgeRequestError("request_too_large", "Request body is too large.", 413)
        raw = self.rfile.read(length)
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise BridgeRequestError("invalid_json", "Request body must be valid JSON.") from error
        if not isinstance(payload, dict):
            raise BridgeRequestError("invalid_json", "Request JSON must be an object.")
        return payload

    def _serve_static(self, route: str) -> None:
        if not self._valid_host():
            self.send_error(HTTPStatus.BAD_REQUEST)
            return
        root = self.server.site_directory
        if root is None:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        relative = unquote(route).lstrip("/") or "index.html"
        candidate = (root / relative).resolve()
        try:
            candidate.relative_to(root)
        except ValueError:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        if not candidate.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        content = candidate.read_bytes()
        media_type = mimetypes.guess_type(candidate.name)[0] or "application/octet-stream"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", f"{media_type}; charset=utf-8" if media_type.startswith("text/") or media_type in {"application/javascript", "application/json"} else media_type)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        if candidate.suffix.lower() == ".html":
            self.send_header(
                "Set-Cookie",
                f"{BRIDGE_COOKIE_NAME}={self.server.bridge_state.token}; "
                "HttpOnly; SameSite=Strict; Path=/v1",
            )
        self.end_headers()
        self.wfile.write(content)

    def _json_response(self, status: int, payload: Mapping[str, Any]) -> None:
        content = json.dumps(payload, allow_nan=False, separators=(",", ":")).encode("utf-8")
        origin = self.headers.get("Origin")
        self.send_response(status)
        if self._origin_allowed(origin):
            self._cors_headers(origin)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(content)

    def _json_error(self, status: int, code: str, message: str) -> None:
        self._json_response(status, {"error": {"code": code, "message": message}})

    def _cors_headers(self, origin: str | None) -> None:
        if origin is None:
            return
        self.send_header("Access-Control-Allow-Origin", origin)
        self.send_header("Vary", "Origin")


def create_server(
    state: BridgeState,
    *,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    site_directory: str | Path | None = None,
    allowed_origins: frozenset[str] = DEFAULT_ALLOWED_ORIGINS,
) -> SpectraLoopHTTPServer:
    """Create a loopback server; binding to another interface is forbidden."""

    if host != DEFAULT_HOST:
        raise ValueError("SpectraLoop bridge may bind only to 127.0.0.1")
    if isinstance(port, bool) or not isinstance(port, int) or not 0 <= port <= 65535:
        raise ValueError("port must be an integer from 0 through 65535")
    root = Path(site_directory) if site_directory is not None else None
    if root is not None and not root.is_dir():
        raise ValueError(f"site directory does not exist: {root}")
    server = SpectraLoopHTTPServer(
        (host, port),
        state,
        site_directory=root,
        allowed_origins=allowed_origins,
    )
    actual_port = server.server_address[1]
    server.allowed_origins = frozenset(
        {
            *allowed_origins,
            f"http://127.0.0.1:{actual_port}",
            f"http://localhost:{actual_port}",
        }
    )
    return server


def _browser_url(base_url: str, token: str) -> str:
    parsed = urlsplit(base_url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("web URL must use http or https")
    if parsed.scheme == "http" and parsed.hostname not in {"127.0.0.1", "localhost"}:
        raise ValueError("non-loopback web URLs must use https")
    fragment = f"bridge_token={token}"
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, parsed.query, fragment))


def _runtime_path(environment_name: str, fallback: Path) -> Path:
    value = os.environ.get(environment_name)
    return Path(value).expanduser() if value else fallback


def _build_worker_gateway(arguments: argparse.Namespace) -> DiscoveryGateway:
    if arguments.disable_chi_worker:
        return UnavailableDiscoveryGateway(
            "The persistent CHI worker is disabled.",
            target=arguments.instrument_label,
        )
    config = WorkerLaunchConfig(
        python_executable=arguments.worker_python,
        worker_script=arguments.worker_script,
        sdk_directory=arguments.sdk_dir,
        runtime_directory=arguments.runtime_dir,
        dll_name=arguments.dll_name,
        enable_chi760e_commissioning=arguments.enable_chi760e_commissioning,
    )
    try:
        worker = PersistentSDKWorker(config, timeout_s=arguments.worker_timeout)
        if arguments.enable_chi760e_commissioning:
            return SDKWorkerCommissioningGateway(
                worker,
                target=arguments.instrument_label,
                execution_enabled=True,
            )
        return SDKWorkerDiscoveryGateway(
            worker,
            target=arguments.instrument_label,
        )
    except (VendorCallError, ValueError) as error:
        return UnavailableDiscoveryGateway(
            f"Persistent 32-bit CHI worker unavailable: {error}",
            target=arguments.instrument_label,
        )


def _close_gateway(gateway: DiscoveryGateway) -> None:
    close = getattr(gateway, "close", None)
    if callable(close):
        close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the SpectraLoop local bridge")
    worker_defaults = default_worker_launch_config()
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--site-dir", type=Path)
    parser.add_argument("--config", type=Path, default=default_config_path())
    parser.add_argument(
        "--start-page",
        choices=("setup", "echem"),
        default="setup",
        help="Bundled page to open when --web-url is not supplied.",
    )
    parser.add_argument(
        "--web-url",
        help="Optional deployed SpectraLoop setup URL; defaults to the bundled local UI.",
    )
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument(
        "--worker-python",
        type=Path,
        default=_runtime_path(
            "SPECTRALOOP_CHI_WORKER_PYTHON", worker_defaults.python_executable
        ),
    )
    parser.add_argument(
        "--worker-script",
        type=Path,
        default=_runtime_path(
            "SPECTRALOOP_CHI_WORKER_SCRIPT", worker_defaults.worker_script
        ),
    )
    parser.add_argument(
        "--sdk-dir",
        type=Path,
        default=_runtime_path("SPECTRALOOP_CHI_SDK_DIR", worker_defaults.sdk_directory),
    )
    parser.add_argument(
        "--runtime-dir",
        type=Path,
        default=_runtime_path(
            "SPECTRALOOP_CHI_RUNTIME_DIR", worker_defaults.runtime_directory
        ),
    )
    parser.add_argument(
        "--dll-name",
        default=os.environ.get("SPECTRALOOP_CHI_DLL", worker_defaults.dll_name),
    )
    parser.add_argument(
        "--instrument-label",
        default=os.environ.get("SPECTRALOOP_CHI_INSTRUMENT", "CHI 760E SDK"),
    )
    parser.add_argument(
        "--worker-timeout",
        type=float,
        default=DEFAULT_WORKER_TIMEOUT_S,
    )
    parser.add_argument("--disable-chi-worker", action="store_true")
    parser.add_argument(
        "--enable-chi760e-commissioning",
        action="store_true",
        help=(
            "Enable only the bounded CHI 760E internal-dummy CV worker workflow."
        ),
    )
    parser.add_argument(
        "--chi760d-exe",
        type=Path,
        default=_runtime_path(
            "SPECTRALOOP_CHI760D_EXE", default_chi760d_executable()
        ),
    )
    parser.add_argument(
        "--enable-chi760d-dummy",
        action="store_true",
        help="Enable only the bounded CHI 760D internal-dummy CV/wait series workflow.",
    )
    args = parser.parse_args(argv)
    if args.disable_chi_worker and args.enable_chi760e_commissioning:
        parser.error(
            "--disable-chi-worker and --enable-chi760e-commissioning cannot be combined"
        )
    if args.enable_chi760d_dummy and args.enable_chi760e_commissioning:
        parser.error(
            "760D and 760E commissioning modes cannot be enabled in one bridge"
        )

    token = secrets.token_urlsafe(32)
    site_directory = args.site_dir
    if site_directory is None:
        candidate = Path(__file__).resolve().parents[2] / "SpectraLoop"
        site_directory = candidate if candidate.is_dir() else None
    gateway = _build_worker_gateway(args)
    commissioning_760e = (
        gateway if isinstance(gateway, SDKWorkerCommissioningGateway) else None
    )
    state = BridgeState(
        token=token,
        storage=StorageSettings(args.config),
        gateway=gateway,
        commissioning_760e=commissioning_760e,
        desktop_760d=CHI760DDesktopController(
            args.chi760d_exe,
            execution_enabled=args.enable_chi760d_dummy,
        ),
    )
    try:
        server = create_server(
            state,
            port=args.port,
            site_directory=site_directory,
        )
    except OSError as error:
        _close_gateway(gateway)
        print(
            f"Could not start SpectraLoop bridge on 127.0.0.1:{args.port}: {error}"
        )
        print("Close the earlier bridge console, then run the launcher once.")
        return 2
    port = server.server_address[1]
    local_start_url = f"http://127.0.0.1:{port}/{args.start_page}.html"
    browser_url = _browser_url(args.web_url or local_start_url, token)
    print(f"SpectraLoop local bridge {BRIDGE_VERSION}")
    print(f"Listening only on http://127.0.0.1:{port}")
    if args.enable_chi760e_commissioning:
        print(
            "Mode: CHI 760E internal-dummy CV commissioning enabled; "
            "all other experiments are locked"
        )
    elif args.enable_chi760d_dummy:
        print("Mode: CHI 760D internal-dummy CV/wait series enabled; external-cell experiments are locked")
    else:
        print("Mode: SDK discovery only; experiments are disabled")
    if not args.no_browser:
        webbrowser.open(browser_url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        _close_gateway(gateway)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

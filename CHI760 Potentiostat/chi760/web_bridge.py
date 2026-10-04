"""Loopback-only web bridge for the SpectraLoop browser interface.

The bridge is deliberately small and dependency-free.  It gives a browser UI
an authenticated local boundary for storage selection and a future verified
instrument adapter without exposing the instrument computer to the network.

The default gateway is unavailable and performs zero hardware calls.  A live
gateway has to be supplied explicitly after the matching vendor interface has
been verified.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import hmac
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
import os
from pathlib import Path
import secrets
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
from .live_backend import CHI760ELiveBackend, LiveConnectionState


BRIDGE_VERSION = "0.1.0"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
MAX_REQUEST_BYTES = 64 * 1024
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
    ) -> None:
        self.blocker = blocker
        self.hardware_calls = 0

    def public_status(self) -> Mapping[str, Any]:
        return {
            "target": "CHI 760E",
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
ApprovalPrompt = Callable[[], bool]


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
                "Confirm CHI 760E identity check",
                "Allow one read-only instrument identity check?\n\n"
                "Confirm that no sample or electrochemical cell is connected, "
                "the electrode leads are safe, and the CHI cell output is off.\n\n"
                "This approval does not authorize an experiment.",
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
    discovery_approval: ApprovalPrompt = native_discovery_approval

    def status_payload(self) -> dict[str, Any]:
        return {
            "api_version": "v1",
            "service": {
                "name": "SpectraLoop local bridge",
                "version": BRIDGE_VERSION,
                "binding": "loopback_only",
            },
            "storage": self.storage.public_status(),
            "instrument": dict(self.gateway.public_status()),
            "safety": {
                "mode": "identity_discovery_only",
                "experiments_enabled": False,
                "raman_enabled": False,
                "laser_enabled": False,
                "automated_decisions_enabled": False,
                "local_confirmation_required": True,
            },
        }


class SpectraLoopHTTPServer(ThreadingHTTPServer):
    daemon_threads = True

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
        if self.headers.get("Access-Control-Request-Private-Network") == "true":
            self.send_header("Access-Control-Allow-Private-Network", "true")
        self.send_header("Content-Length", "0")
        self.end_headers()

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
            payload = self._read_json()
            route = urlsplit(self.path).path
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
                    {"connected": True, "discovery": dict(discovery_result)},
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
        if not self._origin_allowed(origin):
            self._json_error(HTTPStatus.FORBIDDEN, "origin_not_allowed", "Origin is not allowed.")
            return False
        authorization = self.headers.get("Authorization", "")
        prefix = "Bearer "
        supplied = authorization[len(prefix) :] if authorization.startswith(prefix) else ""
        if not supplied or not hmac.compare_digest(
            supplied, self.server.bridge_state.token
        ):
            self._json_error(HTTPStatus.UNAUTHORIZED, "unauthorized", "Bridge token is missing or invalid.")
            return False
        return True

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

    def _read_json(self) -> dict[str, Any]:
        content_type = self.headers.get("Content-Type", "")
        if content_type.split(";", 1)[0].strip().lower() != "application/json":
            raise BridgeRequestError(
                "invalid_content_type", "Content-Type must be application/json."
            )
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as error:
            raise BridgeRequestError("invalid_request", "Invalid Content-Length.") from error
        if length < 0 or length > MAX_REQUEST_BYTES:
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the SpectraLoop local bridge")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--site-dir", type=Path)
    parser.add_argument("--config", type=Path, default=default_config_path())
    parser.add_argument(
        "--web-url",
        help="Optional deployed SpectraLoop setup URL; defaults to the bundled local UI.",
    )
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args(argv)

    token = secrets.token_urlsafe(32)
    site_directory = args.site_dir
    if site_directory is None:
        candidate = Path(__file__).resolve().parents[2] / "SpectraLoop"
        site_directory = candidate if candidate.is_dir() else None
    state = BridgeState(
        token=token,
        storage=StorageSettings(args.config),
        gateway=UnavailableDiscoveryGateway(),
    )
    server = create_server(
        state,
        port=args.port,
        site_directory=site_directory,
    )
    port = server.server_address[1]
    local_setup_url = f"http://127.0.0.1:{port}/setup.html"
    browser_url = _browser_url(args.web_url or local_setup_url, token)
    print(f"SpectraLoop local bridge {BRIDGE_VERSION}")
    print(f"Listening only on http://127.0.0.1:{port}")
    print("Mode: identity discovery only; experiments are disabled")
    if not args.no_browser:
        webbrowser.open(browser_url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

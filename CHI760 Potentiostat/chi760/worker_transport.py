"""Persistent subprocess transport for the isolated 32-bit CHI SDK worker.

The local web bridge runs in the normal project Python process.  The legacy
``libec`` DLL must instead be hosted by a 32-bit Python process.  This module
keeps that helper process alive and exchanges one JSON object per line over
private stdin/stdout pipes.  No socket or network listener is created.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import json
import os
from pathlib import Path
import queue
import subprocess
import threading
from typing import Any, Mapping, Protocol

from .errors import VendorCallError, VendorCallTimeoutError


WORKER_PROTOCOL_VERSION = "0.1"
DEFAULT_WORKER_TIMEOUT_S = 10.0


class WorkerProtocolError(VendorCallError):
    """Raised when the private worker returns malformed or mismatched data."""


@dataclass(frozen=True)
class WorkerLaunchConfig:
    """Runtime-supplied worker paths; no computer-specific path is embedded."""

    python_executable: Path
    worker_script: Path
    sdk_directory: Path
    runtime_directory: Path
    dll_name: str = "libec760e.dll"

    def command(self) -> list[str]:
        return [
            str(self.python_executable),
            "-u",
            str(self.worker_script),
            "serve",
            "--sdk-dir",
            str(self.sdk_directory),
            "--runtime-dir",
            str(self.runtime_directory),
            "--dll-name",
            self.dll_name,
            "--parent-pid",
            str(os.getpid()),
        ]


def default_worker_launch_config() -> WorkerLaunchConfig:
    """Use the repository-local, ignored runtime assembled on this computer."""

    repository_root = Path(__file__).resolve().parents[2]
    runtime_root = repository_root / ".runtime"
    worker_runtime = runtime_root / "chi-worker"
    return WorkerLaunchConfig(
        python_executable=runtime_root / "python-x86" / "python.exe",
        worker_script=Path(__file__).resolve().with_name("sdk_worker.py"),
        sdk_directory=worker_runtime,
        runtime_directory=worker_runtime,
    )


class WorkerClient(Protocol):
    @property
    def running(self) -> bool: ...

    def start(self) -> Mapping[str, Any]: ...

    def request(
        self,
        command: str,
        *,
        payload: Mapping[str, Any] | None = None,
        timeout_s: float | None = None,
    ) -> Mapping[str, Any]: ...

    def close(self) -> None: ...


class PersistentSDKWorker:
    """Own one long-lived 32-bit helper process and serialize its requests."""

    def __init__(
        self,
        config: WorkerLaunchConfig,
        *,
        timeout_s: float = DEFAULT_WORKER_TIMEOUT_S,
    ) -> None:
        if isinstance(timeout_s, bool) or timeout_s <= 0:
            raise ValueError("timeout_s must be a positive number")
        self.config = config
        self.timeout_s = float(timeout_s)
        self._process: subprocess.Popen[str] | None = None
        self._responses: queue.Queue[object] = queue.Queue()
        self._request_lock = threading.Lock()
        self._lifecycle_lock = threading.Lock()
        self._next_request_id = 0
        self._stderr: deque[str] = deque(maxlen=20)
        self._last_status: Mapping[str, Any] | None = None

    @property
    def running(self) -> bool:
        process = self._process
        return process is not None and process.poll() is None

    @property
    def last_status(self) -> Mapping[str, Any] | None:
        return self._last_status

    def start(self) -> Mapping[str, Any]:
        with self._lifecycle_lock:
            if self.running:
                if self._last_status is None:
                    raise WorkerProtocolError("CHI worker has no startup status")
                return self._last_status
            self._validate_launch_files()
            creationflags = 0
            if os.name == "nt":
                creationflags = int(getattr(subprocess, "CREATE_NO_WINDOW", 0))
            try:
                self._process = subprocess.Popen(
                    self.config.command(),
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    bufsize=1,
                    cwd=str(self.config.worker_script.parent),
                    creationflags=creationflags,
                )
            except OSError as error:
                self._process = None
                raise WorkerProtocolError(
                    "The persistent 32-bit CHI worker could not be started"
                ) from error
            threading.Thread(
                target=self._read_stdout,
                name="chi-worker-stdout",
                daemon=True,
            ).start()
            threading.Thread(
                target=self._read_stderr,
                name="chi-worker-stderr",
                daemon=True,
            ).start()
        try:
            status = self.request("status")
        except Exception:
            self._terminate()
            raise
        self._last_status = status
        return status

    def request(
        self,
        command: str,
        *,
        payload: Mapping[str, Any] | None = None,
        timeout_s: float | None = None,
    ) -> Mapping[str, Any]:
        wait_s = self.timeout_s if timeout_s is None else float(timeout_s)
        if wait_s <= 0:
            raise ValueError("timeout_s must be positive")
        with self._request_lock:
            process = self._process
            if process is None or process.poll() is not None:
                raise WorkerProtocolError("The persistent CHI worker is not running")
            if process.stdin is None:
                raise WorkerProtocolError("The CHI worker input pipe is unavailable")
            self._next_request_id += 1
            request_id = self._next_request_id
            request_payload: dict[str, Any] = {
                "schema_version": WORKER_PROTOCOL_VERSION,
                "id": request_id,
                "command": command,
            }
            if payload:
                request_payload.update(payload)
            try:
                encoded = json.dumps(
                    request_payload,
                    allow_nan=False,
                    separators=(",", ":"),
                )
                process.stdin.write(encoded + "\n")
                process.stdin.flush()
            except (BrokenPipeError, OSError, ValueError) as error:
                self._terminate()
                raise WorkerProtocolError("The CHI worker request could not be sent") from error
            try:
                response = self._responses.get(timeout=wait_s)
            except queue.Empty as error:
                self._terminate()
                raise VendorCallTimeoutError(
                    f"CHI worker command {command!r} timed out"
                ) from error
            if isinstance(response, BaseException):
                self._terminate()
                raise WorkerProtocolError(str(response)) from response
            if not isinstance(response, Mapping):
                self._terminate()
                raise WorkerProtocolError("CHI worker returned a non-object response")
            if response.get("schema_version") != WORKER_PROTOCOL_VERSION:
                self._terminate()
                raise WorkerProtocolError("CHI worker protocol version mismatch")
            if response.get("id") != request_id:
                self._terminate()
                raise WorkerProtocolError("CHI worker response ID mismatch")
            if response.get("ok") is not True:
                message = response.get("error")
                raise WorkerProtocolError(
                    str(message) if message else "CHI worker rejected the request"
                )
            result = response.get("result")
            if not isinstance(result, Mapping):
                raise WorkerProtocolError("CHI worker response is missing its result")
            return result

    def close(self) -> None:
        with self._lifecycle_lock:
            process = self._process
            if process is None:
                return
        if process.poll() is None:
            try:
                self.request("shutdown", timeout_s=min(self.timeout_s, 2.0))
            except VendorCallError:
                pass
        try:
            process.wait(timeout=2.0)
        except subprocess.TimeoutExpired:
            self._terminate()
        finally:
            self._close_process_streams(process)
            self._process = None

    def _validate_launch_files(self) -> None:
        if not self.config.python_executable.is_file():
            raise WorkerProtocolError(
                "The repository-local 32-bit Python worker runtime is missing"
            )
        if not self.config.worker_script.is_file():
            raise WorkerProtocolError("The CHI worker script is missing")
        if not self.config.sdk_directory.is_dir():
            raise WorkerProtocolError("The configured CHI SDK directory is missing")
        if not self.config.runtime_directory.is_dir():
            raise WorkerProtocolError("The configured CHI runtime directory is missing")
        if Path(self.config.dll_name).name != self.config.dll_name:
            raise WorkerProtocolError("The CHI SDK DLL name must not contain a path")

    def _read_stdout(self) -> None:
        process = self._process
        if process is None or process.stdout is None:
            return
        try:
            for line in process.stdout:
                if not line.strip():
                    continue
                try:
                    self._responses.put(json.loads(line))
                except json.JSONDecodeError as error:
                    self._responses.put(
                        WorkerProtocolError("CHI worker emitted invalid JSON")
                    )
                    return
        finally:
            if process.poll() is not None:
                detail = self._stderr[-1] if self._stderr else "no diagnostic output"
                self._responses.put(
                    WorkerProtocolError(f"CHI worker exited unexpectedly: {detail}")
                )

    def _read_stderr(self) -> None:
        process = self._process
        if process is None or process.stderr is None:
            return
        for line in process.stderr:
            value = line.strip()
            if value:
                self._stderr.append(value)

    def _terminate(self) -> None:
        process = self._process
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2.0)
        if process is not None:
            self._close_process_streams(process)

    @staticmethod
    def _close_process_streams(process: subprocess.Popen[str]) -> None:
        for stream in (process.stdin, process.stdout, process.stderr):
            if stream is not None and not stream.closed:
                stream.close()


class SDKWorkerDiscoveryGateway:
    """Bridge-facing, discovery-only view of a persistent SDK worker."""

    def __init__(
        self,
        worker: WorkerClient,
        *,
        target: str = "CHI 760E SDK",
    ) -> None:
        self.worker = worker
        self.target = target
        self._lock = threading.Lock()
        self._status = dict(worker.start())
        self.hardware_calls = 0
        self.vendor_functions_called = 0

    def public_status(self) -> Mapping[str, Any]:
        ready = self._ready()
        blocker = None
        if not ready:
            if not self.worker.running:
                blocker = "The persistent 32-bit CHI worker is not running."
            else:
                blocker = str(self._status.get("error") or "CHI SDK preflight failed.")
        return {
            "target": self.target,
            "state": "sdk_worker_ready" if ready else "adapter_unavailable",
            "discovery_enabled": ready,
            "experiment_control_enabled": False,
            "hardware_calls": self.hardware_calls,
            "vendor_functions_called": self.vendor_functions_called,
            "worker_connected": self.worker.running,
            "worker_bitness": self._status.get("process_bitness"),
            "sdk_library_loaded": False,
            "physical_connection_confirmed": False,
            "blocker": blocker,
            "detail": (
                "Persistent 32-bit SDK worker ready; physical instrument identity "
                "is not confirmed."
                if ready
                else None
            ),
        }

    def discover(self) -> Mapping[str, Any]:
        with self._lock:
            if not self._ready():
                raise VendorCallError(
                    str(self.public_status().get("blocker") or "CHI worker is unavailable")
                )
            result = dict(
                self.worker.request(
                    "discover",
                    payload={
                        "confirmations": {
                            "identity_only": True,
                            "no_sample_connected": True,
                            "electrode_leads_safe": True,
                            "cell_output_off": True,
                        }
                    },
                )
            )
            calls = result.get("vendor_functions_called", 0)
            if isinstance(calls, int) and not isinstance(calls, bool) and calls > 0:
                self.vendor_functions_called += calls
            error = result.get("error")
            if error:
                raise VendorCallError(str(error))
            model = result.get("reported_model_series")
            if not isinstance(model, str) or not model.strip():
                raise VendorCallError("CHI SDK returned no model-series value")
            techniques = result.get("supported_techniques")
            if not isinstance(techniques, list):
                raise VendorCallError("CHI SDK returned invalid capability data")
            return {
                "identity": {
                    "model": model.strip(),
                    "serial_number": "Not provided by libec",
                    "firmware_version": "Not provided by libec",
                    "software_version": "libec SDK",
                },
                "capabilities": {"techniques": techniques},
                "worker": {
                    "persistent": True,
                    "process_bitness": result.get("process_bitness"),
                    "library_bitness": result.get("library_bitness"),
                    "library_sha256": result.get("library_sha256"),
                },
                "physical_connection_confirmed": False,
                "note": result.get("note"),
            }

    def close(self) -> None:
        self.worker.close()

    def _ready(self) -> bool:
        return (
            self.worker.running
            and self._status.get("ready_to_load") is True
            and self._status.get("process_bitness") == 32
            and self._status.get("library_bitness") == 32
            and self._status.get("error") is None
        )

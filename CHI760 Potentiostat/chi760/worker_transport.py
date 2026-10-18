"""Persistent subprocess transport for the isolated 32-bit CHI SDK worker.

The local web bridge runs in the normal project Python process.  The legacy
``libec`` DLL must instead be hosted by a 32-bit Python process.  This module
keeps that helper process alive and exchanges one JSON object per line over
private stdin/stdout pipes.  No socket or network listener is created.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from math import isfinite
import os
from pathlib import Path
import queue
import secrets
import subprocess
import threading
from typing import Any, Mapping, Protocol

from .data_store import RunDataStore, RunWriter
from .errors import VendorCallError, VendorCallTimeoutError


WORKER_PROTOCOL_VERSION = "0.1"
DEFAULT_WORKER_TIMEOUT_S = 10.0
REQUIRED_760E_COMMISSIONING_CONFIRMATIONS = frozenset(
    {
        "commissioning_approved",
        "target_is_760e",
        "no_other_chi_measurement_running",
        "chi_desktop_closed",
        "internal_dummy_cell_connected",
        "external_sample_disconnected",
        "electrode_leads_verified",
        "cell_output_confirmed_off",
    }
)
_CV_PLAN_FIELDS = frozenset(
    {
        "target_model",
        "initial_potential_v",
        "high_potential_v",
        "low_potential_v",
        "initial_scan_direction",
        "scan_rate_v_s",
        "potential_step_v",
        "quiet_time_s",
        "sweep_segments",
    }
)


class WorkerProtocolError(VendorCallError):
    """Raised when the private worker returns malformed or mismatched data."""


class CHI760ECommissioningError(ValueError):
    """Raised when a 760E commissioning request fails before worker dispatch."""


@dataclass(frozen=True)
class WorkerLaunchConfig:
    """Runtime-supplied worker paths; no computer-specific path is embedded."""

    python_executable: Path
    worker_script: Path
    sdk_directory: Path
    runtime_directory: Path
    dll_name: str = "libec760e.dll"
    enable_chi760e_commissioning: bool = False

    def command(self) -> list[str]:
        command = [
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
        if self.enable_chi760e_commissioning:
            command.append("--enable-chi760e-commissioning")
        return command


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


@dataclass
class Prepared760ECVRun:
    token: str
    task_name: str
    plan: dict[str, Any]
    writer: RunWriter
    prepared_at: datetime
    started_at: str | None = None
    job_id: str | None = None
    finalized: bool = False


class SDKWorkerCommissioningGateway(SDKWorkerDiscoveryGateway):
    """Bridge-facing controller for one explicitly enabled internal-dummy CV."""

    def __init__(
        self,
        worker: WorkerClient,
        *,
        target: str = "CHI 760E SDK",
        execution_enabled: bool = False,
    ) -> None:
        self.execution_enabled = execution_enabled
        self._commissioning_lock = threading.RLock()
        self._prepared: dict[str, Prepared760ECVRun] = {}
        self._active: Prepared760ECVRun | None = None
        self._last_job_status: dict[str, Any] | None = None
        super().__init__(worker, target=target)

    def public_status(self) -> Mapping[str, Any]:
        status = dict(super().public_status())
        ready = self._commissioning_ready()
        blocker = status.get("blocker")
        if blocker is None and not ready:
            if not self.execution_enabled:
                blocker = "The 760E commissioning mode was not enabled at bridge start."
            elif self._status.get("commissioning_mode_enabled") is not True:
                blocker = "The 32-bit worker commissioning mode is locked."
            else:
                blocker = str(
                    self._status.get("error")
                    or "The 760E worker did not pass commissioning preflight."
                )
        status.update(
            {
                "state": (
                    "running_internal_dummy"
                    if self._last_job_status is not None
                    and self._last_job_status.get("state")
                    in {"starting", "running", "stopping"}
                    else "ready_for_internal_dummy"
                    if ready
                    else status["state"]
                ),
                "experiment_control_enabled": ready,
                "experiment_scope": "internal_dummy_bounded_cv",
                "remote_stop_available": ready,
                "blocker": None if ready else blocker,
                "active": (
                    dict(self._last_job_status)
                    if self._last_job_status is not None
                    else None
                ),
            }
        )
        return status

    def prepare(
        self,
        plan: Mapping[str, Any],
        data_root: str | Path,
        task_name: str,
    ) -> dict[str, Any]:
        self._require_commissioning_ready()
        normalized = _normalize_760e_cv_plan(plan)
        root = Path(data_root).expanduser()
        if not root.is_absolute() or not root.is_dir():
            raise CHI760ECommissioningError(
                "Choose an available storage folder before preparing the 760E CV."
            )
        with self._commissioning_lock:
            if self._prepared:
                raise CHI760ECommissioningError(
                    "An unused 760E preparation already exists; restart the bridge to discard it."
                )
            if self._active is not None and not self._active.finalized:
                raise CHI760ECommissioningError(
                    "A 760E commissioning run is already active or awaiting finalization."
                )
            store = RunDataStore(root)
            store.ensure_layout()
            try:
                writer = store.create_task_trial(task_name)
            except ValueError as error:
                raise CHI760ECommissioningError(str(error)) from error
            except OSError as error:
                raise CHI760ECommissioningError(
                    "The task trial folder could not be reserved."
                ) from error
            normalized_task_name = task_name.strip()
            writer.write_protocol_once(
                {
                    "schema_version": "0.1",
                    "target_model": "760E",
                    "task_name": normalized_task_name,
                    "commissioning_plan": normalized,
                }
            )
            token = secrets.token_urlsafe(24)
            prepared = Prepared760ECVRun(
                token=token,
                task_name=normalized_task_name,
                plan=normalized,
                writer=writer,
                prepared_at=datetime.now(timezone.utc),
            )
            writer.append_instrument_trace(
                {
                    "operation": "prepare_chi760e_internal_dummy_cv",
                    "prepared_at": prepared.prepared_at.isoformat(),
                    "worker_command_sent": False,
                    "scope": "internal_dummy_bounded_cv",
                }
            )
            self._prepared[token] = prepared
        return {
            "preparation_token": token,
            "run_label": writer.paths.directory.name,
            "task_name": normalized_task_name,
            "task_folder": writer.paths.directory.parent.name,
            "summary": dict(normalized),
            "requires_local_approval": True,
            "remote_stop_available": True,
        }

    def preparation_summary(self, preparation_token: str) -> dict[str, Any]:
        with self._commissioning_lock:
            prepared = self._prepared.get(preparation_token)
            if prepared is None:
                raise CHI760ECommissioningError(
                    "The prepared 760E run is missing or already used."
                )
            return {
                "run_label": prepared.writer.paths.directory.name,
                "task_name": prepared.task_name,
                **prepared.plan,
            }

    def start(
        self,
        preparation_token: str,
        confirmations: Mapping[str, Any],
    ) -> dict[str, Any]:
        self._require_commissioning_ready()
        missing = sorted(
            name
            for name in REQUIRED_760E_COMMISSIONING_CONFIRMATIONS
            if confirmations.get(name) is not True
        )
        if missing:
            raise CHI760ECommissioningError(
                f"Missing 760E commissioning confirmations: {', '.join(missing)}."
            )
        with self._commissioning_lock:
            prepared = self._prepared.pop(preparation_token, None)
            if prepared is None:
                raise CHI760ECommissioningError(
                    "The prepared 760E run is missing or already used."
                )
            if self._active is not None and not self._active.finalized:
                raise CHI760ECommissioningError(
                    "A 760E commissioning run is already active."
                )
            started_at = datetime.now(timezone.utc).isoformat()
            prepared.started_at = started_at
            self.hardware_calls += 1
            try:
                result = dict(
                    self.worker.request(
                        "cv-start",
                        payload={
                            "plan": prepared.plan,
                            "confirmations": dict(confirmations),
                        },
                    )
                )
                job_id = result.get("job_id")
                if not isinstance(job_id, str) or not job_id:
                    raise WorkerProtocolError(
                        "CHI worker start response is missing its job id"
                    )
                prepared.job_id = job_id
                self._active = prepared
                self._last_job_status = {
                    **result,
                    "run_label": prepared.writer.paths.directory.name,
                }
                prepared.writer.write_metadata(
                    self._metadata(prepared, state="running")
                )
                prepared.writer.append_instrument_trace(
                    {
                        "operation": "start_chi760e_internal_dummy_cv",
                        "started_at": started_at,
                        "job_id": job_id,
                        "scope": "internal_dummy_bounded_cv",
                    }
                )
                return {
                    **self._last_job_status,
                    "started": True,
                    "remote_stop_available": True,
                }
            except Exception as error:
                prepared.writer.write_metadata(
                    self._metadata(prepared, state="error", error=str(error))
                )
                prepared.writer.append_instrument_trace(
                    {
                        "operation": "start_chi760e_internal_dummy_cv_failed",
                        "failed_at": datetime.now(timezone.utc).isoformat(),
                        "error": str(error),
                    }
                )
                prepared.finalized = True
                self._active = prepared
                raise

    def job_status(self, job_id: str) -> dict[str, Any]:
        with self._commissioning_lock:
            prepared = self._require_active_job(job_id)
            result = dict(
                self.worker.request("cv-status", payload={"job_id": job_id})
            )
            state = result.get("state")
            if state not in {
                "starting",
                "running",
                "stopping",
                "completed",
                "stopped",
                "error",
            }:
                raise WorkerProtocolError("CHI worker returned an invalid job state")
            public = {
                **result,
                "run_label": prepared.writer.paths.directory.name,
                "data_saved": prepared.finalized,
            }
            self._last_job_status = public
            if state in {"completed", "stopped", "error"} and not prepared.finalized:
                self._finalize(prepared, result)
                public["data_saved"] = prepared.finalized
                self._last_job_status = public
            return public

    def stop(self, job_id: str) -> dict[str, Any]:
        with self._commissioning_lock:
            prepared = self._require_active_job(job_id)
            self.hardware_calls += 1
            result = dict(
                self.worker.request("cv-stop", payload={"job_id": job_id})
            )
            public = {
                **result,
                "run_label": prepared.writer.paths.directory.name,
                "remote_stop_available": True,
            }
            self._last_job_status = public
            prepared.writer.append_instrument_trace(
                {
                    "operation": "stop_chi760e_internal_dummy_cv",
                    "requested_at": datetime.now(timezone.utc).isoformat(),
                    "job_id": job_id,
                }
            )
            return public

    def result_page(self, job_id: str, offset: int, limit: int) -> dict[str, Any]:
        if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
            raise CHI760ECommissioningError(
                "760E result offset must be a non-negative integer."
            )
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 4096:
            raise CHI760ECommissioningError(
                "760E result limit must be an integer from 1 to 4096."
            )
        with self._commissioning_lock:
            prepared = self._require_active_job(job_id)
            result = dict(
                self.worker.request(
                    "cv-result",
                    payload={"job_id": job_id, "offset": offset, "limit": limit},
                )
            )
            return {
                **result,
                "run_label": prepared.writer.paths.directory.name,
            }

    def _commissioning_ready(self) -> bool:
        return (
            self.execution_enabled
            and self._ready()
            and self._status.get("commissioning_mode_enabled") is True
            and self._status.get("experiments_enabled") is True
            and not self._status.get("missing_commissioning_exports")
        )

    def _require_commissioning_ready(self) -> None:
        if not self._commissioning_ready():
            blocker = self.public_status().get("blocker")
            raise CHI760ECommissioningError(
                str(blocker) if blocker else "760E commissioning is locked."
            )

    def _require_active_job(self, job_id: str) -> Prepared760ECVRun:
        if not isinstance(job_id, str) or not job_id:
            raise CHI760ECommissioningError("A 760E job id is required.")
        prepared = self._active
        if prepared is None or prepared.job_id != job_id:
            raise CHI760ECommissioningError("The 760E job id does not match.")
        return prepared

    def _finalize(
        self,
        prepared: Prepared760ECVRun,
        worker_status: Mapping[str, Any],
    ) -> None:
        state = worker_status.get("state")
        completed_at = datetime.now(timezone.utc).isoformat()
        error: str | None = None
        data_points = 0
        if state in {"completed", "stopped"}:
            if worker_status.get("result_available") is not True:
                error = "The worker finished without retrievable CV result data."
            else:
                try:
                    data_points = self._save_result(prepared)
                except (OSError, ValueError, VendorCallError) as result_error:
                    error = f"Could not save the CV result: {result_error}"
        else:
            error = str(worker_status.get("error") or "The CHI worker reported an error.")

        metadata_state = "error" if error else "completed"
        metadata = self._metadata(
            prepared,
            state=metadata_state,
            completed_at=completed_at,
            error=error,
        )
        metadata["worker_state"] = state
        metadata["data_points"] = data_points
        metadata["stopped_by_operator"] = state == "stopped"
        prepared.writer.write_metadata(metadata)
        prepared.writer.append_instrument_trace(
            {
                "operation": "finalize_chi760e_internal_dummy_cv",
                "completed_at": completed_at,
                "worker_state": state,
                "state": metadata_state,
                "data_points": data_points,
                "error": error,
            }
        )
        prepared.finalized = True

    def _save_result(self, prepared: Prepared760ECVRun) -> int:
        if prepared.job_id is None:
            raise ValueError("The prepared run has no worker job id.")
        offset = 0
        expected_total: int | None = None
        rows = ["potential_V,current_A\n"]
        while True:
            requested_offset = offset
            page = dict(
                self.worker.request(
                    "cv-result",
                    payload={
                        "job_id": prepared.job_id,
                        "offset": offset,
                        "limit": 4096,
                    },
                )
            )
            x_values = page.get("x_values")
            y_values = page.get("y_values")
            total = page.get("total")
            next_offset = page.get("next_offset")
            page_offset = page.get("offset")
            page_count = page.get("count")
            if (
                not isinstance(x_values, list)
                or not isinstance(y_values, list)
                or len(x_values) != len(y_values)
            ):
                raise ValueError("The worker returned malformed CV result channels.")
            if page_offset != requested_offset or page_count != len(x_values):
                raise ValueError("The worker returned inconsistent CV page metadata.")
            if isinstance(total, bool) or not isinstance(total, int) or not 0 <= total <= 65_535:
                raise ValueError("The worker returned an invalid CV result total.")
            if expected_total is None:
                expected_total = total
            elif total != expected_total:
                raise ValueError("The worker changed the CV result total between pages.")
            for potential, current in zip(x_values, y_values):
                if (
                    isinstance(potential, bool)
                    or isinstance(current, bool)
                    or not isfinite(float(potential))
                    or not isfinite(float(current))
                ):
                    raise ValueError("The worker returned non-finite CV result data.")
                rows.append(f"{float(potential):.9g},{float(current):.9g}\n")
            offset += len(x_values)
            if next_offset is None:
                break
            if (
                isinstance(next_offset, bool)
                or not isinstance(next_offset, int)
                or next_offset != offset
                or next_offset <= requested_offset
            ):
                raise ValueError("The worker returned an invalid CV result offset.")
        if expected_total is None or offset != expected_total:
            raise ValueError("The retrieved CV result count did not match its total.")
        prepared.writer.append_raw_output("".join(rows).encode("ascii"))
        return offset

    @staticmethod
    def _metadata(
        prepared: Prepared760ECVRun,
        *,
        state: str,
        completed_at: str | None = None,
        error: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "started_at": prepared.started_at or prepared.prepared_at.isoformat(),
            "units": {"potential": "V", "current": "A"},
            "technique": "CV",
            "parameters": prepared.plan,
            "software_version": "SpectraLoop-CHI760E-worker-0.1",
            "chi_identity": {
                "model": "CHI 760E",
                "verification": "operator_confirmed_target_and_model_specific_sdk",
            },
            "state": state,
        }
        if completed_at is not None:
            payload["completed_at"] = completed_at
        if error:
            payload["error"] = error
        return payload


def _normalize_760e_cv_plan(plan: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(plan, Mapping):
        raise CHI760ECommissioningError("The 760E CV plan must be an object.")
    unknown = sorted(set(plan) - _CV_PLAN_FIELDS)
    missing = sorted(_CV_PLAN_FIELDS - set(plan))
    if unknown:
        raise CHI760ECommissioningError(
            f"Unsupported 760E CV fields: {', '.join(unknown)}."
        )
    if missing:
        raise CHI760ECommissioningError(
            f"Missing 760E CV fields: {', '.join(missing)}."
        )
    if plan.get("target_model") != "760E":
        raise CHI760ECommissioningError("The commissioning target must be 760E.")
    if plan.get("initial_scan_direction") != "positive":
        raise CHI760ECommissioningError(
            "The first 760E commissioning CV must scan positive initially."
        )
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
        value = plan.get(name)
        if value is None or isinstance(value, bool):
            raise CHI760ECommissioningError(f"{name} must be a finite number.")
        try:
            number = float(value)
        except (TypeError, ValueError) as error:
            raise CHI760ECommissioningError(
                f"{name} must be a finite number."
            ) from error
        if not isfinite(number):
            raise CHI760ECommissioningError(f"{name} must be a finite number.")
        normalized[name] = number
    segments = plan.get("sweep_segments")
    if isinstance(segments, bool) or not isinstance(segments, int) or segments != 2:
        raise CHI760ECommissioningError(
            "The first 760E commissioning CV must use exactly two sweeps."
        )
    normalized["sweep_segments"] = segments
    if any(
        abs(normalized[name]) > 0.25
        for name in ("initial_potential_v", "high_potential_v", "low_potential_v")
    ):
        raise CHI760ECommissioningError(
            "The first 760E commissioning CV must stay within +/-0.25 V."
        )
    if not (
        normalized["low_potential_v"]
        < normalized["initial_potential_v"]
        < normalized["high_potential_v"]
    ):
        raise CHI760ECommissioningError(
            "Initial potential must be strictly between low and high."
        )
    if not 0.01 <= normalized["scan_rate_v_s"] <= 0.2:
        raise CHI760ECommissioningError(
            "760E commissioning scan rate must be from 0.01 to 0.2 V/s."
        )
    if not 0.001 <= normalized["potential_step_v"] <= 0.01:
        raise CHI760ECommissioningError(
            "760E commissioning potential step must be from 0.001 to 0.01 V."
        )
    if not 0.0 <= normalized["quiet_time_s"] <= 10.0:
        raise CHI760ECommissioningError(
            "760E commissioning quiet time must be from 0 to 10 seconds."
        )
    return normalized

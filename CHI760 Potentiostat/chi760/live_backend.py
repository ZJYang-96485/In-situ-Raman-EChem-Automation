"""Fail-closed CHI 760E live discovery boundary.

The installed 760E help documents a desktop command-line macro runner, but no
non-energizing identity or capability query.  This module therefore provides a
real, traceable boundary for a future verified adapter while refusing to start
the desktop executable, open COM3, or load a library with unresolved mappings.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from hashlib import sha256
from math import isfinite
from pathlib import Path
from time import monotonic
from typing import Any, Mapping, Protocol

from .errors import (
    BackendStateError,
    HardwareOperationBlockedError,
    InvalidVendorResponseError,
    VendorCallError,
    VendorCallTimeoutError,
    VendorEvidenceUnavailableError,
)
from .preflight import inspect_sdk_candidate
from .runtime_profile import (
    ELECTROCHEMISTRY_ONLY,
    HardwareOperation,
    RuntimeProfile,
)


class DiscoveryOperation(str, Enum):
    OPEN = "open"
    QUERY_MODEL = "query_model"
    QUERY_SERIAL = "query_serial"
    QUERY_FIRMWARE = "query_firmware"
    QUERY_SOFTWARE = "query_software"
    QUERY_CAPABILITIES = "query_capabilities"
    CLOSE = "close"


class LiveConnectionState(str, Enum):
    DISCONNECTED = "disconnected"
    CONNECTED = "connected"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class InstalledCHIEvidence:
    executable_path: str
    executable_sha256: str
    executable_architecture: str
    executable_bitness: int
    software_version: str
    help_path: str
    help_sha256: str
    documented_automation_mechanism: str
    read_only_identity_query_documented: bool


@dataclass(frozen=True)
class VerifiedDiscoveryMapping:
    """Exact identifiers supplied by matching vendor evidence.

    Identifiers are deliberately strings owned by a future transport adapter;
    this class does not assume DLL exports, COM members, serial messages, or
    executable switches.
    """

    interface_kind: str
    evidence_paths: tuple[str, ...]
    open_identifier: str | None = None
    model_identifier: str | None = None
    serial_identifier: str | None = None
    firmware_identifier: str | None = None
    software_identifier: str | None = None
    capabilities_identifier: str | None = None
    close_identifier: str | None = None

    @property
    def resolved(self) -> bool:
        identifiers = (
            self.open_identifier,
            self.model_identifier,
            self.serial_identifier,
            self.firmware_identifier,
            self.software_identifier,
            self.capabilities_identifier,
            self.close_identifier,
        )
        return bool(self.interface_kind and self.evidence_paths) and all(
            isinstance(identifier, str) and bool(identifier.strip())
            for identifier in identifiers
        )

    def identifier_for(self, operation: DiscoveryOperation) -> str | None:
        return {
            DiscoveryOperation.OPEN: self.open_identifier,
            DiscoveryOperation.QUERY_MODEL: self.model_identifier,
            DiscoveryOperation.QUERY_SERIAL: self.serial_identifier,
            DiscoveryOperation.QUERY_FIRMWARE: self.firmware_identifier,
            DiscoveryOperation.QUERY_SOFTWARE: self.software_identifier,
            DiscoveryOperation.QUERY_CAPABILITIES: self.capabilities_identifier,
            DiscoveryOperation.CLOSE: self.close_identifier,
        }[operation]


UNRESOLVED_INSTALLED_MAPPING = VerifiedDiscoveryMapping(
    interface_kind="desktop_executable_macro_runner",
    evidence_paths=("installed chi760e.chm: hidd_dialog_macro.htm",),
)


@dataclass(frozen=True)
class VendorResponse:
    ok: bool
    value: Any = None
    return_code: str | int | None = None
    error: str | None = None


class DiscoveryTransport(Protocol):
    """Internal adapter contract; it is not a claim about a vendor API."""

    def call(self, identifier: str, *, timeout_s: float) -> VendorResponse: ...


@dataclass(frozen=True)
class LiveTraceEvent:
    timestamp_utc: str
    operation: str
    vendor_identifier: str | None
    timeout_s: float
    return_code: str | int | None
    success: bool
    connection_state: str
    error: str | None

    def as_dict(self) -> dict[str, object]:
        return {
            "timestamp_utc": self.timestamp_utc,
            "operation": self.operation,
            "vendor_identifier": self.vendor_identifier,
            "timeout_s": self.timeout_s,
            "return_code": self.return_code,
            "success": self.success,
            "connection_state": self.connection_state,
            "error": self.error,
        }


class CHI760ELiveBackend:
    """Discovery-only live boundary with no built-in physical transport."""

    execution_mode = "live_discovery_only"

    def __init__(
        self,
        evidence: InstalledCHIEvidence,
        *,
        mapping: VerifiedDiscoveryMapping = UNRESOLVED_INSTALLED_MAPPING,
        transport: DiscoveryTransport | None = None,
        timeout_s: float = 5.0,
        runtime_profile: RuntimeProfile = ELECTROCHEMISTRY_ONLY,
    ) -> None:
        if isinstance(timeout_s, bool) or not isinstance(timeout_s, (int, float)):
            raise ValueError("timeout_s must be a positive finite number")
        if not isfinite(timeout_s) or timeout_s <= 0:
            raise ValueError("timeout_s must be a positive finite number")
        self.evidence = evidence
        self.mapping = mapping
        self.transport = transport
        self.timeout_s = float(timeout_s)
        self.runtime_profile = runtime_profile
        self._state = LiveConnectionState.DISCONNECTED
        self._hardware_calls = 0
        self._events: list[LiveTraceEvent] = []

    @property
    def connection_state(self) -> LiveConnectionState:
        return self._state

    @property
    def hardware_calls(self) -> int:
        return self._hardware_calls

    @property
    def trace_events(self) -> tuple[LiveTraceEvent, ...]:
        return tuple(self._events)

    def connect(self) -> bool:
        if self._state is not LiveConnectionState.DISCONNECTED:
            raise BackendStateError("live discovery session is not disconnected")
        self.runtime_profile.require(HardwareOperation.CHI_DISCOVERY, "CHI connect")
        if not self.mapping.resolved or self.transport is None:
            self._record_unresolved(DiscoveryOperation.OPEN)
            raise VendorEvidenceUnavailableError(
                "installed vendor evidence does not establish a non-energizing "
                "open/identity/capability/close sequence"
            )
        try:
            self._invoke(DiscoveryOperation.OPEN)
        except Exception:
            self._state = LiveConnectionState.DISCONNECTED
            raise
        self._state = LiveConnectionState.CONNECTED
        return True

    def query_identity(self) -> dict[str, str]:
        self._require_connected()
        try:
            values = {
                "model": self._required_text(DiscoveryOperation.QUERY_MODEL),
                "serial_number": self._required_text(DiscoveryOperation.QUERY_SERIAL),
                "firmware_version": self._required_text(
                    DiscoveryOperation.QUERY_FIRMWARE
                ),
                "software_version": self._required_text(
                    DiscoveryOperation.QUERY_SOFTWARE
                ),
            }
        except Exception:
            self._close_after_failure()
            raise
        return values

    def query_capabilities(self) -> Any:
        self._require_connected()
        try:
            response = self._invoke(DiscoveryOperation.QUERY_CAPABILITIES)
            return _validated_value(response.value, "capabilities")
        except Exception:
            self._close_after_failure()
            raise

    def disconnect(self) -> None:
        self._require_connected()
        try:
            self._invoke(DiscoveryOperation.CLOSE)
        finally:
            self._state = LiveConnectionState.DISCONNECTED

    def run_cv(self, **params: Any) -> dict[str, Any]:
        return self._block_experiment("CV")

    def run_it(self, **params: Any) -> dict[str, Any]:
        return self._block_experiment("i-t")

    def run_lsv(self, **params: Any) -> dict[str, Any]:
        return self._block_experiment("LSV")

    def run_eis(self, **params: Any) -> dict[str, Any]:
        return self._block_experiment("EIS/IMP")

    def run_ocp(self, **params: Any) -> dict[str, Any]:
        return self._block_experiment("OCP/OCPT")

    def run_ca(self, **params: Any) -> dict[str, Any]:
        return self._block_experiment("CA")

    def run_swv(self, **params: Any) -> dict[str, Any]:
        return self._block_experiment("SWV")

    def run_impe(self, **params: Any) -> dict[str, Any]:
        return self._block_experiment("IMPE")

    def run_step(self, **params: Any) -> dict[str, Any]:
        return self._block_experiment("STEP")

    def run_istep(self, **params: Any) -> dict[str, Any]:
        return self._block_experiment("ISTEP/CPCS")

    def prepare_ir_compensation(self, *_args: Any, **_kwargs: Any) -> None:
        self.runtime_profile.require(
            HardwareOperation.IR_COMPENSATION, "iR compensation application"
        )
        raise HardwareOperationBlockedError("iR compensation remains blocked")

    def disable_ir_compensation(self) -> None:
        self.runtime_profile.require(
            HardwareOperation.IR_COMPENSATION, "iR compensation disable"
        )
        raise HardwareOperationBlockedError("iR compensation remains blocked")

    def cell_off(self) -> None:
        self.runtime_profile.require(HardwareOperation.CHI_EXPERIMENT, "cell control")
        raise HardwareOperationBlockedError("cell control remains blocked")

    def trace_payload(self) -> dict[str, object]:
        return {
            "schema_version": "0.1",
            "execution_mode": self.execution_mode,
            "target_model": "760E",
            "executable_sha256": self.evidence.executable_sha256,
            "architecture": self.evidence.executable_architecture,
            "bitness": self.evidence.executable_bitness,
            "software_version": self.evidence.software_version,
            "mapping_resolved": self.mapping.resolved,
            "connection_state": self._state.value,
            "hardware_calls": self._hardware_calls,
            "events": [event.as_dict() for event in self._events],
        }

    def _required_text(self, operation: DiscoveryOperation) -> str:
        response = self._invoke(operation)
        if not isinstance(response.value, str) or not response.value.strip():
            raise InvalidVendorResponseError(
                f"{operation.value} returned a missing or invalid value"
            )
        return response.value.strip()

    def _invoke(self, operation: DiscoveryOperation) -> VendorResponse:
        self.runtime_profile.require(HardwareOperation.CHI_DISCOVERY, operation.value)
        identifier = self.mapping.identifier_for(operation)
        if not self.mapping.resolved or not identifier or self.transport is None:
            self._record_unresolved(operation)
            raise VendorEvidenceUnavailableError(
                f"vendor mapping for {operation.value} is unresolved"
            )
        started = monotonic()
        self._hardware_calls += 1
        try:
            response = self.transport.call(identifier, timeout_s=self.timeout_s)
        except TimeoutError as error:
            self._record(operation, identifier, None, False, str(error) or "timeout")
            raise VendorCallTimeoutError(f"{operation.value} timed out") from error
        except Exception as error:
            self._record(operation, identifier, None, False, str(error))
            raise VendorCallError(f"{operation.value} failed: {error}") from error
        elapsed = monotonic() - started
        if elapsed > self.timeout_s:
            self._record(operation, identifier, response.return_code, False, "timeout")
            raise VendorCallTimeoutError(f"{operation.value} exceeded its timeout")
        if response.return_code is None:
            self._record(operation, identifier, None, False, "missing return code")
            raise InvalidVendorResponseError(
                f"{operation.value} returned no return code"
            )
        if not response.ok:
            message = response.error or "vendor reported failure"
            self._record(operation, identifier, response.return_code, False, message)
            raise VendorCallError(f"{operation.value} failed: {message}")
        try:
            _validate_operation_value(operation, response.value)
        except InvalidVendorResponseError as error:
            self._record(
                operation,
                identifier,
                response.return_code,
                False,
                str(error),
            )
            raise
        self._record(operation, identifier, response.return_code, True, None)
        return response

    def _close_after_failure(self) -> None:
        try:
            if self._state is LiveConnectionState.CONNECTED:
                self._invoke(DiscoveryOperation.CLOSE)
        except Exception:
            self._state = LiveConnectionState.UNKNOWN
        else:
            self._state = LiveConnectionState.DISCONNECTED

    def _block_experiment(self, technique: str) -> dict[str, Any]:
        self.runtime_profile.require(
            HardwareOperation.CHI_EXPERIMENT, f"{technique} experiment execution"
        )
        raise HardwareOperationBlockedError(
            f"{technique} execution is not enabled by this discovery-only backend"
        )

    def _require_connected(self) -> None:
        if self._state is not LiveConnectionState.CONNECTED:
            raise BackendStateError("open a verified live discovery session first")

    def _record_unresolved(self, operation: DiscoveryOperation) -> None:
        self._record(operation, self.mapping.identifier_for(operation), None, False,
                     "vendor mapping unresolved; no transport call made")

    def _record(
        self,
        operation: DiscoveryOperation,
        identifier: str | None,
        return_code: str | int | None,
        success: bool,
        error: str | None,
    ) -> None:
        self._events.append(
            LiveTraceEvent(
                timestamp_utc=datetime.now(timezone.utc).isoformat(),
                operation=operation.value,
                vendor_identifier=identifier,
                timeout_s=self.timeout_s,
                return_code=return_code,
                success=success,
                connection_state=self._state.value,
                error=error,
            )
        )


def inspect_installed_chi(
    executable_path: str | Path,
    help_path: str | Path,
    *,
    software_version: str,
) -> InstalledCHIEvidence:
    """Hash and inspect installed files without loading or executing them."""

    executable = inspect_sdk_candidate(executable_path)
    if executable.error or not executable.sha256:
        raise VendorEvidenceUnavailableError(
            f"cannot inspect CHI executable: {executable.error or 'missing hash'}"
        )
    help_file = Path(help_path)
    if not help_file.is_file():
        raise VendorEvidenceUnavailableError("installed CHI help file is missing")
    help_digest = sha256(help_file.read_bytes()).hexdigest()
    if not executable.architecture or not executable.bitness:
        raise VendorEvidenceUnavailableError("CHI executable architecture is unresolved")
    return InstalledCHIEvidence(
        executable_path=str(Path(executable_path)),
        executable_sha256=executable.sha256,
        executable_architecture=executable.architecture,
        executable_bitness=executable.bitness,
        software_version=software_version,
        help_path=str(help_file),
        help_sha256=help_digest,
        documented_automation_mechanism="desktop command-line macro runner",
        read_only_identity_query_documented=False,
    )


def _validated_value(value: Any, name: str) -> Any:
    if value is None:
        raise InvalidVendorResponseError(f"{name} response is missing")
    if isinstance(value, float) and not isfinite(value):
        raise InvalidVendorResponseError(f"{name} response contains a non-finite value")
    if isinstance(value, Mapping):
        if not value:
            raise InvalidVendorResponseError(f"{name} response is empty")
        return {
            str(key): _validated_value(item, name)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        if not value:
            raise InvalidVendorResponseError(f"{name} response is empty")
        return [_validated_value(item, name) for item in value]
    if isinstance(value, (str, int, float, bool)):
        if isinstance(value, str) and not value.strip():
            raise InvalidVendorResponseError(f"{name} response contains a blank value")
        return value
    raise InvalidVendorResponseError(
        f"{name} response has unsupported type {type(value).__name__}"
    )


def _validate_operation_value(operation: DiscoveryOperation, value: Any) -> None:
    if operation in {
        DiscoveryOperation.QUERY_MODEL,
        DiscoveryOperation.QUERY_SERIAL,
        DiscoveryOperation.QUERY_FIRMWARE,
        DiscoveryOperation.QUERY_SOFTWARE,
    }:
        if not isinstance(value, str) or not value.strip():
            raise InvalidVendorResponseError(
                f"{operation.value} returned a missing or invalid value"
            )
        return
    _validated_value(value, operation.value)

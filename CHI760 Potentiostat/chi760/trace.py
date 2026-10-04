"""JSON-safe command tracing and connection-free replay for CHI backends."""

from __future__ import annotations

from dataclasses import asdict, dataclass, is_dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
import json
from math import isfinite
from pathlib import Path
from time import monotonic_ns
from typing import Any, Callable, Mapping, Sequence


TRACE_SCHEMA_VERSION = "0.1"


class TraceValidationError(ValueError):
    """Raised when a stored trace is malformed or unsafe to replay."""


class TraceMismatchError(RuntimeError):
    """Raised when a replay call differs from the recorded operation."""


def json_safe(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return json_safe(asdict(value))
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        safe_mapping: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError("trace object keys must be strings")
            safe_mapping[key] = json_safe(item)
        return safe_mapping
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [json_safe(item) for item in value]
    if isinstance(value, float) and not isfinite(value):
        raise ValueError("trace floats must be finite")
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError(f"trace value of type {type(value).__name__} is not JSON-safe")


@dataclass(frozen=True)
class TraceEvent:
    sequence: int
    timestamp_utc: str
    monotonic_ns: int
    operation: str
    payload: dict[str, Any]
    result: dict[str, Any] | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "sequence": self.sequence,
            "timestamp_utc": self.timestamp_utc,
            "monotonic_ns": self.monotonic_ns,
            "operation": self.operation,
            "payload": json_safe(self.payload),
            "result": json_safe(self.result),
        }


class CommandTrace:
    """Append-only trace for planned or executed backend operations."""

    def __init__(
        self,
        *,
        execution_mode: str,
        wall_clock: Callable[[], datetime] | None = None,
        monotonic_clock: Callable[[], int] | None = None,
    ) -> None:
        if not execution_mode:
            raise ValueError("execution_mode is required")
        self.execution_mode = execution_mode
        self._wall_clock = wall_clock or (lambda: datetime.now(timezone.utc))
        self._monotonic_clock = monotonic_clock or monotonic_ns
        self._events: list[TraceEvent] = []

    @property
    def events(self) -> tuple[TraceEvent, ...]:
        return tuple(self._events)

    def record(
        self,
        operation: str,
        payload: Mapping[str, Any] | None = None,
        result: Mapping[str, Any] | None = None,
    ) -> TraceEvent:
        if not operation:
            raise ValueError("operation is required")
        safe_payload = json_safe(dict(payload or {}))
        safe_result = json_safe(dict(result)) if result is not None else None
        wall_time = self._wall_clock()
        if wall_time.tzinfo is None or wall_time.utcoffset() is None:
            raise ValueError("trace wall clock must be timezone-aware")
        monotonic_value = self._monotonic_clock()
        if isinstance(monotonic_value, bool) or not isinstance(monotonic_value, int):
            raise ValueError("trace monotonic clock must return an integer")
        if monotonic_value < 0:
            raise ValueError("trace monotonic clock cannot be negative")
        if self._events and monotonic_value < self._events[-1].monotonic_ns:
            raise ValueError("trace monotonic clock moved backwards")
        event = TraceEvent(
            sequence=len(self._events),
            timestamp_utc=wall_time.astimezone(timezone.utc).isoformat(),
            monotonic_ns=monotonic_value,
            operation=operation,
            payload=safe_payload,
            result=safe_result,
        )
        self._events.append(event)
        return event

    def to_payload(self) -> dict[str, Any]:
        return {
            "schema_version": TRACE_SCHEMA_VERSION,
            "execution_mode": self.execution_mode,
            "hardware_connected": False,
            "hardware_calls": 0,
            "events": [event.as_dict() for event in self._events],
        }

    def to_json(self, *, indent: int = 2) -> str:
        return json.dumps(self.to_payload(), indent=indent, sort_keys=True) + "\n"

    def write_json(self, path: str | Path) -> Path:
        destination = Path(path)
        destination.write_text(self.to_json(), encoding="utf-8")
        return destination


def validate_trace_payload(payload: Mapping[str, Any]) -> tuple[TraceEvent, ...]:
    if payload.get("schema_version") != TRACE_SCHEMA_VERSION:
        raise TraceValidationError("unsupported trace schema version")
    if payload.get("hardware_connected") is not False:
        raise TraceValidationError("trace must explicitly record hardware_connected=false")
    if payload.get("hardware_calls") != 0:
        raise TraceValidationError("connection-free trace must record zero hardware calls")
    execution_mode = payload.get("execution_mode")
    if not isinstance(execution_mode, str) or not execution_mode:
        raise TraceValidationError("trace must declare a non-empty execution_mode")
    raw_events = payload.get("events")
    if not isinstance(raw_events, list):
        raise TraceValidationError("trace events must be a list")
    events: list[TraceEvent] = []
    previous_monotonic_ns: int | None = None
    for index, raw in enumerate(raw_events):
        if not isinstance(raw, Mapping):
            raise TraceValidationError(f"trace event {index} must be an object")
        if raw.get("sequence") != index:
            raise TraceValidationError("trace event sequences must be contiguous")
        operation = raw.get("operation")
        timestamp = raw.get("timestamp_utc")
        monotonic_value = raw.get("monotonic_ns")
        event_payload = raw.get("payload")
        result = raw.get("result")
        if not isinstance(operation, str) or not operation:
            raise TraceValidationError(f"trace event {index} has an invalid operation")
        if not isinstance(timestamp, str) or not timestamp:
            raise TraceValidationError(f"trace event {index} has an invalid timestamp")
        try:
            parsed_timestamp = datetime.fromisoformat(timestamp)
        except ValueError as error:
            raise TraceValidationError(
                f"trace event {index} has an invalid timestamp"
            ) from error
        if parsed_timestamp.tzinfo is None or parsed_timestamp.utcoffset() is None:
            raise TraceValidationError(
                f"trace event {index} timestamp must include a timezone"
            )
        if parsed_timestamp.utcoffset() != timedelta(0):
            raise TraceValidationError(
                f"trace event {index} timestamp_utc must use a UTC offset"
            )
        if isinstance(monotonic_value, bool) or not isinstance(monotonic_value, int):
            raise TraceValidationError(f"trace event {index} has an invalid monotonic clock")
        if monotonic_value < 0:
            raise TraceValidationError(
                f"trace event {index} has a negative monotonic clock"
            )
        if previous_monotonic_ns is not None and monotonic_value < previous_monotonic_ns:
            raise TraceValidationError("trace monotonic clock values must not decrease")
        if not isinstance(event_payload, dict):
            raise TraceValidationError(f"trace event {index} has an invalid payload")
        if result is not None and not isinstance(result, dict):
            raise TraceValidationError(f"trace event {index} has an invalid result")
        try:
            safe_payload = json_safe(event_payload)
            safe_result = json_safe(result)
        except (TypeError, ValueError) as error:
            raise TraceValidationError(
                f"trace event {index} contains a non-JSON-safe value"
            ) from error
        events.append(
            TraceEvent(
                sequence=index,
                timestamp_utc=timestamp,
                monotonic_ns=monotonic_value,
                operation=operation,
                payload=safe_payload,
                result=safe_result,
            )
        )
        previous_monotonic_ns = monotonic_value
    return tuple(events)


def load_trace(path: str | Path) -> dict[str, Any]:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise TraceValidationError("trace root must be an object")
    validate_trace_payload(raw)
    return raw


class TraceReplayBackend:
    """Replay a zero-hardware trace and reject any command drift."""

    def __init__(self, payload: Mapping[str, Any]) -> None:
        self._events = validate_trace_payload(payload)
        self._cursor = 0
        self._logical_session_open = False
        self.hardware_calls = 0
        self.hardware_connected = False

    @property
    def remaining_events(self) -> int:
        return len(self._events) - self._cursor

    def _consume(self, operation: str, payload: Mapping[str, Any]) -> dict[str, Any] | None:
        if self._cursor >= len(self._events):
            raise TraceMismatchError(f"unexpected {operation}; trace is exhausted")
        event = self._events[self._cursor]
        safe_payload = json_safe(dict(payload))
        if event.operation != operation:
            raise TraceMismatchError(
                f"expected operation {event.operation!r}, received {operation!r}"
            )
        if event.payload != safe_payload:
            raise TraceMismatchError(
                f"payload mismatch for {operation}: expected {event.payload!r}, "
                f"received {safe_payload!r}"
            )
        self._cursor += 1
        return json_safe(event.result)

    def connect(self) -> bool:
        if self._logical_session_open:
            raise TraceMismatchError("replay session is already open")
        result = self._consume("connect", {})
        connected = bool(result and result.get("logical_session_open"))
        self._logical_session_open = connected
        return connected

    def disconnect(self) -> None:
        self._require_open()
        self._consume("disconnect", {})
        self._logical_session_open = False

    def _run(self, operation: str, params: Mapping[str, Any]) -> dict[str, Any]:
        self._require_open()
        result = self._consume(operation, {"parameters": dict(params)})
        if result is None:
            raise TraceMismatchError(f"recorded {operation} has no result")
        return result

    def run_cv(self, **params: Any) -> dict[str, Any]:
        return self._run("run_cv", params)

    def run_it(self, **params: Any) -> dict[str, Any]:
        return self._run("run_it", params)

    def run_lsv(self, **params: Any) -> dict[str, Any]:
        return self._run("run_lsv", params)

    def run_eis(self, **params: Any) -> dict[str, Any]:
        return self._run("run_eis", params)

    def run_ocp(self, **params: Any) -> dict[str, Any]:
        return self._run("run_ocp", params)

    def run_ca(self, **params: Any) -> dict[str, Any]:
        return self._run("run_ca", params)

    def run_swv(self, **params: Any) -> dict[str, Any]:
        return self._run("run_swv", params)

    def run_impe(self, **params: Any) -> dict[str, Any]:
        return self._run("run_impe", params)

    def run_step(self, **params: Any) -> dict[str, Any]:
        return self._run("run_step", params)

    def run_istep(self, **params: Any) -> dict[str, Any]:
        return self._run("run_istep", params)

    def prepare_ir_compensation(
        self,
        plan: Any,
        *,
        trial_ru_attempts_ohm: Sequence[Sequence[float | None]],
        observed_fractions: Sequence[float | None],
    ) -> dict[str, Any]:
        self._require_open()
        result = self._consume(
            "prepare_ir_compensation",
            {
                "plan": plan,
                "trial_ru_attempts_ohm": trial_ru_attempts_ohm,
                "observed_fractions": observed_fractions,
            },
        )
        if result is None:
            raise TraceMismatchError("recorded prepare_ir_compensation has no result")
        return result

    def disable_ir_compensation(self) -> dict[str, Any]:
        self._require_open()
        result = self._consume("disable_ir_compensation", {})
        if result is None:
            raise TraceMismatchError("recorded disable_ir_compensation has no result")
        return result

    def cell_off(self) -> dict[str, Any]:
        self._require_open()
        result = self._consume("cell_off", {})
        if result is None:
            raise TraceMismatchError("recorded cell_off has no result")
        return result

    def _require_open(self) -> None:
        if not self._logical_session_open:
            raise TraceMismatchError("open the replay session before requesting operations")

"""Append-safe local storage for electrochemistry runs and discovery records."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
import os
from pathlib import Path
import re
from typing import Any, Mapping
from uuid import uuid4


_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
_INVALID_WINDOWS_COMPONENT = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_TRIAL_DIRECTORY = re.compile(r"^trial-(\d{3,})$")
_WINDOWS_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{number}" for number in range(1, 10)),
    *(f"LPT{number}" for number in range(1, 10)),
}
_MAX_TASK_FOLDER_LENGTH = 80
_REQUIRED_METADATA = {
    "started_at",
    "units",
    "technique",
    "parameters",
    "software_version",
    "chi_identity",
    "state",
}
_VALID_STATES = {"running", "completed", "error"}


class RunDirectoryExistsError(FileExistsError):
    """Raised instead of overwriting an existing run directory."""


@dataclass(frozen=True)
class RunPaths:
    directory: Path
    metadata: Path
    protocol: Path
    echem_raw: Path
    echem_processed: Path
    instrument_trace: Path
    events: Path
    simulation_session: Path


class RunDataStore:
    """Create unique run directories without placing simulations in runs/."""

    def __init__(self, data_root: str | Path) -> None:
        self.data_root = Path(data_root)

    @property
    def runs_root(self) -> Path:
        return self.data_root / "runs"

    @property
    def discovery_root(self) -> Path:
        return self.data_root / "discovery"

    @property
    def simulations_root(self) -> Path:
        return self.data_root / "simulations"

    def ensure_layout(self) -> None:
        self.runs_root.mkdir(parents=True, exist_ok=True)
        self.discovery_root.mkdir(parents=True, exist_ok=True)
        self.simulations_root.mkdir(parents=True, exist_ok=True)

    def create_run(
        self,
        *,
        run_id: str | None = None,
        timestamp: datetime | None = None,
    ) -> "RunWriter":
        moment = timestamp or datetime.now().astimezone()
        if moment.tzinfo is None or moment.utcoffset() is None:
            raise ValueError("timestamp must be timezone-aware")
        identifier = run_id or uuid4().hex[:12]
        if not _RUN_ID.fullmatch(identifier):
            raise ValueError(
                "run_id must start with an alphanumeric character and contain "
                "only alphanumeric characters, underscores, or hyphens"
            )
        day_directory = self.runs_root / moment.strftime("%Y-%m-%d")
        run_directory = day_directory / (
            f"{moment.strftime('%Y%m%d_%H%M%S')}_{identifier}"
        )
        try:
            run_directory.mkdir(parents=True, exist_ok=False)
        except FileExistsError as error:
            raise RunDirectoryExistsError(
                f"refusing to overwrite existing run {run_directory}"
            ) from error
        return RunWriter(_paths_for(run_directory))

    def create_task_trial(
        self,
        task_name: str,
        *,
        timestamp: datetime | None = None,
    ) -> "RunWriter":
        """Reserve ``runs/date/task/trial-NNN`` without overwriting a trial.

        The task name is converted to one portable Windows path component. Trial
        numbers increase within each task and day, and the final directory
        creation is atomic so simultaneous preparations cannot share a trial.
        """

        return self._create_task_trial(
            self.runs_root,
            "runs",
            task_name,
            timestamp=timestamp,
        )

    def create_simulation_trial(
        self,
        task_name: str,
        *,
        timestamp: datetime | None = None,
    ) -> "RunWriter":
        """Reserve ``simulations/date/task/trial-NNN`` without overwriting."""

        return self._create_task_trial(
            self.simulations_root,
            "simulations",
            task_name,
            timestamp=timestamp,
        )

    def _create_task_trial(
        self,
        category_root: Path,
        category_name: str,
        task_name: str,
        *,
        timestamp: datetime | None,
    ) -> "RunWriter":
        moment = timestamp or datetime.now().astimezone()
        if moment.tzinfo is None or moment.utcoffset() is None:
            raise ValueError("timestamp must be timezone-aware")
        task_folder = safe_task_folder_name(task_name)
        task_directory = category_root / moment.strftime("%Y-%m-%d") / task_folder
        task_directory.mkdir(parents=True, exist_ok=True)
        try:
            task_directory.resolve(strict=True).relative_to(
                category_root.resolve(strict=True)
            )
        except ValueError as error:
            raise ValueError(
                f"task folder must remain inside the {category_name} directory"
            ) from error

        existing_numbers = [
            int(match.group(1))
            for child in task_directory.iterdir()
            if (match := _TRIAL_DIRECTORY.fullmatch(child.name)) is not None
        ]
        trial_number = max(existing_numbers, default=0) + 1
        while True:
            trial_directory = task_directory / f"trial-{trial_number:03d}"
            try:
                trial_directory.mkdir(exist_ok=False)
                return RunWriter(_paths_for(trial_directory))
            except FileExistsError:
                trial_number += 1

    def write_discovery_record(
        self,
        filename: str,
        payload: Mapping[str, Any],
    ) -> Path:
        """Write a read-only discovery result outside runs/ and simulations/."""

        if Path(filename).name != filename or not filename.endswith(".json"):
            raise ValueError("discovery filename must be a plain .json filename")
        self.discovery_root.mkdir(parents=True, exist_ok=True)
        destination = self.discovery_root / filename
        if destination.exists():
            raise FileExistsError(f"refusing to overwrite {destination}")
        _atomic_write_json(destination, payload, replace=False)
        return destination


class RunWriter:
    """Write one already-reserved run directory incrementally."""

    def __init__(self, paths: RunPaths) -> None:
        self.paths = paths

    def write_protocol_once(self, protocol: Mapping[str, Any]) -> Path:
        if self.paths.protocol.exists():
            raise FileExistsError(f"refusing to overwrite {self.paths.protocol}")
        _atomic_write_json(self.paths.protocol, protocol, replace=False)
        return self.paths.protocol

    def write_simulation_session_once(self, session: Mapping[str, Any]) -> Path:
        if self.paths.simulation_session.exists():
            raise FileExistsError(
                f"refusing to overwrite {self.paths.simulation_session}"
            )
        _atomic_write_json(self.paths.simulation_session, session, replace=False)
        return self.paths.simulation_session

    def write_metadata(self, metadata: Mapping[str, Any]) -> Path:
        missing = sorted(_REQUIRED_METADATA - set(metadata))
        if missing:
            raise ValueError(f"metadata is missing required fields: {', '.join(missing)}")
        state = metadata.get("state")
        if state not in _VALID_STATES:
            raise ValueError("metadata state must be running, completed, or error")
        if state == "completed" and not metadata.get("completed_at"):
            raise ValueError("completed metadata requires completed_at")
        if state == "error" and not metadata.get("error"):
            raise ValueError("error metadata requires a non-empty error field")
        _atomic_write_json(self.paths.metadata, metadata, replace=True)
        return self.paths.metadata

    def append_raw_output(self, chunk: bytes) -> Path:
        """Append vendor bytes exactly as received, then force them to disk."""

        if not isinstance(chunk, bytes) or not chunk:
            raise ValueError("raw output chunk must be non-empty bytes")
        _append_and_flush(self.paths.echem_raw, chunk)
        return self.paths.echem_raw

    def append_processed_output(self, chunk: bytes) -> Path:
        if not isinstance(chunk, bytes) or not chunk:
            raise ValueError("processed output chunk must be non-empty bytes")
        _append_and_flush(self.paths.echem_processed, chunk)
        return self.paths.echem_processed

    def append_instrument_trace(self, event: Mapping[str, Any]) -> Path:
        _append_json_line(self.paths.instrument_trace, event)
        return self.paths.instrument_trace

    def append_event(self, event: Mapping[str, Any]) -> Path:
        _append_json_line(self.paths.events, event)
        return self.paths.events


def safe_task_folder_name(task_name: str) -> str:
    """Return a readable, single-component Windows-safe task folder name."""

    if not isinstance(task_name, str) or not task_name.strip():
        raise ValueError("task name must be a non-empty string")
    cleaned = _INVALID_WINDOWS_COMPONENT.sub("-", task_name.strip())
    cleaned = re.sub(r"\s+", " ", cleaned)
    cleaned = re.sub(r"\s*-\s*", "-", cleaned)
    cleaned = re.sub(r"-{2,}", "-", cleaned).strip(" .-")
    if not cleaned:
        raise ValueError("task name must contain folder-safe characters")
    if len(cleaned) > _MAX_TASK_FOLDER_LENGTH:
        raise ValueError(
            f"task name must be at most {_MAX_TASK_FOLDER_LENGTH} characters after cleaning"
        )
    reserved_stem = cleaned.split(".", 1)[0].upper()
    if reserved_stem in _WINDOWS_RESERVED_NAMES:
        raise ValueError(f"task name {cleaned!r} is reserved by Windows")
    return cleaned


def _paths_for(directory: Path) -> RunPaths:
    return RunPaths(
        directory=directory,
        metadata=directory / "metadata.json",
        protocol=directory / "protocol.json",
        echem_raw=directory / "echem_raw.csv",
        echem_processed=directory / "echem_processed.csv",
        instrument_trace=directory / "instrument_trace.jsonl",
        events=directory / "events.jsonl",
        simulation_session=directory / "simulation_session.json",
    )


def _atomic_write_json(
    destination: Path,
    payload: Mapping[str, Any],
    *,
    replace: bool,
) -> None:
    rendered = (
        json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n"
    ).encode("utf-8")
    temporary = destination.with_name(f".{destination.name}.{uuid4().hex}.tmp")
    try:
        with temporary.open("xb") as stream:
            stream.write(rendered)
            stream.flush()
            os.fsync(stream.fileno())
        if replace:
            os.replace(temporary, destination)
        else:
            os.link(temporary, destination)
            temporary.unlink()
    finally:
        if temporary.exists():
            temporary.unlink()


def _append_and_flush(destination: Path, chunk: bytes) -> None:
    with destination.open("ab") as stream:
        stream.write(chunk)
        stream.flush()
        os.fsync(stream.fileno())


def _append_json_line(destination: Path, event: Mapping[str, Any]) -> None:
    rendered = (
        json.dumps(event, sort_keys=True, allow_nan=False, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")
    _append_and_flush(destination, rendered)

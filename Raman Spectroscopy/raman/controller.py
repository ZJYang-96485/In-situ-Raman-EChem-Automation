"""Connection-state and safety boundary for Raman acquisition."""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Mapping

from .backend import RamanBackend
from .errors import RamanNotConnectedError, RamanSafetyError
from .models import (
    ConnectionState,
    InstrumentIdentity,
    RamanAcquisitionPlan,
    RamanAcquisitionResult,
    TriggerMode,
)


class RamanController:
    """Coordinate a Raman backend without enabling laser or TTL control.

    The controller accepts only software-triggered plans until the physical
    trigger wiring, interlocks, and an instrument-specific backend have been
    validated. ``correlation_metadata`` offers a safe place to attach an
    electrochemistry run ID or other external state without coupling this
    package to a potentiostat implementation.
    """

    def __init__(self, backend: RamanBackend, *, live_connection_enabled: bool = False):
        self.backend = backend
        self._live_connection_enabled = live_connection_enabled
        self._connection_state = ConnectionState.DISCONNECTED
        self._identity: InstrumentIdentity | None = None

    @property
    def connected(self) -> bool:
        return self._connection_state is ConnectionState.CONNECTED

    @property
    def connection_state(self) -> ConnectionState:
        return self._connection_state

    @property
    def identity(self) -> InstrumentIdentity | None:
        return self._identity

    def connect(self) -> InstrumentIdentity:
        if self._connection_state is ConnectionState.UNKNOWN:
            raise RamanSafetyError(
                "Raman connection state is unknown after a backend failure; "
                "verify the instrument manually before trying again"
            )
        if self.connected:
            assert self._identity is not None
            return self._identity

        self._require_live_connection_authorization()
        try:
            identity = self.backend.connect()
        except Exception:
            self._identity = None
            try:
                self.backend.disconnect()
            except Exception:
                self._connection_state = ConnectionState.UNKNOWN
            else:
                self._connection_state = ConnectionState.DISCONNECTED
            raise

        self._identity = identity
        self._connection_state = ConnectionState.CONNECTED
        assert self._identity is not None
        return self._identity

    def disconnect(self) -> None:
        if self._connection_state is ConnectionState.DISCONNECTED:
            return
        if self._connection_state is ConnectionState.UNKNOWN:
            raise RamanSafetyError(
                "Raman connection state is unknown; verify the instrument "
                "manually before attempting another disconnect"
            )
        try:
            self.backend.disconnect()
        except Exception:
            self._connection_state = ConnectionState.UNKNOWN
            raise
        else:
            self._connection_state = ConnectionState.DISCONNECTED
            self._identity = None

    def acquire(
        self,
        plan: RamanAcquisitionPlan,
        *,
        correlation_metadata: Mapping[str, Any] | None = None,
    ) -> RamanAcquisitionResult:
        self._require_connection()
        if plan.trigger_mode is not TriggerMode.SOFTWARE:
            raise RamanSafetyError(
                "hardware-triggered acquisition is disabled until the trigger "
                "wiring and laser interlocks are verified"
            )

        result = self.backend.acquire(plan)
        if correlation_metadata:
            metadata = dict(result.metadata)
            metadata["correlation"] = dict(correlation_metadata)
            return replace(result, metadata=metadata)
        return result

    def abort(self) -> None:
        self._require_connection()
        self.backend.abort()

    def _require_connection(self) -> None:
        if not self.connected:
            raise RamanNotConnectedError(
                "connect the Raman backend before requesting an acquisition"
            )

    def _require_live_connection_authorization(self) -> None:
        if getattr(self.backend, "is_simulated", False):
            return
        if not self._live_connection_enabled:
            raise RamanSafetyError(
                "live Raman connection is disabled; enable it only after the "
                "hardware setup has been reviewed"
            )
        if not getattr(self.backend, "hardware_verified", False):
            raise RamanSafetyError(
                "live Raman connection requires a verified hardware profile"
            )

    def __enter__(self) -> "RamanController":
        self.connect()
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.disconnect()

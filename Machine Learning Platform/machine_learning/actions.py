"""Hard block automated actions on the electrochemistry-only execution node."""

from __future__ import annotations

from typing import Any, Callable


class AutomatedActionBlockedError(RuntimeError):
    """Raised before ML or decision automation can reach an action callback."""


def request_ml_action(_action: Callable[[], Any] | None = None) -> None:
    raise AutomatedActionBlockedError(
        "ML actions are blocked by the electrochemistry-only runtime profile"
    )


def request_automated_decision(_action: Callable[[], Any] | None = None) -> None:
    raise AutomatedActionBlockedError(
        "automated decision actions are blocked by the electrochemistry-only "
        "runtime profile"
    )

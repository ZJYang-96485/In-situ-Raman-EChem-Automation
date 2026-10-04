"""Errors specific to the flexible CHI 760-series controller."""


class UnsupportedTechniqueError(ValueError):
    """Raised when a selected instrument profile does not support a technique."""


class BackendStateError(RuntimeError):
    """Raised when backend operations are requested in an invalid state."""


class LiveExecutionUnavailableError(RuntimeError):
    """Raised when an unresolved live SDK operation is requested."""

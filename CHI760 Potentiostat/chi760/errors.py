"""Errors specific to the flexible CHI 760-series controller."""


class UnsupportedTechniqueError(ValueError):
    """Raised when a selected instrument profile does not support a technique."""


class BackendStateError(RuntimeError):
    """Raised when backend operations are requested in an invalid state."""


class LiveExecutionUnavailableError(RuntimeError):
    """Raised when an unresolved live SDK operation is requested."""


class HardwareOperationBlockedError(RuntimeError):
    """Raised before a runtime profile can dispatch a blocked hardware call."""


class VendorEvidenceUnavailableError(RuntimeError):
    """Raised when installed vendor material does not establish a safe call."""


class VendorCallError(RuntimeError):
    """Raised when a verified vendor discovery operation reports failure."""


class VendorCallTimeoutError(VendorCallError):
    """Raised when a verified vendor discovery operation exceeds its timeout."""


class InvalidVendorResponseError(VendorCallError):
    """Raised when a vendor response is missing required success evidence."""

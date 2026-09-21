"""Exceptions used by the connection-safe Raman subsystem."""


class RamanError(Exception):
    """Base class for Raman acquisition errors."""


class RamanNotConnectedError(RamanError):
    """Raised when an acquisition is requested before a backend is connected."""


class RamanHardwareNotConfiguredError(RamanError):
    """Raised when live hardware access is requested before it is implemented."""


class RamanSafetyError(RamanError):
    """Raised when a disabled laser or hardware-trigger path is requested."""


class RamanAcquisitionAbortedError(RamanError):
    """Raised when a backend reports that an acquisition was aborted."""

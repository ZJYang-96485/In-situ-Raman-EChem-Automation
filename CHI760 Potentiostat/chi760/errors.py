"""Errors specific to the flexible CHI 760-series controller."""


class UnsupportedTechniqueError(ValueError):
    """Raised when a selected instrument profile does not support a technique."""

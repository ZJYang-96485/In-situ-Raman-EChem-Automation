"""Pure calibration helpers; no optical hardware access is performed here."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Sequence


@dataclass(frozen=True)
class WavelengthCalibration:
    """Polynomial mapping from detector pixel to wavelength in nm.

    Coefficients are ordered from the constant term upward. For example,
    ``(500.0, 0.05)`` represents ``wavelength_nm = 500.0 + 0.05 * pixel``.
    Populate this only from a recorded, verified wavelength calibration.
    """

    coefficients_nm: Sequence[float]
    source: str | None = None

    def __post_init__(self) -> None:
        coefficients = tuple(float(value) for value in self.coefficients_nm)
        if not coefficients:
            raise ValueError("coefficients_nm cannot be empty")
        if not all(isfinite(value) for value in coefficients):
            raise ValueError("coefficients_nm values must be finite")
        if self.source is not None and not self.source.strip():
            raise ValueError("source cannot be blank")
        object.__setattr__(self, "coefficients_nm", coefficients)

    def wavelength_nm(self, pixel: float) -> float:
        """Evaluate the calibration polynomial at one detector pixel."""

        if (
            isinstance(pixel, bool)
            or not isinstance(pixel, (int, float))
            or not isfinite(pixel)
        ):
            raise ValueError("pixel must be finite")
        wavelength = 0.0
        for coefficient in reversed(self.coefficients_nm):
            wavelength = wavelength * pixel + coefficient
        if not isfinite(wavelength) or wavelength <= 0:
            raise ValueError(
                "calibration produced a non-finite or non-positive wavelength"
            )
        return wavelength

    def wavelengths_nm(self, pixels: Sequence[float]) -> tuple[float, ...]:
        """Evaluate the calibration polynomial for a pixel axis."""

        return tuple(self.wavelength_nm(float(pixel)) for pixel in pixels)


def raman_shift_cm1(
    excitation_wavelength_nm: float, scattered_wavelength_nm: float
) -> float:
    """Convert excitation/scattered wavelengths to Raman shift in cm^-1.

    Positive values describe Stokes shifts; negative values are retained for
    anti-Stokes data. This calculation does not substitute for calibration.
    """

    _require_positive_finite(excitation_wavelength_nm, "excitation_wavelength_nm")
    _require_positive_finite(scattered_wavelength_nm, "scattered_wavelength_nm")
    shift = 10_000_000.0 * (
        1.0 / excitation_wavelength_nm - 1.0 / scattered_wavelength_nm
    )
    if not isfinite(shift):
        raise ValueError("Raman-shift calculation produced a non-finite value")
    return shift


def _require_positive_finite(value: float, name: str) -> None:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not isfinite(value)
        or value <= 0
    ):
        raise ValueError(f"{name} must be finite and > 0")

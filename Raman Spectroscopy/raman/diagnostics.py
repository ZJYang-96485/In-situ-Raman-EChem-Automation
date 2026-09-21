"""Connection-free quality diagnostics for raw or preprocessed Raman frames."""

from dataclasses import dataclass
from statistics import median

from .models import SpectrumFrame


@dataclass(frozen=True)
class SpectrumDiagnostics:
    """Non-destructive health metrics for one spectrum."""

    point_count: int
    minimum_counts: float
    maximum_counts: float
    median_counts: float
    dynamic_range_counts: float
    saturated_point_count: int | None
    warnings: tuple[str, ...]


def diagnose_frame(
    frame: SpectrumFrame,
    *,
    saturation_threshold_counts: float | None = None,
) -> SpectrumDiagnostics:
    """Summarize quality without modifying spectral data.

    A saturation threshold is intentionally caller-supplied because detector
    range must be verified for the selected camera/readout configuration.
    """

    if saturation_threshold_counts is not None and saturation_threshold_counts <= 0:
        raise ValueError("saturation_threshold_counts must be > 0 when provided")

    counts = frame.intensity_counts
    minimum = min(counts)
    maximum = max(counts)
    median_counts = median(counts)
    warnings = []
    saturated_point_count = None
    if saturation_threshold_counts is not None:
        saturated_point_count = sum(
            count >= saturation_threshold_counts for count in counts
        )
        if saturated_point_count:
            warnings.append("saturation threshold reached")
    if maximum == minimum:
        warnings.append("flat spectrum")

    return SpectrumDiagnostics(
        point_count=len(counts),
        minimum_counts=minimum,
        maximum_counts=maximum,
        median_counts=median_counts,
        dynamic_range_counts=maximum - minimum,
        saturated_point_count=saturated_point_count,
        warnings=tuple(warnings),
    )

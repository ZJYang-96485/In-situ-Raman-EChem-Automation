"""Explicit, reproducible Raman preprocessing owned by the Raman module."""

from __future__ import annotations

from dataclasses import dataclass, replace
from math import isfinite
from statistics import median

from .models import SpectrumFrame


@dataclass(frozen=True)
class RamanPreprocessingPlan:
    """Conservative processing settings applied to raw CCD-count frames.

    The default plan is non-destructive. Users must choose each cleaning step,
    and applied settings are recorded in the returned frame metadata.
    """

    despike_threshold: float | None = None
    smoothing_window_points: int = 1
    baseline_mode: str = "none"
    normalization: str = "none"

    def __post_init__(self) -> None:
        if self.despike_threshold is not None and (
            not isfinite(self.despike_threshold) or self.despike_threshold <= 0
        ):
            raise ValueError("despike_threshold must be finite and > 0")
        if (
            isinstance(self.smoothing_window_points, bool)
            or not isinstance(self.smoothing_window_points, int)
            or self.smoothing_window_points < 1
            or self.smoothing_window_points % 2 == 0
        ):
            raise ValueError("smoothing_window_points must be an odd integer >= 1")
        if self.baseline_mode not in {"none", "edge_linear"}:
            raise ValueError("baseline_mode must be 'none' or 'edge_linear'")
        if self.normalization not in {"none", "max"}:
            raise ValueError("normalization must be 'none' or 'max'")


def preprocess_frame(
    frame: SpectrumFrame, plan: RamanPreprocessingPlan
) -> SpectrumFrame:
    """Return a processed copy while retaining the raw frame unchanged."""

    counts = list(frame.intensity_counts)
    applied_steps = []

    if plan.despike_threshold is not None:
        counts, replaced_count = _despike(counts, plan.despike_threshold)
        applied_steps.append(
            {"name": "median_despike", "replaced_points": replaced_count}
        )
    if plan.smoothing_window_points > 1:
        counts = _moving_average(counts, plan.smoothing_window_points)
        applied_steps.append(
            {"name": "moving_average", "window_points": plan.smoothing_window_points}
        )
    if plan.baseline_mode == "edge_linear":
        counts = _subtract_edge_linear_baseline(counts)
        applied_steps.append({"name": "edge_linear_baseline"})
    if plan.normalization == "max":
        maximum = max(counts)
        if maximum == 0:
            raise ValueError("cannot apply max normalization to an all-zero spectrum")
        counts = [count / maximum for count in counts]
        applied_steps.append({"name": "max_normalization"})

    metadata = dict(frame.metadata)
    metadata["preprocessing"] = {
        "plan": {
            "despike_threshold": plan.despike_threshold,
            "smoothing_window_points": plan.smoothing_window_points,
            "baseline_mode": plan.baseline_mode,
            "normalization": plan.normalization,
        },
        "applied_steps": applied_steps,
    }
    return replace(frame, intensity_counts=tuple(counts), metadata=metadata)


def _despike(counts: list[float], threshold: float) -> tuple[list[float], int]:
    if len(counts) < 3:
        return counts, 0
    cleaned = counts.copy()
    replaced_count = 0
    for index in range(1, len(counts) - 1):
        local_values = (counts[index - 1], counts[index], counts[index + 1])
        local_median = median(local_values)
        local_mad = median(abs(value - local_median) for value in local_values)
        scale = max(local_mad, 1e-12)
        if abs(counts[index] - local_median) > threshold * scale:
            cleaned[index] = local_median
            replaced_count += 1
    return cleaned, replaced_count


def _moving_average(counts: list[float], window_points: int) -> list[float]:
    half_window = window_points // 2
    return [
        sum(counts[max(0, index - half_window) : index + half_window + 1])
        / len(counts[max(0, index - half_window) : index + half_window + 1])
        for index in range(len(counts))
    ]


def _subtract_edge_linear_baseline(counts: list[float]) -> list[float]:
    if len(counts) == 1:
        return [0.0]
    start = counts[0]
    slope = (counts[-1] - start) / (len(counts) - 1)
    return [count - (start + slope * index) for index, count in enumerate(counts)]

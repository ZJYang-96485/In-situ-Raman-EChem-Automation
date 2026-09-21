"""Contracts for downstream Raman/electrochemistry analysis and ML work."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class AnalysisTask(str, Enum):
    EXPLORATORY = "exploratory"
    REGRESSION = "regression"
    CLASSIFICATION = "classification"
    ANOMALY_DETECTION = "anomaly_detection"


@dataclass(frozen=True)
class PreprocessedDatasetManifest:
    """Describes data handed off from the Raman module to downstream analysis.

    This workspace never cleans raw spectra. ``preprocessing_reference`` must
    point to the Raman plan/metadata used to create the features.
    """

    dataset_name: str
    source_session_ids: tuple[str, ...]
    feature_count: int
    preprocessing_reference: str
    includes_electrochemistry_metadata: bool = False

    def __post_init__(self) -> None:
        if not self.dataset_name.strip():
            raise ValueError("dataset_name must be provided")
        if not self.source_session_ids or any(
            not session_id.strip() for session_id in self.source_session_ids
        ):
            raise ValueError("source_session_ids must contain at least one ID")
        if self.feature_count < 1:
            raise ValueError("feature_count must be >= 1")
        if not self.preprocessing_reference.strip():
            raise ValueError("preprocessing_reference must be provided")


@dataclass(frozen=True)
class AnalysisProjectConfiguration:
    """Configuration only; fitting/evaluation implementations come later."""

    project_name: str
    task: AnalysisTask = AnalysisTask.EXPLORATORY
    target_name: str | None = None
    validation_fraction: float = 0.2

    def __post_init__(self) -> None:
        if not self.project_name.strip():
            raise ValueError("project_name must be provided")
        if not isinstance(self.task, AnalysisTask):
            object.__setattr__(self, "task", AnalysisTask(self.task))
        if not 0 < self.validation_fraction < 1:
            raise ValueError("validation_fraction must be between 0 and 1")
        if self.task in {AnalysisTask.REGRESSION, AnalysisTask.CLASSIFICATION}:
            if not self.target_name or not self.target_name.strip():
                raise ValueError("supervised tasks require target_name")

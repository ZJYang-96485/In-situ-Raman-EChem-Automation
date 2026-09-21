"""Validate that a preprocessed Raman dataset is ready for analysis."""

from .models import AnalysisProjectConfiguration, PreprocessedDatasetManifest


def validate_analysis_readiness(
    dataset: PreprocessedDatasetManifest,
    project: AnalysisProjectConfiguration,
) -> tuple[str, ...]:
    """Return human-readable blockers; this function performs no preprocessing."""

    blockers = []
    if dataset.feature_count < 2:
        blockers.append("at least two features are recommended for analysis")
    if project.task.value in {"regression", "classification"} and not project.target_name:
        blockers.append("supervised analysis requires a target name")
    if not dataset.includes_electrochemistry_metadata:
        blockers.append("electrochemistry metadata is not attached to this dataset")
    return tuple(blockers)

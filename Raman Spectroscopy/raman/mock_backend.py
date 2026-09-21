"""Deterministic, connection-free Raman backend for development and tests."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from math import exp
from time import monotonic

from .errors import RamanAcquisitionAbortedError, RamanNotConnectedError, RamanSafetyError
from .models import (
    InstrumentIdentity,
    RamanAcquisitionPlan,
    RamanAcquisitionResult,
    SpectrumFrame,
    TimingQuality,
    TriggerMode,
)


class MockRamanBackend:
    """Produce reproducible synthetic raw CCD frames without any hardware I/O."""

    is_simulated = True
    hardware_verified = True

    def __init__(self, pixel_count: int = 1024):
        if (
            isinstance(pixel_count, bool)
            or not isinstance(pixel_count, int)
            or pixel_count < 2
        ):
            raise ValueError("pixel_count must be an integer >= 2")
        self.pixel_count = pixel_count
        self._connected = False
        self._acquiring = False
        self._abort_requested = False
        self._session_count = 0
        self._identity = InstrumentIdentity(
            manufacturer="Andor (simulated)",
            model="Solis Raman acquisition system (simulated)",
        )

    def connect(self) -> InstrumentIdentity:
        self._connected = True
        self._abort_requested = False
        return self._identity

    def disconnect(self) -> None:
        if self._acquiring:
            raise RamanSafetyError("abort the mock acquisition before disconnecting")
        self._connected = False
        self._abort_requested = False

    def acquire(self, plan: RamanAcquisitionPlan) -> RamanAcquisitionResult:
        if not self._connected:
            raise RamanNotConnectedError("mock Raman backend is not connected")
        if plan.trigger_mode is not TriggerMode.SOFTWARE:
            raise RamanSafetyError("mock backend supports software triggering only")
        if self._acquiring:
            raise RamanSafetyError("mock Raman acquisition is already active")

        self._acquiring = True
        try:
            result_started_at = datetime.now(timezone.utc)
            result_monotonic_started_s = monotonic()
            frame_duration_s = (
                plan.parameters.exposure_time_s * plan.parameters.accumulations
            )
            frame_spacing_s = (
                frame_duration_s + plan.parameters.inter_spectrum_delay_s
            )
            frames = []
            for frame_index in range(plan.parameters.spectra_count):
                if self._abort_requested:
                    raise RamanAcquisitionAbortedError("mock acquisition was aborted")

                offset_s = frame_index * frame_spacing_s
                frame_started_at = result_started_at + timedelta(seconds=offset_s)
                frame_completed_at = frame_started_at + timedelta(
                    seconds=frame_duration_s
                )
                monotonic_started_s = result_monotonic_started_s + offset_s
                monotonic_completed_s = monotonic_started_s + frame_duration_s
                pixel_axis = tuple(float(pixel) for pixel in range(self.pixel_count))
                intensity_counts = self._synthetic_intensity(
                    pixel_axis,
                    plan.parameters.exposure_time_s,
                    plan.parameters.accumulations,
                    frame_index,
                )
                frames.append(
                    SpectrumFrame(
                        frame_index=frame_index,
                        pixel_axis=pixel_axis,
                        intensity_counts=intensity_counts,
                        started_at=frame_started_at,
                        completed_at=frame_completed_at,
                        monotonic_started_s=monotonic_started_s,
                        monotonic_completed_s=monotonic_completed_s,
                        metadata={"source": "mock", "axis": "raw_pixel"},
                    )
                )

            self._session_count += 1
            return RamanAcquisitionResult(
                session_id=f"mock-raman-{self._session_count:04d}",
                plan=plan,
                frames=frames,
                started_at=result_started_at,
                completed_at=frames[-1].completed_at,
                timing_quality=TimingQuality.SIMULATED,
                metadata={
                    "source": "mock",
                    "calibration": "not_applied",
                    "hardware_io": False,
                    "timing_model": "virtual_requested_duration",
                },
            )
        finally:
            self._acquiring = False
            self._abort_requested = False

    def abort(self) -> None:
        if self._acquiring:
            self._abort_requested = True

    @staticmethod
    def _synthetic_intensity(
        pixel_axis: tuple[float, ...],
        exposure_time_s: float,
        accumulations: int,
        frame_index: int,
    ) -> tuple[float, ...]:
        """Generate stable test data, not a physically calibrated spectrum."""

        pixel_count = len(pixel_axis)
        signal_scale = exposure_time_s * accumulations * 1000.0
        frame_offset = frame_index * 0.5
        peaks = (
            (0.23 * (pixel_count - 1), 0.018 * pixel_count, 0.90),
            (0.52 * (pixel_count - 1), 0.030 * pixel_count, 0.65),
            (0.79 * (pixel_count - 1), 0.022 * pixel_count, 1.10),
        )
        return tuple(
            100.0
            + 0.02 * pixel
            + frame_offset
            + signal_scale
            * sum(
                height * exp(-0.5 * ((pixel - center) / width) ** 2)
                for center, width, height in peaks
            )
            for pixel in pixel_axis
        )

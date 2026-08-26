from dataclasses import dataclass


@dataclass
class CVParameters:
    initial_potential: float
    high_potential: float
    low_potential: float
    scan_rate: float
    cycles: int = 1

    def __post_init__(self):
        if self.scan_rate <= 0:
            raise ValueError("scan_rate must be > 0")
        if self.cycles < 1:
            raise ValueError("cycles must be >= 1")


@dataclass
class LSVParameters:
    initial_potential: float
    final_potential: float
    scan_rate: float

    def __post_init__(self):
        if self.scan_rate <= 0:
            raise ValueError("scan_rate must be > 0")
        if self.initial_potential == self.final_potential:
            raise ValueError(
                "initial_potential and final_potential cannot be equal"
            )


@dataclass
class OCPParameters:
    duration: float
    sample_interval: float = 1.0

    def __post_init__(self):
        if self.duration <= 0:
            raise ValueError("duration must be > 0")
        if self.sample_interval <= 0:
            raise ValueError("sample_interval must be > 0")
        if self.sample_interval > self.duration:
            raise ValueError(
                "sample_interval cannot exceed duration"
            )


@dataclass
class ITParameters:
    potential: float
    duration: float
    sample_interval: float = 1.0

    def __post_init__(self):
        if self.duration <= 0:
            raise ValueError("duration must be > 0")
        if self.sample_interval <= 0:
            raise ValueError("sample_interval must be > 0")
        if self.sample_interval > self.duration:
            raise ValueError(
                "sample_interval cannot exceed duration"
            )


@dataclass
class EISParameters:
    dc_potential: float
    ac_amplitude: float
    start_frequency: float
    end_frequency: float
    points_per_decade: int = 10

    def __post_init__(self):
        if self.ac_amplitude <= 0:
            raise ValueError("ac_amplitude must be > 0")

        if self.start_frequency <= 0:
            raise ValueError("start_frequency must be > 0")

        if self.end_frequency <= 0:
            raise ValueError("end_frequency must be > 0")

        if self.start_frequency <= self.end_frequency:
            raise ValueError(
                "start_frequency must be greater than end_frequency"
            )

        if self.points_per_decade < 1:
            raise ValueError(
                "points_per_decade must be >= 1"
            )
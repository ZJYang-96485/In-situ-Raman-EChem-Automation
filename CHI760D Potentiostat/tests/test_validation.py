from chi760d.models import CVParameters, EISParameters


try:
    CVParameters(
        initial_potential=0.0,
        high_potential=1.0,
        low_potential=-0.2,
        scan_rate=-0.05,
        cycles=3
    )
except ValueError as error:
    print("CV validation passed:", error)


try:
    EISParameters(
        dc_potential=0.5,
        ac_amplitude=0.01,
        start_frequency=0.1,
        end_frequency=100000,
        points_per_decade=10
    )
except ValueError as error:
    print("EIS validation passed:", error)
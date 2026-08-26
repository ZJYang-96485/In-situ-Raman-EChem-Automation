from chi760d.controller import CHI760DController
from chi760d.mock_backend import MockCHI760D
from chi760d.models import (
    CVParameters,
    LSVParameters,
    OCPParameters,
    ITParameters,
    EISParameters
)

chi = CHI760DController(MockCHI760D())

chi.connect()

cv = CVParameters(
    initial_potential=0.0,
    high_potential=1.0,
    low_potential=-0.2,
    scan_rate=0.05,
    cycles=3
)

lsv = LSVParameters(
    initial_potential=0.0,
    final_potential=1.2,
    scan_rate=0.01
)

ocp = OCPParameters(
    duration=60
)

it = ITParameters(
    potential=0.5,
    duration=120
)

eis = EISParameters(
    dc_potential=0.5,
    ac_amplitude=0.01,
    start_frequency=100000,
    end_frequency=0.1,
    points_per_decade=10
)

print(chi.run_cv(cv))
print(chi.run_lsv(lsv))
print(chi.run_ocp(ocp))
print(chi.run_it(it))
print(chi.run_eis(eis))

chi.disconnect()
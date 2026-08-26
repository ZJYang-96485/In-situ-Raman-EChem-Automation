from chi760d.controller import CHI760DController
from chi760d.mock_backend import MockCHI760D
from chi760d.models import CVParameters

chi = CHI760DController(MockCHI760D())

chi.connect()

params = CVParameters(
    initial_potential=0.0,
    high_potential=1.0,
    low_potential=-0.2,
    scan_rate=0.05,
    cycles=3
)

result = chi.run_cv(params)

print(result)

chi.disconnect()
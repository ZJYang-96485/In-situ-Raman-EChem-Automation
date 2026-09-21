# CHI 760-series Potentiostat

This module is model-profiled so the project can move between CHI 760B, 760C,
760D, and 760E instruments without changing its public controller name.

```python
from chi760 import CHI760Controller, MockCHI760

potentiostat = CHI760Controller(MockCHI760(), model="760D")
```

The active profile gates calls before they reach the backend. The current
project-level automation surface is:

| Model | CV | i-t | LSV | EIS | OCP |
| --- | --- | --- | --- | --- | --- |
| 760B | ✓ | ✓ | — | — | — |
| 760C | ✓ | ✓ | — | ✓ | — |
| 760D | ✓ | ✓ | ✓ | ✓ | ✓ |
| 760E | ✓ | ✓ | — | ✓ | ✓ |

This reflects the vendor's documented 7xx libec automation matrix—not all
capabilities of the physical instrument or desktop software. The implementation
still uses a mock backend; live adapter selection and parameter mapping must be
validated for each installed unit.

Run tests from this directory:

```sh
python -B -m unittest discover -s tests -v
```

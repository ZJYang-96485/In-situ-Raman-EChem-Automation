"""Connection-free electrochemistry calculations."""

from __future__ import annotations

from math import isfinite
from typing import Sequence


def cumulative_charge_C(
    time_s: Sequence[float],
    current_A: Sequence[float],
    *,
    initial_charge_C: float = 0.0,
) -> tuple[float, ...]:
    """Integrate a CA current trace using the trapezoidal rule.

    This is the project's supported CC representation for a 760E: charge is a
    derived data series from a CA measurement, not a claimed libec technique.
    """

    if any(isinstance(value, bool) for value in (*time_s, *current_A)) or isinstance(initial_charge_C, bool):
        raise ValueError("time, current, and charge values cannot be booleans")
    times = tuple(float(value) for value in time_s)
    currents = tuple(float(value) for value in current_A)
    initial_charge = float(initial_charge_C)
    if not times:
        raise ValueError("time_s and current_A cannot be empty")
    if len(times) != len(currents):
        raise ValueError("time_s and current_A must have equal length")
    if not all(isfinite(value) for value in (*times, *currents, initial_charge)):
        raise ValueError("time, current, and charge values must be finite")
    if any(later <= earlier for earlier, later in zip(times, times[1:])):
        raise ValueError("time_s values must be strictly increasing")

    charge = [initial_charge]
    for index in range(1, len(times)):
        delta_t = times[index] - times[index - 1]
        charge.append(
            charge[-1] + 0.5 * (currents[index - 1] + currents[index]) * delta_t
        )
    return tuple(charge)


def chronocoulometry_from_ca_C(
    time_s: Sequence[float],
    current_A: Sequence[float],
    *,
    initial_charge_C: float = 0.0,
) -> tuple[float, ...]:
    """Return chronocoulometry (CC) as the integral of a CA current trace."""

    return cumulative_charge_C(
        time_s,
        current_A,
        initial_charge_C=initial_charge_C,
    )

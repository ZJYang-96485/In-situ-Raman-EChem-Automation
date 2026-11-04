"""Create a dependency-free SVG plot from a saved SpectraLoop E-Chem CSV."""

from __future__ import annotations

import argparse
import csv
import math
from dataclasses import dataclass
from html import escape
from pathlib import Path
from typing import Iterable, Sequence


@dataclass(frozen=True)
class CvPoint:
    potential_v: float
    current_a: float


COLORS = (
    "#1769aa",
    "#d97706",
    "#14866d",
    "#7c3aed",
    "#c2415b",
    "#3f6212",
)


def read_cv_points(path: Path) -> list[CvPoint]:
    points: list[CvPoint] = []
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        required = {"x_value", "current_A"}
        if not reader.fieldnames or not required.issubset(reader.fieldnames):
            raise ValueError("CSV must contain x_value and current_A columns")
        for row_number, row in enumerate(reader, start=2):
            if row.get("technique", "cv").strip().lower() != "cv":
                continue
            if row.get("x_name", "potential").strip().lower() != "potential":
                continue
            try:
                potential_v = float(row["x_value"])
                current_a = float(row["current_A"])
            except (TypeError, ValueError) as error:
                raise ValueError(f"Invalid numeric value on CSV row {row_number}") from error
            if not math.isfinite(potential_v) or not math.isfinite(current_a):
                raise ValueError(f"Non-finite numeric value on CSV row {row_number}")
            points.append(CvPoint(potential_v, current_a))
    if not points:
        raise ValueError("CSV contains no CV potential/current points")
    return points


def _split_half_sweeps(points: Sequence[CvPoint]) -> list[list[CvPoint]]:
    sweeps: list[list[CvPoint]] = []
    start = 0
    prior_direction = 0
    for index in range(1, len(points)):
        delta = points[index].potential_v - points[index - 1].potential_v
        direction = (delta > 0) - (delta < 0)
        if direction and prior_direction and direction != prior_direction:
            sweeps.append(list(points[start:index]))
            start = index
        if direction:
            prior_direction = direction
    sweeps.append(list(points[start:]))
    return [sweep for sweep in sweeps if sweep]


def _pair_cycles(points: Sequence[CvPoint]) -> list[list[CvPoint]]:
    sweeps = _split_half_sweeps(points)
    return [
        [point for sweep in sweeps[index : index + 2] for point in sweep]
        for index in range(0, len(sweeps), 2)
    ]


def _ticks(low: float, high: float, count: int = 6) -> Iterable[tuple[float, str]]:
    for index in range(count + 1):
        value = low + (high - low) * index / count
        yield value, f"{value:.3g}"


def render_cv_svg(points: Sequence[CvPoint], title: str) -> str:
    width, height = 1200, 760
    left, right, top, bottom = 112, 46, 122, 105
    plot_width = width - left - right
    plot_height = height - top - bottom

    potentials = [point.potential_v for point in points]
    currents_ua = [point.current_a * 1e6 for point in points]
    x_min, x_max = min(potentials), max(potentials)
    y_min, y_max = min(currents_ua), max(currents_ua)
    if x_min == x_max:
        x_min, x_max = x_min - 0.5, x_max + 0.5
    if y_min == y_max:
        y_min, y_max = y_min - 1.0, y_max + 1.0
    x_padding = (x_max - x_min) * 0.03
    y_padding = (y_max - y_min) * 0.07
    x_low, x_high = x_min - x_padding, x_max + x_padding
    y_low, y_high = y_min - y_padding, y_max + y_padding

    def sx(value: float) -> float:
        return left + (value - x_low) / (x_high - x_low) * plot_width

    def sy(value: float) -> float:
        return top + (y_high - value) / (y_high - y_low) * plot_height

    cycles = _pair_cycles(points)
    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-labelledby="title description">',
        f'<title id="title">{escape(title)}</title>',
        f'<desc id="description">Cyclic voltammogram with {len(points)} points and {len(cycles)} cycles.</desc>',
        '<rect width="100%" height="100%" fill="#f7fafc"/>',
        f'<text x="{left}" y="48" font-family="Segoe UI,Arial,sans-serif" font-size="30" font-weight="700" fill="#102a43">{escape(title)}</text>',
        f'<text x="{left}" y="80" font-family="Segoe UI,Arial,sans-serif" font-size="16" fill="#52687a">{len(points):,} points · {len(cycles)} cycles · {x_min:.3g} to {x_max:.3g} V · {y_min:.3g} to {y_max:.3g} µA</text>',
        f'<rect x="{left}" y="{top}" width="{plot_width}" height="{plot_height}" fill="#ffffff" stroke="#bfd0dc"/>',
    ]

    for value, label in _ticks(x_low, x_high):
        x = sx(value)
        parts.append(f'<line x1="{x:.2f}" y1="{top}" x2="{x:.2f}" y2="{top + plot_height}" stroke="#dce6ed"/>')
        parts.append(f'<text x="{x:.2f}" y="{top + plot_height + 30}" text-anchor="middle" font-family="Segoe UI,Arial,sans-serif" font-size="14" fill="#40566a">{label}</text>')
    for value, label in _ticks(y_low, y_high):
        y = sy(value)
        parts.append(f'<line x1="{left}" y1="{y:.2f}" x2="{left + plot_width}" y2="{y:.2f}" stroke="#dce6ed"/>')
        parts.append(f'<text x="{left - 15}" y="{y + 5:.2f}" text-anchor="end" font-family="Segoe UI,Arial,sans-serif" font-size="14" fill="#40566a">{label}</text>')

    if x_low <= 0 <= x_high:
        parts.append(f'<line x1="{sx(0):.2f}" y1="{top}" x2="{sx(0):.2f}" y2="{top + plot_height}" stroke="#93a8b7" stroke-width="1.4"/>')
    if y_low <= 0 <= y_high:
        parts.append(f'<line x1="{left}" y1="{sy(0):.2f}" x2="{left + plot_width}" y2="{sy(0):.2f}" stroke="#93a8b7" stroke-width="1.4"/>')

    for cycle_index, cycle in enumerate(cycles):
        color = COLORS[cycle_index % len(COLORS)]
        coordinates = " ".join(
            f"{sx(point.potential_v):.2f},{sy(point.current_a * 1e6):.2f}"
            for point in cycle
        )
        parts.append(f'<polyline points="{coordinates}" fill="none" stroke="{color}" stroke-width="2.2" stroke-linejoin="round" stroke-linecap="round"/>')

    legend_x = left + plot_width - max(118, len(cycles) * 82)
    for cycle_index in range(len(cycles)):
        color = COLORS[cycle_index % len(COLORS)]
        x = legend_x + cycle_index * 82
        parts.append(f'<line x1="{x}" y1="94" x2="{x + 24}" y2="94" stroke="{color}" stroke-width="4"/>')
        parts.append(f'<text x="{x + 31}" y="99" font-family="Segoe UI,Arial,sans-serif" font-size="14" fill="#40566a">C{cycle_index + 1}</text>')

    parts.extend(
        [
            f'<text x="{left + plot_width / 2:.2f}" y="{height - 34}" text-anchor="middle" font-family="Segoe UI,Arial,sans-serif" font-size="18" font-weight="600" fill="#243b53">Potential (V)</text>',
            f'<text x="31" y="{top + plot_height / 2:.2f}" transform="rotate(-90 31 {top + plot_height / 2:.2f})" text-anchor="middle" font-family="Segoe UI,Arial,sans-serif" font-size="18" font-weight="600" fill="#243b53">Current (µA)</text>',
            '</svg>',
        ]
    )
    return "\n".join(parts) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv_path", type=Path, help="Path to echem_raw.csv")
    parser.add_argument("--output", type=Path, help="Output SVG path")
    parser.add_argument("--title", help="Plot title")
    arguments = parser.parse_args()

    source = arguments.csv_path.resolve()
    output = (arguments.output or source.with_name("echem_cv.svg")).resolve()
    title = arguments.title or source.parent.parent.name
    output.write_text(render_cv_svg(read_cv_points(source), title), encoding="utf-8")
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

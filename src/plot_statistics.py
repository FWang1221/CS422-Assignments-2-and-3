"""Shared descriptive statistics for TCP telemetry plots."""

from __future__ import annotations

import math
import statistics

from matplotlib.axes import Axes


def number(row: dict[str, str], field: str) -> float | None:
    value = row.get(field, "").strip()
    if not value:
        return None
    parsed = float(value)
    return parsed if math.isfinite(parsed) else None


def pearson_label(x_values: list[float], y_values: list[float]) -> str:
    if len(x_values) < 3:
        return "N/A (<3 pairs)"
    if min(x_values) == max(x_values) or min(y_values) == max(y_values):
        return "N/A (constant)"
    return f"{statistics.correlation(x_values, y_values):.3f}"


def summary_rows(
    series: list[tuple[str, list[float], list[float]]],
    x_label: str,
    y_label: str,
    scatter: bool,
) -> list[list[str]]:
    rows: list[list[str]] = []
    for algorithm, x_values, y_values in series:
        correlation = pearson_label(x_values, y_values) if scatter else "--"
        metrics = [(x_label, x_values), (y_label, y_values)] if scatter else [(y_label, y_values)]
        for index, (metric, values) in enumerate(metrics):
            rows.append([
                algorithm,
                metric,
                f"{statistics.mean(values):.4g}" if values else "N/A",
                f"{statistics.median(values):.4g}" if values else "N/A",
                str(len(values)),
                correlation if index == 0 else "",
            ])
    return rows


def draw_statistics(
    axis: Axes,
    series: list[tuple[str, list[float], list[float]]],
    x_label: str,
    y_label: str,
    scatter: bool,
) -> None:
    axis.set_axis_off()
    table = axis.table(
        cellText=summary_rows(series, x_label, y_label, scatter),
        colLabels=["Algorithm", "Metric", "Mean", "Median", "n", "Pearson r"],
        colWidths=[0.17, 0.34, 0.12, 0.12, 0.06, 0.19],
        cellLoc="center",
        bbox=[0, 0.18, 1, 0.82],
    )
    table.auto_set_font_size(False)
    table.set_fontsize(8)
    axis.text(
        0, 0, "Sample-weighted; valid plotted samples pooled across repetitions. "
        "Pearson r is descriptive, not causal.",
        transform=axis.transAxes, fontsize=7, va="bottom",
    )

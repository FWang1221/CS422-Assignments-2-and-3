"""! @file plot_assignment2_question3.py
@brief Shared-axis comparison plots for Assignment 2 Question 3(a)."""

from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
from matplotlib import pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages

from src.plot_statistics import draw_statistics, number as _number

_SPECS = (
    ("Congestion window over time", "elapsed_s", "snd_cwnd_bytes", "Elapsed time (s)", "Congestion window (KiB)", 1, 1024, "line"),
    ("RTT over time", "elapsed_s", "srtt_us", "Elapsed time (s)", "Smoothed RTT (ms)", 1, 1000, "line"),
    ("Retransmission proxy over time", "elapsed_s", "total_retransmits_delta", "Elapsed time (s)", "Retransmissions (packets)", 1, 1, "line"),
    ("Goodput over time", "elapsed_s", "goodput_bps", "Elapsed time (s)", "Goodput (Mbps)", 1, 1_000_000, "line"),
    ("Congestion window vs goodput", "snd_cwnd_bytes", "goodput_bps", "Congestion window (KiB)", "Goodput (Mbps)", 1024, 1_000_000, "scatter"),
    ("RTT vs goodput", "srtt_us", "goodput_bps", "Smoothed RTT (ms)", "Goodput (Mbps)", 1000, 1_000_000, "scatter"),
    ("Retransmission proxy vs goodput", "total_retransmits_delta", "goodput_bps", "Retransmissions (packets)", "Goodput (Mbps)", 1, 1_000_000, "scatter"),
)


def _algorithm_colors(algorithms: list[str]) -> dict[str, str]:
    """! @brief Assign one Matplotlib color to each comparison algorithm."""
    return {algorithm: f"C{index}" for index, algorithm in enumerate(algorithms)}


def generate_comparison_plots(base_run_id: str, tables_directory: Path, output_directory: Path, destination: str | None = None) -> Path:
    """! @brief Produce shared-axis CUBIC/Reno/BBR PDF plots by destination.

    @param base_run_id Comparison coordinator base ID.
    @param tables_directory Directory containing comparison manifest and samples.
    @param output_directory Directory receiving the PDF.
    @param destination Optional representative-destination filter.
    @return Generated multi-page comparison PDF path. Without a filter, the PDF
    includes grouped pages for every completed destination.
    """
    manifest_path = tables_directory / f"comparison_manifest_{base_run_id}.csv"
    with manifest_path.open(newline="", encoding="utf-8") as handle:
        manifest_rows = [row for row in csv.DictReader(handle) if row["status"] == "completed"]
    if not manifest_rows:
        raise ValueError("comparison manifest has no completed runs")
    destinations = [destination] if destination is not None else list(dict.fromkeys(row["destination"] for row in manifest_rows))
    samples_by_destination: dict[str, dict[str, list[list[dict[str, str]]]]] = {}
    for representative in destinations:
        grouped: dict[str, list[list[dict[str, str]]]] = defaultdict(list)
        for row in manifest_rows:
            if row["destination"] != representative:
                continue
            with (tables_directory / f"samples_{row['run_id']}.csv").open(newline="", encoding="utf-8") as handle:
                samples = [sample for sample in csv.DictReader(handle) if sample["destination"] == representative]
            grouped[row["requested_algorithm"]].append(samples)
        if grouped:
            samples_by_destination[representative] = grouped
    if not samples_by_destination:
        raise ValueError(f"representative destination not found: {destination}")
    output_directory.mkdir(parents=True, exist_ok=True)
    suffix = f"_{destination.replace(':', '_')}" if destination is not None else ""
    plot_path = output_directory / f"comparison_plots_{base_run_id}{suffix}.pdf"
    with PdfPages(plot_path) as pdf:
        for representative, grouped in samples_by_destination.items():
            colors = _algorithm_colors(list(grouped))
            for title, x_field, y_field, x_label, y_label, x_scale, y_scale, style in _SPECS:
                scatter = style == "scatter"
                table_height = 0.6 + 0.28 * len(grouped) * (2 if scatter else 1)
                figure, (axis, statistics_axis) = plt.subplots(
                    2, 1, figsize=(10, 5.5 + table_height),
                    gridspec_kw={"height_ratios": [4, table_height]},
                )
                series = []
                for algorithm, runs in grouped.items():
                    pooled_x: list[float] = []
                    pooled_y: list[float] = []
                    for index, samples in enumerate(runs):
                        pairs = [(_number(sample, x_field), _number(sample, y_field)) for sample in samples]
                        pairs = [(x, y) for x, y in pairs if x is not None and y is not None]
                        x_values = [x / x_scale for x, _ in pairs]
                        y_values = [y / y_scale for _, y in pairs]
                        pooled_x.extend(x_values)
                        pooled_y.extend(y_values)
                        label = algorithm if index == 0 else None
                        if style == "line":
                            axis.plot(x_values, y_values, marker=".", linewidth=1.1, alpha=0.7, color=colors[algorithm], label=label)
                        else:
                            axis.scatter(x_values, y_values, s=16, alpha=0.55, color=colors[algorithm], label=label)
                    series.append((algorithm, pooled_x, pooled_y))
                axis.set_title(f"{title}\n{representative}, comparison {base_run_id}")
                axis.set_xlabel(x_label)
                axis.set_ylabel(y_label)
                axis.grid(True, alpha=0.3)
                axis.legend(title="Algorithm\n(each trace: one repetition)")
                draw_statistics(statistics_axis, series, x_label, y_label, scatter)
                figure.tight_layout()
                pdf.savefig(figure)
                plt.close(figure)
    return plot_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate shared-axis Assignment 2 Question 3 comparison plots.")
    parser.add_argument("base_run_id")
    parser.add_argument("--tables-dir", type=Path, default=Path("outputs/tables"))
    parser.add_argument("--output-dir", type=Path, default=Path("outputs/plots"))
    parser.add_argument("--destination", default=None)
    arguments = parser.parse_args()
    print(generate_comparison_plots(arguments.base_run_id, arguments.tables_dir, arguments.output_dir, arguments.destination))


if __name__ == "__main__":
    main()
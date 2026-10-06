"""! @file plot_assignment2.py
@brief Generate Assignment 2 sections 1(c) and 2(b) PDF visualizations.

@details The module reads a run's raw sample CSV and produces time-series and
scatter plots for every completed destination. This includes the representative
destination required by section 2(b), while retaining all destinations for the
section 1(c) throughput view.
"""

from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
from matplotlib import pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages


def _number(row: dict[str, str], field: str) -> float | None:
    value = row.get(field, "").strip()
    return float(value) if value else None


def _load_samples(samples_path: Path) -> dict[str, list[dict[str, str]]]:
    """! @brief Read and validate the telemetry columns needed for plotting.

    @param samples_path Run-specific `samples_<run_id>.csv` path.
    @return CSV rows grouped by destination.
    @throws FileNotFoundError If the requested run has no sample table.
    @throws ValueError If required telemetry is missing or the table is empty.
    """
    if not samples_path.exists():
        raise FileNotFoundError(f"sample table not found: {samples_path}")
    with samples_path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    required_fields = {"destination", "elapsed_s", "goodput_bps", "snd_cwnd_bytes", "srtt_us", "total_retransmits_delta"}
    if not rows:
        raise ValueError(f"sample table is empty: {samples_path}")
    missing_fields = required_fields - set(rows[0])
    if missing_fields:
        raise ValueError(f"sample table is missing columns: {', '.join(sorted(missing_fields))}")
    samples_by_destination: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        samples_by_destination[row["destination"]].append(row)
    return dict(samples_by_destination)


def _pairs(rows: list[dict[str, str]], x_field: str, y_field: str, x_scale: float, y_scale: float) -> tuple[list[float], list[float]]:
    pairs = [(_number(row, x_field), _number(row, y_field)) for row in rows]
    valid_pairs = [(x, y) for x, y in pairs if x is not None and y is not None]
    return ([x / x_scale for x, _ in valid_pairs], [y / y_scale for _, y in valid_pairs])


def _plot_pages(pdf: PdfPages, run_id: str, samples_by_destination: dict[str, list[dict[str, str]]]) -> None:
    """! @brief Add required Assignment 2 visualization pages to a PDF.

    @param pdf Open multi-page PDF destination.
    @param run_id Identifier shown on each page.
    @param samples_by_destination Valid samples grouped by destination.

    @details Produces time series for congestion window, RTT, retransmission
proxy, and acknowledged goodput plus the three required goodput scatter plots.
`total_retransmits_delta` is used as the documented loss proxy.
    """
    plot_specs = (
        ("Time series: congestion window", "elapsed_s", "snd_cwnd_bytes", "Elapsed time (s)", "Congestion window (KiB)", 1.0, 1024.0, "line"),
        ("Time series: RTT", "elapsed_s", "srtt_us", "Elapsed time (s)", "Smoothed RTT (ms)", 1.0, 1_000.0, "line"),
        ("Time series: retransmission proxy", "elapsed_s", "total_retransmits_delta", "Elapsed time (s)", "Retransmissions during interval (packets)", 1.0, 1.0, "line"),
        ("Time series: acknowledged goodput", "elapsed_s", "goodput_bps", "Elapsed time (s)", "Goodput (Mbps)", 1.0, 1_000_000.0, "line"),
        ("Scatter: congestion window vs goodput", "snd_cwnd_bytes", "goodput_bps", "Congestion window (KiB)", "Goodput (Mbps)", 1024.0, 1_000_000.0, "scatter"),
        ("Scatter: RTT vs goodput", "srtt_us", "goodput_bps", "Smoothed RTT (ms)", "Goodput (Mbps)", 1_000.0, 1_000_000.0, "scatter"),
        ("Scatter: retransmission proxy vs goodput", "total_retransmits_delta", "goodput_bps", "Retransmissions during interval (packets)", "Goodput (Mbps)", 1.0, 1_000_000.0, "scatter"),
    )
    destination_count = len(samples_by_destination)
    for title, x_field, y_field, x_label, y_label, x_scale, y_scale, style in plot_specs:
        figure, axes = plt.subplots(destination_count, 1, figsize=(8.5, 3.4 * destination_count), squeeze=False)
        figure.suptitle(f"{title}\nRun {run_id}")
        for axis, (destination, rows) in zip(axes[:, 0], samples_by_destination.items()):
            x_values, y_values = _pairs(rows, x_field, y_field, x_scale, y_scale)
            if style == "line":
                axis.plot(x_values, y_values, marker=".", linewidth=1.2)
            else:
                axis.scatter(x_values, y_values, s=18, alpha=0.8)
            algorithm = rows[0].get("actual_algorithm", "unknown")
            axis.set_title(f"{destination} ({algorithm})", fontsize=10)
            axis.set_xlabel(x_label)
            axis.set_ylabel(y_label)
            axis.grid(True, alpha=0.3)
        figure.tight_layout()
        pdf.savefig(figure)
        plt.close(figure)


def generate_run_plots(run_id: str, tables_directory: Path = Path("outputs/tables"), output_directory: Path = Path("outputs/plots")) -> Path:
    """! @brief Create the required time-series and scatter plots for one run.

    @param run_id Full run ID or timestamp token after the `step1-` prefix.
    @param tables_directory Directory containing experiment CSV tables.
    @param output_directory Directory receiving the generated PDF.
    @return Path to `plots_<resolved-run-id>.pdf`.

    @todo Section 2(c) observations belong in the report; this generator does
not infer or write conclusions from the plotted data.
    """
    candidate_run_ids = (run_id,) if run_id.startswith("step1-") else (run_id, f"step1-{run_id}")
    resolved_run_id = next(
        (candidate for candidate in candidate_run_ids if (tables_directory / f"samples_{candidate}.csv").exists()),
        run_id,
    )
    samples_by_destination = _load_samples(tables_directory / f"samples_{resolved_run_id}.csv")
    output_directory.mkdir(parents=True, exist_ok=True)
    plot_path = output_directory / f"plots_{resolved_run_id}.pdf"
    with PdfPages(plot_path) as pdf:
        _plot_pages(pdf, resolved_run_id, samples_by_destination)
    return plot_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate Assignment 2 TCP plots from a run ID.")
    parser.add_argument("run_id", help="Run ID or timestamp token, for example step1-20261002T005606Z or 20261002T005606Z.")
    parser.add_argument("--tables-dir", type=Path, default=Path("outputs/tables"))
    parser.add_argument("--output-dir", type=Path, default=Path("outputs/plots"))
    arguments = parser.parse_args()
    print(generate_run_plots(arguments.run_id, arguments.tables_dir, arguments.output_dir))


if __name__ == "__main__":
    main()
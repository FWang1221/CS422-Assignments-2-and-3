"""! @file assignment2_question3.py
@brief Fixed-endpoint CUBIC/Reno/BBR comparison coordinator for Assignment 2 3(a).

@todo Interpret operating regimes, BDP, queueing, loss, and run variability in
the report after collecting repeated measurements.
"""

from __future__ import annotations

import argparse
import csv
from collections.abc import Callable, Iterable
from datetime import datetime, timezone
from pathlib import Path

from src.assignment2_step1 import LinuxIperf3Client, Step1Client, run_step1_experiment
from src.congestion_control import CongestionAlgorithm, CUSTOM_ALGORITHM_DEFAULT, normalize_algorithms
from src.simulated_client import Endpoint


MANIFEST_FIELDS = [
    "base_run_id",
    "run_id",
    "test_order",
    "repetition",
    "requested_algorithm",
    "kernel_algorithm",
    "actual_algorithm",
    "destination",
    "port",
    "status",
]


def load_endpoint_plan(path: Path) -> list[Endpoint]:
    """! @brief Load successful endpoints from a prior selected-endpoints CSV."""
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    required = set(Endpoint.__dataclass_fields__)
    if not rows or not required.issubset(rows[0]):
        raise ValueError(f"endpoint plan is empty or missing required columns: {path}")
    return [Endpoint(**{field: int(row[field]) if field == "port" else row[field] for field in Endpoint.__dataclass_fields__}) for row in rows]


def run_algorithm_comparison(
    output_directory: Path,
    *,
    base_run_id: str,
    endpoints: Iterable[Endpoint],
    algorithms: list[CongestionAlgorithm],
    repetitions: int,
    duration_s: float,
    sample_interval_s: float,
    client_factory: Callable[[CongestionAlgorithm], Step1Client] | None = None,
) -> Path:
    """! @brief Run a rotated, repeated comparison against one fixed endpoint plan.

    @details Failed endpoints are recorded without replacement so every algorithm
    is evaluated against the same destinations. Each per-algorithm run retains
    the normal raw samples, summaries, and metadata; the returned manifest adds
    test order and repetition for report reproducibility.
    """
    fixed_endpoints = list(endpoints)
    if not fixed_endpoints or not algorithms or repetitions <= 0:
        raise ValueError("endpoints, algorithms, and repetitions must be non-empty/positive")
    output_directory.mkdir(parents=True, exist_ok=True)
    client_factory = client_factory or (
        lambda algorithm: LinuxIperf3Client(
            congestion_algorithm=algorithm.kernel_name,
            requested_algorithm=algorithm.label,
        )
    )
    manifest_rows: list[dict[str, object]] = []
    test_order = 0
    for repetition in range(1, repetitions + 1):
        offset = (repetition - 1) % len(algorithms)
        for algorithm in algorithms[offset:] + algorithms[:offset]:
            test_order += 1
            run_id = f"q3-{base_run_id}-r{repetition:02d}-{algorithm.kernel_name}"
            run_step1_experiment(
                output_directory,
                destinations=len(fixed_endpoints),
                duration_s=duration_s,
                sample_interval_s=sample_interval_s,
                run_id=run_id,
                candidates=fixed_endpoints,
                client=client_factory(algorithm),
                max_attempts=len(fixed_endpoints),
                workers=1,
                algorithm=algorithm.label,
            )
            with (output_directory / f"summary_{run_id}.csv").open(newline="", encoding="utf-8") as handle:
                summaries = {(row["destination"], int(row["port"])): row for row in csv.DictReader(handle)}
            with (output_directory / f"attempts_{run_id}.csv").open(newline="", encoding="utf-8") as handle:
                attempts = {(row["host"], int(row["port"])): row for row in csv.DictReader(handle)}
            for endpoint in fixed_endpoints:
                summary = summaries.get((endpoint.host, endpoint.port))
                attempt = attempts.get((endpoint.host, endpoint.port), {})
                manifest_rows.append(
                    {
                        "base_run_id": base_run_id,
                        "run_id": run_id,
                        "test_order": test_order,
                        "repetition": repetition,
                        "requested_algorithm": algorithm.label,
                        "kernel_algorithm": algorithm.kernel_name,
                        "actual_algorithm": summary["algorithm"] if summary else "unavailable",
                        "destination": endpoint.host,
                        "port": endpoint.port,
                        "status": summary["status"] if summary else attempt.get("status", "not_attempted"),
                    }
                )
    manifest_path = output_directory / f"comparison_manifest_{base_run_id}.csv"
    with manifest_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=MANIFEST_FIELDS)
        writer.writeheader()
        writer.writerows(manifest_rows)
    return manifest_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Run fixed-endpoint Assignment 2 Question 3 comparisons.")
    parser.add_argument("--endpoint-plan", type=Path, required=True, help="selected_endpoints CSV from a successful prior run")
    parser.add_argument("--algorithms", nargs="+", default=["CUBIC", "Reno", "BBR"])
    parser.add_argument("--handwritten-kernel-name", default=CUSTOM_ALGORITHM_DEFAULT)
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument("--duration", type=float, default=60.0)
    parser.add_argument("--sample-interval", type=float, default=1.0)
    parser.add_argument("--output-dir", type=Path, default=Path("outputs/tables"))
    parser.add_argument("--base-run-id", default=None)
    arguments = parser.parse_args()
    base_run_id = arguments.base_run_id or datetime.now(timezone.utc).strftime("comparison-%Y%m%dT%H%M%SZ")
    manifest = run_algorithm_comparison(
        arguments.output_dir,
        base_run_id=base_run_id,
        endpoints=load_endpoint_plan(arguments.endpoint_plan),
        algorithms=normalize_algorithms(arguments.algorithms, arguments.handwritten_kernel_name),
        repetitions=arguments.repetitions,
        duration_s=arguments.duration,
        sample_interval_s=arguments.sample_interval,
    )
    print(manifest)


if __name__ == "__main__":
    main()
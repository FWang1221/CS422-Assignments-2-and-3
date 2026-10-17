"""! @file assignment2_pipeline.py
@brief Single entry point for the Assignment 2 live experiment and plot pipeline."""

from __future__ import annotations

import argparse
import json
import platform
from datetime import datetime, timezone
from pathlib import Path

from src.assignment2_question3 import load_endpoint_plan, run_algorithm_comparison
from src.assignment2_step1 import run_step1_experiment
from src.congestion_control import CongestionAlgorithm, CUSTOM_ALGORITHM_DEFAULT, normalize_algorithms
from src.plot_assignment2_question3 import generate_comparison_plots
from src.simulated_client import load_endpoints, select_endpoints


def available_congestion_algorithms() -> set[str]:
    """! @brief Return Linux algorithms exposed by the current host kernel."""
    available_path = Path("/proc/sys/net/ipv4/tcp_available_congestion_control")
    if not available_path.exists():
        raise RuntimeError("Linux TCP congestion-control inventory is unavailable; use Linux or WSL2")
    return set(available_path.read_text(encoding="utf-8").split())


def validate_available_algorithms(algorithms: list[CongestionAlgorithm], available: set[str]) -> None:
    """! @brief Reject a comparison before network I/O if an algorithm is unavailable."""
    missing = [algorithm.kernel_name for algorithm in algorithms if algorithm.kernel_name not in available]
    if missing:
        raise RuntimeError(
            "requested congestion-control algorithms are unavailable in this host kernel: "
            f"{', '.join(missing)}; available: {', '.join(sorted(available))}"
        )


def run_pipeline(
    *,
    server_list: Path,
    output_directory: Path,
    destinations: int,
    max_attempts: int,
    duration_s: float,
    sample_interval_s: float,
    repetitions: int,
    seed: int,
    baseline_run_id: str,
    comparison_run_id: str,
    algorithms: list[CongestionAlgorithm],
) -> dict[str, str]:
    """! @brief Execute baseline selection, fixed comparisons, and grouped plots.

    @details Docker standardizes Python dependencies but not TCP behavior: this
    function records the host kernel and refuses unavailable requested algorithms
    before opening any public-server connection.
    """
    available = available_congestion_algorithms()
    validate_available_algorithms(algorithms, available)
    output_directory.mkdir(parents=True, exist_ok=True)
    environment_path = output_directory / f"pipeline_environment_{comparison_run_id}.json"
    environment_path.write_text(
        json.dumps(
            {
                "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
                "system": platform.platform(),
                "kernel_release": platform.release(),
                "available_congestion_algorithms": sorted(available),
                "requested_congestion_algorithms": [algorithm.kernel_name for algorithm in algorithms],
            },
            indent=2,
        ) + "\n",
        encoding="utf-8",
    )
    candidates = select_endpoints(load_endpoints(server_list, seed), max_attempts, seed)
    baseline_metadata = run_step1_experiment(
        output_directory,
        destinations=destinations,
        duration_s=duration_s,
        sample_interval_s=sample_interval_s,
        run_id=baseline_run_id,
        candidates=candidates,
        max_attempts=max_attempts,
    )
    if baseline_metadata["completed_destinations"] != destinations:
        raise RuntimeError("baseline selection did not produce the requested number of endpoints; inspect its attempt table")
    endpoint_plan = output_directory / f"selected_endpoints_{baseline_run_id}.csv"
    manifest_path = run_algorithm_comparison(
        output_directory,
        base_run_id=comparison_run_id,
        endpoints=load_endpoint_plan(endpoint_plan),
        algorithms=algorithms,
        repetitions=repetitions,
        duration_s=duration_s,
        sample_interval_s=sample_interval_s,
    )
    plot_path = generate_comparison_plots(comparison_run_id, output_directory, output_directory.parent / "plots")
    return {"endpoint_plan": str(endpoint_plan), "manifest": str(manifest_path), "plots": str(plot_path), "environment": str(environment_path)}


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the complete Assignment 2 live experiment and comparison pipeline.")
    parser.add_argument("--server-list", type=Path, default=Path("config/listed_iperf3_servers.csv"))
    parser.add_argument("--output-dir", type=Path, default=Path("outputs/tables"))
    parser.add_argument("--destinations", type=int, default=10)
    parser.add_argument("--max-attempts", type=int, default=30)
    parser.add_argument("--duration", type=float, default=60.0)
    parser.add_argument("--sample-interval", type=float, default=1.0)
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument("--seed", type=int, default=422)
    parser.add_argument("--algorithms", nargs="+", default=["CUBIC", "Reno", "BBR"])
    parser.add_argument("--handwritten-kernel-name", default=CUSTOM_ALGORITHM_DEFAULT)
    parser.add_argument("--baseline-run-id", default=None)
    parser.add_argument("--comparison-run-id", default=None)
    arguments = parser.parse_args()
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    result = run_pipeline(
        server_list=arguments.server_list,
        output_directory=arguments.output_dir,
        destinations=arguments.destinations,
        max_attempts=arguments.max_attempts,
        duration_s=arguments.duration,
        sample_interval_s=arguments.sample_interval,
        repetitions=arguments.repetitions,
        seed=arguments.seed,
        baseline_run_id=arguments.baseline_run_id or f"baseline-{timestamp}",
        comparison_run_id=arguments.comparison_run_id or f"q3-{timestamp}",
        algorithms=normalize_algorithms(arguments.algorithms, arguments.handwritten_kernel_name),
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
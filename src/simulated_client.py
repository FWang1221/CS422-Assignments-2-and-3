"""Deterministic, network-free placeholder for the future iperf3 client."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
import statistics
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class Endpoint:
    host: str
    port: int
    capacity: str
    continent: str
    country: str
    site: str
    provider: str


@dataclass(frozen=True)
class RunResult:
    endpoint: Endpoint
    status: str
    samples: list[dict[str, object]]
    failure_reason: str = ""


def _parse_port_spec(port_spec: str) -> tuple[int, int]:
    parts = port_spec.strip().split("-", maxsplit=1)
    try:
        low = int(parts[0])
        high = int(parts[-1])
    except ValueError as error:
        raise ValueError(f"invalid port specification: {port_spec!r}") from error
    if not 1 <= low <= high <= 65535:
        raise ValueError(f"invalid port range: {port_spec!r}")
    return low, high


def load_endpoints(server_list: Path, seed: int) -> list[Endpoint]:
    """Load CSV rows and pick a reproducible port from each row's range."""
    randomizer = random.Random(seed)
    endpoints: list[Endpoint] = []
    with server_list.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        required = {"IP/HOST", "PORT", "GB/S", "CONTINENT", "COUNTRY", "SITE", "PROVIDER"}
        if reader.fieldnames is None or not required.issubset(reader.fieldnames):
            raise ValueError("server list is missing one or more required columns")
        for line_number, row in enumerate(reader, start=2):
            host = row["IP/HOST"].strip()
            if not host:
                raise ValueError(f"line {line_number}: host is empty")
            low, high = _parse_port_spec(row["PORT"])
            endpoints.append(
                Endpoint(
                    host=host,
                    port=randomizer.randint(low, high),
                    capacity=row["GB/S"].strip(),
                    continent=row["CONTINENT"].strip(),
                    country=row["COUNTRY"].strip(),
                    site=row["SITE"].strip(),
                    provider=row["PROVIDER"].strip(),
                )
            )
    return endpoints


def select_endpoints(endpoints: Iterable[Endpoint], count: int, seed: int) -> list[Endpoint]:
    if count <= 0:
        raise ValueError("destination count must be positive")
    unique = list(dict.fromkeys(endpoints))
    return random.Random(seed).sample(unique, k=min(count, len(unique)))


def _seed_for(endpoint: Endpoint, run_id: str, algorithm: str) -> int:
    source = f"{run_id}|{endpoint.host}|{endpoint.port}|{algorithm}".encode("ascii")
    return int.from_bytes(hashlib.sha256(source).digest()[:8], "big")


class PlaceholderClient:
    """Produces reproducible samples and deliberately performs no network I/O."""

    measurement_mode = "simulated"

    def __init__(self, rejected_hosts: Iterable[str] = ()) -> None:
        self.rejected_hosts = frozenset(rejected_hosts)

    def run(
        self,
        endpoint: Endpoint,
        run_id: str,
        duration_s: float,
        sample_interval_s: float,
        algorithm: str,
    ) -> RunResult:
        if duration_s <= 0 or sample_interval_s <= 0:
            raise ValueError("duration and sample interval must be positive")
        if endpoint.host in self.rejected_hosts:
            return RunResult(endpoint, "rejected", [], "simulated_rate_limit")

        randomizer = random.Random(_seed_for(endpoint, run_id, algorithm))
        base_rate_bps = randomizer.randint(20_000_000, 180_000_000)
        elapsed_values = [0.0]
        elapsed = sample_interval_s
        while elapsed < duration_s:
            elapsed_values.append(round(elapsed, 9))
            elapsed += sample_interval_s
        if elapsed_values[-1] != duration_s:
            elapsed_values.append(duration_s)

        cumulative_acked = 0
        previous_elapsed: float | None = None
        samples: list[dict[str, object]] = []
        for elapsed in elapsed_values:
            if previous_elapsed is None:
                interval_s = None
                goodput_bps = None
            else:
                interval_s = elapsed - previous_elapsed
                rate_bps = base_rate_bps * randomizer.uniform(0.82, 1.18)
                acknowledged_delta = max(1, int(rate_bps * interval_s / 8))
                cumulative_acked += acknowledged_delta
                goodput_bps = acknowledged_delta * 8 / interval_s
            samples.append(
                {
                    "run_id": run_id,
                    "measurement_mode": self.measurement_mode,
                    "destination": endpoint.host,
                    "port": endpoint.port,
                    "requested_algorithm": algorithm,
                    "actual_algorithm": algorithm,
                    "elapsed_s": elapsed,
                    "interval_s": interval_s,
                    "bytes_acked": cumulative_acked,
                    "goodput_bps": goodput_bps,
                    "snd_cwnd_bytes": randomizer.randint(64_000, 1_500_000),
                    "srtt_us": randomizer.randint(12_000, 110_000),
                    "rttvar_us": randomizer.randint(1_000, 20_000),
                    "retransmits": randomizer.randint(0, 2),
                    "lost": randomizer.randint(0, 1),
                    "delivered": cumulative_acked,
                    "pacing_rate_bps": base_rate_bps,
                    "notes": "deterministic placeholder; no network I/O",
                }
            )
            previous_elapsed = elapsed
        return RunResult(endpoint, "completed", samples)


def _percentile_95(values: list[float]) -> float:
    ordered = sorted(values)
    return ordered[round((len(ordered) - 1) * 0.95)]


def _write_csv(path: Path, rows: list[dict[str, object]], fieldnames: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def run_placeholder_experiment(
    server_list: Path,
    output_dir: Path,
    destinations: int,
    duration_s: float,
    sample_interval_s: float,
    seed: int,
    algorithm: str = "cubic",
    run_id: str = "simulated-run",
    client: PlaceholderClient | None = None,
) -> dict[str, object]:
    """Run simulated candidates, replacing rejected ones until candidates are exhausted."""
    client = client or PlaceholderClient()
    candidates = select_endpoints(load_endpoints(server_list, seed), destinations * 3, seed)
    output_dir.mkdir(parents=True, exist_ok=True)

    selected_rows: list[dict[str, object]] = []
    attempt_rows: list[dict[str, object]] = []
    sample_rows: list[dict[str, object]] = []
    summary_rows: list[dict[str, object]] = []
    completed = 0
    for attempt_number, endpoint in enumerate(candidates, start=1):
        if completed == destinations:
            break
        result = client.run(endpoint, run_id, duration_s, sample_interval_s, algorithm)
        attempt_rows.append(
            {
                "run_id": run_id,
                "attempt_number": attempt_number,
                "host": endpoint.host,
                "port": endpoint.port,
                "client": "placeholder",
                "status": result.status,
                "failure_reason": result.failure_reason,
            }
        )
        if result.status != "completed":
            continue
        completed += 1
        selected_rows.append({"selection_order": completed, **asdict(endpoint)})
        sample_rows.extend(result.samples)
        goodputs = [float(row["goodput_bps"]) for row in result.samples if row["goodput_bps"] is not None]
        summary_rows.append(
            {
                "run_id": run_id,
                "destination": endpoint.host,
                "port": endpoint.port,
                "algorithm": algorithm,
                "measurement_mode": client.measurement_mode,
                "sample_count": len(goodputs),
                "min_goodput_bps": min(goodputs),
                "median_goodput_bps": statistics.median(goodputs),
                "mean_goodput_bps": statistics.mean(goodputs),
                "p95_goodput_bps": _percentile_95(goodputs),
                "status": result.status,
            }
        )

    _write_csv(output_dir / f"selected_endpoints_{run_id}.csv", selected_rows, ["selection_order", *Endpoint.__dataclass_fields__])
    _write_csv(output_dir / f"attempts_{run_id}.csv", attempt_rows, list(attempt_rows[0]) if attempt_rows else ["run_id", "attempt_number", "host", "port", "client", "status", "failure_reason"])
    sample_fields = list(sample_rows[0]) if sample_rows else []
    _write_csv(output_dir / f"samples_{run_id}.csv", sample_rows, sample_fields)
    summary_fields = list(summary_rows[0]) if summary_rows else ["run_id", "destination", "port", "algorithm", "measurement_mode", "sample_count", "min_goodput_bps", "median_goodput_bps", "mean_goodput_bps", "p95_goodput_bps", "status"]
    _write_csv(output_dir / f"summary_{run_id}.csv", summary_rows, summary_fields)

    metadata = {
        "run_id": run_id,
        "client": "placeholder",
        "measurement_mode": client.measurement_mode,
        "network_io": False,
        "server_list": str(server_list),
        "seed": seed,
        "requested_destinations": destinations,
        "completed_destinations": completed,
        "shortfall": destinations - completed,
        "duration_s": duration_s,
        "sample_interval_s": sample_interval_s,
        "algorithm": algorithm,
    }
    (output_dir / f"run_metadata_{run_id}.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    return metadata


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate deterministic simulated experiment tables.")
    parser.add_argument("--server-list", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=Path("outputs/tables"))
    parser.add_argument("--destinations", type=int, default=10)
    parser.add_argument("--duration", type=float, default=60.0)
    parser.add_argument("--sample-interval", type=float, default=1.0)
    parser.add_argument("--seed", type=int, default=422)
    parser.add_argument("--algorithm", default="cubic")
    parser.add_argument("--run-id", default=None)
    arguments = parser.parse_args()
    run_id = arguments.run_id or datetime.now(timezone.utc).strftime("simulated-%Y%m%dT%H%M%SZ")
    metadata = run_placeholder_experiment(
        arguments.server_list,
        arguments.output_dir,
        arguments.destinations,
        arguments.duration,
        arguments.sample_interval,
        arguments.seed,
        arguments.algorithm,
        run_id,
    )
    print(json.dumps(metadata, indent=2))


if __name__ == "__main__":
    main()
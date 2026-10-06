"""! @file assignment2_step1.py
@brief Live implementation for Assignment 2 sections 1(a-c) and 2(a).

@details The client implements a forward TCP iperf3-compatible test against
public servers without invoking the iperf3 binary or running a custom receiver.
It selects replacement destinations, measures acknowledged goodput from the data
socket, and writes the raw telemetry consumed by the plotting module.

@todo Assignment 3(a) must add per-socket congestion-control selection for
CUBIC, Reno, and BBR plus repeated, controlled experiment scheduling.
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import math
import select
import socket
import statistics
import threading
import time
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Protocol

from src.iperf3_protocol import (
    CREATE_STREAMS,
    DISPLAY_RESULTS,
    EXCHANGE_RESULTS,
    IPERF_DONE,
    PARAM_EXCHANGE,
    TEST_END,
    TEST_RUNNING,
    TEST_START,
    IperfProtocolError,
    make_cookie,
    recv_json,
    recv_state,
    send_json,
    send_state,
)
from src.simulated_client import Endpoint, load_endpoints, select_endpoints
from src.tcp_info import TcpInfo, configure_congestion_algorithm, get_congestion_algorithm, get_tcp_info


LOGGER = logging.getLogger(__name__)
FILE_LOCK = threading.RLock()
SAMPLE_FIELDS = [
    "run_id",
    "measurement_mode",
    "destination",
    "port",
    "timestamp_utc",
    "requested_algorithm",
    "actual_algorithm",
    "elapsed_s",
    "interval_s",
    "bytes_acked",
    "acknowledged_bytes_delta",
    "goodput_bps",
    "snd_cwnd_segments",
    "snd_cwnd_bytes",
    "srtt_us",
    "rttvar_us",
    "retransmits",
    "lost",
    "lost_change",
    "total_retransmits",
    "total_retransmits_delta",
    "pacing_rate_bps",
    "delivery_rate_bps",
    "notes",
]
ATTEMPT_FIELDS = ["run_id", "attempt_number", "host", "port", "client", "status", "failure_reason"]
SUMMARY_FIELDS = [
    "run_id",
    "destination",
    "port",
    "algorithm",
    "measurement_mode",
    "sample_count",
    "min_goodput_bps",
    "median_goodput_bps",
    "mean_goodput_bps",
    "p95_goodput_bps",
    "status",
]

# The first endpoint is deliberately closed on normal developer machines. The
# second is a public endpoint from config/listed_iperf3_servers.csv and may still
# reject a test when busy or rate-limited; that outcome is recorded, not hidden.
DEBUG_ENDPOINTS = [
    Endpoint("127.0.0.1", 1, "", "debug", "", "intentional failure", "local"),
    Endpoint("speedtest.nyc1.us.leaseweb.net", 5201, "10", "North America", "US", "New York City", "LeaseWeb"),
]


@dataclass(frozen=True)
class LiveRunResult:
    """! @brief Outcome of one attempted public-server transfer.

    @details A failed attempt has no samples and carries a normalized failure
    reason. A completed attempt carries data-socket telemetry and the congestion
    algorithm that the Linux kernel actually selected.
    """

    endpoint: Endpoint
    status: str
    samples: list[dict[str, object]]
    failure_reason: str = ""
    actual_algorithm: str = "unknown"
    requested_algorithm: str = "system-default"


class Step1Client(Protocol):
    """! @brief Injectable client boundary used by the experiment coordinator."""

    def run(self, endpoint: Endpoint, run_id: str, duration_s: float, sample_interval_s: float) -> LiveRunResult: ...


class LinuxIperf3Client:
    """! @brief One-stream forward TCP client compatible with public iperf3 servers.

    @details Implements Assignment 2 section 1(a): control connection, JSON
    parameter exchange, data connection, continuous transfer, and orderly
    protocol termination. During sending it captures data-socket telemetry for
    sections 1(c) and 2(a).
    """

    def __init__(
        self,
        *,
        timeout_s: float = 10.0,
        block_size: int = 128 * 1024,
        congestion_algorithm: str | None = None,
        requested_algorithm: str | None = None,
    ) -> None:
        if timeout_s <= 0 or block_size <= 0:
            raise ValueError("timeout and block size must be positive")
        self.timeout_s = timeout_s
        self.block_size = block_size
        self.congestion_algorithm = congestion_algorithm
        self.requested_algorithm = requested_algorithm or congestion_algorithm or "system-default"

    def _connect(self, endpoint: Endpoint, congestion_algorithm: str | None = None) -> socket.socket:
        """! @brief Open one timeout-bound TCP connection to an endpoint.

        @param endpoint Destination host and port from the public-server list.
        @return A connected socket with the configured timeout.
        @throws OSError If DNS lookup or TCP connection establishment fails.
        """
        LOGGER.debug("connecting to %s:%s", endpoint.host, endpoint.port)
        if congestion_algorithm is None:
            connection = socket.create_connection((endpoint.host, endpoint.port), self.timeout_s)
            connection.settimeout(self.timeout_s)
            return connection

        last_error: OSError | None = None
        for family, socket_type, protocol, _, address in socket.getaddrinfo(endpoint.host, endpoint.port, type=socket.SOCK_STREAM):
            connection = socket.socket(family, socket_type, protocol)
            try:
                connection.settimeout(self.timeout_s)
                configure_congestion_algorithm(connection, congestion_algorithm)
                connection.connect(address)
                return connection
            except OSError as error:
                connection.close()
                last_error = error
        if last_error is not None:
            raise last_error
        raise OSError(f"no TCP addresses found for {endpoint.host}:{endpoint.port}")

    @staticmethod
    def _expect_state(control_socket: socket.socket, expected: int) -> None:
        actual = recv_state(control_socket)
        if actual != expected:
            raise IperfProtocolError(f"expected state {expected}, received {actual}")

    def _parameters(self, duration_s: float) -> dict[str, Any]:
        """! @brief Build the iperf3 JSON parameters for a forward TCP stream.

        @param duration_s Requested continuous-send duration in seconds.
        @return The protocol parameter object sent during `PARAM_EXCHANGE`.
        """
        return {
            "tcp": True,
            "omit": 0,
            "time": math.ceil(duration_s),
            "num": 0,
            "blockcount": 0,
            "parallel": 1,
            "len": self.block_size,
            "client_version": "cs422-assignment2-step1",
        }

    @staticmethod
    def _sample(
        endpoint: Endpoint,
        run_id: str,
        elapsed_s: float,
        info: TcpInfo,
        previous_elapsed_s: float | None,
        previous_bytes_acked: int | None,
        previous_total_retransmits: int | None = None,
        previous_lost: int | None = None,
        timestamp_utc: datetime | None = None,
        requested_algorithm: str = "system-default",
        actual_algorithm: str = "unknown",
    ) -> dict[str, object]:
        """! @brief Convert a TCP_INFO snapshot into one CSV-ready measurement.

        @param elapsed_s Monotonic seconds since data transfer started.
        @param info Decoded Linux TCP_INFO snapshot from the data socket.
        @param previous_elapsed_s Prior sample time, if any.
        @param previous_bytes_acked Prior cumulative acknowledged-byte counter.
        @param previous_total_retransmits Prior cumulative retransmission count.
        @param previous_lost Prior non-monotonic current-loss estimate.
        @return A sample with acknowledged goodput, congestion metrics, units,
        and counter-change diagnostics.

        @details Implements Assignment 2 section 1(c) with
        `acknowledged_bytes_delta * 8 / interval_s`. It also implements section
        2(a) by retaining TCP_INFO values and using `total_retransmits_delta` as
        the cumulative loss/retransmission proxy. `lost_change` is signed because
        `tcpi_lost` is an estimate rather than a cumulative counter.
        """
        interval_s = None if previous_elapsed_s is None else elapsed_s - previous_elapsed_s
        goodput_bps: float | None = None
        acknowledged_bytes_delta: int | None = None
        total_retransmits_delta: int | None = None
        lost_change: int | None = None
        notes = ""
        if interval_s is not None and interval_s > 0 and previous_bytes_acked is not None:
            acknowledged_delta = info.bytes_acked - previous_bytes_acked
            if acknowledged_delta >= 0:
                acknowledged_bytes_delta = acknowledged_delta
                goodput_bps = acknowledged_delta * 8 / interval_s
            else:
                notes = "bytes_acked counter decreased; goodput omitted"
        if previous_total_retransmits is not None:
            total_retransmits_delta = info.total_retransmits - previous_total_retransmits
            if total_retransmits_delta < 0:
                total_retransmits_delta = None
                notes = f"{notes}; total_retransmits counter decreased".strip("; ")
        if previous_lost is not None:
            lost_change = info.lost - previous_lost
        return {
            "run_id": run_id,
            "measurement_mode": "live",
            "destination": endpoint.host,
            "port": endpoint.port,
            "timestamp_utc": timestamp_utc.isoformat() if timestamp_utc is not None else None,
            "requested_algorithm": requested_algorithm,
            "actual_algorithm": actual_algorithm,
            "elapsed_s": elapsed_s,
            "interval_s": interval_s,
            "bytes_acked": info.bytes_acked,
            "acknowledged_bytes_delta": acknowledged_bytes_delta,
            "goodput_bps": goodput_bps,
            "snd_cwnd_segments": info.snd_cwnd_segments,
            "snd_cwnd_bytes": info.snd_cwnd_segments * info.snd_mss_bytes if info.snd_mss_bytes else None,
            "srtt_us": info.rtt_us,
            "rttvar_us": info.rttvar_us,
            "retransmits": info.retransmits,
            "lost": info.lost,
            "lost_change": lost_change,
            "total_retransmits": info.total_retransmits,
            "total_retransmits_delta": total_retransmits_delta,
            "pacing_rate_bps": info.pacing_rate_bytes_per_s * 8 if info.pacing_rate_bytes_per_s is not None else None,
            "delivery_rate_bps": info.delivery_rate_bytes_per_s * 8 if info.delivery_rate_bytes_per_s is not None else None,
            "notes": notes,
        }

    def run(self, endpoint: Endpoint, run_id: str, duration_s: float, sample_interval_s: float) -> LiveRunResult:
        """! @brief Execute one complete live public-server experiment attempt.

        @param endpoint Server selected for this attempt.
        @param run_id Identifier shared by all output rows from the experiment.
        @param duration_s Requested continuous transfer duration in seconds.
        @param sample_interval_s Requested TCP_INFO sampling interval in seconds.
        @return Completed telemetry or a normalized failed attempt result.

        @details The data socket, not the iperf3 control socket, supplies both
        acknowledged-byte and TCP_INFO measurements required by sections 1(c)
        and 2(a). `TCP_CONGESTION` records the actual selected algorithm.
        """
        if duration_s <= 0 or sample_interval_s <= 0:
            raise ValueError("duration and sample interval must be positive")
        control_socket: socket.socket | None = None
        data_socket: socket.socket | None = None
        actual_algorithm = "unknown"
        try:
            LOGGER.debug("starting run %s for %s:%s", run_id, endpoint.host, endpoint.port)
            cookie = make_cookie()
            control_socket = self._connect(endpoint)
            control_socket.sendall(cookie)
            self._expect_state(control_socket, PARAM_EXCHANGE)
            send_json(control_socket, self._parameters(duration_s))
            self._expect_state(control_socket, CREATE_STREAMS)

            data_socket = self._connect(endpoint, self.congestion_algorithm)
            data_socket.sendall(cookie)
            self._expect_state(control_socket, TEST_START)
            self._expect_state(control_socket, TEST_RUNNING)
            actual_algorithm = get_congestion_algorithm(data_socket)
            if self.congestion_algorithm is not None and actual_algorithm != self.congestion_algorithm:
                raise IperfProtocolError(
                    f"requested congestion control {self.congestion_algorithm!r}, kernel selected {actual_algorithm!r}"
                )
            LOGGER.debug("data socket for %s:%s uses %s", endpoint.host, endpoint.port, actual_algorithm)

            data_socket.setblocking(False)
            samples: list[dict[str, object]] = []
            payload = b"0" * self.block_size
            start_time = time.monotonic()
            start_timestamp_utc = datetime.now(timezone.utc)
            deadline = start_time + duration_s
            next_sample_time = start_time
            previous_elapsed_s: float | None = None
            previous_bytes_acked: int | None = None
            previous_total_retransmits: int | None = None
            previous_lost: int | None = None
            bytes_sent = 0

            while time.monotonic() < deadline:
                now = time.monotonic()
                if now >= next_sample_time:
                    info = get_tcp_info(data_socket)
                    elapsed_s = now - start_time
                    sample = self._sample(
                        endpoint,
                        run_id,
                        elapsed_s,
                        info,
                        previous_elapsed_s,
                        previous_bytes_acked,
                        previous_total_retransmits,
                        previous_lost,
                        start_timestamp_utc + timedelta(seconds=elapsed_s),
                        requested_algorithm=self.requested_algorithm,
                        actual_algorithm=actual_algorithm,
                    )
                    samples.append(sample)
                    LOGGER.debug(
                        "sample %s:%s elapsed=%.3fs acked=%s goodput=%s",
                        endpoint.host,
                        endpoint.port,
                        sample["elapsed_s"],
                        info.bytes_acked,
                        sample["goodput_bps"],
                    )
                    previous_elapsed_s = float(sample["elapsed_s"])
                    previous_bytes_acked = info.bytes_acked
                    previous_total_retransmits = info.total_retransmits
                    previous_lost = info.lost
                    next_sample_time += sample_interval_s
                    continue

                wait_s = min(next_sample_time - now, deadline - now, 0.1)
                readable, writable, _ = select.select([control_socket], [data_socket], [], max(wait_s, 0.0))
                if readable:
                    state = recv_state(control_socket)
                    raise IperfProtocolError(f"unexpected control state during transfer: {state}")
                if writable:
                    try:
                        bytes_sent += data_socket.send(payload)
                    except BlockingIOError:
                        pass

            final_elapsed_s = time.monotonic() - start_time
            if not samples or final_elapsed_s > float(samples[-1]["elapsed_s"]):
                info = get_tcp_info(data_socket)
                samples.append(
                    self._sample(
                        endpoint,
                        run_id,
                        final_elapsed_s,
                        info,
                        previous_elapsed_s,
                        previous_bytes_acked,
                        previous_total_retransmits,
                        previous_lost,
                        start_timestamp_utc + timedelta(seconds=final_elapsed_s),
                        requested_algorithm=self.requested_algorithm,
                        actual_algorithm=actual_algorithm,
                    )
                )

            send_state(control_socket, TEST_END)
            self._expect_state(control_socket, EXCHANGE_RESULTS)
            send_json(
                control_socket,
                {
                    "cpu_util_total": 0.0,
                    "cpu_util_user": 0.0,
                    "cpu_util_system": 0.0,
                    "sender_has_retransmits": -1,
                    "streams": [
                        {
                            "id": 1,
                            "bytes": bytes_sent,
                            "retransmits": -1,
                            "jitter": 0.0,
                            "errors": 0,
                            "omitted_errors": 0,
                            "packets": 0,
                            "omitted_packets": 0,
                            "start_time": 0.0,
                            "end_time": final_elapsed_s,
                        }
                    ],
                },
            )
            recv_json(control_socket)
            self._expect_state(control_socket, DISPLAY_RESULTS)
            send_state(control_socket, IPERF_DONE)
            LOGGER.debug("completed run %s for %s:%s", run_id, endpoint.host, endpoint.port)
            return LiveRunResult(
                endpoint,
                "completed",
                samples,
                actual_algorithm=actual_algorithm,
                requested_algorithm=self.requested_algorithm,
            )
        except (OSError, IperfProtocolError) as error:
            LOGGER.debug("failed run %s for %s:%s: %s", run_id, endpoint.host, endpoint.port, error)
            return LiveRunResult(endpoint, "failed", [], _failure_reason(error))
        finally:
            if data_socket is not None:
                data_socket.close()
            if control_socket is not None:
                control_socket.close()


def _failure_reason(error: BaseException) -> str:
    if isinstance(error, ConnectionRefusedError):
        return "connection_refused"
    if isinstance(error, (socket.timeout, TimeoutError)):
        return "timeout"
    if isinstance(error, ConnectionResetError):
        return "connection_reset"
    message = str(error).lower()
    if "denied" in message:
        return "access_denied"
    if "unexpected eof" in message:
        return "premature_termination"
    return f"{type(error).__name__}: {error}"


def _percentile_95(values: list[float]) -> float:
    return sorted(values)[round((len(values) - 1) * 0.95)]


def _write_csv(path: Path, rows: list[dict[str, object]], fields: list[str]) -> None:
    with FILE_LOCK:
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)


def run_step1_experiment(
    output_dir: Path,
    *,
    destinations: int,
    duration_s: float,
    sample_interval_s: float,
    run_id: str,
    candidates: Iterable[Endpoint],
    client: Step1Client | None = None,
    max_attempts: int,
    workers: int = 1,
    algorithm: str = "system-default",
    debug: bool = False,
) -> dict[str, object]:
    """! @brief Coordinate random-server attempts and write Assignment 2 tables.

    @param output_dir Directory receiving selected-endpoint, attempt, sample,
    summary, and metadata artifacts.
    @param destinations Required count of completed destinations.
    @param candidates Bounded ordered candidates selected from the server list.
    @param max_attempts Total attempt cap, including failed replacements.
    @param workers Maximum concurrent independent endpoint attempts.
    @return Metadata including the requested/completed count, shortfall, units,
    and actual congestion-control algorithms.

    @details Implements section 1(b) by recording selections, failures, bounded
    replacements, and shortfall. It implements section 1(c) by writing per-run
    throughput summaries, and section 2(a) by preserving raw telemetry with its
    decoding/units metadata. File writes are serialized with `FILE_LOCK`.
    """
    if destinations <= 0 or max_attempts <= 0 or workers <= 0:
        raise ValueError("destinations, max attempts, and workers must be positive")
    run_started_at_utc = datetime.now(timezone.utc).isoformat()
    with FILE_LOCK:
        output_dir.mkdir(parents=True, exist_ok=True)
    client = client or LinuxIperf3Client()
    selected_rows: list[dict[str, object]] = []
    attempt_rows: list[dict[str, object]] = []
    sample_rows: list[dict[str, object]] = []
    summary_rows: list[dict[str, object]] = []
    completed = 0
    submitted_attempts = 0
    candidate_iterator = iter(candidates)

    def submit_next(executor: ThreadPoolExecutor, pending: dict[Future[LiveRunResult], tuple[int, Endpoint]]) -> bool:
        nonlocal submitted_attempts
        if submitted_attempts >= max_attempts:
            return False
        try:
            endpoint = next(candidate_iterator)
        except StopIteration:
            return False
        submitted_attempts += 1
        LOGGER.debug("submitting attempt %s for %s:%s", submitted_attempts, endpoint.host, endpoint.port)
        pending[executor.submit(client.run, endpoint, run_id, duration_s, sample_interval_s)] = (submitted_attempts, endpoint)
        return True

    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="iperf3") as executor:
        pending: dict[Future[LiveRunResult], tuple[int, Endpoint]] = {}
        while len(pending) < min(workers, destinations):
            if not submit_next(executor, pending):
                break
        while pending:
            done, _ = wait(pending, return_when=FIRST_COMPLETED)
            for future in sorted(done, key=lambda completed_future: pending[completed_future][0]):
                attempt_number, endpoint = pending.pop(future)
                try:
                    result = future.result()
                except BaseException as error:
                    LOGGER.exception("worker failed unexpectedly for %s:%s", endpoint.host, endpoint.port)
                    result = LiveRunResult(endpoint, "failed", [], _failure_reason(error))
                LOGGER.debug("attempt %s for %s:%s finished with %s", attempt_number, endpoint.host, endpoint.port, result.status)
                attempt_rows.append(
                    {
                        "run_id": run_id,
                        "attempt_number": attempt_number,
                        "host": endpoint.host,
                        "port": endpoint.port,
                        "client": "iperf3-live",
                        "status": result.status,
                        "failure_reason": result.failure_reason,
                    }
                )
                if result.status != "completed" or completed >= destinations:
                    continue
                completed += 1
                for sample in result.samples:
                    sample["requested_algorithm"] = algorithm
                selected_rows.append({"selection_order": completed, **asdict(endpoint)})
                sample_rows.extend(result.samples)
                goodputs = [float(row["goodput_bps"]) for row in result.samples if row["goodput_bps"] is not None]
                summary_rows.append(
                    {
                        "run_id": run_id,
                        "destination": endpoint.host,
                        "port": endpoint.port,
                        "algorithm": result.actual_algorithm,
                        "measurement_mode": "live",
                        "sample_count": len(goodputs),
                        "min_goodput_bps": min(goodputs) if goodputs else None,
                        "median_goodput_bps": statistics.median(goodputs) if goodputs else None,
                        "mean_goodput_bps": statistics.mean(goodputs) if goodputs else None,
                        "p95_goodput_bps": _percentile_95(goodputs) if goodputs else None,
                        "status": result.status,
                    }
                )
            while len(pending) < workers and completed + len(pending) < destinations:
                if not submit_next(executor, pending):
                    break

    _write_csv(output_dir / f"selected_endpoints_{run_id}.csv", selected_rows, ["selection_order", *Endpoint.__dataclass_fields__])
    _write_csv(output_dir / f"attempts_{run_id}.csv", attempt_rows, ATTEMPT_FIELDS)
    _write_csv(output_dir / f"samples_{run_id}.csv", sample_rows, SAMPLE_FIELDS)
    _write_csv(output_dir / f"summary_{run_id}.csv", summary_rows, SUMMARY_FIELDS)
    metadata = {
        "run_id": run_id,
        "client": "iperf3-live",
        "measurement_mode": "live",
        "network_io": True,
        "debug": debug,
        "requested_destinations": destinations,
        "run_started_at_utc": run_started_at_utc,
        "completed_destinations": completed,
        "shortfall": destinations - completed,
        "duration_s": duration_s,
        "sample_interval_s": sample_interval_s,
        "algorithm": algorithm,
        "actual_algorithms": sorted({row["algorithm"] for row in summary_rows}),
        "max_attempts": max_attempts,
        "tcp_info_layout": "Linux struct tcp_info: core through tcpi_bytes_acked (128 bytes); pacing rate at offset 104 and delivery rate at offset 160 when returned by the host kernel",
        "units": {
            "timestamp_utc": "ISO 8601 UTC",
            "elapsed_s": "seconds from data-transfer start",
            "interval_s": "actual elapsed seconds between samples",
            "bytes_acked": "bytes",
            "acknowledged_bytes_delta": "bytes",
            "goodput_bps": "bits per second",
            "snd_cwnd_segments": "TCP segments",
            "snd_cwnd_bytes": "bytes, snd_cwnd_segments multiplied by tcpi_snd_mss",
            "srtt_us": "microseconds",
            "rttvar_us": "microseconds",
            "lost": "current packet-loss estimate reported by tcpi_lost",
            "lost_change": "signed change in the tcpi_lost estimate between samples; not a count of newly lost packets",
            "total_retransmits": "cumulative retransmitted packets",
            "total_retransmits_delta": "retransmitted packets during the actual sample interval",
            "pacing_rate_bps": "bits per second",
            "delivery_rate_bps": "bits per second",
        },
    }
    with FILE_LOCK:
        (output_dir / f"run_metadata_{run_id}.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    return metadata


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Assignment 2 Step 1 against standard iperf3 servers.")
    parser.add_argument("--server-list", type=Path, default=Path("config/listed_iperf3_servers.csv"))
    parser.add_argument("--output-dir", type=Path, default=Path("outputs/tables"))
    parser.add_argument("--destinations", type=int, default=10)
    parser.add_argument("--duration", type=float, default=60.0)
    parser.add_argument("--sample-interval", type=float, default=1.0)
    parser.add_argument("--max-attempts", type=int, default=None)
    parser.add_argument("--seed", type=int, default=422)
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--workers", type=int, default=4, help="Maximum concurrent endpoint attempts.")
    parser.add_argument("--debug", action="store_true", help="Try one intentional failure, then one fixed public endpoint.")
    parser.add_argument("--debug-log", action="store_true", help="Print thread-aware protocol and scheduling details.")
    arguments = parser.parse_args()
    if arguments.debug_log:
        logging.basicConfig(
            level=logging.DEBUG,
            format="%(asctime)s %(levelname)s [%(threadName)s] %(name)s: %(message)s",
        )
    run_id = arguments.run_id or datetime.now(timezone.utc).strftime("step1-%Y%m%dT%H%M%SZ")
    if arguments.debug:
        destinations = 1
        max_attempts = 2
        candidates = DEBUG_ENDPOINTS
    else:
        max_attempts = arguments.max_attempts or arguments.destinations * 3
        with FILE_LOCK:
            candidates = select_endpoints(load_endpoints(arguments.server_list, arguments.seed), max_attempts, arguments.seed)
        destinations = arguments.destinations
    metadata = run_step1_experiment(
        arguments.output_dir,
        destinations=destinations,
        duration_s=arguments.duration,
        sample_interval_s=arguments.sample_interval,
        run_id=run_id,
        candidates=candidates,
        max_attempts=max_attempts,
        workers=arguments.workers,
        debug=arguments.debug,
    )
    print(json.dumps(metadata, indent=2))


if __name__ == "__main__":
    main()
import csv
import tempfile
import threading
import unittest
from datetime import datetime, timezone
from pathlib import Path

from src.assignment2_step1 import LinuxIperf3Client, LiveRunResult, run_step1_experiment
from src.simulated_client import Endpoint
from src.tcp_info import TcpInfo


class FakeLiveClient:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def run(self, endpoint: Endpoint, run_id: str, duration_s: float, sample_interval_s: float) -> LiveRunResult:
        self.calls.append(endpoint.host)
        if endpoint.host == "fail.example":
            return LiveRunResult(endpoint, "failed", [], "access_denied")
        return LiveRunResult(
            endpoint,
            "completed",
            [
                {
                    "run_id": run_id,
                    "measurement_mode": "live",
                    "destination": endpoint.host,
                    "port": endpoint.port,
                    "elapsed_s": 0.0,
                    "interval_s": None,
                    "bytes_acked": 100,
                    "goodput_bps": None,
                    "snd_cwnd_segments": 10,
                    "srtt_us": 1_000,
                    "rttvar_us": 100,
                    "retransmits": 0,
                    "lost": 0,
                    "total_retransmits": 0,
                    "notes": "",
                },
                {
                    "run_id": run_id,
                    "measurement_mode": "live",
                    "destination": endpoint.host,
                    "port": endpoint.port,
                    "elapsed_s": 1.0,
                    "interval_s": 1.0,
                    "bytes_acked": 300,
                    "goodput_bps": 1_600.0,
                    "snd_cwnd_segments": 12,
                    "srtt_us": 1_100,
                    "rttvar_us": 100,
                    "retransmits": 0,
                    "lost": 0,
                    "total_retransmits": 0,
                    "notes": "",
                },
            ],
        )


class ConcurrentFakeClient:
    def __init__(self) -> None:
        self.barrier = threading.Barrier(2)
        self.lock = threading.Lock()
        self.active = 0
        self.max_active = 0

    def run(self, endpoint: Endpoint, run_id: str, duration_s: float, sample_interval_s: float) -> LiveRunResult:
        with self.lock:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        try:
            self.barrier.wait(timeout=1.0)
            return LiveRunResult(endpoint, "completed", [])
        finally:
            with self.lock:
                self.active -= 1


class Assignment2Step1Tests(unittest.TestCase):
    def test_goodput_uses_acknowledged_byte_delta_and_actual_interval(self) -> None:
        endpoint = Endpoint("works.example", 5201, "", "", "", "", "")
        info = TcpInfo(1_250, 10, 1_000, 100, 3, 0, 7, 1_000, 2_000_000, 1_500_000)

        sample = LinuxIperf3Client._sample(
            endpoint,
            "goodput-test",
            1.5,
            info,
            0.25,
            1_000,
            previous_total_retransmits=5,
            previous_lost=2,
            timestamp_utc=datetime(2026, 10, 1, tzinfo=timezone.utc),
            actual_algorithm="cubic",
        )

        self.assertEqual(sample["interval_s"], 1.25)
        self.assertEqual(sample["goodput_bps"], 1_600.0)
        self.assertEqual(sample["total_retransmits_delta"], 2)
        self.assertEqual(sample["lost_change"], 1)
        self.assertEqual(sample["actual_algorithm"], "cubic")
        self.assertEqual(sample["timestamp_utc"], "2026-10-01T00:00:00+00:00")
        self.assertEqual(sample["snd_cwnd_bytes"], 10_000)
        self.assertEqual(sample["pacing_rate_bps"], 16_000_000)
        self.assertEqual(sample["delivery_rate_bps"], 12_000_000)

    def test_lost_change_preserves_a_decrease_in_the_current_loss_estimate(self) -> None:
        endpoint = Endpoint("works.example", 5201, "", "", "", "", "")
        info = TcpInfo(1_000, 10, 1_000, 100, 2, 0, 7)

        sample = LinuxIperf3Client._sample(
            endpoint,
            "lost-change-test",
            2.0,
            info,
            1.0,
            500,
            previous_total_retransmits=5,
            previous_lost=7,
        )

        self.assertEqual(sample["lost"], 2)
        self.assertEqual(sample["lost_change"], -5)
        self.assertNotIn("lost counter decreased", str(sample["notes"]))

    def test_goodput_is_omitted_when_the_acknowledged_counter_decreases(self) -> None:
        endpoint = Endpoint("works.example", 5201, "", "", "", "", "")
        info = TcpInfo(999, 10, 1_000, 100, 0, 0, 0)

        sample = LinuxIperf3Client._sample(endpoint, "goodput-test", 2.0, info, 1.0, 1_000)

        self.assertIsNone(sample["goodput_bps"])
        self.assertIn("decreased", str(sample["notes"]))

    def test_failed_endpoint_is_replaced_and_required_tables_are_written(self) -> None:
        endpoints = [
            Endpoint("fail.example", 5201, "", "", "", "", ""),
            Endpoint("works.example", 5201, "", "", "", "", ""),
        ]
        client = FakeLiveClient()
        with tempfile.TemporaryDirectory() as temporary_directory:
            output_directory = Path(temporary_directory)
            metadata = run_step1_experiment(
                output_directory,
                destinations=1,
                duration_s=1.0,
                sample_interval_s=1.0,
                run_id="step1-test",
                candidates=endpoints,
                client=client,
                max_attempts=2,
            )

            self.assertEqual(client.calls, ["fail.example", "works.example"])
            self.assertEqual(metadata["completed_destinations"], 1)
            self.assertEqual(metadata["shortfall"], 0)
            self.assertTrue((output_directory / "selected_endpoints_step1-test.csv").exists())
            self.assertTrue((output_directory / "attempts_step1-test.csv").exists())
            self.assertTrue((output_directory / "samples_step1-test.csv").exists())
            self.assertTrue((output_directory / "summary_step1-test.csv").exists())

            with (output_directory / "attempts_step1-test.csv").open(newline="", encoding="utf-8") as handle:
                attempts = list(csv.DictReader(handle))
            self.assertEqual(attempts[0]["failure_reason"], "access_denied")
            self.assertEqual(attempts[1]["status"], "completed")

    def test_workers_run_independent_endpoint_attempts_in_parallel(self) -> None:
        endpoints = [
            Endpoint("one.example", 5201, "", "", "", "", ""),
            Endpoint("two.example", 5201, "", "", "", "", ""),
        ]
        client = ConcurrentFakeClient()
        with tempfile.TemporaryDirectory() as temporary_directory:
            metadata = run_step1_experiment(
                Path(temporary_directory),
                destinations=2,
                duration_s=1.0,
                sample_interval_s=1.0,
                run_id="parallel-test",
                candidates=endpoints,
                client=client,
                max_attempts=2,
                workers=2,
            )

        self.assertEqual(metadata["completed_destinations"], 2)
        self.assertEqual(client.max_active, 2)


if __name__ == "__main__":
    unittest.main()
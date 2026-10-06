import csv
import tempfile
import unittest
from pathlib import Path

from src.assignment2_question3 import run_algorithm_comparison
from src.congestion_control import normalize_algorithms
from src.assignment2_step1 import LiveRunResult
from src.simulated_client import Endpoint


class FakeComparisonClient:
    def __init__(self, algorithm: str) -> None:
        self.algorithm = algorithm

    def run(self, endpoint: Endpoint, run_id: str, duration_s: float, sample_interval_s: float) -> LiveRunResult:
        return LiveRunResult(endpoint, "completed", [], actual_algorithm=self.algorithm, requested_algorithm=self.algorithm)


class Assignment2Question3Tests(unittest.TestCase):
    def test_reuses_endpoints_and_rotates_algorithm_order(self) -> None:
        endpoints = [Endpoint("one.example", 5201, "", "", "", "", "")]
        algorithms = normalize_algorithms(["CUBIC", "Reno"])
        with tempfile.TemporaryDirectory() as temporary_directory:
            output_directory = Path(temporary_directory)
            manifest_path = run_algorithm_comparison(
                output_directory,
                base_run_id="comparison-test",
                endpoints=endpoints,
                algorithms=algorithms,
                repetitions=2,
                duration_s=1.0,
                sample_interval_s=1.0,
                client_factory=lambda algorithm: FakeComparisonClient(algorithm.kernel_name),
            )

            with manifest_path.open(newline="", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))

        self.assertEqual([row["requested_algorithm"] for row in rows], ["CUBIC", "Reno", "Reno", "CUBIC"])
        self.assertEqual([row["repetition"] for row in rows], ["1", "1", "2", "2"])
        self.assertEqual({row["destination"] for row in rows}, {"one.example"})
        self.assertEqual([row["test_order"] for row in rows], ["1", "2", "3", "4"])


if __name__ == "__main__":
    unittest.main()
import unittest

from src.assignment2_pipeline import validate_available_algorithms
from src.congestion_control import normalize_algorithms


class Assignment2PipelineTests(unittest.TestCase):
    def test_reports_all_requested_algorithms_missing_from_the_host_kernel(self) -> None:
        algorithms = normalize_algorithms(["CUBIC", "Reno", "BBR"])

        with self.assertRaisesRegex(RuntimeError, "bbr"):
            validate_available_algorithms(algorithms, {"cubic", "reno"})

    def test_accepts_requested_algorithms_available_on_the_host_kernel(self) -> None:
        algorithms = normalize_algorithms(["CUBIC", "Reno"])

        validate_available_algorithms(algorithms, {"cubic", "reno", "bbr"})


if __name__ == "__main__":
    unittest.main()
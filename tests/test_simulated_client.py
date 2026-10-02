import csv
import json
import tempfile
import unittest
from pathlib import Path

from src.simulated_client import PlaceholderClient, load_endpoints, run_placeholder_experiment, select_endpoints


CSV_CONTENT = """IP/HOST,PORT,GB/S,CONTINENT,COUNTRY,SITE,PROVIDER
alpha.example,5201-5203,10,North America,US,Alpha,Example
bravo.example,5201,10,Europe,GB,Bravo,Example
charlie.example,6000-6002,1,Asia,JP,Charlie,Example
delta.example,7000,1,Asia,SG,Delta,Example
"""


class SimulatedClientTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.server_list = self.root / "servers.csv"
        self.server_list.write_text(CSV_CONTENT, encoding="utf-8")

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_port_ranges_and_seeded_selection_are_reproducible(self) -> None:
        endpoints_a = load_endpoints(self.server_list, seed=22)
        endpoints_b = load_endpoints(self.server_list, seed=22)
        self.assertEqual(endpoints_a, endpoints_b)
        alpha = next(endpoint for endpoint in endpoints_a if endpoint.host == "alpha.example")
        self.assertTrue(5201 <= alpha.port <= 5203)
        self.assertEqual(select_endpoints(endpoints_a, 2, 99), select_endpoints(endpoints_b, 2, 99))

    def test_placeholder_samples_are_deterministic_and_labelled_simulated(self) -> None:
        endpoint = load_endpoints(self.server_list, seed=1)[0]
        client = PlaceholderClient()
        first = client.run(endpoint, "test-run", 2.0, 1.0, "cubic")
        second = client.run(endpoint, "test-run", 2.0, 1.0, "cubic")
        self.assertEqual(first.samples, second.samples)
        self.assertEqual(first.samples[0]["measurement_mode"], "simulated")
        self.assertIsNone(first.samples[0]["goodput_bps"])
        sample = first.samples[1]
        acknowledged_delta = int(sample["bytes_acked"])
        self.assertEqual(sample["goodput_bps"], acknowledged_delta * 8 / float(sample["interval_s"]))
        self.assertIn("no network I/O", str(sample["notes"]))

    def test_rejected_candidate_is_replaced_and_tables_are_written(self) -> None:
        output_directory = self.root / "tables"
        metadata = run_placeholder_experiment(
            self.server_list,
            output_directory,
            destinations=2,
            duration_s=2.0,
            sample_interval_s=1.0,
            seed=5,
            run_id="replacement-test",
            client=PlaceholderClient(rejected_hosts={"alpha.example"}),
        )
        self.assertEqual(metadata["completed_destinations"], 2)
        self.assertTrue((output_directory / "selected_endpoints_replacement-test.csv").exists())
        self.assertTrue((output_directory / "attempts_replacement-test.csv").exists())
        self.assertTrue((output_directory / "samples_replacement-test.csv").exists())
        self.assertTrue((output_directory / "summary_replacement-test.csv").exists())

        with (output_directory / "samples_replacement-test.csv").open(newline="", encoding="utf-8") as handle:
            samples = list(csv.DictReader(handle))
        self.assertTrue(samples)
        self.assertTrue(all(row["measurement_mode"] == "simulated" for row in samples))

        with (output_directory / "run_metadata_replacement-test.json").open(encoding="utf-8") as handle:
            saved_metadata = json.load(handle)
        self.assertFalse(saved_metadata["network_io"])


if __name__ == "__main__":
    unittest.main()
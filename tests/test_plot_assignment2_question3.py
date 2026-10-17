import csv
import tempfile
import unittest
from pathlib import Path

from src.plot_assignment2_question3 import _algorithm_colors, generate_comparison_plots


class Assignment2Question3PlotTests(unittest.TestCase):
    def test_assigns_one_stable_color_to_every_algorithm(self) -> None:
        colors = _algorithm_colors(["CUBIC", "Reno", "BBR"])

        self.assertEqual(colors, {"CUBIC": "C0", "Reno": "C1", "BBR": "C2"})

    def test_default_plot_groups_comparisons_for_every_destination(self) -> None:
        manifest_rows = []
        with tempfile.TemporaryDirectory() as temporary_directory:
            tables_directory = Path(temporary_directory) / "tables"
            output_directory = Path(temporary_directory) / "plots"
            tables_directory.mkdir()
            for destination in ("one.example", "two.example"):
                for algorithm in ("CUBIC", "Reno"):
                    run_id = f"{destination}-{algorithm}"
                    manifest_rows.append(
                        {
                            "run_id": run_id,
                            "requested_algorithm": algorithm,
                            "destination": destination,
                            "status": "completed",
                        }
                    )
                    with (tables_directory / f"samples_{run_id}.csv").open("w", newline="", encoding="utf-8") as handle:
                        writer = csv.DictWriter(handle, fieldnames=["destination", "elapsed_s", "snd_cwnd_bytes", "srtt_us", "total_retransmits_delta", "goodput_bps"])
                        writer.writeheader()
                        writer.writerow({"destination": destination, "elapsed_s": "1", "snd_cwnd_bytes": "100000", "srtt_us": "20000", "total_retransmits_delta": "1", "goodput_bps": "10000000"})
            with (tables_directory / "comparison_manifest_comparison-test.csv").open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=manifest_rows[0].keys())
                writer.writeheader()
                writer.writerows(manifest_rows)

            plot_path = generate_comparison_plots("comparison-test", tables_directory, output_directory)

            self.assertEqual(plot_path, output_directory / "comparison_plots_comparison-test.pdf")
            self.assertTrue(plot_path.exists())
            self.assertGreater(plot_path.stat().st_size, 0)


if __name__ == "__main__":
    unittest.main()
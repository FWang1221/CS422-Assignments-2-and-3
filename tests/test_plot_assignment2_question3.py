import csv
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.plot_assignment2_question3 import _algorithm_colors, generate_comparison_plots
from src.plot_statistics import draw_statistics


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

            with patch("src.plot_assignment2_question3.draw_statistics", wraps=draw_statistics) as draw:
                plot_path = generate_comparison_plots("comparison-test", tables_directory, output_directory)

            self.assertEqual(draw.call_count, 14)
            self.assertEqual(draw.call_args_list[0].args[1], [
                ("CUBIC", [1.0], [100000 / 1024]),
                ("Reno", [1.0], [100000 / 1024]),
            ])
            self.assertFalse(draw.call_args_list[0].args[4])
            self.assertTrue(draw.call_args_list[4].args[4])

            self.assertEqual(plot_path, output_directory / "comparison_plots_comparison-test.pdf")
            self.assertTrue(plot_path.exists())
            self.assertGreater(plot_path.stat().st_size, 0)

    def test_statistics_pool_repetitions_per_algorithm_without_joining_traces(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = []
            for algorithm, repetitions in (("CUBIC", ([1, 2], [9])), ("BBR", ([4, 5, 6],))):
                for index, values in enumerate(repetitions):
                    run_id = f"{algorithm}-{index}"
                    manifest.append({
                        "run_id": run_id, "requested_algorithm": algorithm,
                        "destination": "one.example", "status": "completed",
                    })
                    with (root / f"samples_{run_id}.csv").open("w", newline="", encoding="utf-8") as handle:
                        writer = csv.DictWriter(handle, fieldnames=[
                            "destination", "elapsed_s", "snd_cwnd_bytes", "srtt_us",
                            "total_retransmits_delta", "goodput_bps",
                        ])
                        writer.writeheader()
                        for value in values:
                            writer.writerow({
                                "destination": "one.example", "elapsed_s": str(value),
                                "snd_cwnd_bytes": str(value * 1024), "srtt_us": str(value * 1000),
                                "total_retransmits_delta": "0", "goodput_bps": str(value * 1_000_000),
                            })
            with (root / "comparison_manifest_test.csv").open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=manifest[0].keys())
                writer.writeheader()
                writer.writerows(manifest)
            with patch("src.plot_assignment2_question3.draw_statistics", wraps=draw_statistics) as draw:
                generate_comparison_plots("test", root, root)
            self.assertEqual(draw.call_args_list[4].args[1], [
                ("CUBIC", [1, 2, 9], [1, 2, 9]),
                ("BBR", [4, 5, 6], [4, 5, 6]),
            ])


if __name__ == "__main__":
    unittest.main()
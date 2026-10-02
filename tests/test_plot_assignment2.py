import csv
import tempfile
import unittest
from pathlib import Path

from src.plot_assignment2 import generate_run_plots


class Assignment2PlotTests(unittest.TestCase):
    def test_generates_a_pdf_for_each_required_metric_from_a_run_id(self) -> None:
        rows = []
        for destination, base_goodput in (("one.example", 10_000_000), ("two.example", 20_000_000)):
            for elapsed_s in (1, 2):
                rows.append(
                    {
                        "destination": destination,
                        "port": "5201",
                        "actual_algorithm": "cubic",
                        "elapsed_s": str(elapsed_s),
                        "goodput_bps": str(base_goodput * elapsed_s),
                        "snd_cwnd_bytes": str(100_000 * elapsed_s),
                        "srtt_us": str(20_000 * elapsed_s),
                        "total_retransmits_delta": str(elapsed_s),
                    }
                )

        with tempfile.TemporaryDirectory() as temporary_directory:
            tables_directory = Path(temporary_directory) / "tables"
            output_directory = Path(temporary_directory) / "plots"
            tables_directory.mkdir()
            samples_path = tables_directory / "samples_step1-test.csv"
            with samples_path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=rows[0].keys())
                writer.writeheader()
                writer.writerows(rows)

            plot_path = generate_run_plots("step1-test", tables_directory, output_directory)

            self.assertEqual(plot_path, output_directory / "plots_step1-test.pdf")
            self.assertTrue(plot_path.exists())
            self.assertGreater(plot_path.stat().st_size, 0)

            timestamp_plot_path = generate_run_plots("test", tables_directory, output_directory)
            self.assertEqual(timestamp_plot_path, plot_path)


if __name__ == "__main__":
    unittest.main()
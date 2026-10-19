import csv
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from src.plot_assignment2 import _pairs, _plot_pages, generate_run_plots


class Assignment2PlotTests(unittest.TestCase):
    def test_pairs_exclude_non_finite_and_missing_values_and_apply_units(self) -> None:
        rows = [
            {"x": "1024", "y": "2000"},
            {"x": "nan", "y": "3000"},
            {"x": "2048", "y": ""},
            {"x": "3072", "y": "inf"},
            {"x": "0", "y": "0"},
        ]
        self.assertEqual(_pairs(rows, "x", "y", 1024, 1000), ([1, 0], [2, 0]))

    def test_each_page_contains_per_algorithm_statistics_in_displayed_units(self) -> None:
        rows = []
        for algorithm, factor in (("cubic", 1), ("reno", 2)):
            for sample in (1, 2, 9):
                rows.append({
                    "actual_algorithm": algorithm, "elapsed_s": str(sample),
                    "snd_cwnd_bytes": str(sample * factor * 1024),
                    "srtt_us": str(sample * factor * 1000),
                    "total_retransmits_delta": str(sample * factor),
                    "goodput_bps": str(sample * factor * 1_000_000),
                })
        tables = []

        def capture(figure) -> None:
            table = figure.axes[1].tables[0]
            tables.append({cell: value.get_text().get_text() for cell, value in table.get_celld().items()})

        pdf = Mock()
        pdf.savefig.side_effect = capture
        _plot_pages(pdf, "test", {"one.example": rows})

        self.assertEqual(len(tables), 7)
        self.assertEqual(tables[0][1, 0], "cubic")
        self.assertEqual(tables[0][1, 2], "4")
        self.assertEqual(tables[0][1, 3], "2")
        self.assertEqual(tables[0][2, 0], "reno")
        self.assertEqual(tables[0][2, 2], "8")
        self.assertEqual(tables[0][1, 5], "--")
        self.assertEqual(tables[4][1, 5], "1.000")
        self.assertEqual(tables[4][2, 1], "Goodput (Mbps)")

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
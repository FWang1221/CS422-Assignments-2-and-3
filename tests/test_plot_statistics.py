import unittest

from src.plot_statistics import number, pearson_label, summary_rows


class PlotStatisticsTests(unittest.TestCase):
    def test_numbers_exclude_missing_and_non_finite_but_reject_malformed(self) -> None:
        for value in ("", " ", "nan", "inf", "-inf"):
            self.assertIsNone(number({"metric": value}, "metric"))
        self.assertIsNone(number({}, "metric"))
        self.assertEqual(number({"metric": " 0 "}, "metric"), 0)
        with self.assertRaises(ValueError):
            number({"metric": "invalid"}, "metric")

    def test_pearson_handles_direction_and_undefined_cases(self) -> None:
        self.assertEqual(pearson_label([1, 2, 3], [2, 4, 6]), "1.000")
        self.assertEqual(pearson_label([1, 2, 3], [6, 4, 2]), "-1.000")
        self.assertEqual(pearson_label([1, 2, 3], [1, 0, 1]), "0.000")
        self.assertEqual(pearson_label([], []), "N/A (<3 pairs)")
        self.assertEqual(pearson_label([1, 2], [2, 4]), "N/A (<3 pairs)")
        self.assertEqual(pearson_label([1, 1, 1], [2, 4, 6]), "N/A (constant)")
        self.assertEqual(pearson_label([1, 2, 3], [2, 2, 2]), "N/A (constant)")

    def test_scatter_summarizes_both_metrics_separately_per_algorithm(self) -> None:
        rows = summary_rows(
            [("cubic", [1, 2, 9], [2, 4, 18]), ("reno", [], [])],
            "RTT (ms)", "Goodput (Mbps)", True,
        )
        self.assertEqual(rows, [
            ["cubic", "RTT (ms)", "4", "2", "3", "1.000"],
            ["cubic", "Goodput (Mbps)", "8", "4", "3", ""],
            ["reno", "RTT (ms)", "N/A", "N/A", "0", "N/A (<3 pairs)"],
            ["reno", "Goodput (Mbps)", "N/A", "N/A", "0", ""],
        ])

    def test_time_series_summarizes_only_metric_without_time_correlation(self) -> None:
        self.assertEqual(
            summary_rows([("bbr", [1, 2, 3], [2, 4, 18])], "Time (s)", "RTT (ms)", False),
            [["bbr", "RTT (ms)", "8", "4", "3", "--"]],
        )


if __name__ == "__main__":
    unittest.main()

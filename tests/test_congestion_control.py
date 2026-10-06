import unittest

from src.congestion_control import CUSTOM_ALGORITHM_DEFAULT, normalize_algorithms


class CongestionControlTests(unittest.TestCase):
    def test_normalizes_builtin_aliases_and_preserves_order(self) -> None:
        algorithms = normalize_algorithms(["CUBIC", "Reno", "bbr"])

        self.assertEqual([algorithm.label for algorithm in algorithms], ["CUBIC", "Reno", "BBR"])
        self.assertEqual([algorithm.kernel_name for algorithm in algorithms], ["cubic", "reno", "bbr"])
        self.assertFalse(any(algorithm.is_handwritten for algorithm in algorithms))

    def test_resolves_hand_written_to_the_configured_future_kernel_name(self) -> None:
        algorithm = normalize_algorithms(["Hand-Written"])[0]

        self.assertEqual(algorithm.kernel_name, CUSTOM_ALGORITHM_DEFAULT)
        self.assertTrue(algorithm.is_handwritten)

    def test_rejects_unknown_and_duplicate_algorithm_requests(self) -> None:
        with self.assertRaises(ValueError):
            normalize_algorithms(["vegas"])
        with self.assertRaises(ValueError):
            normalize_algorithms(["cubic", "CUBIC"])


if __name__ == "__main__":
    unittest.main()
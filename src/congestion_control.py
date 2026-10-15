"""! @file congestion_control.py
@brief Congestion-control request normalization for Assignment 2 Question 3(a).

@details Built-in names map to Linux `TCP_CONGESTION` values. `Hand-Written`
uses the TCP eBPF registration name for Assignment 2 Question 3(b) and
Assignment 3; it remains unavailable until the custom object is loaded into
the host kernel.
"""

from __future__ import annotations

from dataclasses import dataclass


CUSTOM_ALGORITHM_DEFAULT = "cs422_handwrite"


@dataclass(frozen=True)
class CongestionAlgorithm:
    """! @brief One requested algorithm and its Linux kernel identifier.

    @param label Report-facing canonical algorithm label.
    @param kernel_name Value passed to `setsockopt(TCP_CONGESTION)`.
    @param is_handwritten Whether this names the custom kernel algorithm.
    """

    label: str
    kernel_name: str
    is_handwritten: bool = False


_BUILTIN_ALGORITHMS = {
    "cubic": CongestionAlgorithm("CUBIC", "cubic"),
    "reno": CongestionAlgorithm("Reno", "reno"),
    "bbr": CongestionAlgorithm("BBR", "bbr"),
}
_HAND_WRITTEN_ALIASES = {"hand-written", "handwritten", "hand_written"}


def normalize_algorithms(requested: list[str], handwritten_kernel_name: str = CUSTOM_ALGORITHM_DEFAULT) -> list[CongestionAlgorithm]:
    """! @brief Normalize one or more user-requested comparison algorithms.

    @param requested Case-insensitive CLI algorithm names.
    @param handwritten_kernel_name Custom Linux algorithm registration name.
    @return Ordered, duplicate-free algorithm specifications.
    @throws ValueError For empty, unsupported, duplicate, or invalid requests.
    """
    if not requested:
        raise ValueError("at least one congestion-control algorithm is required")
    custom_name = handwritten_kernel_name.strip()
    if not custom_name or len(custom_name.encode("ascii", errors="ignore")) != len(custom_name) or len(custom_name) > 15:
        raise ValueError("hand-written kernel algorithm name must be 1-15 ASCII characters")

    algorithms: list[CongestionAlgorithm] = []
    seen_kernel_names: set[str] = set()
    for value in requested:
        normalized = value.strip().lower()
        if normalized in _BUILTIN_ALGORITHMS:
            algorithm = _BUILTIN_ALGORITHMS[normalized]
        elif normalized in _HAND_WRITTEN_ALIASES:
            algorithm = CongestionAlgorithm("Hand-Written", custom_name, is_handwritten=True)
        else:
            raise ValueError(f"unsupported congestion-control algorithm: {value!r}")
        if algorithm.kernel_name in seen_kernel_names:
            raise ValueError(f"duplicate congestion-control algorithm: {value!r}")
        seen_kernel_names.add(algorithm.kernel_name)
        algorithms.append(algorithm)
    return algorithms
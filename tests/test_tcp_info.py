import struct
import unittest
from unittest.mock import patch

from src.tcp_info import configure_congestion_algorithm, decode_tcp_info


class RecordingSocket:
    def __init__(self) -> None:
        self.calls: list[tuple[int, int, bytes]] = []

    def setsockopt(self, level: int, option: int, value: bytes) -> None:
        self.calls.append((level, option, value))


class TcpInfoTests(unittest.TestCase):
    def test_configures_a_named_algorithm_before_connect(self) -> None:
        data_socket = RecordingSocket()
        with patch("src.tcp_info.socket.TCP_CONGESTION", 42, create=True):
            configure_congestion_algorithm(data_socket, "reno")

        self.assertEqual(data_socket.calls, [(6, 42, b"reno")])

    def test_decodes_linux_tcp_info_fields_used_by_assignment_one(self) -> None:
        raw = bytearray(168)
        struct.pack_into("=I", raw, 32, 7)  # tcpi_lost
        struct.pack_into("=I", raw, 36, 11)  # tcpi_retrans
        struct.pack_into("=I", raw, 68, 25_000)  # tcpi_rtt
        struct.pack_into("=I", raw, 72, 5_000)  # tcpi_rttvar
        struct.pack_into("=I", raw, 80, 128)  # tcpi_snd_cwnd, in segments
        struct.pack_into("=I", raw, 100, 13)  # tcpi_total_retrans
        struct.pack_into("=Q", raw, 104, 12_500_000)  # tcpi_pacing_rate, bytes/s
        struct.pack_into("=Q", raw, 120, 12_345_678)  # tcpi_bytes_acked
        struct.pack_into("=I", raw, 16, 1_440)  # tcpi_snd_mss
        struct.pack_into("=Q", raw, 160, 11_000_000)  # tcpi_delivery_rate, bytes/s

        info = decode_tcp_info(bytes(raw))

        self.assertEqual(info.bytes_acked, 12_345_678)
        self.assertEqual(info.snd_cwnd_segments, 128)
        self.assertEqual(info.rtt_us, 25_000)
        self.assertEqual(info.rttvar_us, 5_000)
        self.assertEqual(info.lost, 7)
        self.assertEqual(info.retransmits, 11)
        self.assertEqual(info.total_retransmits, 13)
        self.assertEqual(info.snd_mss_bytes, 1_440)
        self.assertEqual(info.pacing_rate_bytes_per_s, 12_500_000)
        self.assertEqual(info.delivery_rate_bytes_per_s, 11_000_000)

    def test_rejects_a_buffer_without_bytes_acked(self) -> None:
        with self.assertRaises(ValueError):
            decode_tcp_info(b"\x00" * 120)


if __name__ == "__main__":
    unittest.main()
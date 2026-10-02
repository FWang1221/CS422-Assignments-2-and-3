"""Linux TCP_INFO decoding used by Assignment 2 measurements.

The core layout through `tcpi_bytes_acked` is available in Linux 4.9+. Newer
kernels append pacing and delivery-rate fields; unavailable appended fields are
represented as ``None`` rather than guessed.
"""

from __future__ import annotations

import socket
import struct
from dataclasses import dataclass


TCP_INFO_MIN_SIZE = 128


@dataclass(frozen=True)
class TcpInfo:
    bytes_acked: int
    snd_cwnd_segments: int
    rtt_us: int
    rttvar_us: int
    lost: int
    retransmits: int
    total_retransmits: int
    snd_mss_bytes: int = 0
    pacing_rate_bytes_per_s: int | None = None
    delivery_rate_bytes_per_s: int | None = None


def decode_tcp_info(raw: bytes) -> TcpInfo:
    if len(raw) < TCP_INFO_MIN_SIZE:
        raise ValueError(f"TCP_INFO buffer is too short: expected at least {TCP_INFO_MIN_SIZE} bytes")
    return TcpInfo(
        bytes_acked=struct.unpack_from("=Q", raw, 120)[0],
        snd_cwnd_segments=struct.unpack_from("=I", raw, 80)[0],
        rtt_us=struct.unpack_from("=I", raw, 68)[0],
        rttvar_us=struct.unpack_from("=I", raw, 72)[0],
        lost=struct.unpack_from("=I", raw, 32)[0],
        retransmits=struct.unpack_from("=I", raw, 36)[0],
        total_retransmits=struct.unpack_from("=I", raw, 100)[0],
        snd_mss_bytes=struct.unpack_from("=I", raw, 16)[0],
        pacing_rate_bytes_per_s=struct.unpack_from("=Q", raw, 104)[0] if len(raw) >= 112 else None,
        delivery_rate_bytes_per_s=struct.unpack_from("=Q", raw, 160)[0] if len(raw) >= 168 else None,
    )


def get_tcp_info(data_socket: socket.socket) -> TcpInfo:
    tcp_info_option = getattr(socket, "TCP_INFO", None)
    if tcp_info_option is None:
        raise OSError("TCP_INFO is unavailable; run the live experiment on Linux or WSL2")
    raw = data_socket.getsockopt(socket.IPPROTO_TCP, tcp_info_option, 256)
    return decode_tcp_info(raw)


def get_congestion_algorithm(data_socket: socket.socket) -> str:
    """Return the kernel-confirmed congestion-control algorithm for a socket."""
    tcp_congestion_option = getattr(socket, "TCP_CONGESTION", None)
    if tcp_congestion_option is None:
        raise OSError("TCP_CONGESTION is unavailable; run the live experiment on Linux or WSL2")
    raw = data_socket.getsockopt(socket.IPPROTO_TCP, tcp_congestion_option, 16)
    algorithm = raw.split(b"\x00", maxsplit=1)[0].decode("ascii")
    if not algorithm:
        raise OSError("kernel returned an empty TCP congestion-control algorithm")
    return algorithm
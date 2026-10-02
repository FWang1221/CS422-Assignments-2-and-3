"""A narrow TCP-only iperf3 client for local protocol testing.

This client supports one forward TCP stream. It is intentionally separate from
the deterministic placeholder and is not yet the Assignment 2 measurement
client: it does not collect TCP_INFO or write experiment tables.
"""

from __future__ import annotations

import argparse
import json
import math
import socket
import time
from dataclasses import dataclass
from typing import Any, Callable

from src.iperf3_protocol import (
    CREATE_STREAMS,
    DISPLAY_RESULTS,
    EXCHANGE_RESULTS,
    IPERF_DONE,
    PARAM_EXCHANGE,
    TEST_END,
    TEST_RUNNING,
    TEST_START,
    IperfProtocolError,
    make_cookie,
    recv_json,
    recv_state,
    send_json,
    send_state,
)


SocketFactory = Callable[[tuple[str, int], float], socket.socket]


@dataclass(frozen=True)
class TestResult:
    bytes_sent: int
    elapsed_s: float
    server_results: dict[str, Any]


class Iperf3TestClient:
    """Run a basic forward TCP iperf3 transfer against a standard server."""

    def __init__(
        self,
        host: str,
        port: int = 5201,
        *,
        duration_s: float = 5.0,
        block_size: int = 128 * 1024,
        timeout_s: float = 10.0,
        socket_factory: SocketFactory = socket.create_connection,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if not host:
            raise ValueError("host is required")
        if not 1 <= port <= 65535:
            raise ValueError("port must be between 1 and 65535")
        if duration_s <= 0:
            raise ValueError("duration must be positive")
        if block_size <= 0:
            raise ValueError("block size must be positive")
        if timeout_s <= 0:
            raise ValueError("timeout must be positive")
        self.host = host
        self.port = port
        self.duration_s = duration_s
        self.block_size = block_size
        self.timeout_s = timeout_s
        self.socket_factory = socket_factory
        self.clock = clock

    def _connect(self) -> socket.socket:
        connection = self.socket_factory((self.host, self.port), self.timeout_s)
        connection.settimeout(self.timeout_s)
        return connection

    def _parameters(self) -> dict[str, Any]:
        return {
            "tcp": True,
            "omit": 0,
            "time": math.ceil(self.duration_s),
            "num": 0,
            "blockcount": 0,
            "parallel": 1,
            "len": self.block_size,
            "client_version": "cs422-test-client",
        }

    @staticmethod
    def _expect_state(control_socket: socket.socket, expected: int) -> None:
        actual = recv_state(control_socket)
        if actual != expected:
            raise IperfProtocolError(f"expected state {expected}, received {actual}")

    def run(self) -> TestResult:
        control_socket: socket.socket | None = None
        data_socket: socket.socket | None = None
        try:
            cookie = make_cookie()
            control_socket = self._connect()
            control_socket.sendall(cookie)

            self._expect_state(control_socket, PARAM_EXCHANGE)
            send_json(control_socket, self._parameters())
            self._expect_state(control_socket, CREATE_STREAMS)

            data_socket = self._connect()
            data_socket.sendall(cookie)
            self._expect_state(control_socket, TEST_START)
            self._expect_state(control_socket, TEST_RUNNING)

            payload = b"0" * self.block_size
            bytes_sent = 0
            start_time = self.clock()
            deadline = start_time + self.duration_s
            current_time = start_time
            while current_time < deadline:
                data_socket.sendall(payload)
                bytes_sent += len(payload)
                current_time = self.clock()

            elapsed_s = current_time - start_time
            send_state(control_socket, TEST_END)
            self._expect_state(control_socket, EXCHANGE_RESULTS)
            send_json(
                control_socket,
                {
                    "cpu_util_total": 0.0,
                    "cpu_util_user": 0.0,
                    "cpu_util_system": 0.0,
                    "sender_has_retransmits": -1,
                    "streams": [
                        {
                            "id": 1,
                            "bytes": bytes_sent,
                            "retransmits": -1,
                            "jitter": 0.0,
                            "errors": 0,
                            "omitted_errors": 0,
                            "packets": 0,
                            "omitted_packets": 0,
                            "start_time": 0.0,
                            "end_time": elapsed_s,
                        }
                    ],
                },
            )
            server_results = recv_json(control_socket)
            self._expect_state(control_socket, DISPLAY_RESULTS)
            send_state(control_socket, IPERF_DONE)
            return TestResult(bytes_sent, elapsed_s, server_results)
        finally:
            if data_socket is not None:
                data_socket.close()
            if control_socket is not None:
                control_socket.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a minimal TCP-only iperf3 protocol test.")
    parser.add_argument("host")
    parser.add_argument("--port", type=int, default=5201)
    parser.add_argument("--duration", type=float, default=5.0)
    parser.add_argument("--block-size", type=int, default=128 * 1024)
    parser.add_argument("--timeout", type=float, default=10.0)
    arguments = parser.parse_args()
    result = Iperf3TestClient(
        arguments.host,
        arguments.port,
        duration_s=arguments.duration,
        block_size=arguments.block_size,
        timeout_s=arguments.timeout,
    ).run()
    print(json.dumps({"bytes_sent": result.bytes_sent, "elapsed_s": result.elapsed_s, "server_results": result.server_results}, indent=2))


if __name__ == "__main__":
    main()
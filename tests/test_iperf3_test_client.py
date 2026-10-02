import json
import struct
import unittest

from src.iperf3_protocol import (
    CREATE_STREAMS,
    DISPLAY_RESULTS,
    EXCHANGE_RESULTS,
    PARAM_EXCHANGE,
    TEST_RUNNING,
    TEST_START,
)
from src.iperf3_test_client import Iperf3TestClient


def frame_json(value: dict[str, object]) -> bytes:
    encoded = json.dumps(value, separators=(",", ":")).encode("utf-8")
    return struct.pack("!I", len(encoded)) + encoded


class ScriptedSocket:
    def __init__(self, incoming: bytes = b"") -> None:
        self.incoming = bytearray(incoming)
        self.sent = bytearray()
        self.closed = False
        self.timeout: float | None = None

    def recv(self, size: int) -> bytes:
        result = bytes(self.incoming[:size])
        del self.incoming[:size]
        return result

    def sendall(self, payload: bytes) -> None:
        self.sent.extend(payload)

    def settimeout(self, timeout: float) -> None:
        self.timeout = timeout

    def setsockopt(self, level: int, option: int, value: int) -> None:
        pass

    def close(self) -> None:
        self.closed = True


class Iperf3TestClientTests(unittest.TestCase):
    def test_client_follows_one_stream_lifecycle_and_closes_sockets(self) -> None:
        server_results = {
            "cpu_util_total": 1.0,
            "cpu_util_user": 0.5,
            "cpu_util_system": 0.5,
            "sender_has_retransmits": 0,
            "streams": [],
        }
        control = ScriptedSocket(
            bytes([PARAM_EXCHANGE, CREATE_STREAMS, TEST_START, TEST_RUNNING, EXCHANGE_RESULTS])
            + frame_json(server_results)
            + bytes([DISPLAY_RESULTS])
        )
        data = ScriptedSocket()
        sockets = iter([control, data])
        clock_values = iter([0.0, 0.0, 0.02])
        client = Iperf3TestClient(
            "127.0.0.1",
            5201,
            duration_s=0.01,
            block_size=8,
            socket_factory=lambda address, timeout: next(sockets),
            clock=lambda: next(clock_values),
        )

        result = client.run()

        self.assertGreaterEqual(result.bytes_sent, 8)
        self.assertEqual(result.server_results, server_results)
        self.assertTrue(control.closed)
        self.assertTrue(data.closed)
        self.assertEqual(data.sent[:37][-1:], b"\x00")
        self.assertGreater(len(data.sent), 37)

        parameter_size = struct.unpack("!I", control.sent[37:41])[0]
        parameters = json.loads(control.sent[41 : 41 + parameter_size])
        self.assertEqual(parameters["len"], 8)
        self.assertEqual(parameters["parallel"], 1)
        self.assertTrue(parameters["tcp"])


if __name__ == "__main__":
    unittest.main()
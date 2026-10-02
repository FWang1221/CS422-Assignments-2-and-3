import json
import struct
import unittest

from src.iperf3_protocol import (
    ACCESS_DENIED,
    PARAM_EXCHANGE,
    SERVER_ERROR,
    IperfAccessDenied,
    IperfServerError,
    decode_state,
    make_cookie,
    recv_json,
    send_json,
)


class FragmentedSocket:
    def __init__(self, chunks: list[bytes]) -> None:
        self.chunks = list(chunks)
        self.sent = bytearray()

    def recv(self, size: int) -> bytes:
        if not self.chunks:
            return b""
        chunk = self.chunks.pop(0)
        if len(chunk) <= size:
            return chunk
        self.chunks.insert(0, chunk[size:])
        return chunk[:size]

    def sendall(self, payload: bytes) -> None:
        self.sent.extend(payload)


class Iperf3ProtocolTests(unittest.TestCase):
    def test_cookie_is_a_37_byte_ascii_c_string(self) -> None:
        cookie = make_cookie()
        self.assertEqual(len(cookie), 37)
        self.assertEqual(cookie[-1:], b"\x00")
        self.assertTrue(cookie[:-1].decode("ascii").isalnum())

    def test_json_frames_round_trip_when_tcp_fragments_reads(self) -> None:
        payload = {"tcp": True, "time": 5, "parallel": 1}
        encoded = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        framed = struct.pack(">I", len(encoded)) + encoded
        socket = FragmentedSocket([framed[:1], framed[1:3], framed[3:7], framed[7:]])

        self.assertEqual(recv_json(socket), payload)
        send_json(socket, payload)
        self.assertEqual(bytes(socket.sent), framed)

    def test_signed_control_states_identify_access_denied(self) -> None:
        self.assertEqual(decode_state(bytes([PARAM_EXCHANGE])), PARAM_EXCHANGE)
        with self.assertRaises(IperfAccessDenied):
            decode_state(struct.pack("b", ACCESS_DENIED))

    def test_server_error_reads_both_protocol_and_system_error_numbers(self) -> None:
        socket = FragmentedSocket([struct.pack("!i", 121), struct.pack("!i", 0)])
        with self.assertRaises(IperfServerError) as raised:
            decode_state(struct.pack("b", SERVER_ERROR), socket)
        self.assertEqual(raised.exception.iperf_error, 121)
        self.assertEqual(raised.exception.system_error, 0)


if __name__ == "__main__":
    unittest.main()
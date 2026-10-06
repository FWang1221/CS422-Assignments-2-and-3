"""! @file iperf3_protocol.py
@brief Framed control-channel primitives for Assignment 2 section 1(a).

@details State values match upstream iperf3 `src/iperf_api.h`. These helpers
keep the live client compatible with standard public iperf3 servers without
invoking the iperf3 binary.
"""

from __future__ import annotations

import json
import secrets
import struct
from typing import Any, Protocol


TEST_START = 1
TEST_RUNNING = 2
TEST_END = 4
PARAM_EXCHANGE = 9
CREATE_STREAMS = 10
SERVER_TERMINATE = 11
CLIENT_TERMINATE = 12
EXCHANGE_RESULTS = 13
DISPLAY_RESULTS = 14
IPERF_DONE = 16
ACCESS_DENIED = -1
SERVER_ERROR = -2
COOKIE_SIZE = 37
MAX_JSON_SIZE = 1024 * 1024


class SocketLike(Protocol):
    def recv(self, size: int) -> bytes: ...

    def sendall(self, payload: bytes) -> None: ...


class IperfProtocolError(RuntimeError):
    """The peer sent an invalid, unexpected, or incomplete protocol message."""


class IperfAccessDenied(IperfProtocolError):
    """The server is busy or rejected the client."""


class IperfServerError(IperfProtocolError):
    def __init__(self, iperf_error: int, system_error: int) -> None:
        self.iperf_error = iperf_error
        self.system_error = system_error
        super().__init__(f"server error {iperf_error}, system error {system_error}")


def make_cookie() -> bytes:
    """! @brief Create the fixed-size cookie required on each iperf3 connection.

    @return A 36-character ASCII token followed by a NUL byte (`COOKIE_SIZE`).
    """
    return secrets.token_hex(18).encode("ascii") + b"\x00"


def recv_exact(socket: SocketLike, size: int) -> bytes:
    """! @brief Read exactly one protocol frame fragment from a stream socket.

    @param socket Control socket or socket-compatible test double.
    @param size Required byte count.
    @return Exactly `size` bytes.
    @throws IperfProtocolError If the peer closes the connection prematurely.
    """
    chunks = bytearray()
    while len(chunks) < size:
        chunk = socket.recv(size - len(chunks))
        if not chunk:
            raise IperfProtocolError(f"unexpected EOF while reading {size} bytes")
        chunks.extend(chunk)
    return bytes(chunks)


def send_json(socket: SocketLike, value: dict[str, Any]) -> None:
    """! @brief Send a length-prefixed JSON control message.

    @param socket Connected iperf3 control socket.
    @param value JSON object for parameter or result exchange.
    @throws ValueError If the encoded message is empty or exceeds the safety cap.
    """
    encoded = json.dumps(value, separators=(",", ":")).encode("utf-8")
    if not encoded or len(encoded) > MAX_JSON_SIZE:
        raise ValueError("JSON control message has an invalid size")
    socket.sendall(struct.pack("!I", len(encoded)) + encoded)


def recv_json(socket: SocketLike, max_size: int = MAX_JSON_SIZE) -> dict[str, Any]:
    """! @brief Receive and validate one length-prefixed JSON control message.

    @param socket Connected iperf3 control socket.
    @param max_size Maximum accepted payload length in bytes.
    @return Decoded JSON object.
    @throws IperfProtocolError For malformed framing, JSON, or payload shape.
    """
    size = struct.unpack("!I", recv_exact(socket, 4))[0]
    if size == 0 or size > max_size:
        raise IperfProtocolError(f"invalid JSON control message size: {size}")
    try:
        value = json.loads(recv_exact(socket, size).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise IperfProtocolError("invalid JSON control message") from error
    if not isinstance(value, dict):
        raise IperfProtocolError("JSON control message must be an object")
    return value


def decode_state(state_bytes: bytes, socket: SocketLike | None = None) -> int:
    """! @brief Decode one signed iperf3 state byte and raise known failures.

    @param state_bytes One signed control-state byte.
    @param socket Control socket used to read extended server errors.
    @return A non-error protocol state.
    @throws IperfAccessDenied If the public server rejects the request.
    @throws IperfServerError If the server reports a protocol/system error.
    """
    if len(state_bytes) != 1:
        raise IperfProtocolError("control state must be exactly one byte")
    state = struct.unpack("b", state_bytes)[0]
    if state == ACCESS_DENIED:
        raise IperfAccessDenied("server denied the test request")
    if state == SERVER_ERROR:
        if socket is None:
            raise IperfProtocolError("server error state requires a control socket")
        iperf_error, system_error = struct.unpack("!ii", recv_exact(socket, 8))
        raise IperfServerError(iperf_error, system_error)
    if state in (SERVER_TERMINATE, CLIENT_TERMINATE):
        raise IperfProtocolError(f"peer terminated the test (state {state})")
    return state


def recv_state(socket: SocketLike) -> int:
    return decode_state(recv_exact(socket, 1), socket)


def send_state(socket: SocketLike, state: int) -> None:
    if not -128 <= state <= 127:
        raise ValueError("control state does not fit in a signed byte")
    socket.sendall(struct.pack("b", state))
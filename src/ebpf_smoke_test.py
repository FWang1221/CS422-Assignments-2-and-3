"""Load, exercise, and detach the custom TCP BPF controller or Reno scaffold.

This is a local integration test, not an Assignment 3 performance experiment.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import json
import os
from pathlib import Path
import platform
import shutil
import socket
import subprocess
import tempfile
import time
from collections.abc import Generator

from src.congestion_control import CUSTOM_ALGORITHM_DEFAULT
from src.tcp_info import configure_congestion_algorithm, get_congestion_algorithm, get_tcp_info


AVAILABLE_ALGORITHMS = Path("/proc/sys/net/ipv4/tcp_available_congestion_control")
IMPLEMENTATIONS = {
    "cs422_scaffold.bpf.o": "reno-backed-registration-scaffold",
    "cs422_handwrite.bpf.o": "delay-based-round-controller",
}


def available_algorithms() -> set[str]:
    return set(AVAILABLE_ALGORITHMS.read_text(encoding="ascii").split())


def wait_for_registration(registered: bool, timeout_s: float = 5.0) -> None:
    deadline = time.monotonic() + timeout_s
    while True:
        if (CUSTOM_ALGORITHM_DEFAULT in available_algorithms()) == registered:
            return
        if time.monotonic() >= deadline:
            state = "registered" if registered else "detached"
            raise RuntimeError(f"{CUSTOM_ALGORITHM_DEFAULT} did not become {state} within {timeout_s}s")
        time.sleep(0.05)


def check_environment(object_path: Path, bpffs: Path) -> None:
    if platform.system() != "Linux":
        raise RuntimeError("run this integration test inside Linux/WSL2")
    if os.geteuid() != 0:
        raise PermissionError("BPF attachment requires privileges; run this smoke test with sudo")
    if not object_path.is_file():
        raise FileNotFoundError(f"build the BPF object first; object not found: {object_path}")
    for command in ("bpftool", "findmnt"):
        if shutil.which(command) is None:
            raise RuntimeError(f"required command is not installed: {command}")
    filesystem = subprocess.run(
        ["findmnt", "--noheadings", "--output", "FSTYPE", "--target", str(bpffs)],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if filesystem != "bpf":
        raise RuntimeError(f"{bpffs} must be on a mounted BPF filesystem; see cc/ebpf/README.md")
    if CUSTOM_ALGORITHM_DEFAULT in available_algorithms():
        raise RuntimeError(f"{CUSTOM_ALGORITHM_DEFAULT} is already registered; refusing to touch it")


@contextmanager
def attached_scaffold(object_path: Path, bpffs: Path) -> Generator[None, None, None]:
    check_environment(object_path, bpffs)
    pin_directory = Path(tempfile.mkdtemp(prefix="cs422-smoke-", dir=bpffs))
    try:
        subprocess.run(
            ["bpftool", "struct_ops", "register", str(object_path), str(pin_directory)],
            check=True,
        )
        wait_for_registration(True)
        yield
    finally:
        # These pins belong exclusively to this invocation, including a partial load.
        for pin in pin_directory.iterdir():
            pin.unlink()
        pin_directory.rmdir()
        wait_for_registration(False)


def exercise_socket() -> dict[str, int | str]:
    payload = b"cs422-scaffold\n" * 1024
    transferred = 0
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.settimeout(5.0)
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sender:
            sender.settimeout(5.0)
            configure_congestion_algorithm(sender, CUSTOM_ALGORITHM_DEFAULT)
            sender.connect(listener.getsockname())
            receiver, _ = listener.accept()
            with receiver:
                receiver.settimeout(5.0)
                actual = get_congestion_algorithm(sender)
                if actual != CUSTOM_ALGORITHM_DEFAULT:
                    raise RuntimeError(f"requested {CUSTOM_ALGORITHM_DEFAULT}, kernel selected {actual}")
                initial = get_tcp_info(sender)
                for _ in range(16):
                    sender.sendall(payload)
                    remaining = len(payload)
                    while remaining:
                        received = receiver.recv(remaining)
                        if not received:
                            raise RuntimeError("local receiver closed before all test data arrived")
                        offset = len(payload) - remaining
                        if received != payload[offset:offset + len(received)]:
                            raise RuntimeError("local transfer payload mismatch")
                        remaining -= len(received)
                        transferred += len(received)
                deadline = time.monotonic() + 5.0
                while True:
                    final = get_tcp_info(sender)
                    acknowledged = final.bytes_acked - initial.bytes_acked
                    if acknowledged >= transferred:
                        break
                    if time.monotonic() >= deadline:
                        raise RuntimeError(f"only {acknowledged} of {transferred} payload bytes were acknowledged")
                    time.sleep(0.01)
                if final.snd_cwnd_segments <= 0:
                    raise RuntimeError("kernel reported a nonpositive congestion window")
                result: dict[str, int | str] = {
                    "actual_algorithm": actual,
                    "received_bytes": transferred,
                    "acknowledged_bytes_delta": acknowledged,
                    "snd_cwnd_segments": final.snd_cwnd_segments,
                    "rtt_us": final.rtt_us,
                }
                if final.pacing_rate_bytes_per_s is not None:
                    result["pacing_rate_bytes_per_s"] = final.pacing_rate_bytes_per_s
                return result


def run_smoke_test(object_path: Path, bpffs: Path) -> dict[str, int | str]:
    if object_path.name not in IMPLEMENTATIONS:
        raise ValueError(f"expected one of these BPF object filenames: {', '.join(IMPLEMENTATIONS)}")
    with attached_scaffold(object_path, bpffs):
        result = exercise_socket()
        if object_path.name == "cs422_handwrite.bpf.o":
            if result.get("pacing_rate_bytes_per_s") in (None, 0, (1 << 64) - 1):
                raise RuntimeError("custom controller did not report a finite positive Linux pacing rate")
    return {
        "status": "passed",
        "implementation": IMPLEMENTATIONS[object_path.name],
        "kernel": platform.release(),
        **result,
        "lifecycle": "loaded, registered, selected, transferred, detached",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--object", type=Path, required=True, help="compiled cs422_handwrite.bpf.o or cs422_scaffold.bpf.o")
    parser.add_argument("--bpffs", type=Path, default=Path("/sys/fs/bpf"))
    arguments = parser.parse_args()
    result = run_smoke_test(arguments.object.resolve(), arguments.bpffs.resolve())
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()

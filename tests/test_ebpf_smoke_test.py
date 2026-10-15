from pathlib import Path
import platform
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from src.ebpf_smoke_test import attached_scaffold, check_environment, exercise_socket, run_smoke_test, wait_for_registration


class BpfScaffoldLifecycleTests(unittest.TestCase):
    def test_rejects_non_linux_before_running_commands(self) -> None:
        with patch("src.ebpf_smoke_test.platform.system", return_value="Windows"):
            with self.assertRaisesRegex(RuntimeError, "Linux/WSL2"):
                check_environment(Path("scaffold.o"), Path("bpffs"))

    def test_rejects_unprivileged_attachment(self) -> None:
        with (
            patch("src.ebpf_smoke_test.platform.system", return_value="Linux"),
            patch("src.ebpf_smoke_test.os.geteuid", return_value=1000, create=True),
        ):
            with self.assertRaises(PermissionError):
                check_environment(Path("scaffold.o"), Path("bpffs"))

    def test_rejects_missing_bpf_filesystem(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            object_path = root / "scaffold.o"
            object_path.touch()
            with (
                patch("src.ebpf_smoke_test.platform.system", return_value="Linux"),
                patch("src.ebpf_smoke_test.os.geteuid", return_value=0, create=True),
                patch("src.ebpf_smoke_test.shutil.which", return_value="/usr/bin/tool"),
                patch("src.ebpf_smoke_test.subprocess.run", return_value=subprocess.CompletedProcess([], 0, "sysfs\n")),
            ):
                with self.assertRaisesRegex(RuntimeError, "mounted BPF filesystem"):
                    check_environment(object_path, root)

    def test_rejects_an_existing_algorithm_registration(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            object_path = root / "scaffold.o"
            object_path.touch()
            with (
                patch("src.ebpf_smoke_test.platform.system", return_value="Linux"),
                patch("src.ebpf_smoke_test.os.geteuid", return_value=0, create=True),
                patch("src.ebpf_smoke_test.shutil.which", return_value="/usr/bin/tool"),
                patch("src.ebpf_smoke_test.subprocess.run", return_value=subprocess.CompletedProcess([], 0, "bpf\n")),
                patch("src.ebpf_smoke_test.available_algorithms", return_value={"cs422_handwrite"}),
            ):
                with self.assertRaisesRegex(RuntimeError, "already registered"):
                    check_environment(object_path, root)

    def test_detachment_timeout_is_an_error(self) -> None:
        with patch("src.ebpf_smoke_test.available_algorithms", return_value={"cs422_handwrite"}):
            with self.assertRaisesRegex(RuntimeError, "did not become detached"):
                wait_for_registration(False, timeout_s=0)

    def test_registration_and_detachment_surround_the_socket_test(self) -> None:
        events: list[object] = []
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)

            def register(command: list[str], *, check: bool) -> None:
                self.assertTrue(check)
                self.assertEqual(command[:3], ["bpftool", "struct_ops", "register"])
                (Path(command[-1]) / "cs422_scaffold").touch()
                events.append("register")

            with (
                patch("src.ebpf_smoke_test.check_environment"),
                patch("src.ebpf_smoke_test.subprocess.run", side_effect=register),
                patch("src.ebpf_smoke_test.wait_for_registration", side_effect=lambda state: events.append(state)),
            ):
                with attached_scaffold(root / "scaffold.o", root):
                    events.append("socket")
            self.assertEqual(list(root.iterdir()), [])
        self.assertEqual(events, ["register", True, "socket", False])

    def test_socket_failure_still_removes_its_pins(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with (
                patch("src.ebpf_smoke_test.check_environment"),
                patch("src.ebpf_smoke_test.subprocess.run"),
                patch("src.ebpf_smoke_test.wait_for_registration") as wait,
            ):
                with self.assertRaisesRegex(RuntimeError, "socket failure"):
                    with attached_scaffold(root / "scaffold.o", root):
                        raise RuntimeError("socket failure")
                self.assertEqual(list(root.iterdir()), [])
                self.assertEqual([call.args for call in wait.call_args_list], [(True,), (False,)])

    def test_partial_registration_failure_removes_created_pins(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)

            def fail_registration(command: list[str], *, check: bool) -> None:
                (Path(command[-1]) / "partial_link").touch()
                raise subprocess.CalledProcessError(1, command)

            with (
                patch("src.ebpf_smoke_test.check_environment"),
                patch("src.ebpf_smoke_test.subprocess.run", side_effect=fail_registration),
                patch("src.ebpf_smoke_test.wait_for_registration"),
            ):
                with self.assertRaises(subprocess.CalledProcessError):
                    with attached_scaffold(root / "scaffold.o", root):
                        self.fail("must not exercise sockets after registration fails")
            self.assertEqual(list(root.iterdir()), [])

    def test_preflight_failure_does_not_create_or_remove_any_pins(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            existing_pin = root / "someone_elses_link"
            existing_pin.touch()
            with patch("src.ebpf_smoke_test.check_environment", side_effect=RuntimeError("already registered")):
                with self.assertRaisesRegex(RuntimeError, "already registered"):
                    with attached_scaffold(root / "scaffold.o", root):
                        self.fail("must not attach")
            self.assertEqual(list(root.iterdir()), [existing_pin])

    def test_success_is_reported_only_after_cleanup(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with (
                patch("src.ebpf_smoke_test.check_environment"),
                patch("src.ebpf_smoke_test.subprocess.run"),
                patch("src.ebpf_smoke_test.wait_for_registration", side_effect=[None, RuntimeError("detach failed")]),
                patch("src.ebpf_smoke_test.exercise_socket", return_value={
                    "actual_algorithm": "cs422_handwrite", "pacing_rate_bytes_per_s": 100000,
                }),
            ):
                with self.assertRaisesRegex(RuntimeError, "detach failed"):
                    run_smoke_test(root / "cs422_scaffold.bpf.o", root)

    def test_success_identifies_scaffold_not_custom_controller(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with (
                patch("src.ebpf_smoke_test.check_environment"),
                patch("src.ebpf_smoke_test.subprocess.run"),
                patch("src.ebpf_smoke_test.wait_for_registration"),
                patch("src.ebpf_smoke_test.exercise_socket", return_value={"actual_algorithm": "cs422_handwrite"}),
            ):
                result = run_smoke_test(root / "cs422_scaffold.bpf.o", root)
            self.assertEqual(result["status"], "passed")
            self.assertEqual(result["implementation"], "reno-backed-registration-scaffold")
            self.assertEqual(list(root.iterdir()), [])

    def test_custom_controller_is_labeled_separately(self) -> None:
        with (
            patch("src.ebpf_smoke_test.attached_scaffold"),
            patch("src.ebpf_smoke_test.exercise_socket", return_value={
                "actual_algorithm": "cs422_handwrite", "pacing_rate_bytes_per_s": 100000,
            }),
        ):
            result = run_smoke_test(Path("cs422_handwrite.bpf.o"), Path("bpffs"))
        self.assertEqual(result["implementation"], "delay-based-round-controller")

    def test_custom_controller_without_finite_pacing_rate_fails(self) -> None:
        for rate in (None, 0, (1 << 64) - 1):
            with (
                self.subTest(rate=rate),
                patch("src.ebpf_smoke_test.attached_scaffold"),
                patch("src.ebpf_smoke_test.exercise_socket", return_value={
                    "actual_algorithm": "cs422_handwrite", "pacing_rate_bytes_per_s": rate,
                }),
            ):
                with self.assertRaisesRegex(RuntimeError, "pacing rate"):
                    run_smoke_test(Path("cs422_handwrite.bpf.o"), Path("bpffs"))

    def test_unknown_object_name_is_rejected_before_loading(self) -> None:
        with patch("src.ebpf_smoke_test.attached_scaffold") as attach:
            with self.assertRaises(ValueError):
                run_smoke_test(Path("unknown.bpf.o"), Path("bpffs"))
        attach.assert_not_called()

    @unittest.skipUnless(platform.system() == "Linux", "requires Linux TCP_INFO")
    def test_socket_transfer_with_existing_reno_without_bpf_or_root(self) -> None:
        with patch("src.ebpf_smoke_test.CUSTOM_ALGORITHM_DEFAULT", "reno"):
            result = exercise_socket()
        self.assertEqual(result["actual_algorithm"], "reno")
        self.assertEqual(result["received_bytes"], 240 * 1024)
        self.assertGreaterEqual(result["acknowledged_bytes_delta"], result["received_bytes"])
        self.assertGreater(result["snd_cwnd_segments"], 0)


if __name__ == "__main__":
    unittest.main()

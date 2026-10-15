# TCP eBPF registration scaffold

This is **Reno under the name `cs422_handwrite`**, not the custom delay-based
controller. Do not use its results as the handwritten algorithm in the report.
It tests the build, verifier, registration, socket selection, and detach path.

## Prerequisites

Use Linux/WSL2 with kernel BTF and TCP BPF `struct_ops` support. The development
machine reports `6.18.54.1-microsoft-standard-WSL2`, Clang 21.1.8, bpftool 7.7.0,
and libbpf development headers 1.6.3. These are the initial target versions;
successful privileged attachment must still be confirmed on the target machine.

The BPF compiler uses the running kernel's BTF to generate `vmlinux.h`.
Full kernel headers and a kernel-module build tree are not required.

```bash
sudo apt update
sudo apt install --no-install-recommends \
  build-essential clang llvm bpftool pkg-config \
  libbpf-dev libelf-dev zlib1g-dev
```

## Build

Run in a WSL terminal as your normal user. Substitute your checkout directory
for the example below. Keep generated build artifacts on the Linux filesystem.

```bash
cd '/mnt/c/Users/Francis Wang/Documents/cs422/assignment2-3'
make -C cc/ebpf BUILD_DIR="$HOME/.cache/cs422-ebpf/$(uname -r)"
```

Rebuild in a fresh build directory after kernel or toolchain changes. The
object delegates the required callbacks to the kernel's `tcp_reno_*` BPF
kfuncs. BTF symbol presence alone does not prove verifier access: the live
test below verifies that the kernel accepts those calls.
The registration permits ordinary users to select this algorithm on their own
sockets while it is attached; attaching it still requires elevated privileges.

## Privileged local smoke test

Check whether the BPF filesystem is mounted:

```bash
findmnt --target /sys/fs/bpf --output TARGET,FSTYPE
```

If the filesystem type is not `bpf`, mount it explicitly:

```bash
sudo mount -t bpf bpf /sys/fs/bpf
```

The mount is runtime environment setup, not persistent system configuration.
The smoke test does not mount or unmount it automatically.

From the repository root:

```bash
sudo python3 -m src.ebpf_smoke_test \
  --object "$HOME/.cache/cs422-ebpf/$(uname -r)/cs422_scaffold.bpf.o"
```

The test uses bpftool/libbpf to register a link-backed `struct_ops` object,
sets `TCP_CONGESTION` before connecting a loopback TCP sender, verifies the
algorithm with `getsockopt`, transfers and checks 240 KiB of payload, and
checks acknowledged-byte progress and the congestion window with `TCP_INFO`.
This local receiver is only an integration fixture; assignment experiments
still use the existing client and standard public iperf3 servers.

All sockets close before cleanup. Removing the test's final link pin releases
the registration. The test checks that the algorithm disappears before
printing a successful JSON result. It never changes the system default
congestion control or qdisc, and refuses to run if the name is already
registered. Errors propagate with diagnostics and a nonzero exit status.

`finally` cleanup also runs after ordinary load or socket-test failures.
Forced process termination or a machine crash can leave a pin beneath
`/sys/fs/bpf/cs422-smoke-*`. Inspect `sudo bpftool link show` and
`sudo bpftool struct_ops show`, close sockets using the algorithm, then remove
only the exact leftover link pin and its empty directory. Do not delete
unrelated BPF pins. Concurrent tests using the same algorithm name are not
supported.

No privileged attachment has been performed automatically. Run the smoke test
and retain its output before treating this scaffold as verified on your kernel.

## Unit tests

```bash
python3 -m unittest tests.test_ebpf_smoke_test tests.test_tcp_info tests.test_congestion_control
```

These exercise cleanup and failure handling without requiring root or BPF
support; they do not replace the privileged integration test.

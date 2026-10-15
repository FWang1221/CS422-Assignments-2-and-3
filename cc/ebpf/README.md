# TCP eBPF controller: build and testing

This is a TCP congestion-control implementation using eBPF `struct_ops`,
not a loadable `.ko` kernel module. Both objects register `cs422_handwrite`:

| Object | Behavior |
| --- | --- |
| `cs422_handwrite.bpf.o` | Custom round-based delay controller |
| `cs422_scaffold.bpf.o` | Original Reno-backed lifecycle baseline only |

Never load both together. Do not label scaffold results as custom-controller
results. The original scaffold's privileged lifecycle test passed on the
development kernel; the new custom object's verifier/load test must be run
separately. Compilation and native tests do not prove kernel acceptance.

The command reference is [kernel_test_help.txt](../../kernel_test_help.txt).
The controller design is in [the report](../../reports/assignment2_3b.txt).

## Prerequisites

Use Linux/WSL2 with kernel BTF and TCP BPF `struct_ops` support. The development
machine reports `6.18.54.1-microsoft-standard-WSL2`, Clang 21.1.8, bpftool 7.7.0,
and libbpf development headers 1.6.3. This is the initial target environment;
other kernels require their own build and privileged verification.

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
make -C cc/ebpf test BUILD_DIR="$HOME/.cache/cs422-ebpf/$(uname -r)"
```

Rebuild in a fresh build directory after kernel or toolchain changes. The
custom object uses the kernel's `tcp_slow_start` and `tcp_cong_avoid_ai` kfuncs;
the scaffold delegates its callbacks to `tcp_reno_*`. BTF symbol presence
alone does not prove verifier access: the live test below checks acceptance.
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
  --object "$HOME/.cache/cs422-ebpf/$(uname -r)/cs422_handwrite.bpf.o"
```

Use `cs422_scaffold.bpf.o` instead to rerun the Reno baseline. If running in a
root shell, `$HOME` is usually `/root`: use the exact build path printed by
make, e.g. `/home/francis_wang/.cache/cs422-ebpf/$(uname -r)/...`.

The test uses bpftool/libbpf to register a link-backed `struct_ops` object,
sets `TCP_CONGESTION` before connecting a loopback TCP sender, verifies the
algorithm with `getsockopt`, transfers and checks 240 KiB of payload, and
checks acknowledged-byte progress and the congestion window with `TCP_INFO`.
For the custom object it also requires a finite positive native pacing rate.
The JSON implementation label is selected from the expected build filename;
do not rename or replace the two objects with each other's contents.
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

No privileged attachment of the custom object has been performed automatically.
Run the smoke test and retain its output before treating it as kernel-verified.

## Controller and diagnostics

Each socket has its own bounded state in `icsk_ca_priv`; a build-time assertion
checks that the state fits. `pkts_acked` filters the last seven positive RTT
samples, while `cong_avoid` tracks ACK sequence round boundaries and byte/time
baselines. Sequence comparisons tolerate 32-bit wrap. Decisions use integer
cross products, retaining fractional-packet threshold distinctions.

Eligible rounds grow cwnd by one segment below 3 estimated queued packets,
hold at/between 3 and 6, and reduce it to floor(0.8*cwnd) above 6. Slow start
uses Linux's helper and permits a delay-triggered early exit. The slow-start
cwnd-limited check includes Linux's half-window utilization rule. Missing or
stale RTT, application/non-cwnd-limited rounds, zero elapsed time, MSS changes,
counter resets, rounds over about 71 minutes, and byte deltas above the TCP
half-sequence-space limit skip delay decisions. A skipped startup round still
permits ordinary Linux slow-start growth; skipped avoidance rounds do not grow.

Loss threshold calculation halves cwnd with a floor of two. CWR/recovery/loss
states invalidate the partial round; Linux retains retransmission, timeout,
and recovery window control. Undo restores the saved pre-loss window subject
to the kernel clamp. The controller requests `SK_PACING_NEEDED` when pacing is
not already enabled, but leaves rate calculation and scheduling to Linux.
No global TCP setting or qdisc is changed.

The per-CPU `cs422_events` map counts callback/decision activity:

| Key | Meaning |
| --- | --- |
| 0 | Socket initializations |
| 1 | Valid RTT samples |
| 2 | Completed rounds, including skipped rounds |
| 3 | Skipped round decisions |
| 4 | Round-based additive increases |
| 5 | Delay-based backoffs, including slow-start exits |
| 6 | Loss/ECN threshold callbacks |

Counters aggregate all sockets using this loaded object. Sum values across
CPUs for each key. They reset on reload and disappear after the object unloads.
Inspect them during a persistent registration with:

```bash
sudo bpftool map dump name cs422_events
```

The short loopback smoke test is often application-limited and may show no
delay backoffs. It proves registration, transfer, telemetry and cleanup, not
algorithm performance, smooth wire pacing, fairness or loss recovery.

## Persistent registration for real experiments

First ensure `cs422_handwrite` is absent from
`sysctl net.ipv4.tcp_available_congestion_control`. Then:

```bash
sudo mkdir /sys/fs/bpf/cs422-handwrite
sudo bpftool struct_ops register \
  "$HOME/.cache/cs422-ebpf/$(uname -r)/cs422_handwrite.bpf.o" \
  /sys/fs/bpf/cs422-handwrite
sysctl net.ipv4.tcp_available_congestion_control
```

An existing pin directory is an error to investigate, not overwrite. If
registration fails, inspect it for a partial link and remove only that link
and the now-empty directory. Do not run the automatic smoke test while this
persistent registration exists.

Run the existing Python client/comparison coordinator as a normal user with
`Hand-Written` selected. The root command reference gives the 10-second,
four-algorithm comparison command. BBR must be available separately. Keep
destinations, sampling, duration and qdisc configuration fixed across algorithms.

After all experiment sockets close, unregister by removing this exact link pin:

```bash
sudo rm /sys/fs/bpf/cs422-handwrite/cs422_handwrite
sudo rmdir /sys/fs/bpf/cs422-handwrite
sysctl net.ipv4.tcp_available_congestion_control
```

Check absence of the algorithm. Never unpin another user's BPF objects or
delete the entire BPF filesystem.

## Unit tests

```bash
python3 -m unittest tests.test_ebpf_smoke_test tests.test_tcp_info tests.test_congestion_control
```

These exercise cleanup and failure handling without requiring root or BPF
support; they do not replace the privileged integration test.

`make ... test` compiles a native C test against the **same controller header**
used by the BPF object. It covers RTT filtering/wrap, strict and fractional
thresholds, startup decisions, window/loss bounds, stale/invalid feedback,
application limitation, one decision per round, sequence wrap, and socket-state
isolation. It does not exercise the verifier, kernel callback ordering or
retransmission machinery. For those, retain the live smoke output and collect
controlled congestion/loss traces before making behavior or performance claims.

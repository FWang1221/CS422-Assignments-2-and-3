# Docker Assignment 2 Pipeline

The image uses `ubuntu:24.04` and runs the single Python entry point
`src.assignment2_pipeline`. It performs baseline endpoint selection, fixed
endpoint CUBIC/Reno/BBR repetitions, raw-table generation, and grouped PDF plot
generation.

Docker uses the host Linux kernel. Before building or running the container,
verify the host/WSL kernel provides every requested algorithm:

```bash
cat /proc/sys/net/ipv4/tcp_available_congestion_control
sudo modprobe tcp_bbr
cat /proc/sys/net/ipv4/tcp_available_congestion_control
uname -r
```

`modprobe` affects the host kernel, not the container. If `bbr` remains absent,
the pipeline stops before public-server traffic and reports the available
algorithms. Use a host kernel with BBR available for the required three-way
comparison.

## Build

From the repository root:

```bash
docker build --tag cs422-assignment2 .
```

## Run

On Linux or WSL2, mount `outputsDocker` so Docker-generated raw data and plots
remain separate from local `outputs`. The `--user` flag prevents root-owned
output files.

```bash
mkdir -p outputsDocker
docker run --rm \
  --user "$(id -u):$(id -g)" \
  --volume "$PWD/outputsDocker:/app/outputs" \
  cs422-assignment2 \
  --destinations 10 \
  --max-attempts 30 \
  --duration 60 \
  --sample-interval 1 \
  --repetitions 3 \
  --algorithms CUBIC Reno BBR \
  --baseline-run-id baseline-20261017 \
  --comparison-run-id q3-20261017
```

The mounted `outputsDocker/tables` directory receives the baseline plan, all raw
samples, summaries, attempt logs, algorithm-comparison manifest, and a
`pipeline_environment_<run-id>.json` record containing the host kernel release
and available congestion-control algorithms. The grouped PDF is written under
`outputsDocker/plots`.

To perform an intentionally partial comparison on a host without BBR, replace
the algorithm list with `--algorithms CUBIC Reno`; this is not a substitute for
the required BBR experiment.

## Assignment 3 TCP eBPF Controller

`cs422_handwrite` is a TCP eBPF `struct_ops` congestion-control implementation,
not a `.ko` module. The image includes its compiler, libbpf headers, and native
test dependencies. Generate the kernel-specific BTF header with the host WSL
`bpftool`; Ubuntu's container packages dispatch to Ubuntu kernel-version tools
and cannot provide a matching binary for a Microsoft WSL kernel.

The following is the normal, non-privileged deterministic test. It builds the
objects, validates their ELF layout and generated RTT-median code, and runs the
native controller tests. Its generated artifacts stay beneath `outputsDocker`.
Run the first two commands on the WSL host, where `bpftool` must already be
installed as described in [`cc/ebpf/README.md`](../cc/ebpf/README.md).

```bash
mkdir -p outputsDocker/ebpf-build
export BPF_BUILD_DIR="$PWD/outputsDocker/ebpf-build/$(uname -r)"
mkdir -p "$BPF_BUILD_DIR"
bpftool btf dump file /sys/kernel/btf/vmlinux format c > "$BPF_BUILD_DIR/vmlinux.h"
test -s "$BPF_BUILD_DIR/vmlinux.h"

docker run --rm \
  --user "$(id -u):$(id -g)" \
  --volume "$PWD/outputsDocker/ebpf-build:/build" \
  --entrypoint make \
  cs422-assignment2 \
  -C cc/ebpf BUILD_DIR="/build/$(uname -r)" test
```

Run the same Python lifecycle tests outside or inside Docker without BPF
privileges:

```bash
python3 -m unittest tests.test_ebpf_smoke_test tests.test_tcp_info tests.test_congestion_control
```

The kernel smoke test registers a real TCP `struct_ops` object, so it changes
the host kernel temporarily and needs a mounted BPF filesystem plus Docker
privileges. Run it on the WSL host, where the host's `bpftool` matches the
kernel. First confirm `/sys/fs/bpf` is already mounted as `bpf`; see
[`cc/ebpf/README.md`](../cc/ebpf/README.md) for the host setup. Do not run it
while a persistent `cs422_handwrite` registration exists.

```bash
sudo python3 -m src.ebpf_smoke_test \
  --object "$BPF_BUILD_DIR/cs422_handwrite.bpf.o"
```

For Assignment 3's live comparison, persistently register the already-tested
object, then use the regular pipeline. Registration is deliberately a separate
privileged host action; the experiment container itself does not need
privileges. First mount the BPF filesystem if it is not already available.
Do not register the algorithm if it is already present in the available list.

```bash
findmnt --target /sys/fs/bpf --output TARGET,FSTYPE
if ! findmnt --noheadings --output FSTYPE --target /sys/fs/bpf | grep -qx bpf; then
  sudo mkdir -p /sys/fs/bpf
  sudo mount -t bpf bpf /sys/fs/bpf
fi

sysctl net.ipv4.tcp_available_congestion_control
test -f "$BPF_BUILD_DIR/cs422_handwrite.bpf.o"
sudo mkdir /sys/fs/bpf/cs422-handwrite
sudo bpftool struct_ops register "$BPF_BUILD_DIR/cs422_handwrite.bpf.o" \
  /sys/fs/bpf/cs422-handwrite
sysctl net.ipv4.tcp_available_congestion_control

docker run --rm \
  --user "$(id -u):$(id -g)" \
  --volume "$PWD/outputsDocker:/app/outputs" \
  cs422-assignment2 \
  --destinations 10 \
  --max-attempts 30 \
  --duration 10 \
  --sample-interval 0.2 \
  --repetitions 3 \
  --algorithms Hand-Written CUBIC Reno BBR \
  --baseline-run-id assignment3-baseline-20261018 \
  --comparison-run-id assignment3-custom-10s
```

This records the actual algorithm from each data socket and uses fixed selected
destinations, duration, sampling interval, repetitions, and rotated test order
for all four algorithms. The pipeline refuses to send public traffic until the
host kernel exposes all four requested algorithms, including BBR and
`cs422_handwrite`.

After all experiment sockets close, remove only the registration created above:

```bash
sudo rm /sys/fs/bpf/cs422-handwrite/cs422_handwrite
sudo rmdir /sys/fs/bpf/cs422-handwrite
```

Do not remove BPF pins you did not create. See
[`cc/ebpf/README.md`](../cc/ebpf/README.md) for the controller design, kernel
requirements, and non-Docker equivalents.
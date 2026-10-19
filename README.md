# CS 422 Assignments 2 and 3

# IMPORTANT NOTE FOR GRADERS:

The group has decided to split the assignment into 2 halves. One deals with the majority of assignment 2 (except the congestion control algorithm), and the other deals with the congestion control algorithm and its associated kernel module and tests.

Assignment 2 (except 3b) including the report should be looked at here:

[Assignment 2](https://github.com/sgannam7477/CS422_HW2/tree/main)

Assignment 2's 3b (congestion control pseudocode and planning) and Assignment 3 (actual kernel module for congestion control) should be looked at here.



This repository contains a raw Python iPerf3-compatible client, TCP_INFO
measurement and plotting pipeline, congestion-control comparisons, and the
Assignment 3 `cs422_handwrite` TCP eBPF `struct_ops` controller. It never uses
the `iperf3` executable to run public-server experiments.

## Start Here

The main experiment trigger is:

```bash
python3 -m src.assignment2_pipeline
```

It selects baseline destinations, records TCP_INFO samples, repeats the fixed
endpoint comparison in rotated algorithm order, and generates the comparison
PDF. It refuses to send public-server traffic until every requested algorithm
is available in the running Linux kernel.

Use Linux or WSL2 for live measurements. Windows-native Python cannot provide
the Linux TCP_INFO and TCP_CONGESTION interfaces used by this project.

## Local Assignment 2 Run

Install the Python dependency and check kernel algorithms:

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt

cat /proc/sys/net/ipv4/tcp_available_congestion_control
sudo modprobe tcp_bbr
cat /proc/sys/net/ipv4/tcp_available_congestion_control
```

Run the three built-in algorithms with new run identifiers:

```bash
python3 -m src.assignment2_pipeline \
  --output-dir outputs/tables \
  --destinations 10 \
  --max-attempts 30 \
  --duration 60 \
  --sample-interval 1 \
  --repetitions 3 \
  --algorithms CUBIC Reno BBR \
  --baseline-run-id baseline-YYYYMMDD \
  --comparison-run-id q3-YYYYMMDD
```

The run writes CSV/JSON tables to `outputs/tables` and the grouped PDF to
`outputs/plots`. `pipeline_environment_<run-id>.json` records the kernel
release, available algorithms, and requested algorithms for reproduction.

## Docker Trigger

Docker standardizes Python and compiler dependencies; it does not provide a
different TCP kernel. Build the image from Linux or WSL2:

```bash
docker build --tag cs422-assignment2 .
```

Use a distinct host output directory for container runs:

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
  --baseline-run-id baseline-YYYYMMDD \
  --comparison-run-id q3-YYYYMMDD
```

Container results are stored in `outputsDocker/tables` and
`outputsDocker/plots`. The full Docker command reference, including the
container-native eBPF test path, is in [docs/docker_assignment2.md](docs/docker_assignment2.md).

## Assignment 3 Custom Controller

`cs422_handwrite` is an eBPF TCP `struct_ops` controller, not a loadable
kernel `.ko` module. It must be compiled for, smoke-tested against, and
registered in the **host WSL/Linux kernel** before it can be selected by the
Docker or local Python pipeline.

The Assignment 3 flow is:

1. On the host, install the BPF build tools and verify BTF/`struct_ops` support.
2. Generate the host-kernel `vmlinux.h` under
   `outputsDocker/ebpf-build/$(uname -r)` with the host `bpftool`.
3. Use the Docker `make` command in [docs/docker_assignment2.md](docs/docker_assignment2.md)
   to compile `cs422_handwrite.bpf.o` and run its deterministic native tests.
4. Run the privileged host smoke test. It proves load, registration, socket
   selection, local transfer, telemetry, and cleanup.
5. Mount `bpffs` if needed, then persistently register the tested object at
   `/sys/fs/bpf/cs422-handwrite`.
6. Run the normal pipeline with all four algorithms:

```bash
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
  --baseline-run-id assignment3-baseline-YYYYMMDD \
  --comparison-run-id assignment3-custom-10s
```

7. After every experiment socket closes, remove only the pin created for this
   controller.

The exact setup, smoke-test, registration, inspection, cleanup, and verifier
troubleshooting commands are in [docs/docker_assignment2.md](docs/docker_assignment2.md),
[cc/ebpf/README.md](cc/ebpf/README.md), and [kernel_test_help.txt](kernel_test_help.txt).

## Tests

Run the Python suite without public-server traffic:

```bash
python3 -m unittest discover -v
```

The eBPF native test and the privileged smoke test are different checks. The
native test validates shared controller logic and generated object layout; the
smoke test verifies that the host verifier accepts and registers the object.
Neither replaces the required repeated public-server comparison.

## Caveats

- Docker shares the host kernel. It cannot make BBR or `cs422_handwrite`
  available. Check `/proc/sys/net/ipv4/tcp_available_congestion_control` before
  a live run.
- `Hand-Written` maps to the kernel name `cs422_handwrite`. The pipeline reads
  the selected name back from each data socket and fails its preflight before
  public traffic if the registration is absent.
- Do not load `cs422_scaffold.bpf.o` and `cs422_handwrite.bpf.o` together;
  both register the same algorithm name. The scaffold is a Reno-backed
  lifecycle baseline, not an Assignment 3 custom-controller result.
- Do not run the temporary smoke test while persistent registration exists.
  Do not remove another user's BPF pins or delete `/sys/fs/bpf` recursively.
- BPF build output is kernel-specific. Regenerate `vmlinux.h`, rebuild, and
  rerun the smoke test after a kernel or toolchain change.
- Public iPerf3 servers can reject, rate-limit, time out, or change paths. The
  attempt tables record failures; preserve them and do not treat a shortfall as
  a successful fixed-endpoint comparison.
- Reuse of a run ID can overwrite or mix artifacts. Use new baseline and
  comparison IDs for each experiment.
- The loopback smoke test proves lifecycle integration only. It does not prove
  public-network performance, fairness, queue behavior, or loss recovery.

## Repository Map

| Path | Purpose |
| --- | --- |
| `src/assignment2_pipeline.py` | Main live-measurement, comparison, and plot trigger. |
| `src/assignment2_step1.py` | Raw iPerf3-compatible client and TCP_INFO sampler. |
| `src/assignment2_question3.py` | Fixed-endpoint, rotated-order algorithm coordinator. |
| `src/plot_assignment2.py` | Single-run Assignment 2 PDF plots. |
| `src/plot_assignment2_question3.py` | Grouped comparison PDF plots. |
| `src/ebpf_smoke_test.py` | Privileged local controller lifecycle integration test. |
| `cc/ebpf/` | Controller source, native test, Makefile, and design documentation. |
| `config/listed_iperf3_servers.csv` | Candidate public iPerf3 server inventory. |
| `docs/tcp_info_measurement_schema.md` | TCP_INFO fields, units, and loss semantics. |
| `reports/assignment3.md` | Current Assignment 3 observations. |
| `outputsDocker` | Folder containing Assignment 3's gathered graphs and data. |


AI was used considerably for reverse engineering iperf3 on assignment 2, and plotting. AI was not used to plan the custom congestion control algorithm in assignment 3, but was used for implementation.
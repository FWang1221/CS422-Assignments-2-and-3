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

On Linux or WSL2, mount `outputs` so raw data and plots persist outside the
container. The `--user` flag prevents root-owned output files.

```bash
mkdir -p outputs
docker run --rm \
  --user "$(id -u):$(id -g)" \
  --volume "$PWD/outputs:/app/outputs" \
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

The mounted `outputs/tables` directory receives the baseline plan, all raw
samples, summaries, attempt logs, algorithm-comparison manifest, and a
`pipeline_environment_<run-id>.json` record containing the host kernel release
and available congestion-control algorithms. The grouped PDF is written under
`outputs/plots`.

To perform an intentionally partial comparison on a host without BBR, replace
the algorithm list with `--algorithms CUBIC Reno`; this is not a substitute for
the required BBR experiment.
# Assignment 2 Sections 1-2 Status

This status is a documentation map for the current implementation. It does not
claim completion for later report or comparison work.

| Section | Current implementation | Follow-up |
| --- | --- | --- |
| 1(a) iPerf client | `src/iperf3_protocol.py` and `LinuxIperf3Client` establish the control/data sockets, exchange parameters, continuously send forward TCP data, and terminate the iperf3 protocol. | None for the required one-stream forward client. |
| 1(b) destinations | `run_step1_experiment` records selected endpoints and attempts, replaces failures within `max_attempts`, and writes the shortfall. | None for one experiment. Repetitions belong to later automation. |
| 1(c) goodput | `_sample` uses acknowledged-byte deltas and actual elapsed intervals; summary CSV provides minimum, median, mean, and 95th-percentile goodput. `plot_assignment2.py` provides time series. | Integrate experiment and plotting in the final single entry-point pipeline. |
| 2(a) TCP tracing | `src/tcp_info.py` reads the data socket and `assignment2_step1.py` logs timestamp, CUBIC/default algorithm, congestion window, RTT, loss proxy, goodput, units, and Linux decoding metadata. | None for default-algorithm tracing. |
| 2(b) plots | `src/plot_assignment2.py` generates a PDF with the four required time series and three required scatter plots. | Select and identify one representative destination in the report. |
| 2(c) observations | No report observations have been written yet. | Explain each metric, its expected effect during congestion avoidance, and anomalies from the selected trace. |

## Out Of Scope For These Sections

## Question 3(a) Foundation

`src/assignment2_question3.py` accepts one or many `--algorithms` values from
`CUBIC`, `Reno`, `BBR`, and `Hand-Written`. It reuses an explicit successful
endpoint plan, rotates algorithm order across repetitions, sets the requested
algorithm on the unconnected data socket, verifies the kernel-selected value,
and writes a comparison manifest. Failed or unavailable algorithms are recorded
without replacing destinations.

`Hand-Written` uses the Linux registration name `cs422_handwrite`. The custom
TCP eBPF controller and separate Reno-backed scaffold are in `cc/ebpf`; only one
may be loaded at a time. The custom algorithm remains unavailable until its
object is registered. See `cc/ebpf/README.md` and `kernel_test_help.txt` for
build, validation, load and detach commands.
`src/plot_assignment2_question3.py` generates the required seven shared-axis
comparison views for one representative destination. Operating-regime
interpretation and report discussion remain TODOs.

The final reproducibility work still needs a unified entry-point script,
Dockerfile based on `ubuntu:24.04`, host-kernel recording, and report assembly.
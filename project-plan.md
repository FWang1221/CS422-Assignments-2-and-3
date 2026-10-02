# CS 422 Assignments 2 and 3 Project Plan

## Scope

Assignment 2 builds a Python client that communicates with standard public iperf3 servers, measures live TCP behavior, compares CUBIC, Reno, and BBR, and produces reproducible data, plots, tables, and observations. It also requires a hand-written congestion-control design.

Assignment 3 implements and evaluates that design. The current team plan assumes Option 1: a Linux kernel module or eBPF congestion-control implementation selected by the Python client. Option 2 (ns-3) remains an alternative only if the team explicitly changes direction.

The experiments must run on Linux or WSL2. Docker standardizes user-space dependencies, but TCP behavior and `TCP_INFO` decoding depend on the host Linux kernel.

## Architecture and Ownership

### Module A: iPerf3 Client and Data Ingestion

**Input:** server list, TCP algorithm, transfer duration, sample interval, run configuration.

**Responsibilities:**

- Establish an iperf3-compatible control connection and complete JSON parameter exchange.
- Open and drive the data connection for the configured duration.
- Select the congestion-control algorithm on the data socket before connection.
- Sample the data socket using `getsockopt(TCP_INFO)`.
- Compute interval goodput from acknowledged-byte counter differences and actual elapsed time.
- Handle timeouts, rejected negotiation, premature termination, rate limits, retries, and replacement servers.

**Output:** strictly formatted measurement rows and per-run metadata.

### Module B: Automation and Visualization

**Input:** measurement rows and per-run metadata produced by Module A.

**Responsibilities:**

- Validate the shared schema.
- Generate summary tables and required PDF time-series and scatter plots.
- Create mock data so visualization work can proceed before live transfers work.
- Provide a Dockerized, one-command experiment and plotting pipeline.

**Output:** PDF plots, aggregate tables, and reproducible pipeline artifacts.

### Module C: Custom Congestion Control

**Input:** the Assignment 2 algorithm design and a supported Linux kernel environment.

**Responsibilities:**

- Specify the algorithm's state, parameters, RTT/loss/throughput response, bounds, stability, and fairness assumptions.
- Implement the algorithm as a kernel module or eBPF-compatible congestion-control implementation.
- Supply build, load, unload, and verification instructions.

**Output:** a congestion-control algorithm name that Module A can select and measure.

## Shared Interfaces

The central integration boundary is the measurement schema. Module A writes it; Module B reads it. Module C only needs to expose an algorithm that Module A can select through the socket API.

One record represents one sample from the **data socket**:

```text
run_id,timestamp_s,destination,port,requested_algorithm,actual_algorithm,
elapsed_s,bytes_acked,goodput_bps,snd_cwnd_bytes,srtt_us,rttvar_us,
retransmits,lost,delivered,pacing_rate_bps,notes
```

Each run also writes metadata containing:

- run ID and experiment arguments
- destination and server-list source
- requested and actual congestion-control algorithm
- host kernel version and TCP_INFO layout/decoder version
- start/end timestamps and outcome
- failure phase and reason, when applicable

Canonical units are seconds, microseconds, bytes, and bits per second.

## Proposed Repository Layout

```text
assignment2-3/
├── README.md
├── Dockerfile
├── requirements.txt
├── pyproject.toml
├── config/
│   ├── servers.example.csv
│   ├── experiment.example.yaml
│   └── tcp_info_layout.md
├── src/
│   ├── cli.py
│   ├── experiment.py
│   ├── iperf3_protocol.py
│   ├── tcp_socket.py
│   ├── tcp_info.py
│   ├── measurements.py
│   ├── server_selection.py
│   └── plotting.py
├── cc/
│   ├── adaptive_cc_design.md
│   └── kernel/
│       ├── Makefile
│       ├── adaptive_cc.c
│       └── load.sh
├── scripts/
│   ├── run_experiments.py
│   ├── generate_mock_data.py
│   ├── generate_plots.py
│   ├── check_environment.sh
│   └── run_pipeline.sh
├── data/
│   ├── mock/
│   ├── raw/
│   ├── processed/
│   └── server_lists/
├── outputs/
│   ├── plots/
│   ├── tables/
│   └── reports/
├── tests/
│   ├── fixtures/
│   ├── test_measurements.py
│   ├── test_tcp_info.py
│   └── test_protocol_framing.py
└── docs/
    ├── protocol_notes.md
    ├── experiment_methodology.md
    ├── reproduction.md
    └── report_outline.md
```

Do not commit large raw captures, generated plots, or large experiment outputs. Keep small fixtures and deterministic mock data under version control.

## Flow

1. Parse configuration and select destinations.
2. Select the TCP congestion-control algorithm on the data socket.
3. Complete the iperf3 control protocol and open the data connection.
4. Send application data while sampling `TCP_INFO` at the configured interval.
5. Compute goodput from counter deltas and actual sample timing.
6. Write raw samples and run metadata.
7. Validate and aggregate measurements.
8. Generate required plots and summary tables.
9. Use results to explain algorithm behavior and tune/design the custom algorithm.

## Test-Driven Development Plan

Use three test markers:

- **unit:** deterministic logic with fakes and fixtures; required for routine development.
- **integration:** host socket or kernel behavior; runs on Linux/WSL2 when prerequisites exist.
- **live:** public iperf3 servers; nondeterministic and not required for ordinary development or Docker smoke tests.

### 1. Measurement Schema

- Test that valid rows serialize and deserialize through CSV and JSON without losing values.
- Reject missing required fields and invalid units.
- Require run ID, destination, port, requested/actual algorithm, timestamp, and goodput-related fields.

### 2. Configuration and Server Lists

- Test defaults and command-line overrides for destination count, duration, interval, repetitions, and algorithms.
- Reject non-positive duration/interval, invalid ports, unknown algorithms, and missing server-list files.
- Test server-list parsing, comments/blank lines, duplicate removal, and malformed-line reporting.

### 3. Run IDs and Filesystem Outputs

- Test predictable run-ID format and uniqueness.
- Test placement of raw data, metadata, failures, tables, and plots.
- Ensure existing outputs are not silently overwritten.

### 4. Congestion-Control Socket Selection

- With a fake socket, verify that `TCP_CONGESTION` is set before `connect`.
- Test structured errors for unsupported or rejected algorithms.
- Add a Linux integration test verifying that the actual selected algorithm matches the requested algorithm where supported.

### 5. TCP_INFO Decoding

- Use fixed binary fixtures for the target kernel layout.
- Verify decoding of `snd_cwnd`, `srtt`, `rttvar`, retransmission/loss fields, delivery metrics, and pacing rate when available.
- Test truncated and unknown-size buffers for safe behavior.
- Test all unit conversions explicitly.

### 6. Goodput Calculation

- Verify $goodput = (\Delta bytes\_acked \times 8) / \Delta t$ from known counters and timestamps.
- Require actual elapsed time, not the configured interval.
- Define the first sample as null/no interval goodput.
- Safely handle counter resets, negative deltas, and zero elapsed time.

### 7. Sampling and Transmission

- With fake clocks and sockets, verify sampling at the requested interval.
- Verify each sample combines TCP telemetry and interval goodput.
- Verify continuous sending until the monotonic-clock deadline.
- Verify partial writes, connection resets, broken pipes, and timeouts have structured outcomes.

### 8. iPerf3 Protocol

- Test control-message framing with fragmented TCP delivery.
- Test expected parameter JSON serialization and message ordering using fixtures.
- Test server errors, invalid JSON, unexpected messages, and early EOF.
- Test the lifecycle: control connection, parameter exchange, data connection, timed sending, termination, cleanup.

### 9. Reliability and Orchestration

- Test bounded retries and replacement-server selection.
- Ensure a failed run does not halt independent scheduled runs.
- Verify every requested algorithm, destination, and repetition is scheduled and recorded with a fixed test order.
- Verify shortfall summaries identify missing destinations and failure reasons.

### 10. Analysis and Pipeline

- With deterministic mock data, test generation of required time-series plots, scatter plots, and summary tables.
- Verify minimum, median, mean, and 95th-percentile calculations against known fixtures.
- Ensure empty or failed-only datasets produce a clear report rather than a crash.
- Run a Docker smoke test using mock data only, with no dependency on public Internet access.

### 11. Custom Algorithm

- Test pseudocode decisions on synthetic RTT, loss, and goodput sequences.
- Verify congestion-window minimum/maximum bounds and documented loss response.
- For Assignment 3, add a host-only integration test that confirms the custom algorithm can be discovered, selected, and measured during a short transfer.

## Temporary Artifacts That Unblock Parallel Work

- `config/experiment.example.yaml`: shared defaults and experiment parameters.
- `data/mock/mock_measurements.csv`: deterministic traces for CUBIC, Reno, BBR, and the custom algorithm.
- `data/mock/mock_run_metadata.json`: example per-run metadata.
- `tests/fixtures/tcp_info_samples.json`: binary sample descriptions and expected decoded values.
- `tests/fixtures/iperf3_messages.json`: captured or protocol-derived control-message fixtures.
- `docs/protocol_notes.md`: handshake ordering, framing observations, failure modes, and open questions.
- `config/tcp_info_layout.md`: struct offsets, sizes, units, kernel assumptions, and references.
- `cc/adaptive_cc_design.md`: algorithm pseudocode and parameter definitions independent of kernel implementation.
- `scripts/generate_mock_data.py`: seed-based generator for stable visualizations.
- `data/server_lists/servers.example.csv`: agreed server-list schema with placeholder destinations.

## Work Order

1. Freeze the schema, CLI options, artifact names, and test markers.
2. Build mock data, schema validation, tables, plots, and Docker smoke pipeline.
3. Implement and test iperf3 framing and TCP_INFO decoding in isolation.
4. Implement live transfer lifecycle, sampling, goodput, and failure handling.
5. Establish CUBIC baseline measurements, then add Reno and BBR comparisons.
6. Finalize the custom-algorithm design based on evidence from the baseline results.
7. Implement, load, select, and measure the custom algorithm.
8. Run repeatable comparisons, generate the final report artifacts, and document host/kernel requirements.

Avoid treating congestion control as an asymptotic-algorithm exercise. The critical design concerns are bounded control updates, RTT and loss interpretation, stability, fairness, queueing, and Linux congestion-control API constraints.
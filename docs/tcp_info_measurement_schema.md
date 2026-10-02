# TCP Measurement Schema

The live runner samples Linux `TCP_INFO` from the iperf3 data socket. It does
not use the iperf3 binary. `timestamp_utc` is ISO 8601 UTC and `elapsed_s` is
relative to the start of the data transfer.

| CSV field | Unit | Source or calculation |
| --- | --- | --- |
| `bytes_acked` | bytes | `tcpi_bytes_acked` |
| `acknowledged_bytes_delta` | bytes | Change in `bytes_acked` from the prior sample |
| `goodput_bps` | bits/s | `acknowledged_bytes_delta * 8 / interval_s` |
| `snd_cwnd_segments` | segments | `tcpi_snd_cwnd` |
| `snd_cwnd_bytes` | bytes | `snd_cwnd_segments * tcpi_snd_mss` |
| `srtt_us`, `rttvar_us` | microseconds | `tcpi_rtt`, `tcpi_rttvar` |
| `lost` | packets | Current `tcpi_lost` kernel loss estimate |
| `lost_change` | packets | Signed change in the `tcpi_lost` estimate since the prior sample |
| `total_retransmits`, `total_retransmits_delta` | packets | `tcpi_total_retrans` and its per-sample change |
| `pacing_rate_bps` | bits/s | `tcpi_pacing_rate * 8` |
| `delivery_rate_bps` | bits/s | `tcpi_delivery_rate * 8` |

`tcpi_lost` is not a monotonic cumulative counter. A negative `lost_change`
means its current estimate fell, for example as recovery or reordering is
observed; it is not treated as invalid data. `total_retransmits_delta` is the
primary interval loss/retransmission proxy because `tcpi_total_retrans` is
cumulative. The runner records both `requested_algorithm` and
`actual_algorithm`; the latter is queried from `TCP_CONGESTION` on the connected
data socket.

The required Linux `struct tcp_info` core extends through `tcpi_bytes_acked`
(128 bytes). Pacing rate begins at offset 104, while delivery rate begins at
offset 160. When an older kernel returns too short a structure for an appended
field, that field is blank rather than inferred.
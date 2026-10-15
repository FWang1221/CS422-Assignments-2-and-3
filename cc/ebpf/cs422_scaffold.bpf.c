// SPDX-License-Identifier: GPL-2.0
#include "vmlinux.h"
#include <bpf/bpf_helpers.h>
#include <bpf/bpf_tracing.h>

/* include/net/tcp.h macro; preprocessor constants are absent from BTF. */
#define TCP_CONG_NON_RESTRICTED (1U << 0)

char LICENSE[] SEC("license") = "GPL";

extern void tcp_reno_cong_avoid(struct sock *sk, __u32 ack, __u32 acked) __ksym;
extern __u32 tcp_reno_ssthresh(struct sock *sk) __ksym;
extern __u32 tcp_reno_undo_cwnd(struct sock *sk) __ksym;

SEC("struct_ops")
void BPF_PROG(scaffold_cong_avoid, struct sock *sk, __u32 ack, __u32 acked)
{
	tcp_reno_cong_avoid(sk, ack, acked);
}

SEC("struct_ops")
__u32 BPF_PROG(scaffold_ssthresh, struct sock *sk)
{
	return tcp_reno_ssthresh(sk);
}

SEC("struct_ops")
__u32 BPF_PROG(scaffold_undo_cwnd, struct sock *sk)
{
	return tcp_reno_undo_cwnd(sk);
}

/* Registration/lifecycle test only: this is Reno, not the custom controller. */
SEC(".struct_ops.link")
struct tcp_congestion_ops cs422_scaffold = {
	.cong_avoid = (void *)scaffold_cong_avoid,
	.ssthresh = (void *)scaffold_ssthresh,
	.undo_cwnd = (void *)scaffold_undo_cwnd,
	.flags = TCP_CONG_NON_RESTRICTED,
	.name = "cs422_handwrite",
};

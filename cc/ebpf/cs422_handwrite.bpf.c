// SPDX-License-Identifier: GPL-2.0
#include "vmlinux.h"
#include <bpf/bpf_helpers.h>
#include <bpf/bpf_core_read.h>
#include <bpf/bpf_tracing.h>
#include "cs422_controller.h"

/* include/net/tcp.h preprocessor constants are not exported in BTF. */
#define TCP_CONG_NON_RESTRICTED (1U << 0)

char LICENSE[] SEC("license") = "GPL";

extern __u32 tcp_slow_start(struct tcp_sock *tp, __u32 acked) __ksym;
extern void tcp_cong_avoid_ai(struct tcp_sock *tp, __u32 w, __u32 acked) __ksym;

enum cc_event {
	CC_EVENT_INIT,
	CC_EVENT_RTT,
	CC_EVENT_ROUND,
	CC_EVENT_SKIP,
	CC_EVENT_GROW,
	CC_EVENT_BACKOFF,
	CC_EVENT_LOSS,
	CC_EVENT_COUNT,
};

struct {
	__uint(type, BPF_MAP_TYPE_PERCPU_ARRAY);
	__uint(max_entries, CC_EVENT_COUNT);
	__type(key, __u32);
	__type(value, __u64);
} cs422_events SEC(".maps");

static __always_inline void count_event(__u32 event)
{
	__u64 *count = bpf_map_lookup_elem(&cs422_events, &event);

	if (count)
		(*count)++;
}

static __always_inline struct cc_state *state(struct sock *sk)
{
	struct inet_connection_sock *icsk = (struct inet_connection_sock *)sk;

	return (struct cc_state *)icsk->icsk_ca_priv;
}

_Static_assert(sizeof(struct cc_state) <=
	       sizeof(((struct inet_connection_sock *)0)->icsk_ca_priv),
	       "controller exceeds TCP per-socket congestion-control storage");

SEC("struct_ops")
void BPF_PROG(handwrite_init, struct sock *sk)
{
	struct cc_state *ca = state(sk);

	__builtin_memset(ca, 0, sizeof(*ca));
	if (sk->sk_pacing_status == SK_PACING_NONE)
		sk->sk_pacing_status = SK_PACING_NEEDED;
	count_event(CC_EVENT_INIT);
}

SEC("struct_ops")
void BPF_PROG(handwrite_pkts_acked, struct sock *sk, const struct ack_sample *sample)
{
	if (sample->rtt_us > 0) {
		cc_rtt(state(sk), sample->rtt_us);
		count_event(CC_EVENT_RTT);
	}
}

SEC("struct_ops")
void BPF_PROG(handwrite_state, struct sock *sk, __u8 new_state)
{
	/* Freeze through CWR, fast recovery and RTO loss; start a fresh flight. */
	if (new_state >= TCP_CA_CWR) {
		state(sk)->active = 0;
		state(sk)->fresh_rtt = 0;
	}
}

SEC("struct_ops")
__u32 BPF_PROG(handwrite_ssthresh, struct sock *sk)
{
	struct tcp_sock *tp = (struct tcp_sock *)sk;
	struct cc_state *ca = state(sk);

	ca->loss_cwnd = tp->snd_cwnd;
	ca->active = 0;
	count_event(CC_EVENT_LOSS);
	return cc_loss_threshold(tp->snd_cwnd);
}

SEC("struct_ops")
__u32 BPF_PROG(handwrite_undo, struct sock *sk)
{
	struct tcp_sock *tp = (struct tcp_sock *)sk;
	__u32 prior = state(sk)->loss_cwnd;

	return cc_bound(tp->snd_cwnd > prior ? tp->snd_cwnd : prior,
			tp->snd_cwnd_clamp);
}

SEC("struct_ops")
void BPF_PROG(handwrite_cong_avoid, struct sock *sk, __u32 ack, __u32 acked)
{
	struct tcp_sock *tp = (struct tcp_sock *)sk;
	struct inet_connection_sock *icsk = (struct inet_connection_sock *)sk;
	struct cc_state *ca = state(sk);
	struct cc_feedback f = {};
	enum cc_action action;
	__u32 limited;

	if (BPF_CORE_READ_BITFIELD_PROBED(icsk, icsk_ca_state) >= TCP_CA_CWR) {
		ca->active = 0;
		return;
	}
	limited = BPF_CORE_READ_BITFIELD_PROBED(tp, is_cwnd_limited);
	if (tp->snd_cwnd < tp->snd_ssthresh &&
	    (__u64)tp->snd_cwnd < 2ULL * tp->max_packets_out)
		limited = 1;

	f.now_us = bpf_ktime_get_ns() / 1000;
	f.bytes_acked = tp->bytes_acked;
	f.snd_una = tp->snd_una;
	f.snd_nxt = tp->snd_nxt;
	f.cwnd = tp->snd_cwnd;
	f.ssthresh = tp->snd_ssthresh;
	f.clamp = tp->snd_cwnd_clamp;
	f.mss = tp->mss_cache;
	f.cwnd_limited = limited;
	f.app_limited = tp->app_limited ||
			BPF_CORE_READ_BITFIELD_PROBED(tp, rate_app_limited);

	action = cc_round(ca, &f);
	if (limited) {
		if (tp->snd_cwnd < tp->snd_ssthresh && action != CC_BACKOFF)
			tcp_slow_start(tp, acked);
		else if (!ca->base_us && tp->snd_cwnd)
			tcp_cong_avoid_ai(tp, tp->snd_cwnd, acked);
	}
	if (action == CC_BACKOFF || action == CC_GROW) {
		tp->snd_cwnd = cc_window(tp->snd_cwnd, tp->snd_cwnd_clamp, action);
		tp->snd_cwnd_cnt = 0;
		if (action == CC_BACKOFF)
			tp->snd_ssthresh = tp->snd_cwnd;
		count_event(action == CC_BACKOFF ? CC_EVENT_BACKOFF : CC_EVENT_GROW);
	}
	if (action != CC_WAIT) {
		count_event(CC_EVENT_ROUND);
		if (action == CC_SKIP)
			count_event(CC_EVENT_SKIP);
	}
	if (!ca->active) {
		f.cwnd = tp->snd_cwnd;
		cc_begin(ca, &f);
	}
}

SEC(".struct_ops.link")
struct tcp_congestion_ops cs422_handwrite = {
	.init = (void *)handwrite_init,
	.pkts_acked = (void *)handwrite_pkts_acked,
	.set_state = (void *)handwrite_state,
	.ssthresh = (void *)handwrite_ssthresh,
	.undo_cwnd = (void *)handwrite_undo,
	.cong_avoid = (void *)handwrite_cong_avoid,
	.flags = TCP_CONG_NON_RESTRICTED,
	.name = "cs422_handwrite",
};

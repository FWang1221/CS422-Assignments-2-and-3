/* SPDX-License-Identifier: GPL-2.0 */
#ifndef CS422_CONTROLLER_H
#define CS422_CONTROLLER_H

#define CC_INLINE static __inline __attribute__((always_inline))
#define CC_RTT_SAMPLES 7
#define CC_U32_MAX 0xffffffffU

enum cc_action {
	CC_WAIT,
	CC_SKIP,
	CC_HOLD,
	CC_GROW,
	CC_BACKOFF,
};

struct cc_state {
	__u64 round_us;
	__u64 round_bytes;
	__u32 rtt[CC_RTT_SAMPLES];
	__u32 base_us;
	__u32 median_us;
	__u32 count;
	__u32 index;
	__u32 round_seq;
	__u32 round_cwnd;
	__u32 round_mss;
	__u32 loss_cwnd;
	__u8 active;
	__u8 fresh_rtt;
	__u8 limited;
};

struct cc_feedback {
	__u64 now_us;
	__u64 bytes_acked;
	__u32 snd_una;
	__u32 snd_nxt;
	__u32 cwnd;
	__u32 ssthresh;
	__u32 clamp;
	__u32 mss;
	__u8 cwnd_limited;
	__u8 app_limited;
};

CC_INLINE __u32 cc_bound(__u32 cwnd, __u32 clamp)
{
	if (cwnd < 2)
		cwnd = 2;
	return cwnd < clamp ? cwnd : clamp;
}

CC_INLINE __u32 cc_swap_mask(__u32 a, __u32 b)
{
#ifdef __BPF__
	__u64 mask;

	/* Keep LLVM from turning the arithmetic mask back into a branch. */
	asm volatile("%0 = %1; %0 -= %2; %0 s>>= 63;"
		     : "=&r"(mask) : "r"((__u64)b), "r"((__u64)a));
	return mask;
#else
	return 0U - (__u32)(((__u64)b - a) >> 63);
#endif
}

CC_INLINE void cc_rtt(struct cc_state *ca, __s32 rtt_us)
{
	__u32 sorted[CC_RTT_SAMPLES];
	__u32 index = ca->index;

	if (rtt_us <= 0)
		return;
	if (index >= CC_RTT_SAMPLES)
		index = 0;
#ifdef __BPF__
#pragma unroll
#endif
	for (__u32 i = 0; i < CC_RTT_SAMPLES; i++) {
		if (i == index)
			ca->rtt[i] = rtt_us;
	}
	ca->index = index + 1 == CC_RTT_SAMPLES ? 0 : index + 1;
	if (ca->count < CC_RTT_SAMPLES)
		ca->count++;
#ifdef __BPF__
#pragma unroll
#endif
	for (__u32 i = 0; i < CC_RTT_SAMPLES; i++)
		sorted[i] = i < ca->count ? ca->rtt[i] : CC_U32_MAX;
#ifdef __BPF__
#pragma unroll
#endif
	for (int pass = 0; pass < CC_RTT_SAMPLES - 1; pass++) {
#ifdef __BPF__
#pragma unroll
#endif
		for (int j = 0; j < CC_RTT_SAMPLES - 1; j++) {
			/* Both operands are u32, so u64 subtraction's top bit
			 * indicates underflow without a verifier-path branch.
			 */
			__u32 a = sorted[j], b = sorted[j + 1];
			__u32 mask = cc_swap_mask(a, b);
			__u32 swap = (a ^ b) & mask;

			sorted[j] = a ^ swap;
			sorted[j + 1] = b ^ swap;
		}
	}
	index = (ca->count - 1) / 2;
	if (index >= CC_RTT_SAMPLES)
		return;
#ifdef __BPF__
#pragma unroll
#endif
	for (__u32 i = 0; i < CC_RTT_SAMPLES; i++) {
		if (i == index)
			ca->median_us = sorted[i];
	}
	if (!ca->base_us || ca->median_us < ca->base_us)
		ca->base_us = ca->median_us;
	ca->fresh_rtt = 1;
}

CC_INLINE void cc_begin(struct cc_state *ca, const struct cc_feedback *f)
{
	ca->round_us = f->now_us;
	ca->round_bytes = f->bytes_acked;
	ca->round_seq = f->snd_nxt;
	ca->round_cwnd = f->cwnd;
	ca->round_mss = f->mss;
	ca->active = f->snd_nxt != f->snd_una;
	ca->fresh_rtt = 0;
	ca->limited = f->app_limited || !f->cwnd_limited;
}

/* Cross products retain fractional packets at the strict 3/6 thresholds. */
CC_INLINE enum cc_action cc_round(struct cc_state *ca, const struct cc_feedback *f)
{
	__u64 elapsed, delivered, expected, actual, diff;
	enum cc_action action = CC_SKIP;

	if (!ca->active) {
		cc_begin(ca, f);
		return CC_WAIT;
	}
	ca->limited |= f->app_limited || !f->cwnd_limited;
	if ((__s32)(f->snd_una - ca->round_seq) < 0)
		return CC_WAIT;
	elapsed = f->now_us - ca->round_us;
	if (ca->limited || !ca->fresh_rtt || !ca->base_us ||
	    !ca->median_us || !ca->round_mss || f->mss != ca->round_mss ||
	    !elapsed || elapsed > CC_U32_MAX ||
	    f->bytes_acked < ca->round_bytes)
		goto next;
	delivered = f->bytes_acked - ca->round_bytes;
	/* TCP rounds span less than half the sequence space. */
	if (delivered > 0x7fffffffU)
		goto next;
	expected = (__u64)ca->round_cwnd * elapsed;
	actual = delivered * ca->base_us / ca->round_mss;
	diff = expected > actual ? expected - actual : 0;
	if (diff > 6 * elapsed)
		action = CC_BACKOFF;
	else if (f->cwnd < f->ssthresh)
		action = CC_HOLD;
	else if (diff < 3 * elapsed ||
		 (diff == 3 * elapsed &&
		  delivered * ca->base_us % ca->round_mss))
		action = CC_GROW;
	else
		action = CC_HOLD;
next:
	/* The caller starts the next round after applying this decision. */
	ca->active = 0;
	return action;
}

CC_INLINE __u32 cc_window(__u32 cwnd, __u32 clamp, enum cc_action action)
{
	if (action == CC_BACKOFF)
		return cc_bound((__u64)cwnd * 4 / 5, clamp);
	if (action == CC_GROW)
		return cc_bound(cwnd == CC_U32_MAX ? cwnd : cwnd + 1, clamp);
	return cwnd;
}

CC_INLINE __u32 cc_loss_threshold(__u32 cwnd)
{
	return cwnd / 2 > 2 ? cwnd / 2 : 2;
}

#endif

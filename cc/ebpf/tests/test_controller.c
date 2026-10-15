/* SPDX-License-Identifier: GPL-2.0 */
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

typedef uint8_t __u8;
typedef uint32_t __u32;
typedef uint64_t __u64;
typedef int32_t __s32;
#include "cs422_controller.h"

static struct cc_feedback feedback(void)
{
	return (struct cc_feedback) {
		.now_us = 1000, .bytes_acked = 10000,
		.snd_una = 100, .snd_nxt = 10100,
		.cwnd = 10, .ssthresh = 10, .clamp = 1000,
		.mss = 1000, .cwnd_limited = 1,
	};
}

static enum cc_action round_diff(unsigned int queued, unsigned int slow_start)
{
	struct cc_state ca = {};
	struct cc_feedback f = feedback();

	f.ssthresh = slow_start ? 100 : 10;
	cc_rtt(&ca, 100);
	assert(cc_round(&ca, &f) == CC_WAIT);
	cc_rtt(&ca, 100);
	f.now_us += 100;
	f.bytes_acked += (10 - queued) * 1000;
	f.snd_una = 10100;
	f.snd_nxt = 20100;
	return cc_round(&ca, &f);
}

static void test_median(void)
{
	struct cc_state ca = {};

	cc_rtt(&ca, 0);
	cc_rtt(&ca, -1);
	assert(ca.count == 0 && ca.base_us == 0);
	cc_rtt(&ca, 100);
	cc_rtt(&ca, 1000);
	assert(ca.median_us == 100); /* lower middle */
	cc_rtt(&ca, 90);
	cc_rtt(&ca, 110);
	cc_rtt(&ca, 120);
	cc_rtt(&ca, 80);
	cc_rtt(&ca, 130);
	assert(ca.median_us == 110 && ca.base_us == 100);
	cc_rtt(&ca, 200);
	assert(ca.count == 7 && ca.median_us == 120 && ca.base_us == 100);
	for (int i = 0; i < 7; i++)
		cc_rtt(&ca, 50);
	assert(ca.base_us == 50);
}

static int compare_u32(const void *left, const void *right)
{
	__u32 a = *(const __u32 *)left, b = *(const __u32 *)right;

	return (a > b) - (a < b);
}

static void check_median_sequence(const __u32 *values, unsigned int length)
{
	struct cc_state ca = {};
	__u32 history[7] = {}, sorted[7], base = CC_U32_MAX;
	unsigned int count = 0;

	for (unsigned int i = 0; i < length; i++) {
		history[i % 7] = values[i];
		if (count < 7)
			count++;
		memcpy(sorted, history, sizeof(sorted));
		qsort(sorted, count, sizeof(sorted[0]), compare_u32);
		__u32 median = sorted[(count - 1) / 2];

		if (median < base)
			base = median;
		cc_rtt(&ca, values[i]);
		assert(ca.median_us == median && ca.base_us == base);
	}
}

static void test_median_permutations(void)
{
	/* All 7! distinct orderings, including every partially-filled prefix. */
	for (unsigned int code = 0; code < 5040; code++) {
		__u32 pool[7] = {1, 2, 3, 100, 1000, 1000000, 0x7fffffff};
		__u32 values[14];
		unsigned int remaining = 7, digits = code;

		for (unsigned int i = 0; i < 7; i++) {
			unsigned int pick = digits % remaining;

			digits /= remaining;
			values[i] = pool[pick];
			for (unsigned int j = pick; j + 1 < remaining; j++)
				pool[j] = pool[j + 1];
			remaining--;
			values[i + 7] = values[i];
		}
		check_median_sequence(values, 14);
	}
	/* All duplicate-heavy seven-sample sequences over three extreme values. */
	for (unsigned int code = 0; code < 2187; code++) {
		const __u32 choices[] = {1, 100, 0x7fffffff};
		__u32 values[7];
		unsigned int digits = code;

		for (unsigned int i = 0; i < 7; i++) {
			values[i] = choices[digits % 3];
			digits /= 3;
		}
		check_median_sequence(values, 7);
	}
}

static void test_thresholds(void)
{
	assert(round_diff(0, 0) == CC_GROW);
	assert(round_diff(2, 0) == CC_GROW);
	assert(round_diff(3, 0) == CC_HOLD);
	assert(round_diff(6, 0) == CC_HOLD);
	assert(round_diff(7, 0) == CC_BACKOFF);
	assert(round_diff(0, 1) == CC_HOLD);
	assert(round_diff(7, 1) == CC_BACKOFF);
	assert(cc_window(10, 1000, CC_BACKOFF) == 8);
	assert(cc_window(10, 1000, CC_GROW) == 11);
	assert(cc_window(2, 1000, CC_BACKOFF) == 2);
	assert(cc_window(10, 1, CC_BACKOFF) == 1);
	assert(cc_window(1000, 1000, CC_GROW) == 1000);
	assert(cc_window(CC_U32_MAX, CC_U32_MAX, CC_GROW) == CC_U32_MAX);
	assert(cc_loss_threshold(10) == 5);
	assert(cc_loss_threshold(1) == 2);
}

static void test_skips_and_round_boundaries(void)
{
	struct cc_state ca = {};
	struct cc_feedback f = feedback();

	cc_rtt(&ca, 100);
	assert(cc_round(&ca, &f) == CC_WAIT);
	f.now_us += 50;
	f.bytes_acked += 1000;
	f.snd_una = 1100;
	assert(cc_round(&ca, &f) == CC_WAIT);
	f.snd_una = f.snd_nxt;
	assert(cc_round(&ca, &f) == CC_SKIP); /* stale RTT */

	for (int reason = 0; reason < 7; reason++) {
		memset(&ca, 0, sizeof(ca));
		f = feedback();
		cc_rtt(&ca, 100);
		cc_begin(&ca, &f);
		cc_rtt(&ca, 100);
		f.snd_una = f.snd_nxt;
		f.bytes_acked += 10000;
		f.now_us += 100;
		switch (reason) {
		case 0: f.app_limited = 1; break;
		case 1: f.cwnd_limited = 0; break;
		case 2: f.now_us = ca.round_us; break;
		case 3: f.mss = 0; break;
		case 4: f.mss = 500; break;
		case 5: f.bytes_acked = 1; break;
		case 6: f.now_us += (__u64)CC_U32_MAX; break;
		}
		assert(cc_round(&ca, &f) == CC_SKIP);
	}
}

static void test_once_per_round_and_wrap(void)
{
	struct cc_state ca = {};
	struct cc_feedback f = feedback();

	f.snd_una = 0xffff0000U;
	f.snd_nxt = 0x1000;
	cc_rtt(&ca, 100);
	cc_begin(&ca, &f);
	cc_rtt(&ca, 100);
	f.snd_una = 0xfffffff0U;
	f.now_us += 100;
	assert(cc_round(&ca, &f) == CC_WAIT);
	f.snd_una = 0x1000;
	f.snd_nxt = 0x2000;
	assert(cc_round(&ca, &f) == CC_BACKOFF);
	f.cwnd = cc_window(f.cwnd, f.clamp, CC_BACKOFF);
	cc_begin(&ca, &f);
	assert(cc_round(&ca, &f) == CC_WAIT);
	assert(f.cwnd == 8);
	/* No data outstanding must not create an immediately-completing round. */
	f.snd_una = f.snd_nxt;
	cc_begin(&ca, &f);
	assert(!ca.active);
}

static void test_fractional_packets_and_isolation(void)
{
	struct cc_state a = {}, b = {};
	struct cc_feedback f = feedback();

	cc_rtt(&a, 100);
	cc_begin(&a, &f);
	cc_rtt(&a, 100);
	f.snd_una = f.snd_nxt;
	f.now_us += 100;
	f.bytes_acked += 3999; /* diff=6.001, not rounded down to 6 */
	assert(cc_round(&a, &f) == CC_BACKOFF);
	f = feedback();
	cc_begin(&a, &f);
	cc_rtt(&a, 100);
	f.snd_una = f.snd_nxt;
	f.now_us += 100;
	f.bytes_acked += 7001; /* diff=2.999, strictly below alpha */
	assert(cc_round(&a, &f) == CC_GROW);
	assert(b.base_us == 0 && b.count == 0 && !b.active);
}

static void test_transient_limitation_and_arithmetic_bounds(void)
{
	struct cc_state ca = {};
	struct cc_feedback f = feedback();

	cc_rtt(&ca, 100);
	cc_begin(&ca, &f);
	cc_rtt(&ca, 100);
	f.app_limited = 1;
	assert(cc_round(&ca, &f) == CC_WAIT);
	f.app_limited = 0;
	f.now_us += 100;
	f.snd_una = f.snd_nxt;
	assert(cc_round(&ca, &f) == CC_SKIP);

	f = feedback();
	f.cwnd = CC_U32_MAX;
	f.ssthresh = CC_U32_MAX;
	f.clamp = CC_U32_MAX;
	cc_begin(&ca, &f);
	cc_rtt(&ca, 0x7fffffff);
	f.now_us += CC_U32_MAX;
	f.bytes_acked += 0x7fffffff;
	f.snd_una = f.snd_nxt;
	assert(cc_round(&ca, &f) == CC_BACKOFF);
	f = feedback();
	cc_begin(&ca, &f);
	cc_rtt(&ca, 100);
	f.snd_una = f.snd_nxt;
	f.now_us++;
	f.bytes_acked += 0x80000000ULL;
	assert(cc_round(&ca, &f) == CC_SKIP);
}

int main(void)
{
	test_median();
	test_median_permutations();
	test_thresholds();
	test_skips_and_round_boundaries();
	test_once_per_round_and_wrap();
	test_fractional_packets_and_isolation();
	test_transient_limitation_and_arithmetic_bounds();
	puts("controller tests passed: median, thresholds, startup decisions, bounds, "
	     "invalid/app-limited feedback, round cadence, sequence wrap, isolation");
	return 0;
}

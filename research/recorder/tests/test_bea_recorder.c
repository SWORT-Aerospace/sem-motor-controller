/* Host tests of the evidence recorder (research/recorder). Build: see tests/research/test_recorder_c.py. */
#define _POSIX_C_SOURCE 199309L
#include <string.h>
#include <time.h>

#include "bea_recorder.h"
#include "mc_test.h"
#include "semmc/mc_crc.h"

#define CAP0 64u
#define CAP1 16u
static bea_slot_t s0[CAP0], s1[CAP1];
static uint8_t out[2048];

static void setup(bea_recorder_t *r, uint32_t rate, uint32_t burst)
{
    bea_slot_t *const st[2] = {s0, s1};
    const uint32_t cap[2] = {CAP0, CAP1}, per[2] = {10000u, 100000u};   /* 100 Hz and 10 Hz channels */
    const bea_config_t cfg = {rate, burst, 512u};
    bea_init(r, &cfg, 2u, st, cap, per);
}

static void feed(bea_recorder_t *r, uint8_t ch, uint32_t t0, uint32_t dt, uint32_t n)
{
    uint8_t body[11];
    for (uint32_t i = 0; i < n; i++) {
        memset(body, (int)(i & 0xFFu), sizeof body);
        bea_on_record(r, ch, 1u, t0 + i * dt, body, sizeof body);
    }
}

static bea_status_t ask(bea_recorder_t *r, uint32_t id, bea_kind_t kind, uint16_t mask, uint32_t t0, uint32_t t1d,
                        uint32_t exp, uint8_t dec, uint32_t now)
{
    uint8_t q[BEA_REQUEST_BYTES];
    bea_encode_request(q, id, kind, mask, t0, t1d, exp, dec);
    return bea_on_request(r, q, sizeof q, now);
}

/* Drains every chunk now available; returns the number of records and checks each chunk's CRC. */
static int drain(bea_recorder_t *r, uint32_t now, uint8_t *last_status, uint32_t *t_min, uint32_t *t_max)
{
    int recs = 0;
    size_t n;
    *t_min = 0xFFFFFFFFu;
    *t_max = 0u;
    while ((n = bea_poll(r, now, out, sizeof out)) > 0u) {
        const uint32_t crc = (uint32_t)out[n - 4] | ((uint32_t)out[n - 3] << 8) | ((uint32_t)out[n - 2] << 16) |
                             ((uint32_t)out[n - 1] << 24);
        CHECK(crc == mc_crc32(out, n - 4u));
        CHECK(out[0] == 'B' && out[1] == 'R' && out[2] == BEA_VERSION_MAJOR);
        *last_status = out[8];
        size_t p = BEA_CHUNK_HEADER_BYTES;
        for (uint8_t k = 0; k < out[11]; k++) {
            const uint32_t t = (uint32_t)out[p + 2] | ((uint32_t)out[p + 3] << 8) | ((uint32_t)out[p + 4] << 16) |
                               ((uint32_t)out[p + 5] << 24);
            if (t < *t_min) *t_min = t;
            if (t > *t_max) *t_max = t;
            p += BEA_RECORD_HEADER_BYTES + out[p + 1];
            recs++;
        }
        CHECK(p == n - 4u);
        if (out[10] & 1u) break;
    }
    return recs;
}

static void test_ring_overwrites_oldest_and_counts(void)
{
    bea_recorder_t r;
    setup(&r, 1000000u, 100000u);
    feed(&r, 0, 1000u, 10000u, CAP0 + 10u);
    CHECK_EQ_INT(r.ring[0].count, CAP0);
    CHECK_EQ_INT(r.c.overwritten, 10);
    CHECK_EQ_INT(r.c.records_in, CAP0 + 10u);
    bea_on_record(&r, 7, 1u, 0u, out, 4u);                  /* no such channel */
    CHECK_EQ_INT(r.c.dropped_bad_channel, 1);
}

static void test_buffer_returns_only_the_window_and_flags_partial(void)
{
    bea_recorder_t r;
    setup(&r, 1000000u, 100000u);
    feed(&r, 0, 0u, 10000u, 50u);                           /* t = 0 .. 490 ms */
    CHECK_EQ_INT(ask(&r, 1u, BEA_REQ_BUFFER, 1u, 100000u, 200000u, 10000000u, 1u, 500000u), BEA_ST_ACCEPTED);
    uint8_t st;
    uint32_t lo, hi;
    CHECK_EQ_INT(drain(&r, 500000u, &st, &lo, &hi), 11);   /* 100, 110, ..., 200 ms inclusive */
    CHECK_EQ_INT(st, BEA_ST_COMPLETE);
    CHECK(lo == 100000u && hi == 200000u);
    feed(&r, 0, 500000u, 10000u, 60u);                      /* overwrites the start of the ring */
    CHECK_EQ_INT(ask(&r, 2u, BEA_REQ_BUFFER, 1u, 0u, 2000000u, 10000000u, 1u, 1200000u), BEA_ST_ACCEPTED);
    drain(&r, 1200000u, &st, &lo, &hi);
    CHECK_EQ_INT(st, BEA_ST_PARTIAL);
}

static void test_buffer_never_returns_records_after_now(void)
{
    bea_recorder_t r;
    setup(&r, 1000000u, 100000u);
    feed(&r, 0, 0u, 10000u, 40u);                           /* up to 390 ms */
    CHECK_EQ_INT(ask(&r, 3u, BEA_REQ_BUFFER, 1u, 0u, 900000u, 10000000u, 1u, 200000u), BEA_ST_ACCEPTED);
    uint8_t st;
    uint32_t lo, hi;
    drain(&r, 200000u, &st, &lo, &hi);
    CHECK(hi <= 200000u);
}

static void test_decimation_keeps_every_nth(void)
{
    bea_recorder_t r;
    setup(&r, 1000000u, 100000u);
    feed(&r, 0, 0u, 10000u, 60u);
    CHECK_EQ_INT(ask(&r, 4u, BEA_REQ_BUFFER, 1u, 0u, 590000u, 10000000u, 10u, 600000u), BEA_ST_ACCEPTED);
    uint8_t st;
    uint32_t lo, hi;
    CHECK_EQ_INT(drain(&r, 600000u, &st, &lo, &hi), 6);
}

static void test_capture_waits_for_its_window_and_is_protected(void)
{
    bea_recorder_t r;
    setup(&r, 1000000u, 100000u);
    feed(&r, 1, 0u, 100000u, 5u);
    CHECK_EQ_INT(ask(&r, 5u, BEA_REQ_CAPTURE, 2u, 0u, 1000u, 50000000u, 1u, 500000u), BEA_ST_ACCEPTED);  /* 1 s */
    CHECK_EQ_INT(bea_poll(&r, 600000u, out, sizeof out), 0u);  /* not before the window has passed */
    feed(&r, 1, 600000u, 100000u, 10u);                     /* 0.6 .. 1.5 s */
    uint8_t st;
    uint32_t lo, hi;
    const int n = drain(&r, 1600000u, &st, &lo, &hi);
    CHECK_EQ_INT(n, 10);
    CHECK(lo >= 500000u && hi <= 1500000u);
    CHECK_EQ_INT(ask(&r, 6u, BEA_REQ_CAPTURE, 2u, 0u, 5000u, 50000000u, 1u, 2000000u), BEA_ST_TOO_LONG);
}

static void test_pinned_records_are_not_overwritten(void)
{
    bea_recorder_t r;
    setup(&r, 100u, 100u);                                   /* a slow uplink: the request stays open */
    feed(&r, 1, 0u, 100000u, CAP1);
    CHECK_EQ_INT(ask(&r, 7u, BEA_REQ_BUFFER, 2u, 0u, 2000000u, 50000000u, 1u, 1600000u), BEA_ST_ACCEPTED);
    feed(&r, 1, 1600000u, 100000u, 5u);
    CHECK_EQ_INT(r.c.dropped_pinned, 5);                     /* new records wait; the owed ones are kept */
    CHECK_EQ_INT(r.c.overwritten, 0);
}

static void test_requests_are_validated(void)
{
    bea_recorder_t r;
    setup(&r, 1000000u, 100000u);
    uint8_t q[BEA_REQUEST_BYTES];
    bea_encode_request(q, 9u, BEA_REQ_BUFFER, 1u, 0u, 10u, 1000u, 1u);
    CHECK_EQ_INT(bea_on_request(&r, q, sizeof q, 0u), BEA_ST_ACCEPTED);
    CHECK_EQ_INT(bea_on_request(&r, q, sizeof q, 0u), BEA_ST_DUPLICATE);
    bea_encode_request(q, 10u, BEA_REQ_BUFFER, 1u, 0u, 10u, 1000u, 1u);
    CHECK_EQ_INT(bea_on_request(&r, q, sizeof q, 5000u), BEA_ST_EXPIRED);
    q[5] ^= 1u;
    CHECK_EQ_INT(bea_on_request(&r, q, sizeof q, 0u), BEA_ST_BAD_CRC);
    bea_encode_request(q, 11u, BEA_REQ_BUFFER, 1u, 0u, 10u, 1000u, 1u);
    q[2] = 2u;
    const uint32_t crc = mc_crc32(q, 28u);
    q[28] = (uint8_t)crc; q[29] = (uint8_t)(crc >> 8); q[30] = (uint8_t)(crc >> 16); q[31] = (uint8_t)(crc >> 24);
    CHECK_EQ_INT(bea_on_request(&r, q, sizeof q, 0u), BEA_ST_BAD_VERSION);
    bea_encode_request(q, 12u, BEA_REQ_BUFFER, 0x80u, 0u, 10u, 1000u, 1u);
    CHECK_EQ_INT(bea_on_request(&r, q, sizeof q, 0u), BEA_ST_BAD_REQUEST);   /* channel 7 does not exist */
    bea_encode_request(q, 13u, BEA_REQ_BUFFER, 1u, 10u, 10u, 1000u, 1u);
    CHECK_EQ_INT(bea_on_request(&r, q, sizeof q, 0u), BEA_ST_BAD_REQUEST);   /* empty window */
    CHECK_EQ_INT(bea_on_request(&r, q, 31u, 0u), BEA_ST_BAD_REQUEST);
    for (uint32_t id = 20u; id < 23u; id++)
        CHECK_EQ_INT(ask(&r, id, BEA_REQ_BUFFER, 1u, 0u, 10u, 1000u, 1u, 0u), BEA_ST_ACCEPTED);
    CHECK_EQ_INT(ask(&r, 30u, BEA_REQ_BUFFER, 1u, 0u, 10u, 1000u, 1u, 0u), BEA_ST_BUSY);
}

static void test_rate_limit_defers_without_losing_records(void)
{
    bea_recorder_t r;
    setup(&r, 2000u, 300u);                                  /* 2 kB/s, 300-byte bucket */
    feed(&r, 0, 0u, 10000u, 60u);
    CHECK_EQ_INT(ask(&r, 40u, BEA_REQ_BUFFER, 1u, 0u, 590000u, 100000000u, 1u, 600000u), BEA_ST_ACCEPTED);
    int recs = 0;
    uint32_t now = 600000u;
    for (int k = 0; k < 4000 && r.active[0].used; k++, now += 5000u) {   /* polls faster than one record of tokens */
        const size_t n = bea_poll(&r, now, out, sizeof out);
        if (n) recs += out[11];
    }
    CHECK_EQ_INT(recs, 60);
    CHECK(r.c.rate_deferred > 0u);
    CHECK(r.c.bytes_sent <= 300u + 2000u * (now - 600000u) / 1000000u + 1u);
}

static void test_expired_request_is_reported_and_released(void)
{
    bea_recorder_t r;
    setup(&r, 1000000u, 100000u);
    CHECK_EQ_INT(ask(&r, 50u, BEA_REQ_CAPTURE, 1u, 0u, 400u, 300000u, 1u, 0u), BEA_ST_ACCEPTED);
    const size_t n = bea_poll(&r, 400000u, out, sizeof out);
    CHECK(n > 0u && out[8] == BEA_ST_EXPIRED && (out[10] & 1u));
    CHECK(!r.active[0].used && r.ring[0].pin_count == 0u);
}

static void test_clock_wrap(void)
{
    bea_recorder_t r;
    setup(&r, 1000000u, 100000u);
    const uint32_t t0 = 0xFFFFFFFFu - 200000u;              /* 0.2 s before the 32-bit clock wraps */
    feed(&r, 0, t0, 10000u, 40u);                            /* runs 0.2 s past the wrap */
    CHECK_EQ_INT(ask(&r, 60u, BEA_REQ_BUFFER, 1u, t0 + 100000u, t0 + 300000u, t0 + 10000000u, 1u, t0 + 400000u),
                 BEA_ST_ACCEPTED);
    uint8_t st;
    uint32_t lo, hi;
    CHECK_EQ_INT(drain(&r, t0 + 400000u, &st, &lo, &hi), 21);
}

static void test_status_reports_counters(void)
{
    bea_recorder_t r;
    setup(&r, 1000000u, 100000u);
    feed(&r, 0, 0u, 10000u, 3u);
    CHECK_EQ_INT(ask(&r, 70u, BEA_REQ_STATUS, 0u, 0u, 0u, 1000000u, 1u, 0u), BEA_ST_ACCEPTED);
    const size_t n = bea_poll(&r, 0u, out, sizeof out);
    CHECK(n == BEA_CHUNK_HEADER_BYTES + sizeof(bea_counters_t) + 4u);
    const uint32_t records_in = (uint32_t)out[24] | ((uint32_t)out[25] << 8);
    CHECK_EQ_INT(records_in, 3);
}

/* Host timing only: a measured maximum on this computer, not a worst-case execution time on the target. */
static void test_host_timing_report(void)
{
    bea_recorder_t r;
    setup(&r, 100000000u, 1000000u);
    uint8_t body[11] = {0};
    struct timespec a, b;
    double worst_rec = 0.0, worst_poll = 0.0;
    for (uint32_t i = 0; i < 20000u; i++) {
        clock_gettime(CLOCK_MONOTONIC, &a);
        bea_on_record(&r, 0, 1u, i * 10000u, body, sizeof body);
        clock_gettime(CLOCK_MONOTONIC, &b);
        const double us = (b.tv_sec - a.tv_sec) * 1e6 + (b.tv_nsec - a.tv_nsec) / 1e3;
        if (us > worst_rec) worst_rec = us;
    }
    CHECK_EQ_INT(ask(&r, 80u, BEA_REQ_BUFFER, 1u, 0u, 200000000u, 300000000u, 1u, 200000000u), BEA_ST_ACCEPTED);
    for (int k = 0; k < 100 && r.active[0].used; k++) {
        clock_gettime(CLOCK_MONOTONIC, &a);
        bea_poll(&r, 200000000u, out, sizeof out);
        clock_gettime(CLOCK_MONOTONIC, &b);
        const double us = (b.tv_sec - a.tv_sec) * 1e6 + (b.tv_nsec - a.tv_nsec) / 1e3;
        if (us > worst_poll) worst_poll = us;
    }
    printf("host measured maximum: bea_on_record %.2f us, bea_poll (512-byte chunk) %.2f us; "
           "not a WCET; sizeof(bea_recorder_t) = %zu bytes\n", worst_rec, worst_poll, sizeof(bea_recorder_t));
    CHECK(worst_rec >= 0.0);
}

int main(void)
{
    RUN(test_ring_overwrites_oldest_and_counts);
    RUN(test_buffer_returns_only_the_window_and_flags_partial);
    RUN(test_buffer_never_returns_records_after_now);
    RUN(test_decimation_keeps_every_nth);
    RUN(test_capture_waits_for_its_window_and_is_protected);
    RUN(test_pinned_records_are_not_overwritten);
    RUN(test_requests_are_validated);
    RUN(test_rate_limit_defers_without_losing_records);
    RUN(test_expired_request_is_reported_and_released);
    RUN(test_clock_wrap);
    RUN(test_status_reports_counters);
    RUN(test_host_timing_report);
    TEST_MAIN_END();
}

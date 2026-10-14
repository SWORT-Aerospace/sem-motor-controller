/* Freshness, sequencing, wraparound, session and repeated-sample tests. */
#include "mc_test.h"
#include "semmc/mc_freshness.h"

#define MS(x) ((mc_time_us_t)(x) * 1000u)

static void test_missing_then_fresh_then_stale(void)
{
    mc_fresh_t f;
    mc_fresh_init(&f, 100000u, 1u, 50u);
    CHECK(mc_fresh_status(&f, MS(0)) == MC_VAL_MISSING);
    CHECK(mc_fresh_on_rx(&f, MS(10), 7u, 1u, 0u, 1000u) == MC_RX_ACCEPTED_FIRST);
    CHECK(mc_fresh_status(&f, MS(10)) & MC_VAL_SESSION_NEW);
    mc_fresh_ack_session(&f);
    CHECK(mc_fresh_status(&f, MS(10)) == MC_VAL_OK);
    CHECK(mc_fresh_status(&f, MS(110)) == MC_VAL_OK);
    CHECK(mc_fresh_status(&f, MS(111)) & MC_VAL_STALE);
}

static void test_duplicate_and_repeated_sample_do_not_renew(void)
{
    mc_fresh_t f;
    mc_fresh_init(&f, 100000u, 1u, 50u);
    (void)mc_fresh_on_rx(&f, MS(0), 7u, 1u, 10u, 5000u);
    mc_fresh_ack_session(&f);
    /* Same frame again 60 ms later: duplicate, no renewal. */
    CHECK(mc_fresh_on_rx(&f, MS(60), 7u, 1u, 10u, 5000u) == MC_RX_DUPLICATE);
    /* New sequence number but the same cached sample (source time unchanged). */
    CHECK(mc_fresh_on_rx(&f, MS(80), 7u, 1u, 11u, 5000u) == MC_RX_REPEATED_SAMPLE);
    CHECK(mc_fresh_on_rx(&f, MS(95), 7u, 1u, 12u, 5000u) == MC_RX_REPEATED_SAMPLE);
    /* Validity still dates from t = 0, so it expires at 100 ms. */
    CHECK(mc_fresh_status(&f, MS(101)) & MC_VAL_STALE);
    CHECK_EQ_INT(f.n_dup, 1);
    CHECK_EQ_INT(f.n_repeat, 2);
}

static void test_reordered_rejected(void)
{
    mc_fresh_t f;
    mc_fresh_init(&f, 100000u, 1u, 50u);
    (void)mc_fresh_on_rx(&f, MS(0), 7u, 1u, 10u, 5000u);
    CHECK(mc_fresh_on_rx(&f, MS(20), 7u, 1u, 12u, 5020u) == MC_RX_ACCEPTED_NEW);
    CHECK(mc_fresh_on_rx(&f, MS(21), 7u, 1u, 11u, 5010u) == MC_RX_REORDERED_OLD);
    CHECK_EQ_INT(f.last_seq, 12);
    CHECK_EQ_INT(f.n_lost, 1);
}

static void test_counter_and_timestamp_wrap(void)
{
    mc_fresh_t f;
    mc_fresh_init(&f, 100000u, 1u, 50u);
    (void)mc_fresh_on_rx(&f, MS(0), 7u, 1u, 254u, 65520u);
    CHECK(mc_fresh_on_rx(&f, MS(20), 7u, 1u, 255u, 65535u) == MC_RX_ACCEPTED_NEW);
    CHECK(mc_fresh_on_rx(&f, MS(40), 7u, 1u, 0u, 19u) == MC_RX_ACCEPTED_NEW);   /* both wrap */
    CHECK(mc_fresh_on_rx(&f, MS(60), 7u, 1u, 1u, 39u) == MC_RX_ACCEPTED_NEW);
    CHECK(mc_fresh_on_rx(&f, MS(61), 7u, 1u, 255u, 65535u) == MC_RX_REORDERED_OLD); /* old across wrap */
    CHECK_EQ_INT(mc_seq8_diff(0u, 255u), 1);
    CHECK_EQ_INT(mc_seq8_diff(255u, 0u), -1);
    CHECK_EQ_INT(mc_ts16_diff(5u, 65530u), 11);
}

static void test_source_reboot_is_new_session(void)
{
    mc_fresh_t f;
    mc_fresh_init(&f, 100000u, 1u, 50u);
    (void)mc_fresh_on_rx(&f, MS(0), 7u, 1u, 100u, 30000u);
    mc_fresh_ack_session(&f);
    /* Source reboots: new session, counters restart low. Must not be "old". */
    CHECK(mc_fresh_on_rx(&f, MS(20), 8u, 1u, 0u, 5u) == MC_RX_SESSION_CHANGED);
    CHECK(mc_fresh_status(&f, MS(20)) & MC_VAL_SESSION_NEW);
    CHECK_EQ_INT(f.n_session_changes, 1);
    CHECK(mc_fresh_on_rx(&f, MS(40), 8u, 1u, 1u, 25u) == MC_RX_ACCEPTED_NEW);
}

static void test_clock_domain_and_time_jump(void)
{
    mc_fresh_t f;
    mc_fresh_init(&f, 100000u, 1u, 50u);
    CHECK(mc_fresh_on_rx(&f, MS(0), 7u, 2u, 0u, 0u) == MC_RX_CLOCK_DOMAIN_MISMATCH);
    CHECK(mc_fresh_status(&f, MS(0)) == MC_VAL_MISSING);
    (void)mc_fresh_on_rx(&f, MS(0), 7u, 1u, 0u, 1000u);
    /* Source claims 5 s passed while 20 ms passed locally: discontinuity. */
    CHECK(mc_fresh_on_rx(&f, MS(20), 7u, 1u, 1u, 6000u) == MC_RX_TIME_DISCONTINUITY);
}

static void test_resync_after_gap_rejects_old_frame(void)
{
    mc_fresh_t f;
    mc_fresh_init(&f, 100000u, 1u, 50u);
    (void)mc_fresh_on_rx(&f, MS(0), 7u, 1u, 10u, 1000u);
    mc_fresh_ack_session(&f);
    (void)mc_fresh_on_rx(&f, MS(20), 7u, 1u, 11u, 1020u);
    /* 2 s gap. A delayed old frame (source time 1010) must not resync. */
    CHECK(mc_fresh_on_rx(&f, MS(2020), 7u, 1u, 200u, 1010u) == MC_RX_REPEATED_SAMPLE);
    CHECK(mc_fresh_status(&f, MS(2020)) & MC_VAL_STALE);
    /* A genuinely new frame consistent with local time resyncs. */
    CHECK(mc_fresh_on_rx(&f, MS(2030), 7u, 1u, 201u, 3030u) == MC_RX_ACCEPTED_RESYNC);
    CHECK(mc_fresh_status(&f, MS(2030)) == MC_VAL_OK);
}

static void test_seq_only_mode(void)
{
    mc_fresh_t f;
    mc_fresh_init_seq_only(&f, 500000u, 1u);
    (void)mc_fresh_on_rx(&f, MS(0), 1u, 1u, 5u, 0u);
    mc_fresh_ack_session(&f);
    CHECK(mc_fresh_on_rx(&f, MS(100), 1u, 1u, 5u, 0u) == MC_RX_DUPLICATE);
    CHECK(mc_fresh_on_rx(&f, MS(200), 1u, 1u, 6u, 0u) == MC_RX_ACCEPTED_NEW);
    CHECK(mc_fresh_on_rx(&f, MS(250), 1u, 1u, 4u, 0u) == MC_RX_REORDERED_OLD);
}

static void test_time_extend(void)
{
    mc_time_us_t t = 0u;
    t = mc_time_extend(t, 0xFFFFFF00u);
    CHECK(t == 0xFFFFFF00ull);
    t = mc_time_extend(t, 0x00000010u); /* hardware counter wrapped */
    CHECK(t == 0x100000010ull);
    t = mc_time_extend(t, 0x00000020u);
    CHECK(t == 0x100000020ull);
}

int main(void)
{
    RUN(test_missing_then_fresh_then_stale);
    RUN(test_duplicate_and_repeated_sample_do_not_renew);
    RUN(test_reordered_rejected);
    RUN(test_counter_and_timestamp_wrap);
    RUN(test_source_reboot_is_new_session);
    RUN(test_clock_domain_and_time_jump);
    RUN(test_resync_after_gap_rejects_old_frame);
    RUN(test_seq_only_mode);
    RUN(test_time_extend);
    TEST_MAIN_END();
}

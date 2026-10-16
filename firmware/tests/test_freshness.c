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

/* Found by test_core_properties: a frame rejected as TIME_DISCONTINUITY did not
 * advance the sequence state, so its re-delivery 20 ms later was accepted. */
static void test_rejected_frame_redelivered_is_duplicate(void)
{
    mc_fresh_t f;
    mc_fresh_init(&f, 100000u, 1u, 100u);
    (void)mc_fresh_on_rx(&f, MS(0), 7u, 1u, 10u, 1000u);
    (void)mc_fresh_on_rx(&f, MS(20), 7u, 1u, 11u, 1020u);
    /* claims 140 ms of source time in 20 ms: rejected */
    CHECK(mc_fresh_on_rx(&f, MS(40), 7u, 1u, 12u, 1160u) == MC_RX_TIME_DISCONTINUITY);
    const mc_time_us_t t_new = f.last_new_rx_us;
    /* the same frame re-delivered later, when its timing would look plausible */
    CHECK(mc_fresh_on_rx(&f, MS(80), 7u, 1u, 12u, 1160u) == MC_RX_DUPLICATE);
    CHECK(mc_fresh_on_rx(&f, MS(130), 7u, 1u, 12u, 1160u) == MC_RX_DUPLICATE);  /* also once stale */
    CHECK(f.last_new_rx_us == t_new);
}

/* An old cached sample after a short silence used to be accepted as a RESYNC
 * (only its step from the previous, already 20 ms late, sample was checked),
 * and every fresh sample after it was then rejected until the 30 s ambiguity
 * limit: supervisor input lost for 30 s. */
static void test_fresh_samples_after_a_delayed_one_are_accepted(void)
{
    mc_fresh_t f;
    mc_fresh_init(&f, 100000u, 1u, 100u);
    (void)mc_fresh_on_rx(&f, MS(0), 7u, 1u, 10u, 1000u);
    CHECK(mc_fresh_on_rx(&f, MS(40), 7u, 1u, 11u, 1020u) == MC_RX_ACCEPTED_NEW);       /* 20 ms late */
    CHECK_EQ_INT(f.lag_us, 19200);       /* docs/MATH_SPEC.md (3.8): 0 + 40 - 20 - 0.02 x 40 ms = 19.2 ms */
    /* 120 ms of silence, then a cached sample whose source time is 120 ms old */
    CHECK(mc_fresh_on_rx(&f, MS(160), 7u, 1u, 12u, 1040u) == MC_RX_TIME_DISCONTINUITY);
    /* fresh samples again */
    for (int k = 0; k <= 20; k++)
        CHECK(mc_rx_renews(mc_fresh_on_rx(&f, MS(180 + 20 * k), 7u, 1u, (uint8_t)(13 + k),
                                          (uint16_t)(1180 + 20 * k))));
    CHECK(mc_fresh_status(&f, MS(590)) == MC_VAL_SESSION_NEW);  /* fresh; session never acknowledged here */
}

/* Delay that grows a little with every frame (each step well inside the
 * tolerance) must be caught once the total exceeds it. */
static void test_creeping_delay_is_bounded(void)
{
    mc_fresh_t f;
    mc_fresh_init(&f, 100000u, 1u, 100u);
    (void)mc_fresh_on_rx(&f, MS(0), 7u, 1u, 0u, 1000u);
    int accepted_late = 0;
    for (int k = 1; k <= 40; k++) {
        /* local 20 ms per frame, source only 10 ms: data ages 10 ms per frame */
        const mc_rx_result_t r = mc_fresh_on_rx(&f, MS(20 * k), 7u, 1u, (uint8_t)k, (uint16_t)(1000 + 10 * k));
        if (r == MC_RX_ACCEPTED_NEW && 10 * k > 100 + 20) accepted_late++;
    }
    CHECK_EQ_INT(accepted_late, 0);   /* nothing more than tolerance + drift allowance behind */
    CHECK(f.n_rejected > 0);
}

/* Found by the 100-seed soak: the controller rebooted while the companion was
 * stalled; the companion's first frame under the new tag carried a request
 * computed 220 ms earlier. That delayed sample became the timing reference and
 * every fresh sample after it looked like a forward jump: locked out. */
static void test_delayed_first_sample_is_reanchored(void)
{
    mc_fresh_t f;
    mc_fresh_init(&f, 100000u, 1u, 100u);
    CHECK(mc_fresh_on_rx(&f, MS(1000), 7u, 1u, 40u, 780u) == MC_RX_ACCEPTED_FIRST);   /* 220 ms old */
    CHECK(mc_fresh_on_rx(&f, MS(1020), 7u, 1u, 41u, 1020u) == MC_RX_TIME_DISCONTINUITY); /* candidate */
    CHECK(mc_fresh_on_rx(&f, MS(1040), 7u, 1u, 42u, 1040u) == MC_RX_ACCEPTED_NEW);       /* agrees: re-anchor */
    for (int k = 1; k <= 10; k++)
        CHECK(mc_fresh_on_rx(&f, MS(1040 + 20 * k), 7u, 1u, (uint8_t)(42 + k), (uint16_t)(1040 + 20 * k)) ==
              MC_RX_ACCEPTED_NEW);
}

/* One CRC-valid frame with a corrupted source time must not move the reference. */
static void test_single_forward_jump_does_not_move_reference(void)
{
    mc_fresh_t f;
    mc_fresh_init(&f, 100000u, 1u, 100u);
    (void)mc_fresh_on_rx(&f, MS(0), 7u, 1u, 0u, 1000u);
    CHECK(mc_fresh_on_rx(&f, MS(20), 7u, 1u, 1u, 1020u) == MC_RX_ACCEPTED_NEW);
    CHECK(mc_fresh_on_rx(&f, MS(40), 7u, 1u, 2u, 9000u) == MC_RX_TIME_DISCONTINUITY);
    for (int k = 3; k <= 12; k++)
        CHECK(mc_fresh_on_rx(&f, MS(20 * k), 7u, 1u, (uint8_t)k, (uint16_t)(1000 + 20 * k)) == MC_RX_ACCEPTED_NEW);
}

/* Found by the soak: after the tracker had gone stale, a frame re-sent from
 * earlier (lower sequence than one seen 20 ms before) was accepted, because
 * past the freshness window only source time was checked. */
static void test_older_frame_rejected_after_stale(void)
{
    mc_fresh_t f;
    mc_fresh_init(&f, 100000u, 1u, 100u);
    (void)mc_fresh_on_rx(&f, MS(0), 7u, 1u, 20u, 1000u);
    (void)mc_fresh_on_rx(&f, MS(20), 7u, 1u, 21u, 1020u);
    /* stale; frame 28 arrives with an implausible source time and is rejected */
    CHECK(mc_fresh_on_rx(&f, MS(600), 7u, 1u, 28u, 1780u) == MC_RX_TIME_DISCONTINUITY);
    /* frame 25, sent before 28, re-delivered 20 ms later: older than one already seen */
    CHECK(mc_fresh_on_rx(&f, MS(620), 7u, 1u, 25u, 1600u) == MC_RX_REORDERED_OLD);
    CHECK(f.last_new_rx_us == MS(20));
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
    RUN(test_rejected_frame_redelivered_is_duplicate);
    RUN(test_fresh_samples_after_a_delayed_one_are_accepted);
    RUN(test_creeping_delay_is_bounded);
    RUN(test_delayed_first_sample_is_reanchored);
    RUN(test_single_forward_jump_does_not_move_reference);
    RUN(test_older_frame_rejected_after_stale);
    RUN(test_seq_only_mode);
    RUN(test_time_extend);
    TEST_MAIN_END();
}

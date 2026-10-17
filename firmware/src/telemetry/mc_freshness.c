#include "semmc/mc_freshness.h"

static void inc(uint16_t *c)
{
    if (*c < UINT16_MAX) (*c)++;
}

void mc_fresh_init(mc_fresh_t *f, uint32_t max_age_us, uint8_t clock_domain, uint16_t max_time_skew_ms)
{
    f->max_age_us = max_age_us;
    f->expected_clock_domain = clock_domain;
    f->max_time_skew_ms = max_time_skew_ms;
    f->uses_source_time = true;
    mc_fresh_reset(f);
}

void mc_fresh_init_seq_only(mc_fresh_t *f, uint32_t max_age_us, uint8_t clock_domain)
{
    mc_fresh_init(f, max_age_us, clock_domain, 0u);
    f->uses_source_time = false;
}

void mc_fresh_reset(mc_fresh_t *f)
{
    f->have_session = false;
    f->session_id = 0;
    f->have_sample = false;
    f->last_seq = 0;
    f->last_src_ms = 0;
    f->last_new_rx_us = 0;
    f->lag_us = 0;
    f->have_cand = false;
    f->cand_rx_us = 0;
    f->cand_src_ms = 0;
    f->have_seen = false;
    f->seen_seq = 0;
    f->seen_src_ms = 0;
    f->floor_seq = 0;
    f->floor_rx_us = 0;
    f->session_new = false;
    f->n_new = f->n_dup = f->n_old = f->n_repeat = f->n_lost = 0;
    f->n_session_changes = f->n_rejected = f->n_integrity = 0;
}

static bool is_stale(const mc_fresh_t *f, mc_time_us_t now_us)
{
    if (!f->have_sample) return true;
    if (now_us < f->last_new_rx_us) return true; /* local time must be monotonic */
    return (now_us - f->last_new_rx_us) > (mc_time_us_t)f->max_age_us;
}

static mc_rx_result_t accept(mc_fresh_t *f, mc_time_us_t now_us, uint8_t seq, uint16_t src_ms, mc_rx_result_t r)
{
    if (f->have_sample) {
        const int8_t dseq = mc_seq8_diff(seq, f->last_seq);
        for (int k = 1; k < dseq; k++) inc(&f->n_lost);
    }
    f->have_sample = true;
    f->last_seq = seq;
    f->last_src_ms = src_ms;
    f->last_new_rx_us = now_us;
    f->have_cand = false;
    inc(&f->n_new);
    return r;
}

/* Accept without a timing reference (first sample, or after an ambiguous gap):
 * the sample becomes the reference. */
static mc_rx_result_t accept_as_reference(mc_fresh_t *f, mc_time_us_t now_us, uint8_t seq, uint16_t src_ms,
                                          mc_rx_result_t r)
{
    f->lag_us = 0;
    return accept(f, now_us, seq, src_ms, r);
}

static int64_t drift_allowance_us(int64_t local_adv_us) { return local_adv_us * MC_FRESH_DRIFT_PPM / 1000000; }

/* Lag of a sample received at now_us with source time src_ms behind a sample
 * received at ref_rx_us with source time ref_src_ms whose own lag was ref_lag
 * (see header). The callers keep now - ref_rx below MC_FRESH_UNAMBIGUOUS_US or
 * the freshness window, so the products fit in 64 bits with a wide margin. */
static int64_t lag_from(int64_t ref_lag_us, mc_time_us_t ref_rx_us, uint16_t ref_src_ms, mc_time_us_t now_us,
                        uint16_t src_ms)
{
    const int64_t local_adv_us = (int64_t)(now_us - ref_rx_us);
    const int64_t drift_us = drift_allowance_us(local_adv_us);
    const int64_t lag = ref_lag_us + local_adv_us - (int64_t)mc_ts16_diff(src_ms, ref_src_ms) * 1000;
    if (lag > drift_us) return lag - drift_us;
    if (lag < -drift_us) return lag + drift_us;
    return 0;
}

/* Timing judgement of a sample whose sequence and source time both advanced. */
static mc_rx_result_t judge(mc_fresh_t *f, mc_time_us_t now_us, uint8_t seq, uint16_t src_ms, mc_rx_result_t ok)
{
    const int64_t tol = (int64_t)f->max_time_skew_ms * 1000;
    const int64_t lag = lag_from(f->lag_us, f->last_new_rx_us, f->last_src_ms, now_us, src_ms);
    if (lag > tol) {
        inc(&f->n_rejected);
        return MC_RX_TIME_DISCONTINUITY; /* older than the reference: delayed or cached */
    }
    if (lag >= -tol) {
        f->lag_us = lag > 0 ? (int32_t)lag : 0; /* a fresher sample becomes the reference */
        return accept(f, now_us, seq, src_ms, ok);
    }
    /* Fresher than the reference by more than the tolerance. */
    if (f->have_cand && now_us >= f->cand_rx_us && now_us - f->cand_rx_us < (mc_time_us_t)MC_FRESH_UNAMBIGUOUS_US &&
        mc_ts16_diff(src_ms, f->cand_src_ms) > 0) {
        const int64_t lag_c = lag_from(0, f->cand_rx_us, f->cand_src_ms, now_us, src_ms);
        if (lag_c >= -tol && lag_c <= tol) {
            f->lag_us = lag_c > 0 ? (int32_t)lag_c : 0; /* re-anchor on the candidate's timeline */
            return accept(f, now_us, seq, src_ms, ok);
        }
    }
    f->have_cand = true;
    f->cand_rx_us = now_us;
    f->cand_src_ms = src_ms;
    inc(&f->n_rejected);
    return MC_RX_TIME_DISCONTINUITY;
}

mc_rx_result_t mc_fresh_on_rx(mc_fresh_t *f, mc_time_us_t now_us, uint32_t session_id,
                              uint8_t clock_domain, uint8_t seq, uint16_t src_ms)
{
    if (clock_domain != f->expected_clock_domain) {
        inc(&f->n_rejected);
        return MC_RX_CLOCK_DOMAIN_MISMATCH;
    }
    if (!f->have_session || session_id != f->session_id) {
        const bool changed = f->have_session;
        f->have_session = true;
        f->session_id = session_id;
        f->have_sample = false;
        f->session_new = true;
        if (changed) inc(&f->n_session_changes);
        f->have_seen = true;
        f->seen_seq = seq;
        f->seen_src_ms = src_ms;
        f->floor_seq = seq;
        f->floor_rx_us = now_us;
        (void)accept_as_reference(f, now_us, seq, src_ms, MC_RX_ACCEPTED_FIRST);
        return changed ? MC_RX_SESSION_CHANGED : MC_RX_ACCEPTED_FIRST;
    }
    /* An exact re-delivery of the last frame seen never renews, accepted or not. */
    const bool same_as_seen = f->have_seen && seq == f->seen_seq && (!f->uses_source_time || src_ms == f->seen_src_ms);
    f->have_seen = true;
    f->seen_seq = seq;
    f->seen_src_ms = src_ms;
    if (same_as_seen) {
        inc(&f->n_dup);
        return MC_RX_DUPLICATE;
    }
    /* Ordering floor: newer than every frame seen within max_age. */
    const bool floor_active = now_us >= f->floor_rx_us && now_us - f->floor_rx_us <= (mc_time_us_t)f->max_age_us;
    if (floor_active) {
        const int8_t d = mc_seq8_diff(seq, f->floor_seq);
        if (d == 0) {
            inc(&f->n_dup);
            return MC_RX_DUPLICATE;
        }
        if (d < 0) {
            inc(&f->n_old);
            return MC_RX_REORDERED_OLD;
        }
    }
    f->floor_seq = seq;
    f->floor_rx_us = now_us;
    if (!f->have_sample) return accept_as_reference(f, now_us, seq, src_ms, MC_RX_ACCEPTED_FIRST);

    const bool stale = is_stale(f, now_us);
    const mc_rx_result_t ok = stale ? MC_RX_ACCEPTED_RESYNC : MC_RX_ACCEPTED_NEW;
    if (!f->uses_source_time) return accept(f, now_us, seq, src_ms, ok);

    if (stale) {
        /* After a gap longer than the freshness window the u8 sequence may
         * have wrapped, so beyond the ordering floor it cannot order frames.
         * The u16 ms source time is still unambiguous while the local gap is
         * < 30 s: there the same lag rule applies, which rejects a delayed
         * old frame or a re-sent cached sample. Beyond 30 s nothing can be
         * checked; the frame becomes the new reference as a RESYNC, which
         * never restores command authority by itself (see mc_core supervisor
         * rules). */
        const mc_time_us_t gap_us = now_us - f->last_new_rx_us;
        if (now_us < f->last_new_rx_us || gap_us >= (mc_time_us_t)MC_FRESH_UNAMBIGUOUS_US)
            return accept_as_reference(f, now_us, seq, src_ms, MC_RX_ACCEPTED_RESYNC);
    }
    if (mc_ts16_diff(src_ms, f->last_src_ms) <= 0) {
        /* Transport advanced but the sample did not: cached value re-sent. */
        inc(&f->n_repeat);
        return MC_RX_REPEATED_SAMPLE;
    }
    return judge(f, now_us, seq, src_ms, ok);
}

void mc_fresh_ack_session(mc_fresh_t *f)
{
    f->session_new = false;
}

void mc_fresh_on_integrity_fail(mc_fresh_t *f)
{
    inc(&f->n_integrity);
}

mc_validity_t mc_fresh_status(const mc_fresh_t *f, mc_time_us_t now_us)
{
    mc_validity_t v = MC_VAL_OK;
    if (!f->have_session || !f->have_sample) return MC_VAL_MISSING;
    if (is_stale(f, now_us)) v |= MC_VAL_STALE;
    if (f->session_new) v |= MC_VAL_SESSION_NEW;
    return v;
}

mc_time_us_t mc_time_extend(mc_time_us_t prev64, uint32_t now32)
{
    const uint32_t prev32 = (uint32_t)prev64;
    mc_time_us_t hi = prev64 & ~(mc_time_us_t)0xFFFFFFFFu;
    if (now32 < prev32) hi += ((mc_time_us_t)1u << 32);
    return hi | now32;
}

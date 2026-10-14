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
    f->have_sample = true;
    f->last_seq = seq;
    f->last_src_ms = src_ms;
    f->last_new_rx_us = now_us;
    inc(&f->n_new);
    return r;
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
        (void)accept(f, now_us, seq, src_ms, MC_RX_ACCEPTED_FIRST);
        return changed ? MC_RX_SESSION_CHANGED : MC_RX_ACCEPTED_FIRST;
    }
    if (!f->have_sample) return accept(f, now_us, seq, src_ms, MC_RX_ACCEPTED_FIRST);

    const bool stale = is_stale(f, now_us);
    const int8_t dseq = mc_seq8_diff(seq, f->last_seq);
    if (!f->uses_source_time) {
        if (dseq == 0) {
            inc(&f->n_dup);
            return MC_RX_DUPLICATE;
        }
        if (stale) return accept(f, now_us, seq, src_ms, MC_RX_ACCEPTED_RESYNC);
        if (dseq < 0) { inc(&f->n_old); return MC_RX_REORDERED_OLD; }
        for (int k = 1; k < dseq; k++) inc(&f->n_lost);
        return accept(f, now_us, seq, src_ms, MC_RX_ACCEPTED_NEW);
    }
    const int16_t dts = mc_ts16_diff(src_ms, f->last_src_ms);

    if (stale) {
        /* After a gap longer than the freshness window the u8 sequence may
         * have wrapped, so it cannot order frames. The u16 ms source time is
         * still unambiguous while the local gap is < 30 s: there the source
         * time must have advanced consistently with local time, which rejects
         * a delayed old frame or a re-sent cached sample. Beyond 30 s nothing
         * can be checked; the frame is accepted only as a RESYNC, which never
         * restores command authority by itself (see mc_core supervisor rules). */
        if (dseq == 0 && dts == 0) {
            inc(&f->n_dup);
            return MC_RX_DUPLICATE;
        }
        const mc_time_us_t gap_us = now_us - f->last_new_rx_us;
        if (now_us >= f->last_new_rx_us && gap_us < (mc_time_us_t)MC_FRESH_UNAMBIGUOUS_US) {
            if (dts <= 0) {
                inc(&f->n_repeat);
                return MC_RX_REPEATED_SAMPLE;
            }
            const int32_t skew = (int32_t)dts - (int32_t)(gap_us / 1000u);
            if (skew > (int32_t)f->max_time_skew_ms || skew < -(int32_t)f->max_time_skew_ms) {
                inc(&f->n_rejected);
                return MC_RX_TIME_DISCONTINUITY;
            }
        }
        return accept(f, now_us, seq, src_ms, MC_RX_ACCEPTED_RESYNC);
    }
    if (dseq == 0) {
        inc(&f->n_dup);
        return MC_RX_DUPLICATE;
    }
    if (dseq < 0) {
        inc(&f->n_old);
        return MC_RX_REORDERED_OLD;
    }
    if (dts <= 0) {
        /* Transport advanced but the sample did not: cached value re-sent. */
        f->last_seq = seq; /* keep ordering current, but do NOT renew validity */
        inc(&f->n_repeat);
        return MC_RX_REPEATED_SAMPLE;
    }
    /* Plausibility of source time advance against local time advance. */
    const mc_time_us_t local_adv_us = now_us - f->last_new_rx_us;
    const int32_t local_adv_ms = (int32_t)(local_adv_us / 1000u);
    const int32_t skew = (int32_t)dts - local_adv_ms;
    if (skew > (int32_t)f->max_time_skew_ms || skew < -(int32_t)f->max_time_skew_ms) {
        inc(&f->n_rejected);
        return MC_RX_TIME_DISCONTINUITY;
    }
    if (dseq > 1) {
        for (int k = 1; k < dseq; k++) inc(&f->n_lost);
    }
    return accept(f, now_us, seq, src_ms, MC_RX_ACCEPTED_NEW);
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

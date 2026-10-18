/* Freshness, sequencing and time-domain handling for received data.
 *
 * Every remotely produced signal carries:
 *   - a SOURCE SESSION id (changes when the source reboots/reconnects),
 *   - a CLOCK DOMAIN id   (whose clock the source timestamp is in),
 *   - a SEQUENCE counter  (u8, wraps; transport-level ordering),
 *   - a SOURCE TIMESTAMP  (u16 ms in the source clock domain, wraps every 65.5 s).
 * The receiver adds a LOCAL monotonic receive time (64-bit us, never wraps).
 *
 * Validity is renewed ONLY by a new sample: a sequence number newer than the
 * last accepted one AND a source timestamp that advanced. A duplicate frame,
 * a reordered (older) frame, or a new frame that carries the same cached
 * sample (timestamp did not advance) never renews validity.
 *
 * Ordering: a frame must carry a sequence number newer than the highest one
 * seen within the last max_age (accepted or not), so a frame re-sent from
 * earlier is REORDERED_OLD even after the tracker has gone stale; an exact
 * re-delivery of the last frame seen (same sequence and source time) is a
 * DUPLICATE at any time.
 *
 * Timing plausibility: the tracker keeps the LAG of the last accepted sample,
 * i.e. how much older it was on arrival than the reference (the
 * freshest-arriving accepted sample), allowing MC_FRESH_DRIFT_PPM of relative
 * clock drift. A new sample's lag is
 *     lag = lag_prev + (local advance) - (source advance) - drift allowance
 * which telescopes over accepted samples, so delay cannot accumulate in steps
 * that are each inside the tolerance.
 *   lag > max_time_skew:  older than the reference by more than the tolerance
 *                         (delayed or cached): rejected.
 *   |lag| <= max_time_skew: accepted; a fresher sample becomes the reference.
 *   lag < -max_time_skew: either the reference itself was a delayed sample
 *                         (e.g. the first one of a session) or the source
 *                         clock jumped. The sample is rejected and kept as a
 *                         candidate; the next sample that is consistent with
 *                         the candidate re-anchors the reference and is
 *                         accepted. One corrupted source time therefore cannot
 *                         move the reference, and a delayed reference costs
 *                         one frame, not a lock-out.
 * Re-anchoring only ever moves the reference towards FRESHER samples, so it
 * cannot make delayed or replayed data acceptable.
 *
 * Wraparound: u8 sequence and u16 timestamp use serial-number arithmetic
 * (RFC 1982 style signed difference). Ambiguity after long gaps is resolved
 * by requiring a resynchronisation when the tracker is already stale.
 */
#ifndef SEMMC_MC_FRESHNESS_H
#define SEMMC_MC_FRESHNESS_H

#include "semmc/mc_types.h"

/* u16 ms source time is unambiguous for gaps below half its period (32.7 s). */
#define MC_FRESH_UNAMBIGUOUS_US 30000000u
/* Relative drift allowed between source and local clocks, parts per million of
 * elapsed local time (2 %: covers an uncalibrated RC oscillator on either side). */
#define MC_FRESH_DRIFT_PPM 20000

typedef enum {
    MC_RX_ACCEPTED_NEW = 0,       /* renews validity */
    MC_RX_ACCEPTED_FIRST,         /* first sample of a session: renews, flags SESSION_NEW */
    MC_RX_ACCEPTED_RESYNC,        /* accepted after the tracker had gone stale */
    MC_RX_DUPLICATE,              /* same sequence number: ignored */
    MC_RX_REORDERED_OLD,          /* older sequence number: ignored */
    MC_RX_REPEATED_SAMPLE,        /* newer sequence but source time did not advance: ignored */
    MC_RX_SESSION_CHANGED,        /* new session id: history reset, sample accepted as FIRST */
    MC_RX_CLOCK_DOMAIN_MISMATCH,  /* rejected */
    MC_RX_TIME_DISCONTINUITY,     /* source time inconsistent with local time (delayed or jumped): rejected */
    MC_RX_INTEGRITY_FAIL          /* recorded by caller after CRC/format failure */
} mc_rx_result_t;

typedef struct {
    /* configuration */
    uint32_t max_age_us;          /* window after a NEW sample during which it is fresh */
    uint8_t expected_clock_domain;
    uint16_t max_time_skew_ms;    /* allowed |source advance - local advance| */
    bool uses_source_time;        /* false: message has no source timestamp (sequence only) */
    /* state */
    bool have_session;
    uint32_t session_id;
    bool have_sample;
    uint8_t last_seq;
    uint16_t last_src_ms;
    mc_time_us_t last_new_rx_us;  /* local receive time of the last NEW sample */
    int32_t lag_us;               /* lag of the last accepted sample behind the reference (>= 0) */
    bool have_cand;               /* rejected forward sample that may re-anchor the reference */
    mc_time_us_t cand_rx_us;
    uint16_t cand_src_ms;
    bool have_seen;               /* last frame seen, accepted or not: for exact duplicates */
    uint8_t seen_seq;
    uint16_t seen_src_ms;
    uint8_t floor_seq;            /* highest sequence seen within max_age (ordering floor) */
    mc_time_us_t floor_rx_us;
    bool session_new;             /* set on first sample of a session until cleared by consumer */
    /* counters (saturating) */
    uint16_t n_new, n_dup, n_old, n_repeat, n_lost, n_session_changes, n_rejected, n_integrity;
} mc_fresh_t;

void mc_fresh_init(mc_fresh_t *f, uint32_t max_age_us, uint8_t clock_domain, uint16_t max_time_skew_ms);
/* For messages without a source timestamp (e.g. declared bounds): ordering and
 * duplicate rejection use the sequence counter only. Such messages must not
 * carry measurements whose staleness matters. */
void mc_fresh_init_seq_only(mc_fresh_t *f, uint32_t max_age_us, uint8_t clock_domain);
/* Forget everything (e.g. on local reboot or explicit link reset). */
void mc_fresh_reset(mc_fresh_t *f);

mc_rx_result_t mc_fresh_on_rx(mc_fresh_t *f, mc_time_us_t now_us, uint32_t session_id,
                              uint8_t clock_domain, uint8_t seq, uint16_t src_ms);
void mc_fresh_on_integrity_fail(mc_fresh_t *f);
/* Consumer acknowledges a new session (after its own re-establishment logic). */
void mc_fresh_ack_session(mc_fresh_t *f);

/* MISSING / STALE / SESSION_NEW bits (0 = fresh). */
mc_validity_t mc_fresh_status(const mc_fresh_t *f, mc_time_us_t now_us);
static inline bool mc_rx_renews(mc_rx_result_t r)
{
    return r == MC_RX_ACCEPTED_NEW || r == MC_RX_ACCEPTED_FIRST || r == MC_RX_ACCEPTED_RESYNC ||
           r == MC_RX_SESSION_CHANGED;
}

/* Serial-number differences. */
static inline int8_t mc_seq8_diff(uint8_t a, uint8_t b) { return (int8_t)(uint8_t)(a - b); }
static inline int16_t mc_ts16_diff(uint16_t a, uint16_t b) { return (int16_t)(uint16_t)(a - b); }

/* Extend a free-running 32-bit hardware counter (us) to 64 bits. Correct as
 * long as it is called at least once per 2^32 us (71.6 min). */
mc_time_us_t mc_time_extend(mc_time_us_t prev64, uint32_t now32);

#endif /* SEMMC_MC_FRESHNESS_H */

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
 * Wraparound: u8 sequence and u16 timestamp use serial-number arithmetic
 * (RFC 1982 style signed difference). Ambiguity after long gaps is resolved
 * by requiring a resynchronisation when the tracker is already stale.
 */
#ifndef SEMMC_MC_FRESHNESS_H
#define SEMMC_MC_FRESHNESS_H

#include "semmc/mc_types.h"

/* u16 ms source time is unambiguous for gaps below half its period (32.7 s). */
#define MC_FRESH_UNAMBIGUOUS_US 30000000u

typedef enum {
    MC_RX_ACCEPTED_NEW = 0,       /* renews validity */
    MC_RX_ACCEPTED_FIRST,         /* first sample of a session: renews, flags SESSION_NEW */
    MC_RX_ACCEPTED_RESYNC,        /* accepted after the tracker had gone stale */
    MC_RX_DUPLICATE,              /* same sequence number: ignored */
    MC_RX_REORDERED_OLD,          /* older sequence number: ignored */
    MC_RX_REPEATED_SAMPLE,        /* newer sequence but source time did not advance: ignored */
    MC_RX_SESSION_CHANGED,        /* new session id: history reset, sample accepted as FIRST */
    MC_RX_CLOCK_DOMAIN_MISMATCH,  /* rejected */
    MC_RX_TIME_DISCONTINUITY,     /* source time jumped implausibly vs local time: rejected */
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

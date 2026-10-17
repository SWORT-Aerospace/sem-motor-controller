/* Evidence recorder for the telemetry unit (portable C11, research; host-tested only).
 *
 * The vehicle half of the record requests proposed in research/RECORDER.md. Inference stays at the
 * pit: the recorder only keeps recent records, answers bounded requests for them, and reports what it
 * could not keep. It never touches the motor controller: it is fed from the telemetry unit's logging
 * path (the same records the STLG log stores) and runs below every control and logging task.
 *
 *   bea_on_record    store one record (O(1), no allocation, never blocks)
 *   bea_on_request   validate a request (version, CRC, bounds, expiry, duplicate id) and accept or refuse it
 *   bea_poll         produce at most one response chunk, within the byte-rate limit
 *
 * Memory is supplied by the caller (fixed-capacity rings, one per channel). Times are the unit's
 * 32-bit microsecond clock, compared modulo 2^32, so they may wrap (every 71.6 minutes).
 *
 * Wire formats (little-endian), version 1.0:
 *   request, 32 bytes:  "BQ" | ver_major | ver_minor | request_id u32 | kind u8 | decimation u8 |
 *                       channel_mask u16 | t0_us u32 | t1_us_or_duration_ms u32 | expires_us u32 |
 *                       reserved u32 | crc32 u32 (zlib CRC-32 of bytes 0 to 27)
 *   response chunk:     "BR" | ver_major | ver_minor | request_id u32 | status u8 | chunk u8 | flags u8 |
 *                       n_records u8 | first_t_us u32 | last_t_us u32 | payload_len u16 | reserved u16 |
 *                       records | crc32 u32 (of every preceding byte)
 *   record (as STLG):   type u8 | body_len u8 | t_us u32 | body (the STLG record bodies, unchanged)
 */
#ifndef BEA_RECORDER_H
#define BEA_RECORDER_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define BEA_VERSION_MAJOR 1u
#define BEA_VERSION_MINOR 0u
#define BEA_MAX_CHANNELS 8u
#define BEA_MAX_ACTIVE 4u
#define BEA_RECENT_IDS 16u
#define BEA_MAX_BODY 14u                       /* largest STLG body kept (CAN: 3 + 8 bytes) */
#define BEA_REQUEST_BYTES 32u
#define BEA_CHUNK_HEADER_BYTES 24u
#define BEA_RECORD_HEADER_BYTES 6u

typedef enum {
    BEA_REQ_BUFFER = 1,                       /* records already held, in [t0, t1] */
    BEA_REQ_CAPTURE = 2,                      /* records of the next duration_ms, sent when it ends */
    BEA_REQ_STATUS = 3                        /* counters and clock state only */
} bea_kind_t;

typedef enum {
    BEA_ST_ACCEPTED = 0,
    BEA_ST_COMPLETE = 1,                      /* response: every requested record was still held */
    BEA_ST_PARTIAL = 2,                       /* response: the start of the window had been overwritten */
    BEA_ST_EMPTY = 3,                         /* response: no record in the window */
    BEA_ST_EXPIRED = 4,                       /* refused, or abandoned at its deadline */
    BEA_ST_DUPLICATE = 5,                     /* refused: this request id was seen recently */
    BEA_ST_BUSY = 6,                          /* refused: BEA_MAX_ACTIVE requests already active */
    BEA_ST_BAD_VERSION = 7,
    BEA_ST_BAD_CRC = 8,
    BEA_ST_BAD_REQUEST = 9,                   /* malformed: length, kind, empty mask, window, decimation */
    BEA_ST_TOO_LONG = 10                      /* refused: a capture longer than the rings can hold */
} bea_status_t;

typedef struct {
    uint8_t type;                             /* STLG record type */
    uint8_t len;
    uint32_t t_us;
    uint8_t body[BEA_MAX_BODY];
} bea_slot_t;

typedef struct {
    bea_slot_t *slot;                         /* caller-supplied storage */
    uint32_t capacity;
    uint32_t head;                            /* next write position */
    uint32_t count;
    uint32_t pin_count;                       /* active requests that pin this ring */
    uint32_t pin_from;                        /* oldest pinned absolute index while pin_count > 0 */
    uint32_t written;                         /* absolute index of the next record (monotonic) */
    uint32_t period_us;                       /* nominal record period, for capture sizing */
} bea_ring_t;

typedef struct {
    bool used;
    uint32_t id;
    uint8_t kind;
    uint8_t decimation;
    uint16_t mask;
    uint32_t t0_us, t1_us, expires_us;
    uint32_t cursor[BEA_MAX_CHANNELS];        /* absolute index of the next record to send, per channel */
    uint32_t first[BEA_MAX_CHANNELS];         /* absolute index of the window's first record (decimation phase) */
    uint8_t chunk;
    uint8_t status;                           /* COMPLETE or PARTIAL, decided at acceptance */
    bool ready;                               /* buffer: at once; capture: once t1 has passed */
    bool pinned;
} bea_active_t;

typedef struct {
    uint32_t records_in, overwritten, dropped_pinned, dropped_bad_channel;
    uint32_t requests_accepted, refused_duplicate, refused_expired, refused_busy, refused_version, refused_crc,
        refused_bad, refused_too_long, abandoned_expired;
    uint32_t chunks_sent, bytes_sent, rate_deferred;
} bea_counters_t;

typedef struct {
    uint32_t rate_bytes_per_s;                /* average uplink share for responses */
    uint32_t burst_bytes;                     /* token-bucket depth */
    uint32_t max_chunk_bytes;                 /* largest chunk bea_poll writes */
} bea_config_t;

typedef struct {
    bea_ring_t ring[BEA_MAX_CHANNELS];
    uint8_t n_channels;
    bea_active_t active[BEA_MAX_ACTIVE];
    uint32_t recent[BEA_RECENT_IDS];
    uint8_t recent_n, recent_next;
    bea_config_t cfg;
    uint32_t tokens;
    uint32_t last_refill_us;
    bool refill_started;
    bea_counters_t c;
} bea_recorder_t;

/* rings[i] supplies storage for channel i; period_us[i] is that channel's nominal record period. */
void bea_init(bea_recorder_t *r, const bea_config_t *cfg, uint8_t n_channels, bea_slot_t *const *storage,
              const uint32_t *capacity, const uint32_t *period_us);
void bea_on_record(bea_recorder_t *r, uint8_t channel, uint8_t type, uint32_t t_us, const uint8_t *body,
                   uint8_t len);
bea_status_t bea_on_request(bea_recorder_t *r, const uint8_t *msg, size_t len, uint32_t now_us);
/* Writes at most one chunk into out (capacity cap) and returns its length, or 0 if nothing is due or
 * the rate limit defers it. */
size_t bea_poll(bea_recorder_t *r, uint32_t now_us, uint8_t *out, size_t cap);
size_t bea_encode_request(uint8_t out[BEA_REQUEST_BYTES], uint32_t id, bea_kind_t kind, uint16_t mask,
                          uint32_t t0_us, uint32_t t1_or_duration, uint32_t expires_us, uint8_t decimation);

/* Wrap-safe time order: true if a is before b. */
static inline bool bea_before(uint32_t a, uint32_t b) { return (int32_t)(a - b) < 0; }

#endif

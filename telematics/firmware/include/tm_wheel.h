/* Wheel Hall-switch edges: accumulation in the capture interrupt, one record per channel per period.
 * The same logic as EdgeAccumulator in host/telematics/wheel.py; tests/telematics/test_firmware_host.py
 * runs both on the same edges and compares the records byte for byte. */
#ifndef TM_WHEEL_H
#define TM_WHEEL_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define TM_WHEEL_FLAG_LINE_HIGH 0x01u
#define TM_WHEEL_FLAG_OVERRUN 0x02u
#define TM_WHEEL_FLAG_HEARTBEAT 0x04u
#define TM_WHEEL_BODY_BYTES 16u

typedef struct {
    uint32_t n;           /* edges since the last record */
    uint64_t t_first;
    uint64_t t_last;
    uint32_t total;       /* edges since start, wraps */
    uint32_t lost;        /* edges lost to capture overrun since the last record */
    bool overrun;
    uint16_t rec_seq;
} tm_wheel_acc_t;

typedef struct {
    uint64_t t_us;        /* last edge, or the evaluation time of a heartbeat */
    uint8_t channel;
    uint8_t flags;
    uint16_t n;
    uint32_t span_us;
    uint32_t total;
    uint16_t rec_seq;
    uint16_t lost;
} tm_wheel_rec_t;

/* Capture interrupt: one edge at t_us. Constant time, no loop. */
void tm_wheel_edge(tm_wheel_acc_t *a, uint64_t t_us);
/* Capture interrupt: the overrun flag was set, at least one edge was lost. */
void tm_wheel_overrun(tm_wheel_acc_t *a);
/* Record task (capture interrupt masked by the caller): take the accumulated edges as one record. */
void tm_wheel_take(tm_wheel_acc_t *a, uint8_t channel, uint64_t now_us, bool line_high, tm_wheel_rec_t *out);
/* STLG WHEEL_EDGES body (<BBHIIHH, 16 bytes). */
size_t tm_wheel_body(const tm_wheel_rec_t *r, uint8_t *out);

/* Plausibility across channels; the same rule, in integers, as classify() in host/telematics/wheel.py.
 *
 * The line level cannot prove standstill. A magnet under the sensor, a signal shorted to ground and a failed
 * sensor all hold an open-collector line at its active (low) level; a wheel stopped between magnets, an open
 * wire, an unpowered sensor and a line shorted high all leave it at the inactive (pulled-up) level. So a
 * channel without edges is only "silent" (no evidence either way) unless another channel shows the vehicle
 * moving: then it is suspect, and its line level says which kind of fault fits.
 *
 *   N  never produced an edge, no channel contradicts it
 *   M  moving: an edge within max(3 of its own recent periods, 250 ms)
 *   S  silent: no edge recently, no channel contradicts it (stopped or failed: unknown)
 *   A  suspect, line at the active level: stuck active (short to ground, failed sensor, magnet stuck)
 *   I  suspect, line at the inactive level: stuck inactive or disconnected (open wire, no supply, shorted high)
 * Suspect: silent for at least 8 periods of a moving channel and at least 1 s. */
#define TM_WHEEL_MOVING_PERIODS 3u
#define TM_WHEEL_MOVING_MIN_US 250000u
#define TM_WHEEL_SUSPECT_PERIODS 8u
#define TM_WHEEL_SUSPECT_MIN_US 1000000u
#define TM_WHEEL_MAX_PERIOD_US 2000000u   /* a longer interval between edges is not a period */

typedef enum {
    TM_WHEEL_NEVER = 'N',
    TM_WHEEL_MOVING = 'M',
    TM_WHEEL_SILENT = 'S',
    TM_WHEEL_SUSPECT_ACTIVE = 'A',
    TM_WHEEL_SUSPECT_INACTIVE = 'I',
} tm_wheel_state_t;

typedef struct {
    uint64_t since_us;    /* latest edge, or the start of tracking before the first edge */
    uint32_t period_us;   /* latest edge period; 0: none */
    bool ever;            /* at least one edge since start */
    bool line_high;       /* line level at the latest record */
} tm_wheel_track_t;

void tm_wheel_track_init(tm_wheel_track_t *t, uint64_t t0_us);
/* Update from the channel's record (any record, heartbeat included). */
void tm_wheel_track_update(tm_wheel_track_t *t, const tm_wheel_rec_t *r);
/* State of channel ch at now_us; *ref (may be null) gets the moving channel that makes it suspect, or -1. */
tm_wheel_state_t tm_wheel_classify(const tm_wheel_track_t *tr, size_t n, size_t ch, uint64_t now_us,
                                   bool active_high, int *ref);

#endif

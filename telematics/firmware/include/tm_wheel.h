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

#endif

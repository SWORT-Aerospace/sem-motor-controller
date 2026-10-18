/* Bounded record queue between the producers (record task, CAN drain, sensor drivers; all in the main
 * loop) and the log writer. A full queue drops the new record and counts it; nothing waits. */
#ifndef TM_QUEUE_H
#define TM_QUEUE_H

#include <stdbool.h>
#include <stdint.h>

#include "tm_config.h"

typedef struct {
    uint64_t t_us;
    uint8_t type;
    uint8_t len;
    uint8_t body[TM_REC_MAX];
} tm_rec_t;

typedef struct {
    tm_rec_t r[TM_QUEUE_LEN];
    uint32_t head;          /* next to write */
    uint32_t tail;          /* next to read */
    uint32_t high_water;
    uint32_t dropped;
} tm_queue_t;

void tm_queue_init(tm_queue_t *q);
uint32_t tm_queue_count(const tm_queue_t *q);
/* false (and counted) when full or the body is too long */
bool tm_queue_push(tm_queue_t *q, uint64_t t_us, uint8_t type, const uint8_t *body, uint32_t len);
/* oldest record, or 0 when empty; tm_queue_pop() removes it */
const tm_rec_t *tm_queue_peek(const tm_queue_t *q);
void tm_queue_pop(tm_queue_t *q);

/* Received CAN frames: written by the FDCAN interrupt, read by the main loop (one producer, one
 * consumer; indices are written by one side each). A full ring drops the frame and counts it. */
typedef struct {
    uint64_t t_us;
    uint32_t id_flags;      /* id in bits 0-28; bit 31 extended, bit 30 FD, bit 29 bit-rate switch */
    uint8_t len;
    uint8_t data[64];
} tm_can_frame_t;

typedef struct {
    tm_can_frame_t f[TM_CAN_RING_LEN];
    volatile uint32_t head;
    volatile uint32_t tail;
    volatile uint32_t overrun;
} tm_can_ring_t;

bool tm_can_ring_push(tm_can_ring_t *r, const tm_can_frame_t *f);   /* interrupt */
bool tm_can_ring_pop(tm_can_ring_t *r, tm_can_frame_t *out);        /* main loop */

#endif

#include "tm_queue.h"

#include <string.h>

#define MASK (TM_QUEUE_LEN - 1u)
#define CMASK (TM_CAN_RING_LEN - 1u)

void tm_queue_init(tm_queue_t *q)
{
    q->head = q->tail = 0u;
    q->high_water = q->dropped = 0u;
}

uint32_t tm_queue_count(const tm_queue_t *q) { return q->head - q->tail; }

bool tm_queue_push(tm_queue_t *q, uint64_t t_us, uint8_t type, const uint8_t *body, uint32_t len)
{
    if (tm_queue_count(q) >= TM_QUEUE_LEN || len > TM_REC_MAX) {
        q->dropped++;
        return false;
    }
    tm_rec_t *r = &q->r[q->head & MASK];
    r->t_us = t_us;
    r->type = type;
    r->len = (uint8_t)len;
    if (len) memcpy(r->body, body, len);
    q->head++;
    if (tm_queue_count(q) > q->high_water) q->high_water = tm_queue_count(q);
    return true;
}

const tm_rec_t *tm_queue_peek(const tm_queue_t *q) { return tm_queue_count(q) ? &q->r[q->tail & MASK] : 0; }

void tm_queue_pop(tm_queue_t *q)
{
    if (tm_queue_count(q)) q->tail++;
}

bool tm_can_ring_push(tm_can_ring_t *r, const tm_can_frame_t *f)
{
    uint32_t h = r->head;
    if (h - r->tail >= TM_CAN_RING_LEN) {
        r->overrun++;
        return false;
    }
    r->f[h & CMASK] = *f;
    __atomic_thread_fence(__ATOMIC_RELEASE);     /* the frame before the index */
    r->head = h + 1u;
    return true;
}

bool tm_can_ring_pop(tm_can_ring_t *r, tm_can_frame_t *out)
{
    uint32_t t = r->tail;
    if (r->head == t) return false;
    __atomic_thread_fence(__ATOMIC_ACQUIRE);
    *out = r->f[t & CMASK];
    __atomic_thread_fence(__ATOMIC_RELEASE);     /* read the frame before freeing its slot */
    r->tail = t + 1u;
    return true;
}

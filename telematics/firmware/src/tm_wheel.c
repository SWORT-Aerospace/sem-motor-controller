#include "tm_wheel.h"

#include "tm_le.h"

void tm_wheel_edge(tm_wheel_acc_t *a, uint64_t t_us)
{
    if (a->n == 0u) a->t_first = t_us;
    a->t_last = t_us;
    a->n++;
    a->total++;
}

void tm_wheel_overrun(tm_wheel_acc_t *a)
{
    a->lost++;
    a->overrun = true;
}

void tm_wheel_take(tm_wheel_acc_t *a, uint8_t channel, uint64_t now_us, bool line_high, tm_wheel_rec_t *out)
{
    uint8_t flags = (uint8_t)((line_high ? TM_WHEEL_FLAG_LINE_HIGH : 0u) | (a->overrun ? TM_WHEEL_FLAG_OVERRUN : 0u));
    out->channel = channel;
    out->total = a->total;
    out->rec_seq = a->rec_seq;
    out->lost = (uint16_t)(a->lost > 0xFFFFu ? 0xFFFFu : a->lost);
    if (a->n != 0u) {
        uint64_t span = a->t_last - a->t_first;
        out->t_us = a->t_last;
        out->n = (uint16_t)(a->n > 0xFFFFu ? 0xFFFFu : a->n);
        out->span_us = (uint32_t)(span > 0xFFFFFFFFu ? 0xFFFFFFFFu : span);
        out->flags = flags;
    } else {
        out->t_us = now_us;
        out->n = 0u;
        out->span_us = 0u;
        out->flags = (uint8_t)(flags | TM_WHEEL_FLAG_HEARTBEAT);
    }
    a->n = 0u;
    a->lost = 0u;
    a->overrun = false;
    a->rec_seq++;
}

size_t tm_wheel_body(const tm_wheel_rec_t *r, uint8_t *out)
{
    out[0] = r->channel;
    out[1] = r->flags;
    tm_le16(out + 2, r->n);
    tm_le32(out + 4, r->span_us);
    tm_le32(out + 8, r->total);
    tm_le16(out + 12, r->rec_seq);
    tm_le16(out + 14, r->lost);
    return TM_WHEEL_BODY_BYTES;
}

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

void tm_wheel_track_init(tm_wheel_track_t *t, uint64_t t0_us)
{
    t->since_us = t0_us;
    t->period_us = 0u;
    t->ever = false;
    t->line_high = true;
}

void tm_wheel_track_update(tm_wheel_track_t *t, const tm_wheel_rec_t *r)
{
    t->line_high = (r->flags & TM_WHEEL_FLAG_LINE_HIGH) != 0u;
    if (r->n == 0u) return;
    uint64_t p = 0u;
    if (r->n >= 2u && r->span_us > 0u)
        p = r->span_us / (uint32_t)(r->n - 1u);
    else if (t->ever && r->t_us > t->since_us)
        p = r->t_us - t->since_us;
    t->period_us = p > TM_WHEEL_MAX_PERIOD_US ? 0u : (uint32_t)p;
    t->since_us = r->t_us;
    t->ever = true;
}

static bool moving(const tm_wheel_track_t *t, uint64_t now_us)
{
    if (!t->ever || t->period_us == 0u) return false;
    if (now_us <= t->since_us) return true;
    uint64_t win = (uint64_t)TM_WHEEL_MOVING_PERIODS * t->period_us;
    if (win < TM_WHEEL_MOVING_MIN_US) win = TM_WHEEL_MOVING_MIN_US;
    return now_us - t->since_us <= win;
}

tm_wheel_state_t tm_wheel_classify(const tm_wheel_track_t *tr, size_t n, size_t ch, uint64_t now_us,
                                   bool active_high, int *ref)
{
    if (ref) *ref = -1;
    const tm_wheel_track_t *c = &tr[ch];
    if (moving(c, now_us)) return TM_WHEEL_MOVING;
    uint64_t silence = now_us > c->since_us ? now_us - c->since_us : 0u;
    for (size_t k = 0; k < n; k++) {
        if (k == ch || !moving(&tr[k], now_us) || tr[k].period_us == 0u) continue;
        if (silence >= (uint64_t)TM_WHEEL_SUSPECT_PERIODS * tr[k].period_us && silence >= TM_WHEEL_SUSPECT_MIN_US) {
            if (ref) *ref = (int)k;
            return c->line_high == active_high ? TM_WHEEL_SUSPECT_ACTIVE : TM_WHEEL_SUSPECT_INACTIVE;
        }
    }
    return c->ever ? TM_WHEEL_SILENT : TM_WHEEL_NEVER;
}

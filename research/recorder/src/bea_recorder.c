/* Evidence recorder: fixed-capacity rings, bounded requests, rate-limited responses. See bea_recorder.h. */
#include "bea_recorder.h"

#include <string.h>

#include "semmc/mc_crc.h"

static uint32_t rd32(const uint8_t *p) { return (uint32_t)p[0] | ((uint32_t)p[1] << 8) | ((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 24); }
static uint16_t rd16(const uint8_t *p) { return (uint16_t)(p[0] | (p[1] << 8)); }
static void wr32(uint8_t *p, uint32_t v) { p[0] = (uint8_t)v; p[1] = (uint8_t)(v >> 8); p[2] = (uint8_t)(v >> 16); p[3] = (uint8_t)(v >> 24); }
static void wr16(uint8_t *p, uint16_t v) { p[0] = (uint8_t)v; p[1] = (uint8_t)(v >> 8); }

static uint32_t oldest_index(const bea_ring_t *g) { return g->written - g->count; }
static const bea_slot_t *at(const bea_ring_t *g, uint32_t abs_index) { return &g->slot[abs_index % g->capacity]; }

void bea_init(bea_recorder_t *r, const bea_config_t *cfg, uint8_t n_channels, bea_slot_t *const *storage,
              const uint32_t *capacity, const uint32_t *period_us)
{
    memset(r, 0, sizeof *r);
    r->cfg = *cfg;
    r->n_channels = n_channels > BEA_MAX_CHANNELS ? (uint8_t)BEA_MAX_CHANNELS : n_channels;
    for (uint8_t i = 0; i < r->n_channels; i++) {
        r->ring[i].slot = storage[i];
        r->ring[i].capacity = capacity[i];
        r->ring[i].period_us = period_us[i];
    }
    r->tokens = cfg->burst_bytes;
}

void bea_on_record(bea_recorder_t *r, uint8_t channel, uint8_t type, uint32_t t_us, const uint8_t *body, uint8_t len)
{
    if (channel >= r->n_channels || len > BEA_MAX_BODY || r->ring[channel].capacity == 0u) {
        r->c.dropped_bad_channel++;
        return;
    }
    bea_ring_t *g = &r->ring[channel];
    if (g->count == g->capacity) {
        if (g->pin_count > 0u && !bea_before(oldest_index(g), g->pin_from) ) {
            r->c.dropped_pinned++;            /* the oldest record is still owed to a request: keep it */
            return;
        }
        r->c.overwritten++;
    } else {
        g->count++;
    }
    bea_slot_t *s = &g->slot[g->head];
    s->type = type;
    s->len = len;
    s->t_us = t_us;
    memcpy(s->body, body, len);
    g->head = (g->head + 1u) % g->capacity;
    g->written++;
    r->c.records_in++;
}

/* First absolute index whose time is not before t (binary search: records are in receipt order). */
static uint32_t first_at_or_after(const bea_ring_t *g, uint32_t t_us)
{
    uint32_t lo = 0u, hi = g->count;
    const uint32_t base = oldest_index(g);
    while (lo < hi) {
        const uint32_t mid = lo + (hi - lo) / 2u;
        if (bea_before(at(g, base + mid)->t_us, t_us)) lo = mid + 1u; else hi = mid;
    }
    return base + lo;
}

static void repin(bea_recorder_t *r)
{
    for (uint8_t ch = 0; ch < r->n_channels; ch++) {
        bea_ring_t *g = &r->ring[ch];
        g->pin_count = 0u;
        for (uint8_t k = 0; k < BEA_MAX_ACTIVE; k++) {
            const bea_active_t *a = &r->active[k];
            if (!a->used || !a->pinned || !(a->mask & (1u << ch))) continue;
            if (g->pin_count == 0u || bea_before(a->cursor[ch], g->pin_from)) g->pin_from = a->cursor[ch];
            g->pin_count++;
        }
    }
}

static bool seen(const bea_recorder_t *r, uint32_t id)
{
    for (uint8_t i = 0; i < r->recent_n; i++)
        if (r->recent[i] == id) return true;
    return false;
}

bea_status_t bea_on_request(bea_recorder_t *r, const uint8_t *msg, size_t len, uint32_t now_us)
{
    if (len != BEA_REQUEST_BYTES || msg[0] != 'B' || msg[1] != 'Q') { r->c.refused_bad++; return BEA_ST_BAD_REQUEST; }
    if (mc_crc32(msg, 28u) != rd32(msg + 28)) { r->c.refused_crc++; return BEA_ST_BAD_CRC; }
    if (msg[2] != BEA_VERSION_MAJOR) { r->c.refused_version++; return BEA_ST_BAD_VERSION; }   /* minor: compatible */
    const uint32_t id = rd32(msg + 4);
    const uint8_t kind = msg[8], dec = msg[9];
    const uint16_t mask = rd16(msg + 10);
    const uint32_t t0 = rd32(msg + 12), t1d = rd32(msg + 16), expires = rd32(msg + 20);
    if (seen(r, id)) { r->c.refused_duplicate++; return BEA_ST_DUPLICATE; }
    if (!bea_before(now_us, expires)) { r->c.refused_expired++; return BEA_ST_EXPIRED; }
    const uint16_t valid_mask = (uint16_t)((1u << r->n_channels) - 1u);
    if ((kind != BEA_REQ_BUFFER && kind != BEA_REQ_CAPTURE && kind != BEA_REQ_STATUS) ||
        (kind != BEA_REQ_STATUS && (mask == 0u || (mask & (uint16_t)~valid_mask) || dec == 0u)) ||
        (kind == BEA_REQ_BUFFER && !bea_before(t0, t1d)) || (kind == BEA_REQ_CAPTURE && (t1d == 0u || t1d > 600000u))) {
        r->c.refused_bad++;
        return BEA_ST_BAD_REQUEST;
    }
    if (kind == BEA_REQ_CAPTURE) {
        for (uint8_t ch = 0; ch < r->n_channels; ch++) {
            const bea_ring_t *g = &r->ring[ch];
            if ((mask & (1u << ch)) && g->period_us && (uint64_t)t1d * 1000u / g->period_us + 1u > g->capacity) {
                r->c.refused_too_long++;
                return BEA_ST_TOO_LONG;
            }
        }
    }
    bea_active_t *a = NULL;
    for (uint8_t k = 0; k < BEA_MAX_ACTIVE && !a; k++)
        if (!r->active[k].used) a = &r->active[k];
    if (!a) { r->c.refused_busy++; return BEA_ST_BUSY; }
    memset(a, 0, sizeof *a);
    a->used = true;
    a->id = id;
    a->kind = kind;
    a->decimation = dec ? dec : 1u;
    a->mask = mask;
    a->expires_us = expires;
    a->status = BEA_ST_COMPLETE;
    if (kind == BEA_REQ_BUFFER) {
        a->t0_us = t0;
        a->t1_us = bea_before(now_us, t1d) ? now_us : t1d;           /* nothing from after now */
        for (uint8_t ch = 0; ch < r->n_channels; ch++) {
            if (!(mask & (1u << ch))) continue;
            const bea_ring_t *g = &r->ring[ch];
            a->cursor[ch] = a->first[ch] = first_at_or_after(g, t0);
            const bool lost_before = g->written != g->count;              /* the ring has overwritten records */
            if (lost_before && g->count && bea_before(t0, at(g, oldest_index(g))->t_us)) a->status = BEA_ST_PARTIAL;
        }
        a->pinned = true;
        a->ready = true;
    } else if (kind == BEA_REQ_CAPTURE) {
        a->t0_us = now_us;
        a->t1_us = now_us + t1d * 1000u;
        for (uint8_t ch = 0; ch < r->n_channels; ch++)
            if (mask & (1u << ch)) a->cursor[ch] = a->first[ch] = r->ring[ch].written;
        a->pinned = true;
    } else {
        a->ready = true;
    }
    r->recent[r->recent_next] = id;
    r->recent_next = (uint8_t)((r->recent_next + 1u) % BEA_RECENT_IDS);
    if (r->recent_n < BEA_RECENT_IDS) r->recent_n++;
    repin(r);
    r->c.requests_accepted++;
    return BEA_ST_ACCEPTED;
}

size_t bea_encode_request(uint8_t out[BEA_REQUEST_BYTES], uint32_t id, bea_kind_t kind, uint16_t mask,
                          uint32_t t0_us, uint32_t t1_or_duration, uint32_t expires_us, uint8_t decimation)
{
    memset(out, 0, BEA_REQUEST_BYTES);
    out[0] = 'B'; out[1] = 'Q'; out[2] = BEA_VERSION_MAJOR; out[3] = BEA_VERSION_MINOR;
    wr32(out + 4, id);
    out[8] = (uint8_t)kind;
    out[9] = decimation;
    wr16(out + 10, mask);
    wr32(out + 12, t0_us);
    wr32(out + 16, t1_or_duration);
    wr32(out + 20, expires_us);
    wr32(out + 28, mc_crc32(out, 28u));
    return BEA_REQUEST_BYTES;
}

static void finish(bea_recorder_t *r, bea_active_t *a)
{
    a->used = false;
    repin(r);
}

static size_t header(uint8_t *out, const bea_active_t *a, uint8_t status, uint8_t flags)
{
    out[0] = 'B'; out[1] = 'R'; out[2] = BEA_VERSION_MAJOR; out[3] = BEA_VERSION_MINOR;
    wr32(out + 4, a->id);
    out[8] = status;
    out[9] = a->chunk;
    out[10] = flags;
    out[11] = 0u;
    memset(out + 12, 0, 12);
    return BEA_CHUNK_HEADER_BYTES;
}

static void refill(bea_recorder_t *r, uint32_t now_us)
{
    if (!r->refill_started) { r->refill_started = true; r->last_refill_us = now_us; return; }
    const uint32_t dt = now_us - r->last_refill_us;
    const uint64_t add = (uint64_t)dt * r->cfg.rate_bytes_per_s / 1000000u;
    if (add == 0u) return;                                       /* keep the remainder for the next call */
    const uint64_t t = (uint64_t)r->tokens + add;
    r->tokens = t > r->cfg.burst_bytes ? r->cfg.burst_bytes : (uint32_t)t;
    r->last_refill_us = now_us;
}

size_t bea_poll(bea_recorder_t *r, uint32_t now_us, uint8_t *out, size_t cap)
{
    refill(r, now_us);
    size_t limit = cap < r->cfg.max_chunk_bytes ? cap : r->cfg.max_chunk_bytes;
    if (limit > r->tokens) limit = r->tokens;                       /* a chunk never exceeds the tokens held */
    if (limit < BEA_CHUNK_HEADER_BYTES + 4u) {
        for (uint8_t k = 0; k < BEA_MAX_ACTIVE; k++)
            if (r->active[k].used) { r->c.rate_deferred++; break; }
        return 0u;
    }
    for (uint8_t k = 0; k < BEA_MAX_ACTIVE; k++) {
        bea_active_t *a = &r->active[k];
        if (!a->used) continue;
        if (!bea_before(now_us, a->expires_us)) {                   /* deadline: report it and stop */
            size_t n = header(out, a, BEA_ST_EXPIRED, 1u);
            wr32(out + n, mc_crc32(out, n));
            n += 4u;
            r->c.abandoned_expired++;
            finish(r, a);
            return n;
        }
        if (a->kind == BEA_REQ_CAPTURE && !a->ready && !bea_before(now_us, a->t1_us)) a->ready = true;
    }
    for (uint8_t k = 0; k < BEA_MAX_ACTIVE; k++) {
        bea_active_t *a = &r->active[k];
        if (!a->used || !a->ready) continue;
        size_t n = BEA_CHUNK_HEADER_BYTES;
        uint8_t nrec = 0u;
        uint32_t saved[BEA_MAX_CHANNELS];
        memcpy(saved, a->cursor, sizeof saved);
        bool done = true;
        uint32_t first_t = 0u, last_t = 0u;
        if (a->kind == BEA_REQ_STATUS) {
            const uint32_t *cv = (const uint32_t *)(const void *)&r->c;
            const size_t words = sizeof r->c / sizeof(uint32_t);
            if (n + 4u * words + 4u > limit) { r->c.rate_deferred++; return 0u; }
            for (size_t i = 0; i < words; i++) wr32(out + n + 4u * i, cv[i]);
            n += 4u * words;
        } else {
            for (uint8_t ch = 0; ch < r->n_channels; ch++) {
                if (!(a->mask & (1u << ch))) continue;
                const bea_ring_t *g = &r->ring[ch];
                while (bea_before(a->cursor[ch], g->written)) {
                    const bea_slot_t *s = at(g, a->cursor[ch]);
                    if (bea_before(a->t1_us, s->t_us)) { a->cursor[ch] = g->written; break; }   /* past the window */
                    const bool keep = ((a->cursor[ch] - a->first[ch]) % a->decimation) == 0u;
                    if (keep) {
                        if (n + BEA_RECORD_HEADER_BYTES + s->len + 4u > limit || nrec == 255u) { done = false; break; }
                        out[n] = s->type; out[n + 1] = s->len; wr32(out + n + 2, s->t_us);
                        memcpy(out + n + BEA_RECORD_HEADER_BYTES, s->body, s->len);
                        n += BEA_RECORD_HEADER_BYTES + s->len;
                        if (nrec == 0u) first_t = s->t_us;
                        last_t = s->t_us;
                        nrec++;
                    }
                    a->cursor[ch]++;
                }
                if (!done) break;
            }
        }
        const size_t total = n + 4u;
        if (total > r->tokens || (!done && nrec == 0u)) {           /* not even one record fits: try later */
            memcpy(a->cursor, saved, sizeof saved);
            r->c.rate_deferred++;
            return 0u;
        }
        const uint8_t status = (a->kind != BEA_REQ_STATUS && a->chunk == 0u && done && nrec == 0u) ? BEA_ST_EMPTY : a->status;
        header(out, a, status, done ? 1u : 0u);
        out[11] = nrec;
        wr32(out + 12, first_t);
        wr32(out + 16, last_t);
        wr16(out + 20, (uint16_t)(n - BEA_CHUNK_HEADER_BYTES));
        wr32(out + n, mc_crc32(out, n));
        r->tokens -= (uint32_t)total;
        r->c.chunks_sent++;
        r->c.bytes_sent += (uint32_t)total;
        a->chunk++;
        if (done) finish(r, a); else repin(r);                       /* sent records may now be overwritten */
        return total;
    }
    return 0u;
}

#include "tm_live.h"

#include <math.h>
#include <stdarg.h>
#include <stdio.h>
#include <string.h>

#include "tm_le.h"

/* validity codes: measurement.VALIDITY in host/telematics/measurement.py, then the live summary's own two */
enum { TM_LQ_VALID, TM_LQ_UNVERIFIED, TM_LQ_INVALID, TM_LQ_OUT_OF_RANGE, TM_LQ_NO_EVIDENCE, TM_LQ_MISSING };
static const char *const QNAME[] = {"valid", "unverified", "invalid", "out_of_range", "no_evidence", "missing"};

/* The unit's own signals in the registry (origin telematics): id pattern, range, stale time. */
static const struct {
    const char *id;
    float lo, hi;
    uint32_t stale_ms;
} REG[] = {
    {"wheel.*.speed", 0.0f, 60.0f, 300u},       {"wheel.*.distance", 0.0f, 10000000.0f, 1000u},
    {"gnss.speed", 0.0f, 60.0f, 500u},          {"gnss.speed_acc", 0.0f, 100.0f, 500u},
    {"gnss.num_sv", 0.0f, 255.0f, 500u},        {"imu.ax", -160.0f, 160.0f, 100u},
    {"imu.gz", -35.0f, 35.0f, 100u},            {"temp.*", -55.0f, 200.0f, 3000u},
    {"batt.voltage", 0.0f, 100.0f, 300u},       {"batt.current", -400.0f, 400.0f, 300u},
};
enum { R_WSPEED, R_WDIST, R_GSPEED, R_GACC, R_GSV, R_AX, R_GZ, R_TEMP, R_BV, R_BA };

static const struct {
    uint8_t id;
    const char *name;
} CNAME[] = {
    {TM_CNT_RX_FRAMES, "rx_frames"},
    {TM_CNT_LOG_RECORDS, "log_records"},
    {TM_CNT_LOG_DROPPED_QUEUE, "log_dropped_queue"},
    {TM_CNT_LOG_DROPPED_STORAGE, "log_dropped_storage"},
    {TM_CNT_QUEUE_HIGH_WATER, "queue_high_water"},
    {TM_CNT_UPLINK_SENT, "uplink_sent"},
    {TM_CNT_UPLINK_DROPPED, "uplink_dropped"},
    {TM_CNT_UPLINK_QUEUE_HIGH_WATER, "uplink_queue_high_water"},
    {TM_CNT_WHEEL_EDGES_LOST, "wheel_edges_lost"},
    {TM_CNT_WHEEL_RECORDS, "wheel_records"},
    {TM_CNT_STORAGE_BLOCKS_WRITTEN, "storage_blocks_written"},
    {TM_CNT_STORAGE_STALL_EVENTS, "storage_stall_events"},
    {TM_CNT_CAN_RX_OVERRUN, "can_rx_overrun"},
    {TM_CNT_CAN_BUS_ERRORS, "can_bus_errors"},
    {TM_CNT_LOG_QUEUE_CAPACITY, "log_queue_capacity"},
    {TM_CNT_UPLINK_QUEUE_CAPACITY, "uplink_queue_capacity"},
    {TM_CNT_STORAGE_WRITE_ERRORS, "storage_write_errors"},
    {TM_CNT_UPTIME_S, "uptime_s"},
    {TM_CNT_WHEEL_SUSPECT_ACTIVE, "wheel_suspect_active"},
    {TM_CNT_WHEEL_SUSPECT_INACTIVE, "wheel_suspect_inactive"},
    {TM_CNT_LOG_THINNED, "log_thinned"},
    {TM_CNT_CAN_NOT_LOGGED, "can_not_logged"},
    {TM_CNT_GNSS_FRAMES, "gnss_frames"},
    {TM_CNT_GNSS_CHECKSUM_ERRORS, "gnss_checksum_errors"},
    {TM_CNT_GNSS_RX_OVERRUN, "gnss_rx_overrun"},
    {TM_CNT_PPS_EDGES, "pps_edges"},
    {TM_CNT_PPS_UNLABELLED, "pps_unlabelled"},
};

const char *tm_counter_name(uint8_t id)
{
    for (size_t i = 0; i < sizeof CNAME / sizeof CNAME[0]; i++)
        if (CNAME[i].id == id) return CNAME[i].name;
    return 0;
}

/* ---------------------------------------------------------------- entries */
static int8_t add(tm_live_t *l, uint8_t reg, const char *id)
{
    if (l->n >= TM_LIVE_SIGNALS) return -1;
    tm_live_entry_t *e = &l->e[l->n];
    memset(e, 0, sizeof *e);
    snprintf(e->id, sizeof e->id, "%s", id);
    e->reg = reg;
    e->q = TM_LQ_MISSING;
    return (int8_t)l->n++;
}

/* measurement.checked(): a NaN or a sentinel is invalid, a value outside the range out of range */
static void put(tm_live_t *l, int8_t ix, double v, bool invalid, uint64_t t_us, bool sample)
{
    if (ix < 0) return;
    tm_live_entry_t *e = &l->e[ix];
    e->t_us = t_us;
    e->sample = sample;
    e->has_upper = false;
    if (invalid || !isfinite(v))
        e->q = TM_LQ_INVALID;
    else if (v < REG[e->reg].lo || v > REG[e->reg].hi)
        e->q = TM_LQ_OUT_OF_RANGE;
    else {
        e->q = TM_LQ_VALID;
        e->v = v;
    }
}

static void put_q(tm_live_t *l, int8_t ix, uint8_t q, double v, uint64_t t_us, bool sample)
{
    if (ix < 0) return;
    tm_live_entry_t *e = &l->e[ix];
    e->q = q;
    e->v = v;
    e->t_us = t_us;
    e->sample = sample;
    e->has_upper = false;
}

static void on_tap(void *ctx, const tm_app_t *app, uint64_t t_us, uint8_t type, const uint8_t *body, uint32_t len)
{
    tm_live_record((tm_live_t *)ctx, app, t_us, type, body, len);
}

void tm_live_init(tm_live_t *l, tm_app_t *app, const tm_app_info_t *info, const tm_live_cfg_t *cfg)
{
    memset(l, 0, sizeof *l);
    snprintf(l->run_id, sizeof l->run_id, "%s-B%04lu", info->run_prefix ? info->run_prefix : info->unit_id,
             (unsigned long)app->boot);
    l->boot = app->boot;
    l->wheel_active_high = info->wheel_active_high;
    l->ix_gnss = l->ix_imu = l->ix_batt = -1;
    char id[32];
    for (uint8_t ch = 0; ch < TM_WHEEL_CHANNELS; ch++) l->ix_speed[ch] = l->ix_dist[ch] = -1;
    if (info->wheel_circumference_mm && info->wheel_ppr) {
        l->pitch_m = (float)info->wheel_circumference_mm / 1000.0f / (float)info->wheel_ppr;
        for (uint8_t ch = 0; ch < TM_WHEEL_CHANNELS; ch++) {
            snprintf(id, sizeof id, "wheel.wheel_%u.speed", (unsigned)ch);
            l->ix_speed[ch] = add(l, R_WSPEED, id);
            snprintf(id, sizeof id, "wheel.wheel_%u.distance", (unsigned)ch);
            l->ix_dist[ch] = add(l, R_WDIST, id);
        }
    }
    if (cfg->gnss) {
        l->ix_gnss = add(l, R_GSPEED, "gnss.speed");
        (void)add(l, R_GACC, "gnss.speed_acc");
        (void)add(l, R_GSV, "gnss.num_sv");
    }
    if (cfg->imu) {
        l->ix_imu = add(l, R_AX, "imu.ax");
        (void)add(l, R_GZ, "imu.gz");
    }
    for (uint8_t k = 0; k < TM_LIVE_TEMP_MAX; k++) l->ix_temp[k] = -1;
    for (uint8_t k = 0; k < cfg->n_temp && k < TM_LIVE_TEMP_MAX; k++) {
        snprintf(id, sizeof id, "temp.%s", cfg->temp_names[k]);
        l->ix_temp[k] = add(l, R_TEMP, id);
    }
    if (cfg->batt) {
        l->ix_batt = add(l, R_BV, "batt.voltage");
        (void)add(l, R_BA, "batt.current");
    }
    l->next_us = app->t0_us + TM_LIVE_PERIOD_US;
    l->next_counters_us = app->t0_us + TM_COUNTERS_PERIOD_US;
    tm_app_set_tap(app, on_tap, l);
}

/* host/telematics/wheel.py WheelEstimator.feed, one channel's record with its state from the cross-channel rule */
static void wheel(tm_live_t *l, const tm_app_t *app, uint64_t t, const uint8_t *b)
{
    const uint8_t ch = b[0], flags = b[1];
    if (ch >= TM_WHEEL_CHANNELS || l->ix_speed[ch] < 0) return;
    const uint32_t n = tm_rd16(b + 2), span = tm_rd32(b + 4), total = tm_rd32(b + 8), lost = tm_rd16(b + 14);
    const uint16_t rec_seq = tm_rd16(b + 12);
    tm_live_wheel_t *w = &l->w[ch];
    const char s = (char)tm_wheel_classify(app->track, TM_WHEEL_CHANNELS, ch, t, l->wheel_active_high, 0);
    const bool suspect_now = s == (char)TM_WHEEL_SUSPECT_ACTIVE || s == (char)TM_WHEEL_SUSPECT_INACTIVE;
    if (suspect_now) w->suspect = true;
    if (w->have_seq && rec_seq != w->expect_seq) w->chain_ok = false;
    w->expect_seq = (uint16_t)(rec_seq + 1u);
    w->have_seq = true;
    if (lost || (flags & TM_WHEEL_FLAG_OVERRUN)) {
        w->lost_edges += lost;
        w->chain_ok = false;
    }
    const double pitch = l->pitch_m;
    if (n > 0u) {
        if (w->chain_ok && w->have_last && t - w->last_edge_us <= (uint64_t)TM_WHEEL_MAX_PERIOD_US * n) {
            const uint64_t dt = t - w->last_edge_us;
            put(l, l->ix_speed[ch], n * pitch * 1e6 / (double)dt, false, w->last_edge_us + dt / 2u, true);
        } else if (n >= 2u && span > 0u) {
            put(l, l->ix_speed[ch], (n - 1u) * pitch * 1e6 / (double)span, false, t - span + span / 2u, true);
        }
        if (n >= 2u)
            w->last_period_us = span / (n - 1u), w->have_period = true;
        else if (w->have_last && w->chain_ok)
            w->last_period_us = (uint32_t)(t - w->last_edge_us), w->have_period = true;
        if (!w->have_total0) w->total0 = total - n, w->have_total0 = true;
        w->last_edge_us = t;
        w->have_last = true;
        w->chain_ok = true;
        /* after lost edges, or once the channel was suspect, the distance is a lower bound: unverified */
        put(l, l->ix_dist[ch], (double)(uint32_t)(total - w->total0) * pitch, false, t, true);
        if (l->e[l->ix_dist[ch]].q == TM_LQ_VALID && (w->lost_edges || w->suspect))
            l->e[l->ix_dist[ch]].q = TM_LQ_UNVERIFIED;
        return;
    }
    if (suspect_now) {
        put_q(l, l->ix_speed[ch], TM_LQ_INVALID, 0.0, t, false);
        return;
    }
    if (w->have_last && w->have_period && (double)(t - w->last_edge_us) <= 3.0 * w->last_period_us)
        return;                                  /* between edges: the latest speed still stands */
    put_q(l, l->ix_speed[ch], TM_LQ_NO_EVIDENCE, 0.0, t, false);
    if (w->have_last && t > w->last_edge_us) {
        l->e[l->ix_speed[ch]].upper = pitch * 1e6 / (double)(t - w->last_edge_us);
        l->e[l->ix_speed[ch]].has_upper = true;
    }
}

static float rdf(const uint8_t *p)
{
    uint32_t u = tm_rd32(p);
    float f;
    memcpy(&f, &u, 4);
    return f;
}

void tm_live_record(tm_live_t *l, const tm_app_t *app, uint64_t t_us, uint8_t type, const uint8_t *b, uint32_t len)
{
    switch (type) {
    case TM_REC_WHEEL_EDGES:
        if (len >= TM_WHEEL_BODY_BYTES) wheel(l, app, t_us, b);
        break;
    case TM_REC_GNSS:
        if (len >= TM_GNSS_BODY_LEN && l->ix_gnss >= 0) {
            const bool fix = b[9] != 0u;
            put(l, l->ix_gnss, rdf(b), !fix, t_us, false);
            put(l, (int8_t)(l->ix_gnss + 1), rdf(b + 4), !fix, t_us, false);
            put(l, (int8_t)(l->ix_gnss + 2), (float)b[8], false, t_us, false);
        }
        break;
    case TM_REC_PPS:
        if (len >= 4u) {
            l->pps_t[0] = l->pps_t[1];
            l->pps_s[0] = l->pps_s[1];
            l->pps_t[1] = t_us;
            l->pps_s[1] = tm_rd32(b);
            if (l->n_pps < 2u) l->n_pps++;
        }
        break;
    case TM_REC_IMU:
        if (len >= 8u && l->ix_imu >= 0) {
            put(l, l->ix_imu, rdf(b), false, t_us, false);
            put(l, (int8_t)(l->ix_imu + 1), rdf(b + 4), false, t_us, false);
        }
        break;
    case TM_REC_TEMP:
        if (len >= 4u && b[0] < TM_LIVE_TEMP_MAX) {
            const int16_t raw = (int16_t)tm_rd16(b + 2);
            const bool bad = b[1] != 0u || raw == -32768;
            put(l, l->ix_temp[b[0]], bad ? NAN : raw / 100.0, bad, t_us, false);
        }
        break;
    case TM_REC_BATT:
        if (len >= 9u && l->ix_batt >= 0) {
            const float v = rdf(b + 1), a = rdf(b + 5);
            const bool ok = b[0] == 0u && isfinite(v) && isfinite(a);    /* stlg.parse_body: both or neither */
            put(l, l->ix_batt, v, !ok, t_us, false);
            put(l, (int8_t)(l->ix_batt + 1), a, !ok, t_us, false);
        }
        break;
    case TM_REC_CAN2:
        l->can_seen = true;
        l->can_last_us = t_us;
        break;
    default:
        break;
    }
}

/* ---------------------------------------------------------------- encoding
 * Only %s and %lu go through vsnprintf: the target's C library (newlib-nano) prints neither floating point nor
 * 64-bit integers, so numbers are formatted here. */
typedef struct {
    char *p;
    uint32_t cap, n;
    bool overflow;
} jw_t;

static void jw(jw_t *w, const char *fmt, ...) __attribute__((format(printf, 2, 3)));
static void jw(jw_t *w, const char *fmt, ...)
{
    if (w->overflow) return;
    va_list ap;
    va_start(ap, fmt);
    int k = vsnprintf(w->p + w->n, w->cap - w->n, fmt, ap);
    va_end(ap);
    if (k < 0 || (uint32_t)k >= w->cap - w->n)
        w->overflow = true;
    else
        w->n += (uint32_t)k;
}

static void ju64(jw_t *w, uint64_t v)
{
    char d[21];
    int i = 20;
    d[i] = 0;
    do {
        d[--i] = (char)('0' + v % 10u);
        v /= 10u;
    } while (v);
    jw(w, "%s", d + i);
}

/* v to `digits` significant digits, a JSON number equal to Python's float(f"{v:.{digits}g}") except, rarely,
 * in the last digit (node.compact rounds the host model's values the same way); null if not finite */
static void jsig(jw_t *w, double v, int digits)
{
    if (!isfinite(v)) {
        jw(w, "null");
        return;
    }
    if (v == 0.0) {
        jw(w, "0");
        return;
    }
    if (v < 0.0) {
        jw(w, "-");
        v = -v;
    }
    int e = 0;                                   /* 10^e <= v < 10^(e+1) */
    double p = 1.0;
    while (v >= p * 10.0 && e < 300) p *= 10.0, e++;
    while (v < p && e > -300) p /= 10.0, e--;
    int x = e - digits + 1;                      /* the last digit's power of ten */
    double sc = v;
    for (int k = 0; k < (x < 0 ? -x : x); k++) sc = x < 0 ? sc * 10.0 : sc / 10.0;
    uint64_t m = (uint64_t)(sc + 0.5);
    uint64_t lim = 1;
    for (int k = 0; k < digits; k++) lim *= 10u;
    if (m >= lim) m /= 10u, x++;
    while (m && m % 10u == 0u) m /= 10u, x++;
    char r[24], d[24];
    int nd = 0;
    do {
        r[nd++] = (char)('0' + m % 10u);
        m /= 10u;
    } while (m);
    for (int k = 0; k < nd; k++) d[k] = r[nd - 1 - k];
    d[nd] = 0;
    if (x >= 0 && x <= 6) {
        jw(w, "%s", d);
        for (int k = 0; k < x; k++) jw(w, "0");
    } else if (x < 0 && -x < nd) {
        jw(w, "%.*s.%s", nd + x, d, d + nd + x);
    } else if (x < 0 && -x - nd <= 6) {
        jw(w, "0.");
        for (int k = 0; k < -x - nd; k++) jw(w, "0");
        jw(w, "%s", d);
    } else {
        jw(w, "%se%s%lu", d, x < 0 ? "-" : "", (unsigned long)(x < 0 ? -x : x));
    }
}

uint32_t tm_live_num(char *out, uint32_t cap, double v, int digits)
{
    jw_t w = {.p = out, .cap = cap};
    jsig(&w, v, digits);
    return w.overflow ? 0u : w.n;
}

static void counter(jw_t *w, bool *first, uint8_t id, uint32_t v)
{
    jw(w, "%s\"%s\":%lu", *first ? "" : ",", tm_counter_name(id), (unsigned long)v);
    *first = false;
}

uint32_t tm_live_encode(tm_live_t *l, const tm_app_t *app, const tm_gnss_t *gnss, uint64_t now, char *out,
                        uint32_t cap)
{
    jw_t w = {.p = out, .cap = cap};
    jw(&w, "{\"schema\":\"sem.telemetry.v4\",\"run_id\":\"%s\",\"boot\":%lu,\"seq\":%lu,\"t_local_ms\":",
       l->run_id, (unsigned long)l->boot, (unsigned long)l->seq);
    ju64(&w, (now + 500u) / 1000u);
    /* UTC from the last two labelled PPS edges (the pit fits more; host/telematics/clocks.py UtcEstimator) */
    if (l->n_pps >= 2u && l->pps_t[1] > l->pps_t[0] && now >= l->pps_t[1]) {
        const double rate = (double)(l->pps_s[1] - l->pps_s[0]) * 1e6 / (double)(l->pps_t[1] - l->pps_t[0]);
        const uint64_t age = now - l->pps_t[1];
        const uint64_t u_us = (uint64_t)l->pps_s[1] * 1000000u + (uint64_t)((double)age * rate + 0.5);
        char frac[8];
        snprintf(frac, sizeof frac, "%06lu", (unsigned long)(u_us % 1000000u));
        jw(&w, ",\"utc\":");
        ju64(&w, u_us / 1000000u);
        jw(&w, ".%s,", frac);
        if (age <= TM_LIVE_UTC_PPS_US)
            jw(&w, "\"utc_q\":\"pps\",\"utc_err_s\":0.000001,");
        else {
            jw(&w, "\"utc_q\":\"holdover\",\"utc_err_s\":");
            jsig(&w, 1e-6 + TM_LIVE_RATE_BOUND_PPM * 1e-6 * ((double)age / 1e6), 6);
            jw(&w, ",");
        }
    } else
        jw(&w, ",\"utc\":null,\"utc_q\":\"none\",\"utc_err_s\":null,");
    jw(&w, "\"adapter\":{\"id\":\"none\",\"fixture\":false,\"silent_ms\":");
    if (l->can_seen && now >= l->can_last_us)
        ju64(&w, (now - l->can_last_us) / 1000u);
    else
        jw(&w, "null");
    jw(&w, "},\"registry\":\"%s\",\"m\":{", TM_REGISTRY_ID);
    for (uint8_t i = 0; i < l->n; i++) {
        const tm_live_entry_t *e = &l->e[i];
        jw(&w, "%s\"%s\":[", i ? "," : "", e->id);
        if (e->q == TM_LQ_MISSING) {
            jw(&w, "null,\"missing\",null,null,null]");
            continue;
        }
        const uint64_t age_us = now > e->t_us ? now - e->t_us : 0u;
        const bool usable = e->q == TM_LQ_VALID || e->q == TM_LQ_UNVERIFIED;
        if (usable && age_us > (uint64_t)REG[e->reg].stale_ms * 1000u)
            jw(&w, "null,\"stale\",");
        else if (usable) {
            jsig(&w, e->v, 6);
            jw(&w, ",\"%s\",", QNAME[e->q]);
        } else
            jw(&w, "null,\"%s\",", QNAME[e->q]);
        ju64(&w, (age_us + 500u) / 1000u);
        jw(&w, ",null,\"%s\"", e->sample ? "s" : "r");
        if (e->has_upper) {
            jw(&w, ",");
            jsig(&w, e->upper, 4);
        }
        jw(&w, "]");
    }
    const tm_counters_t *c = &app->c;
    bool first = true;
    jw(&w, "},\"counters\":{");
    counter(&w, &first, TM_CNT_RX_FRAMES, c->rx_frames);
    counter(&w, &first, TM_CNT_LOG_RECORDS, c->log_records);
    counter(&w, &first, TM_CNT_LOG_DROPPED_QUEUE, c->log_dropped_queue);
    counter(&w, &first, TM_CNT_LOG_DROPPED_STORAGE, c->log_dropped_storage);
    counter(&w, &first, TM_CNT_QUEUE_HIGH_WATER, c->queue_high_water);
    counter(&w, &first, TM_CNT_WHEEL_EDGES_LOST, c->wheel_edges_lost);
    counter(&w, &first, TM_CNT_CAN_RX_OVERRUN, c->can_rx_overrun);
    counter(&w, &first, TM_CNT_CAN_NOT_LOGGED, c->can_not_logged);
    counter(&w, &first, TM_CNT_STORAGE_WRITE_ERRORS, c->storage_write_errors);
    counter(&w, &first, TM_CNT_LOG_THINNED, c->log_thinned);
    counter(&w, &first, TM_CNT_UPTIME_S, (uint32_t)((now - app->t0_us) / 1000000u));
    if (gnss) {
        counter(&w, &first, TM_CNT_GNSS_FRAMES, gnss->frames);
        counter(&w, &first, TM_CNT_GNSS_CHECKSUM_ERRORS, gnss->checksum_errors);
        counter(&w, &first, TM_CNT_PPS_UNLABELLED, gnss->pps_unlabelled);
    }
    counter(&w, &first, TM_CNT_UPLINK_SENT, l->sent);
    counter(&w, &first, TM_CNT_UPLINK_DROPPED, l->dropped);
    counter(&w, &first, TM_CNT_UPLINK_QUEUE_HIGH_WATER, l->high_water);
    counter(&w, &first, TM_CNT_UPLINK_QUEUE_CAPACITY, TM_LIVE_BACKLOG);
    jw(&w, "},\"replayed\":");
    return w.overflow ? 0u : w.n;
}

/* ---------------------------------------------------------------- backlog and sending */
static bool send(tm_live_t *l, const tm_link_t *link, const char *base, uint32_t n, uint32_t seq, bool replayed)
{
    memcpy(l->out, base, n);
    const char *tail = replayed ? "true}" : "false}";
    const uint32_t tl = (uint32_t)strlen(tail);
    memcpy(l->out + n, tail, tl);
    if (!link->publish(link->ctx, TM_LIVE_TOPIC, l->out, n + tl, seq)) return false;
    l->sent++;
    return true;
}

static void keep(tm_live_t *l, const char *base, uint32_t n, uint32_t seq)
{
    if (l->count >= TM_LIVE_BACKLOG) {           /* full: the oldest goes, counted */
        l->head = (l->head + 1u) % TM_LIVE_BACKLOG;
        l->count--;
        l->dropped++;
    }
    const uint32_t k = (l->head + l->count) % TM_LIVE_BACKLOG;
    memcpy(l->msg[k], base, n);
    l->len[k] = (uint16_t)n;
    l->mseq[k] = seq;
    l->count++;
    if (l->count > l->high_water) l->high_water = l->count;
}

void tm_live_tick(tm_live_t *l, tm_app_t *app, const tm_gnss_t *gnss, const tm_link_t *link, uint64_t now)
{
    if (now >= l->next_counters_us) {
        l->next_counters_us += TM_COUNTERS_PERIOD_US;
        if (now >= l->next_counters_us) l->next_counters_us = now + TM_COUNTERS_PERIOD_US;
        const struct {
            uint8_t id;
            uint32_t v;
        } items[] = {{TM_CNT_UPLINK_SENT, l->sent},
                     {TM_CNT_UPLINK_DROPPED, l->dropped},
                     {TM_CNT_UPLINK_QUEUE_HIGH_WATER, l->high_water},
                     {TM_CNT_UPLINK_QUEUE_CAPACITY, TM_LIVE_BACKLOG}};
        uint8_t body[1u + 5u * (sizeof items / sizeof items[0])];
        body[0] = (uint8_t)(sizeof items / sizeof items[0]);
        for (uint32_t i = 0; i < sizeof items / sizeof items[0]; i++) {
            body[1u + 5u * i] = items[i].id;
            tm_le32(body + 2u + 5u * i, items[i].v);
        }
        (void)tm_app_record(app, now, TM_REC_COUNTERS2, body, (uint32_t)sizeof body);
    }
    if (now < l->next_us) return;
    l->next_us += TM_LIVE_PERIOD_US;
    if (now >= l->next_us) l->next_us = now + TM_LIVE_PERIOD_US;     /* fell behind: no burst to catch up */
    const uint32_t n = tm_live_encode(l, app, gnss, now, l->cur, TM_LIVE_MSG_MAX - 8u);
    const uint32_t seq = l->seq++;
    if (n == 0u) {
        l->encode_errors++;                      /* counted; tests show the worst case fits */
        return;
    }
    if (!link || !link->up(link->ctx, now)) {
        keep(l, l->cur, n, seq);
        return;
    }
    while (l->count) {                           /* the backlog first, oldest first, flagged as replayed */
        const uint32_t k = l->head;
        if (!send(l, link, l->msg[k], l->len[k], l->mseq[k], true)) {
            keep(l, l->cur, n, seq);
            return;
        }
        l->head = (l->head + 1u) % TM_LIVE_BACKLOG;
        l->count--;
    }
    if (!send(l, link, l->cur, n, seq, false)) keep(l, l->cur, n, seq);
}

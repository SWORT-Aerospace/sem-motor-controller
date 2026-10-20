#include "tm_gnss.h"

#include <string.h>

#include "tm_counters.h"
#include "tm_le.h"

#define UBX_SYNC1 0xB5u
#define UBX_SYNC2 0x62u
#define UBX_NAV 0x01u
#define UBX_NAV_PVT 0x07u
#define UBX_CFG 0x06u
#define UBX_CFG_VALSET 0x8Au
#define UBX_MAX_LEN 1024u                 /* a longer length field is taken as noise: resynchronise */

/* UBX-NAV-PVT payload offsets (u-blox M9 UBX protocol) */
#define PVT_YEAR 4u
#define PVT_VALID 11u                     /* bit 0 validDate, bit 1 validTime, bit 2 fullyResolved */
#define PVT_NANO 16u
#define PVT_FIX_TYPE 20u
#define PVT_FLAGS 21u                     /* bit 0 gnssFixOK */
#define PVT_NUM_SV 23u
#define PVT_GSPEED 60u                    /* mm/s */
#define PVT_SACC 68u                      /* mm/s */

/* configuration keys (key id, value size in bytes) */
#define CFG_UART1OUTPROT_NMEA 0x10740002u /* L */
#define CFG_MSGOUT_NAV_PVT_UART1 0x20910007u /* U1: output rate per navigation solution */
#define CFG_RATE_MEAS 0x30210001u         /* U2: measurement period, ms */

enum { S_SYNC1, S_SYNC2, S_CLASS, S_ID, S_LEN1, S_LEN2, S_PAYLOAD, S_CKA, S_CKB };

void tm_gnss_init(tm_gnss_t *g)
{
    memset(g, 0, sizeof *g);
    g->state = S_SYNC1;
}

static void ck(tm_gnss_t *g, uint8_t b)
{
    g->ck_a = (uint8_t)(g->ck_a + b);
    g->ck_b = (uint8_t)(g->ck_b + g->ck_a);
}

int64_t tm_gnss_unix_s(uint16_t year, uint8_t month, uint8_t day, uint8_t hour, uint8_t min, uint8_t sec)
{
    /* days from 1970-01-01 to a civil date (H. Hinnant's algorithm) */
    int64_t y = (int64_t)year - (month <= 2u ? 1 : 0);
    int64_t era = (y >= 0 ? y : y - 399) / 400;
    int64_t yoe = y - era * 400;
    int64_t mp = (int64_t)month + (month > 2u ? -3 : 9);
    int64_t doy = (153 * mp + 2) / 5 + (int64_t)day - 1;
    int64_t doe = yoe * 365 + yoe / 4 - yoe / 100 + doy;
    int64_t days = era * 146097 + doe - 719468;
    return days * 86400 + (int64_t)hour * 3600 + (int64_t)min * 60 + (int64_t)sec;
}

static void decode(const uint8_t *p, tm_gnss_pvt_t *o)
{
    o->fix_type = p[PVT_FIX_TYPE];
    o->fix = (p[PVT_FLAGS] & 0x01u) != 0u && (o->fix_type == 3u || o->fix_type == 4u);
    o->num_sv = p[PVT_NUM_SV];
    o->speed_mps = (float)(int32_t)tm_rd32(p + PVT_GSPEED) * 1e-3f;
    o->sacc_mps = (float)tm_rd32(p + PVT_SACC) * 1e-3f;
    o->utc_valid = (p[PVT_VALID] & 0x07u) == 0x07u;
    o->utc_ns = 0;
    if (o->utc_valid) {
        int64_t s = tm_gnss_unix_s(tm_rd16(p + PVT_YEAR), p[6], p[7], p[8], p[9], p[10]);
        o->utc_ns = s * 1000000000 + (int32_t)tm_rd32(p + PVT_NANO);
    }
}

bool tm_gnss_feed(tm_gnss_t *g, uint8_t b, tm_gnss_pvt_t *out)
{
    switch (g->state) {
    case S_SYNC1:
        if (b == UBX_SYNC1) g->state = S_SYNC2;
        return false;
    case S_SYNC2:
        g->state = b == UBX_SYNC2 ? S_CLASS : (b == UBX_SYNC1 ? S_SYNC2 : S_SYNC1);
        return false;
    case S_CLASS:
        g->ck_a = 0u;
        g->ck_b = 0u;
        ck(g, b);
        g->cls = b;
        g->state = S_ID;
        return false;
    case S_ID:
        ck(g, b);
        g->id = b;
        g->state = S_LEN1;
        return false;
    case S_LEN1:
        ck(g, b);
        g->len = b;
        g->state = S_LEN2;
        return false;
    case S_LEN2:
        ck(g, b);
        g->len = (uint16_t)(g->len | (uint16_t)(b << 8));
        g->pos = 0u;
        if (g->len > UBX_MAX_LEN) {
            g->state = S_SYNC1;
            return false;
        }
        g->state = g->len ? S_PAYLOAD : S_CKA;
        return false;
    case S_PAYLOAD:
        ck(g, b);
        if (g->pos < TM_UBX_NAV_PVT_LEN) g->buf[g->pos] = b;
        g->pos++;
        if (g->pos == g->len) g->state = S_CKA;
        return false;
    case S_CKA:
        if (b != g->ck_a) {
            g->checksum_errors++;
            g->state = S_SYNC1;
            return false;
        }
        g->state = S_CKB;
        return false;
    case S_CKB:
        g->state = S_SYNC1;
        if (b != g->ck_b) {
            g->checksum_errors++;
            return false;
        }
        if (g->cls != UBX_NAV || g->id != UBX_NAV_PVT || g->len != TM_UBX_NAV_PVT_LEN) return false;
        g->frames++;
        decode(g->buf, out);
        return true;
    default:
        g->state = S_SYNC1;
        return false;
    }
}

uint32_t tm_gnss_body(const tm_gnss_pvt_t *p, uint8_t *body)
{
    uint32_t u;
    memcpy(&u, &p->speed_mps, 4);
    tm_le32(body, u);
    memcpy(&u, &p->sacc_mps, 4);
    tm_le32(body + 4, u);
    body[8] = p->num_sv;
    body[9] = p->fix ? 1u : 0u;
    return TM_GNSS_BODY_LEN;
}

void tm_gnss_pps_edge(tm_gnss_t *g, uint64_t t_us)
{
    g->pps_edges++;
    if (g->pps_pending) g->pps_unlabelled++;     /* two edges without a usable NAV-PVT between them */
    g->pps_pending = true;
    g->pps_t_us = t_us;
}

bool tm_gnss_pps_label(tm_gnss_t *g, const tm_gnss_pvt_t *p, uint64_t rx_us, uint64_t *edge_us, uint32_t *utc_s)
{
    if (!g->pps_pending || rx_us < g->pps_t_us) return false;
    uint64_t age = rx_us - g->pps_t_us;
    if (age > TM_GNSS_PPS_LABEL_US) {
        g->pps_pending = false;
        g->pps_unlabelled++;
        return false;
    }
    if (!p->utc_valid) return false;             /* a later message may still label it */
    /* the solution's UTC carried back to the edge: the whole second it marks minus the output latency */
    int64_t at_edge_ns = p->utc_ns - (int64_t)age * 1000;
    if (at_edge_ns < 0) return false;
    int64_t s = (at_edge_ns + 500000000) / 1000000000;
    int64_t off_us = (at_edge_ns - s * 1000000000) / 1000;
    g->pps_pending = false;
    if (off_us > (int64_t)TM_GNSS_PPS_TOL_US || off_us < -(int64_t)TM_GNSS_PPS_TOL_US || s > 0xFFFFFFFF) {
        g->pps_unlabelled++;
        return false;
    }
    *edge_us = g->pps_t_us;
    *utc_s = (uint32_t)s;
    return true;
}

static uint32_t put_key(uint8_t *p, uint32_t key, uint32_t value, uint32_t size)
{
    tm_le32(p, key);
    for (uint32_t i = 0; i < size; i++) p[4u + i] = (uint8_t)(value >> (8u * i));
    return 4u + size;
}

uint32_t tm_gnss_config_msg(uint8_t *out, uint32_t cap, uint16_t rate_ms)
{
    const uint32_t len = 4u + 5u + 5u + 6u;
    if (cap < len + 8u) return 0u;
    out[0] = UBX_SYNC1;
    out[1] = UBX_SYNC2;
    out[2] = UBX_CFG;
    out[3] = UBX_CFG_VALSET;
    tm_le16(out + 4, (uint16_t)len);
    uint8_t *p = out + 6;
    p[0] = 0u;                                   /* version */
    p[1] = 0x01u;                                /* layers: RAM */
    p[2] = 0u;
    p[3] = 0u;
    uint32_t n = 4u;
    n += put_key(p + n, CFG_UART1OUTPROT_NMEA, 0u, 1u);
    n += put_key(p + n, CFG_MSGOUT_NAV_PVT_UART1, 1u, 1u);
    n += put_key(p + n, CFG_RATE_MEAS, rate_ms, 2u);
    uint8_t a = 0u, b = 0u;
    for (uint32_t i = 2; i < 6u + n; i++) {
        a = (uint8_t)(a + out[i]);
        b = (uint8_t)(b + a);
    }
    out[6u + n] = a;
    out[7u + n] = b;
    return 8u + n;
}

void tm_gnss_rx(tm_gnss_t *g, tm_app_t *app, uint64_t t_us, uint8_t byte)
{
    tm_gnss_pvt_t p;
    if (!tm_gnss_feed(g, byte, &p)) return;
    uint8_t body[TM_GNSS_BODY_LEN];
    (void)tm_app_record(app, t_us, TM_REC_GNSS, body, tm_gnss_body(&p, body));
    uint64_t edge;
    uint32_t s;
    if (tm_gnss_pps_label(g, &p, t_us, &edge, &s)) {
        uint8_t b[4];
        tm_le32(b, s);
        (void)tm_app_record(app, edge, TM_REC_PPS, b, 4u);
    }
}

void tm_gnss_pps(tm_gnss_t *g, uint64_t t_us) { tm_gnss_pps_edge(g, t_us); }

void tm_gnss_tick(tm_gnss_t *g, tm_app_t *app, uint64_t now_us)
{
    if (now_us < g->next_counters_us) return;
    g->next_counters_us = now_us + TM_COUNTERS_PERIOD_US;
    const struct { uint8_t id; uint32_t v; } items[] = {
        {TM_CNT_GNSS_FRAMES, g->frames}, {TM_CNT_GNSS_CHECKSUM_ERRORS, g->checksum_errors},
        {TM_CNT_GNSS_RX_OVERRUN, g->rx_overrun}, {TM_CNT_PPS_EDGES, g->pps_edges},
        {TM_CNT_PPS_UNLABELLED, g->pps_unlabelled},
    };
    uint8_t body[1u + 5u * (sizeof items / sizeof items[0])];
    body[0] = (uint8_t)(sizeof items / sizeof items[0]);
    for (uint32_t i = 0; i < sizeof items / sizeof items[0]; i++) {
        body[1u + 5u * i] = items[i].id;
        tm_le32(body + 2u + 5u * i, items[i].v);
    }
    (void)tm_app_record(app, now_us, TM_REC_COUNTERS2, body, (uint32_t)sizeof body);
}

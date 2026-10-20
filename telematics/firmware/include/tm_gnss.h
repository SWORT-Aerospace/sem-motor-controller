/* GNSS receiver (u-blox NEO-M9N class) on a UART, and its PPS output on a timer capture channel: the portable
 * part. Bytes from the UART go through a UBX frame parser; each valid UBX-NAV-PVT message becomes an STLG GNSS
 * record (speed, speed accuracy, satellites, fix), and each PPS edge an STLG PPS record carrying the UTC second
 * it marks, so the pit maps the unit's clock to UTC (host/telematics/clocks.py, host/pit/ingest.py).
 *
 * A PPS edge is labelled from the first valid NAV-PVT that follows it: the edge marks the whole UTC second
 * nearest to (NAV-PVT time - (NAV-PVT receive time - edge time)), accepted only when that value is within
 * TM_GNSS_PPS_TOL_US of a whole second and the message came within TM_GNSS_PPS_LABEL_US of the edge. An edge
 * that cannot be labelled is counted (pps_unlabelled) and not logged: a PPS record without its UTC second
 * would be worse than none.
 *
 * The NAV-PVT field offsets and the configuration keys follow the u-blox M9 UBX protocol; they are a document
 * check before the bench (telematics/bench/bench.yaml, the u-blox interface description). Nothing here
 * transmits on the vehicle bus; the only output is the configuration message to the receiver's UART. */
#ifndef TM_GNSS_H
#define TM_GNSS_H

#include <stdbool.h>
#include <stdint.h>

#include "tm_app.h"

#define TM_UBX_NAV_PVT_LEN 92u
#define TM_GNSS_PPS_LABEL_US 1500000u     /* a NAV-PVT more than this after the edge does not label it */
#define TM_GNSS_PPS_TOL_US 400000u        /* NAV-PVT output latency accepted when labelling an edge */
#define TM_GNSS_BODY_LEN 10u              /* STLG GNSS: f32 speed | f32 sacc | u8 num_sv | u8 fix */
#define TM_GNSS_CFG_MAX 64u

typedef struct {
    float speed_mps;                      /* ground speed (gSpeed) */
    float sacc_mps;                       /* speed accuracy estimate (sAcc) */
    uint8_t num_sv;
    uint8_t fix_type;                     /* 0 none, 2 2D, 3 3D, 4 GNSS + dead reckoning, 5 time only */
    bool fix;                             /* gnssFixOK and a 3D (or GNSS + dead reckoning) fix */
    bool utc_valid;                       /* validDate, validTime and fullyResolved */
    int64_t utc_ns;                       /* UTC of the solution, ns since 1970-01-01 (valid when utc_valid) */
} tm_gnss_pvt_t;

typedef struct {
    /* UBX frame parser */
    uint8_t state;
    uint8_t cls, id;
    uint16_t len, pos;
    uint8_t ck_a, ck_b;
    uint8_t buf[TM_UBX_NAV_PVT_LEN];
    /* PPS edge waiting for its label */
    bool pps_pending;
    uint64_t pps_t_us;
    /* counters (STLG COUNTERS2 ids TM_CNT_GNSS_* in tm_counters.h) */
    uint32_t frames;                      /* NAV-PVT messages with a valid checksum */
    uint32_t checksum_errors;
    uint32_t rx_overrun;                  /* bytes the platform's receive ring had to drop */
    uint32_t pps_edges;
    uint32_t pps_unlabelled;
    uint64_t next_counters_us;
} tm_gnss_t;

void tm_gnss_init(tm_gnss_t *g);
/* One received byte. Returns true and fills *out when it completes a NAV-PVT with a valid checksum; other UBX
 * messages and bytes outside UBX frames (NMEA) are skipped. */
bool tm_gnss_feed(tm_gnss_t *g, uint8_t byte, tm_gnss_pvt_t *out);
/* The STLG GNSS record body; returns TM_GNSS_BODY_LEN. */
uint32_t tm_gnss_body(const tm_gnss_pvt_t *p, uint8_t *body);
/* A PPS edge captured at t_us. A previous edge still unlabelled is dropped and counted. */
void tm_gnss_pps_edge(tm_gnss_t *g, uint64_t t_us);
/* After a NAV-PVT received at rx_us: whether it labels the pending edge; if so *edge_us and *utc_s. */
bool tm_gnss_pps_label(tm_gnss_t *g, const tm_gnss_pvt_t *p, uint64_t rx_us, uint64_t *edge_us, uint32_t *utc_s);
/* Seconds since 1970-01-01 of a UTC date and time (proleptic Gregorian calendar). */
int64_t tm_gnss_unix_s(uint16_t year, uint8_t month, uint8_t day, uint8_t hour, uint8_t min, uint8_t sec);
/* UBX-CFG-VALSET (RAM layer) for the receiver's UART1: NAV-PVT on, NMEA off, measurement period rate_ms.
 * Returns its length, 0 if cap is too small. */
uint32_t tm_gnss_config_msg(uint8_t *out, uint32_t cap, uint16_t rate_ms);

/* The application side, used by every platform: bytes and edges in, STLG records out through tm_app_record. */
void tm_gnss_rx(tm_gnss_t *g, tm_app_t *app, uint64_t t_us, uint8_t byte);
void tm_gnss_pps(tm_gnss_t *g, uint64_t t_us);
/* Every TM_COUNTERS_PERIOD_US: a COUNTERS2 record with the GNSS counters (and rx_overrun from the platform). */
void tm_gnss_tick(tm_gnss_t *g, tm_app_t *app, uint64_t now_us);

#endif

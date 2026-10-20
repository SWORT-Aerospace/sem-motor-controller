/* Live summary for the pit (sem.telemetry.v4), the portable part of the uplink. Every TM_LIVE_PERIOD_US the unit
 * sends the latest value of each of its own signals with its validity and age, the UTC estimate from the logged
 * PPS edges and the counters, as the host model does (host/telematics/node.py) and the pit checks
 * (host/pit/ingest.py validate_live). A value that is stale, invalid or never received is null with its reason,
 * never 0. The wheel speed follows the pit's own rule (host/telematics/wheel.py WheelEstimator).
 *
 * The values come from the records the application logs (tm_app_set_tap): the live summary sees what the log
 * sees, and the log does not depend on it. Controller frames are not decoded on the unit: the summary carries no
 * ctrl.* signal and adapter.silent_ms is the time since the last frame received. The controller's frame
 * definitions are not known yet (docs/CONTROLLER_INTERFACE_REQUEST.md).
 *
 * The transport is a tm_link_t (up, publish). While it is down, messages wait in a bounded backlog; when it is
 * full the oldest is dropped and counted (uplink_dropped). Waiting messages are sent first, oldest first, with
 * replayed = true. Only the host simulator has a link so far; the modem's transport is open (T-MODEM). The
 * uplink counters are logged in a COUNTERS2 record every TM_COUNTERS_PERIOD_US, so the pit can account for every
 * sequence number from the log alone. */
#ifndef TM_LIVE_H
#define TM_LIVE_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "tm_app.h"
#include "tm_gnss.h"

#define TM_LIVE_PERIOD_US 500000u          /* 2 Hz, as the host model */
#define TM_LIVE_BACKLOG 30u                /* messages held while the link is down: 15 s at 2 Hz */
#define TM_LIVE_MSG_MAX 2560u              /* one message; tests check the worst case fits */
#define TM_LIVE_SIGNALS 20u
#define TM_LIVE_TEMP_MAX 4u
#define TM_LIVE_TOPIC "sem/car/telemetry"
#define TM_LIVE_UTC_PPS_US 2500000u        /* last labelled edge younger than this: utc_q "pps" */
#define TM_LIVE_RATE_BOUND_PPM 50u         /* holdover error bound: 1 us + 50 ppm of the time since the edge */

/* Signal registry of the pit (telematics/schema/telemetry_schema.yaml through host/telematics/signals.py): the
 * id the live message names and, for the unit's own signals, the range and the time after which a value is stale.
 * tests/telematics/test_firmware_host.py compares both with the Python registry. */
#define TM_REGISTRY_ID "reg-cbac7dc42d28"

typedef struct {
    void *ctx;
    bool (*up)(void *ctx, uint64_t now_us);
    /* hand one message to the transport; false: refused (kept and tried again next period) */
    bool (*publish)(void *ctx, const char *topic, const char *msg, uint32_t len, uint32_t seq);
} tm_link_t;

typedef struct {
    bool gnss;                             /* a GNSS receiver in this image */
    bool imu;                              /* an IMU answered at start-up */
    bool batt;                             /* a battery-side monitor */
    uint8_t n_temp;                        /* temperature channels, names in temp_names (as the log's metadata) */
    const char *temp_names[TM_LIVE_TEMP_MAX];
} tm_live_cfg_t;

typedef struct {
    char id[32];                           /* registry signal id, e.g. "wheel.wheel_0.speed" */
    uint8_t reg;                           /* row of the registry table */
    uint8_t q;                             /* validity code; TM_LQ_MISSING until a value arrives */
    double v;
    double upper;
    bool has_upper;
    bool sample;                           /* t_us is the sample time ("s"), else the receive time ("r") */
    uint64_t t_us;
} tm_live_entry_t;

typedef struct {
    bool have_seq, chain_ok, have_last, have_period, have_total0, suspect;
    uint16_t expect_seq;
    uint32_t total0, lost_edges, last_period_us;
    uint64_t last_edge_us;
} tm_live_wheel_t;

typedef struct {
    char run_id[64];
    uint32_t boot;
    tm_live_entry_t e[TM_LIVE_SIGNALS];
    uint8_t n;
    int8_t ix_speed[TM_WHEEL_CHANNELS], ix_dist[TM_WHEEL_CHANNELS], ix_temp[TM_LIVE_TEMP_MAX];
    int8_t ix_gnss, ix_imu, ix_batt;      /* first of a group: gnss speed, acc, num_sv; imu ax, gz; batt V, A */
    float pitch_m;                         /* 0: circumference or pulses per revolution unknown, no wheel signal */
    bool wheel_active_high;
    tm_live_wheel_t w[TM_WHEEL_CHANNELS];
    uint8_t n_pps;                         /* labelled PPS edges seen (up to 2 kept) */
    uint64_t pps_t[2];
    uint32_t pps_s[2];
    bool can_seen;
    uint64_t can_last_us;
    uint32_t seq;
    uint64_t next_us, next_counters_us;
    uint32_t sent, dropped, high_water, encode_errors;
    char msg[TM_LIVE_BACKLOG][TM_LIVE_MSG_MAX];   /* backlog: messages without their closing "replayed" field */
    uint16_t len[TM_LIVE_BACKLOG];
    uint32_t mseq[TM_LIVE_BACKLOG];
    uint32_t head, count;
    char cur[TM_LIVE_MSG_MAX];
    char out[TM_LIVE_MSG_MAX + 32u];
} tm_live_t;

/* After tm_app_init: the run id and boot of the log, the wheel pitch from its circumference and pulses per
 * revolution; installs the record tap. */
void tm_live_init(tm_live_t *l, tm_app_t *app, const tm_app_info_t *info, const tm_live_cfg_t *cfg);
/* Every record the application logs (the tap). */
void tm_live_record(tm_live_t *l, const tm_app_t *app, uint64_t t_us, uint8_t type, const uint8_t *body, uint32_t len);
/* From the main loop: every TM_LIVE_PERIOD_US one message, sent or kept; every TM_COUNTERS_PERIOD_US the uplink
 * counters into the log. gnss may be 0. */
void tm_live_tick(tm_live_t *l, tm_app_t *app, const tm_gnss_t *gnss, const tm_link_t *link, uint64_t now_us);
/* The message for now_us without its closing "replayed" field; returns its length, 0 if it did not fit. */
uint32_t tm_live_encode(tm_live_t *l, const tm_app_t *app, const tm_gnss_t *gnss, uint64_t now_us, char *out,
                        uint32_t cap);
/* v as a JSON number of `digits` significant digits (null if not finite); returns its length, 0 if cap is short. */
uint32_t tm_live_num(char *out, uint32_t cap, double v, int digits);
/* Name of a COUNTERS2 id (host/telematics/stlg.py COUNTER2_IDS), 0 if unknown. */
const char *tm_counter_name(uint8_t id);

#endif

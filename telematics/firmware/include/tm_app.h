/* The telematics application, portable part: wheel edges and received CAN frames in, a persistent STLG
 * log out. The platform (platform/u575 on the NUCLEO-U575ZI-Q, platform/host for tests) supplies the
 * time, the line levels, the storage and the interrupt masking, and calls:
 *
 *   tm_app_wheel_edge()   from the capture interrupt (constant time)
 *   tm_app_wheel_overrun() from the capture interrupt when a capture was overwritten
 *   tm_app_can_frame()    from the CAN receive interrupt (copies one frame into a ring)
 *   tm_app_poll()         from the main loop, as often as possible: drains the CAN ring, writes the
 *                         wheel records every TM_WHEEL_RECORD_PERIOD_US, the counters every second,
 *                         moves at most TM_POLL_RECORDS records into the open block and starts at most
 *                         one storage operation. It never waits.
 *
 * The application transmits nothing. */
#ifndef TM_APP_H
#define TM_APP_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "tm_config.h"
#include "tm_counters.h"
#include "tm_flashlog.h"
#include "tm_queue.h"
#include "tm_stlg.h"
#include "tm_wheel.h"

#define TM_POLL_RECORDS 64u
#define TM_STATUS_MAX 320u                 /* buffer for one status line; tests check the worst case fits */

typedef struct {
    uint64_t (*now_us)(void);
    bool (*line_high)(uint8_t channel);
    void (*mask_capture)(bool masked);     /* mask / unmask the capture interrupt around a take */
    const tm_flash_if_t *storage;
} tm_platform_t;

typedef struct {
    const char *unit_id;                   /* e.g. "U575-<96-bit UID in hex>" */
    const char *run_prefix;                /* run ids are <run_prefix>-B<boot>; 0: the unit id (each storage
                                              counts its own boots, so each needs its own prefix) */
    const char *firmware;                  /* image name and revision */
    const char *kind;                      /* what produced the log, for its evidence label: the target says
                                            * BENCH, the host simulator HOST SIMULATION; 0 gives UNKNOWN */
    const char *clock_source;              /* what the 1 us timebase runs from, with its accuracy class */
    const char *storage;                   /* e.g. "internal flash bank 2" */
    uint32_t reset_flags;
    const char *reset_cause;
    bool can_enabled;                      /* FDCAN1 in bus-monitoring mode */
    uint32_t wheel_circumference_mm;       /* 0: unknown (no speed at import unless given there) */
    uint32_t wheel_ppr;                    /* 0: unknown */
    bool wheel_active_high;
    const char *imu;                       /* e.g. "LSM6DSOX at 0x6A", "none" */
    const char *temp_channels_json;        /* e.g. {"0":"tmp117_0"}, "{}" when none */
} tm_app_info_t;

typedef struct {
    tm_platform_t pf;
    tm_wheel_acc_t wheel[TM_WHEEL_CHANNELS];
    tm_wheel_track_t track[TM_WHEEL_CHANNELS];       /* plausibility across channels (tm_wheel_classify) */
    char wheel_state[TM_WHEEL_CHANNELS];             /* latest state per channel: N M S A I */
    bool wheel_active_high;
    tm_can_ring_t can;
    tm_queue_t q;
    tm_block_t blk;
    uint32_t blk_records;
    tm_flashlog_t fl;
    tm_counters_t c;
    uint32_t block_seq;
    uint32_t boot;
    uint64_t t0_us, next_wheel_us, next_counters_us;
    bool header_pending;
    bool stalled;
    bool paused;                           /* logging paused (UART dump in progress) */
    bool flush_requested;                  /* write the open block as soon as the queue is empty */
    bool sparse;                           /* only the reserve is left: sparse logging (tm_config.h) */
    uint32_t reserve_slots;
    uint32_t slot0;                        /* first slot of this mode (for the time-left estimate) */
    uint64_t mode_t0_us;                   /* start of this mode (session start, or sparse logging) */
    uint8_t header[TM_SLOT_BYTES];
    char meta[TM_META_MAX];
    size_t meta_len;
} tm_app_t;

/* Scan the storage, count this boot, build the session header and the BOOT record. */
void tm_app_init(tm_app_t *app, const tm_platform_t *pf, const tm_app_info_t *info);
void tm_app_poll(tm_app_t *app);
static inline void tm_app_wheel_edge(tm_app_t *app, uint8_t ch, uint64_t t_us) { tm_wheel_edge(&app->wheel[ch], t_us); }
static inline void tm_app_wheel_overrun(tm_app_t *app, uint8_t ch) { tm_wheel_overrun(&app->wheel[ch]); }
bool tm_app_can_frame(tm_app_t *app, const tm_can_frame_t *f);
/* A record from a main-loop driver (IMU, temperature): into the log queue, dropped and counted if full;
 * in sparse logging not logged, counted as log_thinned. */
bool tm_app_record(tm_app_t *app, uint64_t t_us, uint8_t type, const uint8_t *body, uint32_t len);
/* One status line (no newline) for the UART: time, timer overflows (tov), edges and state per channel,
 * queue, storage, and the estimated recording time left at the current rate (left, s; "?" until known). */
size_t tm_app_status(const tm_app_t *app, char *out, size_t cap);
/* Request that everything queued reaches the storage (before a dump); tm_app_idle() tells when it has. */
void tm_app_request_flush(tm_app_t *app);
bool tm_app_idle(const tm_app_t *app);
/* Bench command "ERASE YES": erase the log region; the platform restarts the MCU afterwards. */
void tm_app_erase_log(tm_app_t *app);

#endif

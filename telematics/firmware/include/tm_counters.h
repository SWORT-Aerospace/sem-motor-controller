/* Counter identifiers of the STLG COUNTERS2 record. Must equal COUNTER2_IDS in host/telematics/stlg.py
 * (tests/telematics/test_firmware_host.py compares them). */
#ifndef TM_COUNTERS_H
#define TM_COUNTERS_H

#include <stdint.h>

enum {
    TM_CNT_RX_FRAMES = 1,
    TM_CNT_LOG_RECORDS = 2,
    TM_CNT_LOG_DROPPED_QUEUE = 3,
    TM_CNT_LOG_DROPPED_STORAGE = 4,
    TM_CNT_QUEUE_HIGH_WATER = 5,
    TM_CNT_WHEEL_EDGES_LOST = 14,
    TM_CNT_WHEEL_RECORDS = 15,
    TM_CNT_STORAGE_BLOCKS_WRITTEN = 16,
    TM_CNT_STORAGE_STALL_EVENTS = 17,
    TM_CNT_CAN_RX_OVERRUN = 18,
    TM_CNT_CAN_BUS_ERRORS = 19,
    TM_CNT_LOG_QUEUE_CAPACITY = 20,
    TM_CNT_STORAGE_WRITE_ERRORS = 22,
    TM_CNT_UPTIME_S = 23,
    TM_CNT_WHEEL_SUSPECT_ACTIVE = 24,     /* episodes: a channel became suspect with its line active */
    TM_CNT_WHEEL_SUSPECT_INACTIVE = 25,   /* episodes: suspect with its line inactive (or disconnected) */
    TM_CNT_LOG_THINNED = 26,              /* records not logged on purpose in sparse logging */
};
#define TM_CNT_ITEMS 17u                  /* counters in one COUNTERS2 record (tm_app.c) */

typedef struct {
    uint32_t rx_frames;
    uint32_t log_records;
    uint32_t log_dropped_queue;
    uint32_t log_dropped_storage;
    uint32_t queue_high_water;
    uint32_t wheel_edges_lost;
    uint32_t wheel_records;
    uint32_t storage_blocks_written;
    uint32_t storage_stall_events;
    uint32_t can_rx_overrun;
    uint32_t can_bus_errors;
    uint32_t storage_write_errors;
    uint32_t uptime_s;
    uint32_t wheel_suspect_active;
    uint32_t wheel_suspect_inactive;
    uint32_t log_thinned;
} tm_counters_t;

#endif

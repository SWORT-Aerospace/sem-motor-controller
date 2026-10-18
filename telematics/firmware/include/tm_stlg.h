/* STLG v1 writer for the firmware (format: host/telematics/stlg.py). A session header and every block
 * occupy one TM_SLOT_BYTES slot of the storage, so a power loss can cost only the slot being written. */
#ifndef TM_STLG_H
#define TM_STLG_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "tm_config.h"

enum {
    TM_REC_PPS = 2, TM_REC_GNSS = 3, TM_REC_IMU = 4, TM_REC_EVENT = 7, TM_REC_TEMP = 8, TM_REC_WHEEL_EDGES = 9,
    TM_REC_COUNTERS2 = 10, TM_REC_CAN2 = 11, TM_REC_BOOT = 12, TM_REC_BATT = 13,
};

/* Session header ("STLG" | u16 1 | u32 len | meta | u32 crc32) into out[TM_SLOT_BYTES]; the rest of the
 * slot is 0xFF. Returns the header length, 0 if the metadata does not fit. */
size_t tm_stlg_header(uint8_t *out, const char *meta, size_t meta_len);

typedef struct {
    uint8_t buf[TM_SLOT_BYTES];
    uint32_t used;          /* payload bytes */
    uint64_t base_us;
    uint64_t opened_us;     /* when the first record went in (for the flush period) */
    bool open;
} tm_block_t;

void tm_block_reset(tm_block_t *b);
/* Whether a record with this time and body length can go into the block as it is. */
bool tm_block_fits(const tm_block_t *b, uint64_t t_us, uint32_t len);
/* Add a record (call tm_block_fits first; an empty block always takes one). */
void tm_block_add(tm_block_t *b, uint64_t t_us, uint8_t type, const uint8_t *body, uint32_t len, uint64_t now_us);
/* Write the block header (sequence number, base, length, CRC-32) and pad the slot with 0xFF. */
void tm_block_finish(tm_block_t *b, uint32_t seq);

#endif

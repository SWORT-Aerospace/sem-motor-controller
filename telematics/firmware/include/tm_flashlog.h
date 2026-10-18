/* Persistent log storage: a region of slots (TM_SLOT_BYTES each), written in order and never wrapped.
 * Each session (one boot) writes a header slot, then block slots. The region is erased only by an explicit
 * command; a full region refuses further blocks and the records in them are counted as storage drops.
 *
 * Every call does at most one erase or one program operation start, so the main loop never waits for the
 * storage: a busy device returns at once. The storage behind `tm_flash_if_t` is the MCU's internal flash
 * (platform/u575/flash_u575.c, bank 2) or an SPI NOR device (src/tm_w25q.c). */
#ifndef TM_FLASHLOG_H
#define TM_FLASHLOG_H

#include <stdbool.h>
#include <stdint.h>

#include "tm_config.h"

typedef struct {
    uint32_t base;          /* address of slot 0, aligned to page_bytes */
    uint32_t slots;
    uint32_t page_bytes;    /* erase unit: 8 KiB internal flash, 4 KiB NOR sector */
    uint32_t prog_bytes;    /* program unit: 16 (quad-word) or 256 (NOR page); divides TM_SLOT_BYTES */
    int (*erase)(void *ctx, uint32_t addr);                                  /* start; 0 ok, <0 error */
    int (*program)(void *ctx, uint32_t addr, const uint8_t *src, uint32_t n); /* start; 0 ok, <0 error */
    int (*busy)(void *ctx);                                                  /* 1 busy, 0 idle, <0 error */
    int (*read)(void *ctx, uint32_t addr, uint8_t *dst, uint32_t n);         /* 0 ok */
    void *ctx;
} tm_flash_if_t;

typedef struct {
    const tm_flash_if_t *io;
    uint32_t next_slot;         /* first free slot */
    uint32_t sessions;          /* session headers found by the scan at start */
    uint32_t erased_until;      /* address below which (from next_slot's page on) the storage is erased */
    uint8_t pending[TM_SLOT_BYTES];
    bool has_pending;
    uint32_t pend_slot;
    uint32_t pend_off;
    uint32_t pend_records;
    bool erasing_all;
    uint32_t erase_all_next;
    uint32_t blocks_written;
    uint32_t write_errors;
    uint32_t dropped_records;   /* records in slots that failed or did not fit */
} tm_flashlog_t;

/* Scan the region for the first free slot and count the sessions in it (bounded: one 16-byte read per
 * slot plus one slot verify). */
void tm_flashlog_init(tm_flashlog_t *fl, const tm_flash_if_t *io);
bool tm_flashlog_full(const tm_flashlog_t *fl);
bool tm_flashlog_ready(const tm_flashlog_t *fl);    /* can take a slot now */
/* Hand over one slot image with the number of records in it. false: not ready (busy or full); when full
 * the records are counted as dropped. */
bool tm_flashlog_submit(tm_flashlog_t *fl, const uint8_t slot[TM_SLOT_BYTES], uint32_t records);
void tm_flashlog_step(tm_flashlog_t *fl);
/* Start erasing the whole region (the "ERASE YES" command); logging stops until it is done. */
void tm_flashlog_erase_all(tm_flashlog_t *fl);
bool tm_flashlog_erasing(const tm_flashlog_t *fl);

#endif

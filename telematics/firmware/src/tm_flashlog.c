#include "tm_flashlog.h"

#include <string.h>

static uint32_t slot_addr(const tm_flashlog_t *fl, uint32_t slot) { return fl->io->base + slot * TM_SLOT_BYTES; }

static bool all_ff(const uint8_t *p, uint32_t n)
{
    for (uint32_t i = 0; i < n; i++)
        if (p[i] != 0xFFu) return false;
    return true;
}

void tm_flashlog_init(tm_flashlog_t *fl, const tm_flash_if_t *io)
{
    memset(fl, 0, sizeof *fl);
    fl->io = io;
    uint8_t h[16];
    uint32_t s = 0;
    for (; s < io->slots; s++) {
        if (io->read(io->ctx, slot_addr(fl, s), h, sizeof h) != 0) break;
        if (all_ff(h, sizeof h)) break;
        if (memcmp(h, "STLG", 4) == 0) fl->sessions++;
    }
    fl->next_slot = s;
    fl->erased_until = slot_addr(fl, s);
    if (s < io->slots) {
        uint32_t a = slot_addr(fl, s);
        if (a % io->page_bytes != 0u) {
            /* mid-page: the page was erased when its first slot was written; check that this slot is clean */
            uint8_t buf[256];
            bool clean = true;
            for (uint32_t off = 0; off < TM_SLOT_BYTES && clean; off += sizeof buf) {
                if (io->read(io->ctx, a + off, buf, sizeof buf) != 0 || !all_ff(buf, sizeof buf)) clean = false;
            }
            if (clean) {
                fl->erased_until = a - a % io->page_bytes + io->page_bytes;
            } else {
                /* a partly written slot (power loss while programming): continue at the next page */
                uint32_t next_page = a - a % io->page_bytes + io->page_bytes;
                fl->next_slot = (next_page - io->base) / TM_SLOT_BYTES;
                fl->erased_until = next_page;
            }
        }
    }
}

bool tm_flashlog_full(const tm_flashlog_t *fl) { return fl->next_slot >= fl->io->slots; }

bool tm_flashlog_ready(const tm_flashlog_t *fl)
{
    return !fl->has_pending && !fl->erasing_all && !tm_flashlog_full(fl);
}

bool tm_flashlog_erasing(const tm_flashlog_t *fl) { return fl->erasing_all; }

bool tm_flashlog_submit(tm_flashlog_t *fl, const uint8_t slot[TM_SLOT_BYTES], uint32_t records)
{
    if (tm_flashlog_full(fl)) {
        fl->dropped_records += records;
        return false;
    }
    if (!tm_flashlog_ready(fl)) return false;
    memcpy(fl->pending, slot, TM_SLOT_BYTES);
    fl->has_pending = true;
    fl->pend_slot = fl->next_slot;
    fl->pend_off = 0u;
    fl->pend_records = records;
    return true;
}

static void fail_pending(tm_flashlog_t *fl)
{
    fl->write_errors++;
    fl->dropped_records += fl->pend_records;
    fl->has_pending = false;
    /* the slot may be partly written: never reuse it; continue at the next page, which is erased first */
    uint32_t a = slot_addr(fl, fl->pend_slot);
    uint32_t next_page = a - a % fl->io->page_bytes + fl->io->page_bytes;
    fl->next_slot = (next_page - fl->io->base) / TM_SLOT_BYTES;
    fl->erased_until = next_page;
}

void tm_flashlog_step(tm_flashlog_t *fl)
{
    const tm_flash_if_t *io = fl->io;
    int b = io->busy(io->ctx);
    if (b > 0) return;
    if (b < 0) {
        if (fl->has_pending) fail_pending(fl);
        return;
    }
    if (fl->erasing_all) {
        uint32_t end = io->base + io->slots * TM_SLOT_BYTES;
        if (fl->erase_all_next < end) {
            if (io->erase(io->ctx, fl->erase_all_next) != 0) fl->write_errors++;
            fl->erase_all_next += io->page_bytes;
        } else {
            fl->erasing_all = false;
            fl->next_slot = 0u;
            fl->sessions = 0u;
            fl->erased_until = end;
        }
        return;
    }
    if (!fl->has_pending) return;
    /* skip program units that are all 0xFF (block padding): erased storage already holds them */
    while (fl->pend_off < TM_SLOT_BYTES && all_ff(fl->pending + fl->pend_off, io->prog_bytes)) fl->pend_off += io->prog_bytes;
    if (fl->pend_off >= TM_SLOT_BYTES) {
        fl->has_pending = false;
        fl->next_slot++;
        fl->blocks_written++;
        return;
    }
    uint32_t a = slot_addr(fl, fl->pend_slot) + fl->pend_off;
    if (a >= fl->erased_until) {             /* first use of this page: erase it */
        uint32_t page = a - a % io->page_bytes;
        if (io->erase(io->ctx, page) != 0) {
            fail_pending(fl);
            return;
        }
        fl->erased_until = page + io->page_bytes;
        return;
    }
    if (io->program(io->ctx, a, fl->pending + fl->pend_off, io->prog_bytes) != 0) {
        fail_pending(fl);
        return;
    }
    fl->pend_off += io->prog_bytes;
}

void tm_flashlog_erase_all(tm_flashlog_t *fl)
{
    fl->has_pending = false;
    fl->erasing_all = true;
    fl->erase_all_next = fl->io->base;
}

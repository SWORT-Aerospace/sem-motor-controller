#include "tm_fakeflash.h"

#include <string.h>

static int ff_busy(void *ctx)
{
    tm_fakeflash_t *ff = ctx;
    uint64_t t = ff->now_us();
    return (t < ff->busy_until || (t >= ff->stall_t0 && t < ff->stall_t1)) ? 1 : 0;
}

static int ff_erase(void *ctx, uint32_t addr)
{
    tm_fakeflash_t *ff = ctx;
    if (ff_busy(ff) || addr % ff->io.page_bytes || addr + ff->io.page_bytes > ff->size) return -1;
    memset(ff->mem + addr, 0xFF, ff->io.page_bytes);
    ff->erases++;
    ff->busy_until = ff->now_us() + ff->erase_us;
    return 0;
}

static int ff_program(void *ctx, uint32_t addr, const uint8_t *src, uint32_t n)
{
    tm_fakeflash_t *ff = ctx;
    if (ff_busy(ff) || addr % ff->io.prog_bytes || n != ff->io.prog_bytes || addr + n > ff->size) return -1;
    if (ff->fail_next_program) {
        ff->fail_next_program = 0;
        return -1;
    }
    for (uint32_t i = 0; i < n; i++) {
        if (ff->mem[addr + i] != 0xFFu) {
            ff->violations++;
            return -1;
        }
    }
    memcpy(ff->mem + addr, src, n);
    ff->programs++;
    ff->busy_until = ff->now_us() + ff->program_us;
    return 0;
}

static int ff_read(void *ctx, uint32_t addr, uint8_t *dst, uint32_t n)
{
    tm_fakeflash_t *ff = ctx;
    if (addr + n > ff->size) return -1;
    memcpy(dst, ff->mem + addr, n);
    return 0;
}

void tm_fakeflash_init(tm_fakeflash_t *ff, uint8_t *mem, uint32_t size, uint32_t page_bytes, uint32_t prog_bytes,
                       uint64_t (*now_us)(void))
{
    memset(ff, 0, sizeof *ff);
    ff->mem = mem;
    ff->size = size;
    ff->now_us = now_us;
    ff->erase_us = 3000u;     /* illustrative timings, not the device's */
    ff->program_us = 60u;
    ff->io = (tm_flash_if_t){.base = 0u, .slots = size / TM_SLOT_BYTES, .page_bytes = page_bytes,
                             .prog_bytes = prog_bytes, .erase = ff_erase, .program = ff_program, .busy = ff_busy,
                             .read = ff_read, .ctx = ff};
}

#include "tm_fakew25q.h"

#include <string.h>

static uint64_t now(const tm_fakew25q_t *f) { return f->now_us ? f->now_us() : 0u; }

static bool busy(const tm_fakew25q_t *f) { return f->now_us && now(f) < f->busy_until; }

static void start(tm_fakew25q_t *f, uint32_t us)
{
    f->wel = false;
    f->busy_until = now(f) + us;
}

static int cmd(tm_fakew25q_t *f, const uint8_t *c, uint32_t nc, const uint8_t *tx, uint8_t *rx, uint32_t n)
{
    if (!f->present) {
        if (rx) memset(rx, 0xFF, n);
        return TM_BUS_OK;
    }
    if (nc == 0u) return TM_BUS_OK;
    uint32_t a = nc >= 4u ? ((uint32_t)c[1] << 16 | (uint32_t)c[2] << 8 | c[3]) : 0u;
    if (c[0] == 0x05u) {                                   /* status: always answered */
        uint8_t sr = (uint8_t)((busy(f) ? 0x01u : 0u) | (f->wel ? 0x02u : 0u));
        if (rx) memset(rx, sr, n);
        return TM_BUS_OK;
    }
    if (busy(f)) {                                         /* the part ignores everything else while busy */
        f->violations++;
        if (rx) memset(rx, 0xFF, n);
        return TM_BUS_OK;
    }
    switch (c[0]) {
    case 0x9Fu:
        if (rx && n >= 4u) {
            rx[0] = 0xFFu;
            memcpy(rx + 1, f->jedec, 3);
        }
        return TM_BUS_OK;
    case 0x06u:
        f->wel = true;
        return TM_BUS_OK;
    case 0x20u:
        if (!f->wel || a % 4096u || a + 4096u > f->size) {
            f->violations++;
            return TM_BUS_OK;
        }
        memset(f->mem + a, 0xFF, 4096u);
        f->erases++;
        start(f, f->sector_erase_us);
        return TM_BUS_OK;
    case 0xC7u:
        if (!f->wel) {
            f->violations++;
            return TM_BUS_OK;
        }
        memset(f->mem, 0xFF, f->size);
        f->chip_erases++;
        start(f, f->chip_erase_us);
        return TM_BUS_OK;
    case 0x02u: {
        uint32_t page = a & ~255u;
        if (!f->wel || page + 256u > f->size || n == 0u || n > 256u || !tx) {
            f->violations++;
            return TM_BUS_OK;
        }
        if ((a % 256u) + n > 256u) f->violations++;        /* the part wraps; the driver must not rely on it */
        for (uint32_t i = 0; i < n; i++) f->mem[page + ((a + i) & 255u)] &= tx[i];   /* clears bits only */
        f->programs++;
        start(f, f->page_program_us);
        return TM_BUS_OK;
    }
    case 0x03u:
        if (a + n > f->size) {
            f->violations++;
            if (rx) memset(rx, 0xFF, n);
            return TM_BUS_OK;
        }
        if (rx) memcpy(rx, f->mem + a, n);
        return TM_BUS_OK;
    default:
        f->violations++;
        return TM_BUS_OK;
    }
}

/* one transfer: the command bytes and the data share the buffers, as on the wire */
static int xfer(void *ctx, const uint8_t *tx, uint8_t *rx, uint32_t n)
{
    tm_fakew25q_t *f = ctx;
    if (n == 0u || !tx) return TM_BUS_ERROR;
    uint32_t nc = (tx[0] == 0x20u || tx[0] == 0x02u || tx[0] == 0x03u) ? 4u : 1u;
    if (nc > n) nc = n;
    if (tx[0] == 0x9Fu || tx[0] == 0x05u) return cmd(f, tx, 1u, 0, rx, n);   /* response from byte 0 */
    return cmd(f, tx, nc, n > nc ? tx + nc : 0, rx ? rx + nc : 0, n - nc);
}

static int xfer2(void *ctx, const uint8_t *c, uint32_t nc, const uint8_t *tx, uint8_t *rx, uint32_t n)
{
    return cmd(ctx, c, nc, tx, rx, n);
}

void tm_fakew25q_init(tm_fakew25q_t *f, uint8_t *mem, uint32_t size, uint8_t capacity_code, uint64_t (*now_us)(void))
{
    memset(f, 0, sizeof *f);
    f->mem = mem;
    f->size = size;
    f->jedec[0] = 0xEFu;          /* Winbond */
    f->jedec[1] = 0x40u;
    f->jedec[2] = capacity_code;
    f->present = true;
    f->now_us = now_us;
    f->sector_erase_us = 45000u;  /* model parameters ("typical" class), not data-sheet values read here */
    f->page_program_us = 700u;
    f->chip_erase_us = 40000000u;
    f->spi = (tm_spi_t){.xfer = xfer, .xfer2 = xfer2, .ctx = f};
}

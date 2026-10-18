#include "tm_w25q.h"

#define CMD_JEDEC 0x9Fu
#define CMD_WREN 0x06u
#define CMD_RDSR1 0x05u
#define CMD_SE4K 0x20u
#define CMD_PP 0x02u
#define CMD_READ 0x03u
#define SR1_BUSY 0x01u
#define SR1_WEL 0x02u

static int status(tm_w25q_t *d, uint8_t *sr)
{
    uint8_t tx[2] = {CMD_RDSR1, 0}, rx[2];
    int e = d->spi->xfer(d->spi->ctx, tx, rx, 2);
    *sr = rx[1];
    return e;
}

static int wren(tm_w25q_t *d)
{
    uint8_t c = CMD_WREN, sr;
    int e = d->spi->xfer(d->spi->ctx, &c, 0, 1);
    if (e) return e;
    if ((e = status(d, &sr)) != 0) return e;
    return (sr & SR1_WEL) ? TM_BUS_OK : TM_BUS_ERROR;
}

static void addr_cmd(uint8_t *c, uint8_t op, uint32_t a)
{
    c[0] = op;
    c[1] = (uint8_t)(a >> 16);
    c[2] = (uint8_t)(a >> 8);
    c[3] = (uint8_t)a;
}

static int w_busy(void *ctx)
{
    uint8_t sr;
    if (status(ctx, &sr) != 0) return -1;
    return (sr & SR1_BUSY) ? 1 : 0;
}

static int w_erase(void *ctx, uint32_t addr)
{
    tm_w25q_t *d = ctx;
    uint8_t c[4];
    if (addr % 4096u || addr >= d->capacity) return -1;
    if (wren(d)) return -1;
    addr_cmd(c, CMD_SE4K, addr);
    return d->spi->xfer(d->spi->ctx, c, 0, 4) ? -1 : 0;
}

static int w_program(void *ctx, uint32_t addr, const uint8_t *src, uint32_t n)
{
    tm_w25q_t *d = ctx;
    uint8_t c[4];
    if (n == 0u || n > 256u || (addr % 256u) + n > 256u || addr + n > d->capacity) return -1;   /* one page */
    if (wren(d)) return -1;
    addr_cmd(c, CMD_PP, addr);
    return d->spi->xfer2(d->spi->ctx, c, 4, src, 0, n) ? -1 : 0;
}

static int w_read(void *ctx, uint32_t addr, uint8_t *dst, uint32_t n)
{
    tm_w25q_t *d = ctx;
    uint8_t c[4];
    if (addr + n > d->capacity) return -1;
    addr_cmd(c, CMD_READ, addr);
    return d->spi->xfer2(d->spi->ctx, c, 4, 0, dst, n) ? -1 : 0;
}

int tm_w25q_init(tm_w25q_t *d, const tm_spi_t *spi, uint32_t base, uint32_t slots)
{
    d->spi = spi;
    uint8_t tx[4] = {CMD_JEDEC, 0, 0, 0}, rx[4] = {0};
    if (spi->xfer(spi->ctx, tx, rx, 4)) return TM_BUS_ERROR;
    d->jedec[0] = rx[1];
    d->jedec[1] = rx[2];
    d->jedec[2] = rx[3];
    if (d->jedec[0] != 0xEFu || d->jedec[2] < 0x14u || d->jedec[2] > 0x19u) return TM_BUS_ERROR;   /* Winbond, 1-32 MiB */
    d->capacity = 1uL << d->jedec[2];
    if (base % 4096u || base + slots * TM_SLOT_BYTES > d->capacity) return TM_BUS_ERROR;
    d->io = (tm_flash_if_t){.base = base, .slots = slots, .page_bytes = 4096u, .prog_bytes = 256u, .erase = w_erase,
                            .program = w_program, .busy = w_busy, .read = w_read, .ctx = d};
    return TM_BUS_OK;
}

/* Drivers against simulated devices: a W25Q128JV command model on the SPI transport, an LSM6DSOX and a
 * TMP117 register model on the I2C transport. The models implement what the drivers rely on (command codes,
 * status bits, register map) as tm_w25q.h and tm_imu.h state it; they are not the parts. */
#include <math.h>
#include <stdio.h>
#include <string.h>

#include "tm_flashlog.h"
#include "tm_imu.h"
#include "tm_w25q.h"

extern int g_drv_fail, g_drv_n;
int g_drv_fail, g_drv_n;
#define CHECK(c)                                                                 \
    do {                                                                         \
        g_drv_n++;                                                               \
        if (!(c)) {                                                              \
            g_drv_fail++;                                                        \
            fprintf(stderr, "%s:%d: CHECK failed: %s\n", __FILE__, __LINE__, #c); \
        }                                                                        \
    } while (0)

/* ---- W25Q model -------------------------------------------------------------------------------- */
#define NOR_SIZE (1u << 20)   /* the model is 1 MiB; it reports a 16 MiB id but rejects addresses past 1 MiB */
static uint8_t nor[NOR_SIZE];
static int nor_wel, nor_busy_polls, nor_present = 1;

static int nor_cmd(const uint8_t *c, uint32_t nc, const uint8_t *tx, uint8_t *rx, uint32_t n)
{
    uint32_t a = nc >= 4 ? ((uint32_t)c[1] << 16 | (uint32_t)c[2] << 8 | c[3]) : 0;
    switch (c[0]) {
    case 0x9F:
        if (rx) {
            rx[0] = 0;
            rx[1] = nor_present ? 0xEF : 0xFF;
            rx[2] = 0x40;
            rx[3] = 0x18;
        }
        return 0;
    case 0x06: nor_wel = 1; return 0;
    case 0x05:
        if (rx) rx[1] = (uint8_t)((nor_busy_polls > 0 ? 1 : 0) | (nor_wel ? 2 : 0));
        if (nor_busy_polls > 0) nor_busy_polls--;
        return 0;
    case 0x20:
        if (!nor_wel || nor_busy_polls || a + 4096u > NOR_SIZE) return -3;
        memset(nor + a, 0xFF, 4096);
        nor_wel = 0;
        nor_busy_polls = 3;
        return 0;
    case 0x02:
        if (!nor_wel || nor_busy_polls || a + n > NOR_SIZE) return -3;
        for (uint32_t i = 0; i < n; i++) nor[a + i] &= tx[i];     /* NOR programming clears bits only */
        nor_wel = 0;
        nor_busy_polls = 1;
        return 0;
    case 0x03:
        if (a + n > NOR_SIZE) return -3;
        memcpy(rx, nor + a, n);
        return 0;
    }
    return -3;
}

static int spi_xfer(void *ctx, const uint8_t *tx, uint8_t *rx, uint32_t n)
{
    (void)ctx;
    return nor_cmd(tx, n, 0, rx, n);
}

static int spi_xfer2(void *ctx, const uint8_t *cmd, uint32_t nc, const uint8_t *tx, uint8_t *rx, uint32_t n)
{
    (void)ctx;
    return nor_cmd(cmd, nc, tx, rx, n);
}

static void test_w25q(void)
{
    static tm_w25q_t d;
    static tm_flashlog_t fl;
    static uint8_t img[TM_SLOT_BYTES];
    tm_spi_t spi = {.xfer = spi_xfer, .xfer2 = spi_xfer2, .ctx = 0};
    memset(nor, 0x00, sizeof nor);                      /* not erased: the log must erase before writing */
    nor_present = 0;
    CHECK(tm_w25q_init(&d, &spi, 0, 16) != 0);           /* no device answers */
    nor_present = 1;
    CHECK(tm_w25q_init(&d, &spi, 0, 16) == 0 && d.capacity == (16u << 20) && d.io.prog_bytes == 256u);
    tm_flashlog_init(&fl, &d.io);
    CHECK(fl.next_slot == 16 && tm_flashlog_full(&fl));  /* never-erased (all-zero) storage reads as used */
    memset(nor, 0xFF, sizeof nor);
    tm_flashlog_init(&fl, &d.io);
    CHECK(fl.next_slot == 0 && fl.erased_until == 0u);
    for (unsigned i = 0; i < sizeof img; i++) img[i] = (uint8_t)(i * 7u + 1u);
    memcpy(img, "STLG", 4);
    for (int slot = 0; slot < 3; slot++) {
        CHECK(tm_flashlog_submit(&fl, img, 1));
        for (int i = 0; i < 1000 && fl.has_pending; i++) tm_flashlog_step(&fl);
        CHECK(!fl.has_pending && memcmp(nor + (uint32_t)slot * TM_SLOT_BYTES, img, sizeof img) == 0);
    }
    CHECK(fl.blocks_written == 3 && fl.write_errors == 0);
    tm_flashlog_init(&fl, &d.io);
    CHECK(fl.next_slot == 3 && fl.sessions == 3);
}

/* ---- I2C models ---------------------------------------------------------------------------------- */
static uint8_t imu_reg[128];
static int16_t tmp_raw = (int16_t)0x8000;
static int i2c_nack;

static int i2c_wr(void *ctx, uint8_t addr, const uint8_t *w, uint32_t nw, uint8_t *r, uint32_t nr)
{
    (void)ctx;
    if (i2c_nack) return TM_BUS_NACK;
    if (addr == 0x6A) {
        uint8_t reg = w[0];
        if (nw == 2) imu_reg[reg] = w[1];
        for (uint32_t i = 0; i < nr; i++) r[i] = imu_reg[(reg + i) & 127];
        return 0;
    }
    if (addr == 0x48) {
        if (w[0] == 0x0F && nr == 2) {
            r[0] = 0x01;
            r[1] = 0x17;
        } else if (w[0] == 0x00 && nr == 2) {
            r[0] = (uint8_t)((uint16_t)tmp_raw >> 8);
            r[1] = (uint8_t)tmp_raw;
        }
        return 0;
    }
    return TM_BUS_NACK;
}

static void test_imu_tmp117(void)
{
    tm_i2c_t bus = {.write_read = i2c_wr, .ctx = 0};
    tm_imu_t m;
    tm_tmp117_t t;
    float a[3], g[3];
    imu_reg[0x0F] = 0x00;
    CHECK(tm_imu_init(&m, &bus, 0x6A) != 0);              /* wrong WHO_AM_I */
    imu_reg[0x0F] = 0x6C;
    CHECK(tm_imu_init(&m, &bus, 0x6A) == 0 && imu_reg[0x10] == 0x48 && imu_reg[0x11] == 0x44 && imu_reg[0x12] == 0x44);
    imu_reg[0x1E] = 0x01;                                 /* accelerometer only */
    CHECK(tm_imu_read(&m, a, g) == 0);
    imu_reg[0x1E] = 0x03;
    int16_t ax = 8197, gz = -2000;                         /* 8197 x 0.122 mg = 1.0000 g; -2000 x 17.5 mdps */
    imu_reg[0x28] = (uint8_t)ax;
    imu_reg[0x29] = (uint8_t)(ax >> 8);
    imu_reg[0x26] = (uint8_t)gz;
    imu_reg[0x27] = (uint8_t)((uint16_t)gz >> 8);
    CHECK(tm_imu_read(&m, a, g) == 1);
    CHECK(fabsf(a[0] - 8197 * 0.122e-3f * 9.80665f) < 1e-4f && fabsf(g[2] - (-35.0f * 0.0174532925f)) < 1e-5f);
    i2c_nack = 1;
    CHECK(tm_imu_read(&m, a, g) == TM_BUS_NACK && m.errors == 1);
    i2c_nack = 0;
    int16_t c;
    CHECK(tm_tmp117_init(&t, &bus, 0x48) == 0);
    CHECK(tm_tmp117_read(&t, &c) != 0);                   /* reset value: no conversion yet */
    tmp_raw = 3200;                                        /* 3200 x 7.8125 m degC = 25.000 degC */
    CHECK(tm_tmp117_read(&t, &c) == 0 && c == 2500);
    tmp_raw = -1;                                          /* -7.8 m degC rounds to -1 centi-degC */
    CHECK(tm_tmp117_read(&t, &c) == 0 && c == -1);
}

void test_drivers(void);
void test_drivers(void)
{
    test_w25q();
    test_imu_tmp117();
    printf("drivers: %d checks, %d failed\n", g_drv_n, g_drv_fail);
}

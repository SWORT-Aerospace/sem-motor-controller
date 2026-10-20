/* Drivers against simulated devices: the W25Q command model (platform/host/tm_fakew25q.c) on the SPI
 * transport, an LSM6DSOX and a TMP117 register model on the I2C transport. The models implement what the drivers rely on (command codes,
 * status bits, register map) as tm_w25q.h and tm_imu.h state it; they are not the parts. */
#include <math.h>
#include <stdio.h>
#include <string.h>

#include "tm_fakew25q.h"
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

/* ---- W25Q (platform/host/tm_fakew25q.c) ------------------------------------------------------------ */
static uint64_t g_t;
static uint64_t t_now(void) { return g_t; }

static void run_log(tm_flashlog_t *fl, uint32_t max_steps)
{
    for (uint32_t i = 0; i < max_steps && (fl->has_pending || tm_flashlog_erasing(fl)); i++) {
        g_t += 250u;                                   /* the main loop polls about every 250 us */
        tm_flashlog_step(fl);
    }
}

static void test_w25q(void)
{
    static tm_fakew25q_t m;
    static tm_w25q_t d;
    static tm_flashlog_t fl;
    static uint8_t img[TM_SLOT_BYTES];
    static uint8_t nor[1u << 20];
    tm_fakew25q_init(&m, nor, sizeof nor, 0x18u, t_now);            /* reports 16 MiB, models 1 MiB */
    memset(nor, 0x00, sizeof nor);                      /* not erased: the log must erase before writing */
    m.present = false;
    CHECK(tm_w25q_init(&d, &m.spi, 0, 16) != 0);         /* no device answers */
    m.present = true;
    m.jedec[2] = 0x19u;                                  /* 32 MiB: needs 4-byte addresses, refused */
    CHECK(tm_w25q_init(&d, &m.spi, 0, 0) != 0);
    m.jedec[0] = 0xC2u;                                  /* another maker's id */
    m.jedec[2] = 0x18u;
    CHECK(tm_w25q_init(&d, &m.spi, 0, 0) != 0);
    m.jedec[0] = 0xEFu;
    CHECK(tm_w25q_init(&d, &m.spi, 0, 16) == 0 && d.capacity == (16u << 20) && d.io.prog_bytes == 256u);
    CHECK(d.io.erase_chip == 0);                         /* only 16 of 4096 slots: no chip erase */
    tm_flashlog_init(&fl, &d.io);
    CHECK(fl.next_slot == 16 && tm_flashlog_full(&fl));  /* never-erased (all-zero) storage reads as used */
    memset(nor, 0xFF, sizeof nor);
    tm_flashlog_init(&fl, &d.io);
    CHECK(fl.next_slot == 0 && fl.erased_until == 0u && tm_flashlog_free_slots(&fl) == 16u);
    for (unsigned i = 0; i < sizeof img; i++) img[i] = (uint8_t)(i * 7u + 1u);
    memcpy(img, "STLG", 4);
    for (int slot = 0; slot < 3; slot++) {
        CHECK(tm_flashlog_submit(&fl, img, 1));
        run_log(&fl, 100000u);
        CHECK(!fl.has_pending && memcmp(nor + (uint32_t)slot * TM_SLOT_BYTES, img, sizeof img) == 0);
    }
    CHECK(fl.blocks_written == 3 && fl.write_errors == 0 && m.violations == 0);
    CHECK(m.erases == 0 && fl.erases_skipped == 3u && m.programs == 3u * 16u);   /* blank: no erase needed */
    tm_flashlog_init(&fl, &d.io);
    CHECK(fl.next_slot == 3 && fl.sessions == 3 && tm_flashlog_free_slots(&fl) == 13u);
    /* slow device (erase 400 ms, program 3 ms) and a sector that is not blank: it is erased first, and the
     * same result follows, only later */
    m.sector_erase_us = 400000u;
    m.page_program_us = 3000u;
    memset(nor + 3u * TM_SLOT_BYTES + 100u, 0x00, 8);
    CHECK(tm_flashlog_submit(&fl, img, 1));
    uint64_t t0 = g_t;
    run_log(&fl, 1000000u);
    CHECK(!fl.has_pending && fl.blocks_written == 1 && m.violations == 0 && g_t - t0 >= 400000u + 16u * 3000u);
    CHECK(m.erases == 1 && memcmp(nor + 3u * TM_SLOT_BYTES, img, sizeof img) == 0);
    /* page-by-page erase of the region */
    tm_flashlog_erase_all(&fl);
    run_log(&fl, 1000000u);
    CHECK(!tm_flashlog_erasing(&fl) && fl.next_slot == 0 && nor[0] == 0xFF && m.violations == 0);

    /* a device whose capacity the region covers completely: chip erase (one command, then BUSY until done) */
    static tm_fakew25q_t m2;
    static uint8_t small[1u << 20];
    tm_fakew25q_init(&m2, small, sizeof small, 0x14u, t_now);       /* 1 MiB part (W25Q80 class) */
    memset(small, 0x5A, sizeof small);
    CHECK(tm_w25q_init(&d, &m2.spi, 0, 0) == 0 && d.io.slots == 256u && d.io.erase_chip != 0);
    tm_flashlog_init(&fl, &d.io);
    tm_flashlog_erase_all(&fl);
    m2.chip_erase_us = 2000000u;
    run_log(&fl, 100000u);
    CHECK(!tm_flashlog_erasing(&fl) && m2.chip_erases == 1 && m2.erases == 0 && small[12345] == 0xFF);
    CHECK(fl.next_slot == 0 && m2.violations == 0);
    CHECK(tm_w25q_init(&d, &m2.spi, 4096u, 0) == 0 && d.io.slots == 255u && d.io.erase_chip == 0);
    CHECK(tm_w25q_init(&d, &m2.spi, 1000u, 0) != 0);    /* base not on a sector */
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

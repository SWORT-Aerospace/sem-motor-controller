/* Host tests for the device-driver logic and the start-up sequence (src/io/mc_ina228.c, mc_drv835x.c,
 * mc_startup.c).
 *
 * The device descriptions below are TEST MAPS, invented for these tests: their addresses, field
 * positions, LSB sizes, identities and timings are not the INA228's or the DRV8353's and must not be
 * copied into the firmware. They exercise the protocol logic (reset, identification, read-back, fault
 * handling, sample ageing, timeouts); the real values come from the data sheets
 * (docs/reference/datasheets/README.md). Each simulated device is a register array behind the same bus
 * callbacks the platform provides, with injectable bus errors and register corruption. */
#include <math.h>
#include <string.h>

#include "mc_test.h"
#include "semmc/mc_drv835x.h"
#include "semmc/mc_ina228.h"
#include "semmc/mc_startup.h"

/* ------------------------------------------------------------------ simulated power monitor */
enum { TR_CONFIG = 0x10, TR_ADC = 0x11, TR_CAL = 0x12, TR_VBUS = 0x13, TR_VSHUNT = 0x14, TR_DIAG = 0x15,
       TR_MAN = 0x16, TR_DEV = 0x17 };

static const mc_ina228_desc_t TEST_INA = {
    .source = "TEST MAP (not the INA228)", .verified = true, .msb_first = true,
    .config = {TR_CONFIG, 2}, .adc_config = {TR_ADC, 2}, .shunt_cal = {TR_CAL, 2}, .vbus = {TR_VBUS, 3},
    .vshunt = {TR_VSHUNT, 3}, .diag = {TR_DIAG, 2}, .manufacturer_id = {TR_MAN, 2}, .device_id = {TR_DEV, 2},
    .manufacturer_id_value = 0x1234u, .device_id_value = 0x0560u, .device_id_mask = 0xFFF0u,
    .reset_mask = 0x8000u, .cnvrf_mask = 0x0002u, .diag_error_mask = 0x0100u,
    .vbus_shift = 4, .vshunt_shift = 4, .vshunt_signed = true,
    .vbus_lsb_V = 0.001f, .vshunt_lsb_V = 1e-6f, .shunt_cal_k = 1.0e6f, .shunt_cal_max = 0x7FFFu,
    .t_reset_us = 500u, .vbus_max_V = 100.0f};

typedef struct {
    uint32_t reg[256];
    int fail_reads, fail_writes; /* next n accesses fail */
    int reads, writes;
    uint32_t config_stuck_bits; /* forced to 1 on read-back */
} sim_mon_t;

static uint8_t width(uint8_t reg)
{
    const mc_reg_t *all[] = {&TEST_INA.config, &TEST_INA.adc_config, &TEST_INA.shunt_cal, &TEST_INA.vbus,
                             &TEST_INA.vshunt, &TEST_INA.diag, &TEST_INA.manufacturer_id, &TEST_INA.device_id};
    for (unsigned i = 0; i < sizeof all / sizeof all[0]; i++) {
        if (all[i]->addr == reg) return all[i]->bytes;
    }
    return 0;
}

static int mon_read(void *ctx, uint8_t reg, uint8_t *d, uint8_t n)
{
    sim_mon_t *s = ctx;
    s->reads++;
    if (s->fail_reads > 0) {
        s->fail_reads--;
        return -1;
    }
    if (width(reg) != n) return -2;
    uint32_t v = s->reg[reg];
    if (reg == TR_CONFIG) v |= s->config_stuck_bits;
    for (uint8_t i = 0; i < n; i++) d[i] = (uint8_t)(v >> (8u * (uint32_t)(n - 1u - i))); /* MSB first */
    if (reg == TR_DIAG) s->reg[TR_DIAG] &= ~TEST_INA.cnvrf_mask;                           /* cleared on read */
    return 0;
}

static int mon_write(void *ctx, uint8_t reg, const uint8_t *d, uint8_t n)
{
    sim_mon_t *s = ctx;
    s->writes++;
    if (s->fail_writes > 0) {
        s->fail_writes--;
        return -1;
    }
    if (width(reg) != n) return -2;
    uint32_t v = 0;
    for (uint8_t i = 0; i < n; i++) v = (v << 8u) | d[i];
    if (reg == TR_CONFIG && (v & TEST_INA.reset_mask)) {
        s->reg[TR_CONFIG] = s->reg[TR_ADC] = s->reg[TR_CAL] = 0;
        return 0;
    }
    s->reg[reg] = v;
    return 0;
}

static void mon_init(sim_mon_t *s)
{
    memset(s, 0, sizeof *s);
    s->reg[TR_MAN] = 0x1234u;
    s->reg[TR_DEV] = 0x0563u; /* revision nibble ignored by the mask */
}

/* A new conversion: bus voltage and signed shunt voltage, with the diagnostic error bit if asked. */
static void mon_convert(sim_mon_t *s, float vbus, float vshunt, bool error)
{
    s->reg[TR_VBUS] = ((uint32_t)lroundf(vbus / 0.001f) << 4) & 0xFFFFFFu;
    s->reg[TR_VSHUNT] = ((uint32_t)(int32_t)lroundf(vshunt / 1e-6f) << 4) & 0xFFFFFFu;
    s->reg[TR_DIAG] = TEST_INA.cnvrf_mask | (error ? TEST_INA.diag_error_mask : 0u);
}

static const mc_ina228_settings_t MON_SET = {.config_value = 0x0010u, .adc_config_value = 0x0BB0u,
                                             .shunt_ohm = 0.002f, .current_lsb_A = 0.001f};

static void ina_bring_up(mc_ina228_t *m, mc_time_us_t *t)
{
    for (int i = 0; i < 10 && m->state != MC_INA_RUNNING; i++) {
        mc_ina228_step(m, *t);
        *t += 1000u;
    }
}

static void test_ina_unverified_never_touches_bus(void)
{
    sim_mon_t s;
    mon_init(&s);
    mc_ina228_t m;
    mc_ina228_init(&m, NULL, &MON_SET, mon_read, mon_write, &s, 3, 0);
    CHECK_EQ_INT(m.state, MC_INA_UNVERIFIED);
    mc_ina228_desc_t unverified = TEST_INA;
    unverified.verified = false;
    for (mc_time_us_t t = 0; t < 10000; t += 1000) mc_ina228_step(&m, t);
    mc_ina228_init(&m, &unverified, &MON_SET, mon_read, mon_write, &s, 3, 0);
    CHECK_EQ_INT(m.state, MC_INA_UNVERIFIED);
    CHECK_EQ_INT(m.error, MC_INA_ERR_NO_DESCRIPTION);
    for (mc_time_us_t t = 0; t < 10000; t += 1000) mc_ina228_step(&m, t);
    CHECK_EQ_INT(s.reads + s.writes, 0);
    bool ok = true;
    CHECK(isnan(mc_ina228_vbus_V(&m, 10000, 1000000u, &ok)) && !ok);
}

static void test_ina_bring_up_scaling_and_sign(void)
{
    sim_mon_t s;
    mon_init(&s);
    mc_ina228_t m;
    mc_time_us_t t = 0;
    mc_ina228_init(&m, &TEST_INA, &MON_SET, mon_read, mon_write, &s, 3, t);
    CHECK_EQ_INT(m.shunt_cal_value, 2); /* 1e6 x 0.001 A x 0.002 ohm */
    mc_ina228_step(&m, t);              /* reset */
    CHECK_EQ_INT(m.state, MC_INA_WAIT_RESET);
    mc_ina228_step(&m, t + 499u);
    CHECK_EQ_INT(m.state, MC_INA_WAIT_RESET); /* the reset time is respected */
    t += 500u;
    ina_bring_up(&m, &t);
    CHECK_EQ_INT(m.state, MC_INA_RUNNING);
    CHECK_EQ_INT(s.reg[TR_CONFIG], 0x0010u);
    CHECK_EQ_INT(s.reg[TR_CAL], 2);
    bool ok = true;
    (void)mc_ina228_vbus_V(&m, t, 100000u, &ok);
    CHECK(!ok); /* running, but no conversion yet: nothing to report */

    mon_convert(&s, 48.123f, -0.004f, false);
    mc_ina228_step(&m, t);
    CHECK_NEAR(mc_ina228_vbus_V(&m, t, 100000u, &ok), 48.123f, 0.0011f);
    CHECK(ok);
    CHECK_NEAR(mc_ina228_vshunt_V(&m, t, 100000u, &ok), -0.004f, 2e-6f); /* sign extension of the 20-bit field */
    CHECK(ok);
}

static void test_ina_sample_ages_without_new_conversion(void)
{
    sim_mon_t s;
    mon_init(&s);
    mc_ina228_t m;
    mc_time_us_t t = 0;
    mc_ina228_init(&m, &TEST_INA, &MON_SET, mon_read, mon_write, &s, 3, t);
    ina_bring_up(&m, &t);
    mon_convert(&s, 50.0f, 0.0f, false);
    mc_ina228_step(&m, t);
    const uint32_t seq = m.vbus.seq;
    bool ok = false;
    /* The bus keeps working but the converter stops: reads succeed, the conversion flag stays clear. */
    for (int i = 0; i < 20; i++) {
        t += 10000u;
        mc_ina228_step(&m, t);
    }
    CHECK_EQ_INT(m.state, MC_INA_RUNNING);
    CHECK_EQ_INT(m.consecutive_errors, 0);
    CHECK_EQ_INT(m.vbus.seq, seq);
    (void)mc_ina228_vbus_V(&m, t, 100000u, &ok);
    CHECK(!ok); /* 200 ms old with a 100 ms limit */
    CHECK_NEAR(mc_ina228_vbus_V(&m, t, 300000u, &ok), 50.0f, 0.002f);
    CHECK(ok);
    /* A conversion with the diagnostic error bit set is read but invalid. */
    mon_convert(&s, 51.0f, 0.0f, true);
    mc_ina228_step(&m, t);
    (void)mc_ina228_vbus_V(&m, t, 300000u, &ok);
    CHECK(!ok);
    /* Out of the description's range: invalid. */
    mon_convert(&s, 120.0f, 0.0f, false);
    mc_ina228_step(&m, t);
    (void)mc_ina228_vbus_V(&m, t, 300000u, &ok);
    CHECK(!ok);
}

static void test_ina_bus_errors_identity_readback_and_retries(void)
{
    sim_mon_t s;
    mon_init(&s);
    mc_ina228_t m;
    mc_time_us_t t = 0;
    mc_ina228_init(&m, &TEST_INA, &MON_SET, mon_read, mon_write, &s, 2, t);
    ina_bring_up(&m, &t);
    mon_convert(&s, 50.0f, 0.0f, false);
    mc_ina228_step(&m, t);
    s.fail_reads = 2; /* two failed steps: the old sample stays, ageing */
    mc_ina228_step(&m, t);
    mc_ina228_step(&m, t);
    CHECK_EQ_INT(m.state, MC_INA_RUNNING);
    s.fail_reads = 1; /* the third in a row: fault, samples invalid */
    mc_ina228_step(&m, t);
    CHECK_EQ_INT(m.state, MC_INA_FAULT);
    CHECK_EQ_INT(m.error, MC_INA_ERR_BUS);
    bool ok = true;
    (void)mc_ina228_vbus_V(&m, t, 1000000u, &ok);
    CHECK(!ok);
    /* Retry after the back-off: the second and last attempt finds the wrong identity. */
    s.reg[TR_MAN] = 0x9999u;
    mc_ina228_step(&m, t + MC_INA_RETRY_US - 1u);
    CHECK_EQ_INT(m.state, MC_INA_FAULT);
    t += MC_INA_RETRY_US;
    for (int i = 0; i < 5; i++) {
        mc_ina228_step(&m, t);
        t += 1000u;
    }
    CHECK_EQ_INT(m.state, MC_INA_FAULT);
    CHECK_EQ_INT(m.init_attempts, 2);
    t += MC_INA_RETRY_US;
    mc_ina228_step(&m, t);
    CHECK(m.retries_exhausted); /* attempts used up: stays in FAULT, with the cause kept */
    CHECK_EQ_INT(m.error, MC_INA_ERR_ID);
    mc_ina228_step(&m, t + 10u * MC_INA_RETRY_US);
    CHECK_EQ_INT(m.state, MC_INA_FAULT);

    /* A configuration bit that does not read back is a read-back fault. */
    mon_init(&s);
    s.config_stuck_bits = 0x0001u;
    t = 0;
    mc_ina228_init(&m, &TEST_INA, &MON_SET, mon_read, mon_write, &s, 1, t);
    ina_bring_up(&m, &t);
    CHECK_EQ_INT(m.state, MC_INA_FAULT);
    CHECK_EQ_INT(m.error, MC_INA_ERR_READBACK);

    /* A shunt calibration outside the register range: a settings error, never retried. */
    mc_ina228_settings_t bad = MON_SET;
    bad.shunt_ohm = 100.0f; /* 1e6 x 0.001 x 100 = 100000 > 0x7FFF */
    mon_init(&s);
    mc_ina228_init(&m, &TEST_INA, &bad, mon_read, mon_write, &s, 3, 0);
    CHECK_EQ_INT(m.error, MC_INA_ERR_SETTINGS);
    mc_ina228_step(&m, 10u * MC_INA_RETRY_US);
    CHECK_EQ_INT(m.state, MC_INA_FAULT);
    CHECK_EQ_INT(s.reads + s.writes, 0);
}

/* ------------------------------------------------------------------ simulated gate driver */
/* Test frame: bit 15 read flag, bits 14..11 address, bits 10..0 data; read data in the same frame. */
static const mc_drv835x_desc_t TEST_DRV = {
    .source = "TEST MAP (not the DRV8353)", .verified = true, .read_flag = 0x8000u, .addr_shift = 11,
    .addr_mask = 0x0Fu, .data_mask = 0x07FFu, .response_in_same_frame = true, .n_status = 2,
    .status_addr = {0x0, 0x1}, .status_fault_mask = {0x07FFu, 0x07FFu}, .clear_addr = 0x2, .clear_bit = 0x0001u,
    .t_wake_us = 1000u, .t_clear_us = 100u};

static const mc_drv835x_settings_t DRV_SET = {.n = 3,
                                              .addr = {0x2, 0x3, 0x4},
                                              .value = {0x0020u, 0x0344u, 0x0155u},
                                              .verify_mask = {0x07FEu, 0x07FFu, 0x07FFu}};

typedef struct {
    uint16_t reg[16];
    int fail; /* next n frames fail */
    int frames;
    bool awake;
    uint16_t stuck_and[16]; /* bits that read as 0 */
} sim_drv_t;

static int drv_xfer(void *ctx, uint16_t tx, uint16_t *rx)
{
    sim_drv_t *s = ctx;
    s->frames++;
    if (s->fail > 0) {
        s->fail--;
        return -1;
    }
    const uint8_t a = (uint8_t)((tx >> 11) & 0x0Fu);
    if (tx & 0x8000u) {
        *rx = (uint16_t)(s->reg[a] & (uint16_t)~s->stuck_and[a]);
        return 0;
    }
    uint16_t v = tx & 0x07FFu;
    if (a == 0x2 && (v & 0x0001u)) { /* clear-fault: self-clearing, clears the status words */
        s->reg[0] = s->reg[1] = 0;
        v &= (uint16_t)~0x0001u;
    }
    if (a >= 2) s->reg[a] = v;
    *rx = 0;
    return 0;
}

static void drv_run(mc_drv835x_t *m, mc_time_us_t *t, int steps, bool awake, bool nfault)
{
    for (int i = 0; i < steps; i++) {
        mc_drv835x_step(m, *t, awake, nfault);
        *t += 1000u;
    }
}

static void test_drv_unverified_keeps_enable_low(void)
{
    sim_drv_t s;
    memset(&s, 0, sizeof s);
    mc_drv835x_t m;
    mc_time_us_t t = 0;
    mc_drv835x_init(&m, NULL, &DRV_SET, drv_xfer, &s, t);
    drv_run(&m, &t, 20, true, false);
    CHECK_EQ_INT(m.state, MC_DRV_UNVERIFIED);
    CHECK(!m.enable_pin && !mc_drv835x_ready(&m));
    CHECK_EQ_INT(s.frames, 0);
    mc_drv835x_settings_t bad = DRV_SET;
    bad.value[1] = 0x0800u; /* outside the data field */
    mc_drv835x_init(&m, &TEST_DRV, &bad, drv_xfer, &s, t);
    CHECK_EQ_INT(m.state, MC_DRV_UNVERIFIED);
    mc_drv835x_desc_t overlap = TEST_DRV;
    overlap.addr_shift = 10; /* address field overlaps the data field */
    mc_drv835x_init(&m, &overlap, &DRV_SET, drv_xfer, &s, t);
    CHECK_EQ_INT(m.state, MC_DRV_UNVERIFIED);
}

static void test_drv_wake_configure_readback_clear(void)
{
    sim_drv_t s;
    memset(&s, 0, sizeof s);
    s.reg[1] = 0x0004u; /* a power-up fault latched in the status register */
    mc_drv835x_t m;
    mc_time_us_t t = 0;
    mc_drv835x_init(&m, &TEST_DRV, &DRV_SET, drv_xfer, &s, t);
    drv_run(&m, &t, 3, false, false);
    CHECK_EQ_INT(m.state, MC_DRV_SLEEP);
    CHECK(!m.enable_pin);
    CHECK_EQ_INT(s.frames, 0);
    mc_drv835x_step(&m, t, true, true); /* nFAULT low during wake-up is expected */
    CHECK(m.enable_pin);
    CHECK_EQ_INT(m.state, MC_DRV_WAKING);
    mc_drv835x_step(&m, t + 999u, true, true);
    CHECK_EQ_INT(m.state, MC_DRV_WAKING); /* no SPI before the wake-up time */
    CHECK_EQ_INT(s.frames, 0);
    t += 1000u;
    mc_drv835x_step(&m, t, true, true);
    CHECK_EQ_INT(m.state, MC_DRV_CONFIGURE);
    mc_drv835x_step(&m, t, true, true);
    CHECK_EQ_INT(m.state, MC_DRV_CLEARING);
    CHECK_EQ_INT(s.reg[3], 0x0344u);
    CHECK_EQ_INT(s.reg[2], 0x0020u); /* the clear-fault bit was written with the register's value */
    CHECK_EQ_INT(s.reg[1], 0);
    mc_drv835x_step(&m, t + 50u, true, false);
    CHECK_EQ_INT(m.state, MC_DRV_CLEARING); /* waits t_clear */
    mc_drv835x_step(&m, t + 100u, true, false);
    CHECK_EQ_INT(m.state, MC_DRV_READY);
    CHECK(mc_drv835x_ready(&m));

    /* READY re-reads one setting per step: a register that lost its value is found within n steps. */
    s.reg[4] = 0;
    t += 1000u;
    drv_run(&m, &t, 3, true, false);
    CHECK_EQ_INT(m.state, MC_DRV_FAULT);
    CHECK_EQ_INT(m.error, MC_DRV_ERR_READBACK);
    CHECK_EQ_INT(m.mismatch_index, 2);
    CHECK(!mc_drv835x_ready(&m));
}

static void test_drv_faults_and_clear_on_request_only(void)
{
    sim_drv_t s;
    memset(&s, 0, sizeof s);
    mc_drv835x_t m;
    mc_time_us_t t = 0;
    mc_drv835x_init(&m, &TEST_DRV, &DRV_SET, drv_xfer, &s, t);
    drv_run(&m, &t, 4, true, false);
    CHECK(mc_drv835x_ready(&m));

    s.reg[0] = 0x0010u; /* a fault bit in the first status word */
    drv_run(&m, &t, 1, true, true);
    CHECK_EQ_INT(m.state, MC_DRV_FAULT);
    CHECK_EQ_INT(m.error, MC_DRV_ERR_FAULT_BITS);
    CHECK_EQ_INT(m.status[0], 0x0010u);
    s.reg[0] = 0;
    drv_run(&m, &t, 10, true, false); /* the cause is gone, but nothing clears without a request */
    CHECK_EQ_INT(m.state, MC_DRV_FAULT);
    CHECK(m.enable_pin); /* left high in FAULT so the status stays readable */
    mc_drv835x_request_clear(&m);
    drv_run(&m, &t, 3, true, false); /* re-configure, read back, clear, then READY */
    CHECK(mc_drv835x_ready(&m));

    /* nFAULT asserted with clean status words is still a fault. */
    drv_run(&m, &t, 1, true, true);
    CHECK_EQ_INT(m.error, MC_DRV_ERR_NFAULT);
    /* A clear while nFAULT stays low ends in NOT_CLEARED. */
    mc_drv835x_request_clear(&m);
    drv_run(&m, &t, 3, true, true);
    CHECK_EQ_INT(m.state, MC_DRV_FAULT);
    CHECK_EQ_INT(m.error, MC_DRV_ERR_NOT_CLEARED);

    /* SPI: one failed status read withdraws ready; three in a row are a fault. */
    mc_drv835x_request_clear(&m);
    drv_run(&m, &t, 3, true, false);
    CHECK(mc_drv835x_ready(&m));
    s.fail = 1;
    drv_run(&m, &t, 1, true, false);
    CHECK_EQ_INT(m.state, MC_DRV_READY);
    CHECK(!mc_drv835x_ready(&m));
    drv_run(&m, &t, 1, true, false);
    CHECK(mc_drv835x_ready(&m));
    s.fail = 3;
    drv_run(&m, &t, 3, true, false);
    CHECK_EQ_INT(m.state, MC_DRV_FAULT);
    CHECK_EQ_INT(m.error, MC_DRV_ERR_SPI);

    /* Not wanted awake: ENABLE low, the fault stays latched. */
    drv_run(&m, &t, 1, false, false);
    CHECK(!m.enable_pin);
    CHECK_EQ_INT(m.state, MC_DRV_FAULT);
    /* A clear while asleep goes to SLEEP; the next wake-up re-runs the whole sequence. */
    mc_drv835x_request_clear(&m);
    drv_run(&m, &t, 1, false, false);
    CHECK_EQ_INT(m.state, MC_DRV_SLEEP);
    drv_run(&m, &t, 5, true, false);
    CHECK(mc_drv835x_ready(&m));
    /* A configuration bit that never reads back: READBACK during configuration. */
    s.stuck_and[3] = 0x0100u;
    drv_run(&m, &t, 1, false, false);
    drv_run(&m, &t, 3, true, false);
    CHECK_EQ_INT(m.error, MC_DRV_ERR_READBACK);
    CHECK_EQ_INT(m.mismatch_index, 1);
}

/* ------------------------------------------------------------------ start-up sequence */
static const mc_startup_params_t SU_P = {.fraction = 0.95f, .timeout_s = 0.5f, .uv_trip_V = 30.0f,
                                         .ov_trip_V = 60.0f, .r_pre_ohm = 50.0f, .agreement_V = 1.0f, .sample_max_age_s = 0.05f,
                                         .step_timeout_s = 0.2f, .max_attempts = 2u};

static mc_startup_in_t su_in_ok(void)
{
    mc_startup_in_t in;
    memset(&in, 0, sizeof in);
    in.config_ok = true;
    in.drv_state = MC_DRV_SLEEP;
    in.ina_state = MC_INA_RUNNING;
    in.v_batt_V = 48.0f;
    in.v_batt_ok = true;
    in.i_batt_A = 0.0f;
    in.i_batt_ok = true;
    in.v_link_V = 0.0f;
    in.v_link_ok = true;
    in.outputs_off = true;
    return in;
}

static void su_run(mc_startup_t *s, mc_startup_in_t *in, int ms)
{
    for (int i = 0; i < ms; i++) mc_startup_step(s, 1e-3f, in);
}

/* The link charging through the precharge resistor, consistent with the battery-side current. */
static void su_link(mc_startup_in_t *in, float v_link)
{
    in->v_link_V = v_link;
    in->i_batt_A = (in->v_batt_V - v_link) / SU_P.r_pre_ohm;
}

static void su_to_ready(mc_startup_t *s, mc_startup_in_t *in)
{
    su_run(s, in, 2);
    su_link(in, 46.0f);
    su_run(s, in, 1);
    in->drv_state = MC_DRV_READY;
    in->drv_ready = true;
    su_run(s, in, 1);
    in->offsets_done_seq = s->offsets_req_seq;
    in->offsets_ok = true;
    su_run(s, in, 1);
}

static void test_startup_inhibited_until_every_prerequisite(void)
{
    mc_startup_t s;
    mc_startup_init(&s, &SU_P);
    mc_startup_in_t in = su_in_ok();
    in.drv_state = MC_DRV_UNVERIFIED; /* the firmware as delivered: no descriptions */
    in.ina_state = MC_INA_UNVERIFIED;
    in.v_batt_ok = false;
    su_link(&in, 47.9f);
    su_run(&s, &in, 1000);
    CHECK_EQ_INT(s.state, MC_SU_INHIBITED);
    CHECK_EQ_INT(s.missing, MC_SU_MISSING_DRIVER | MC_SU_MISSING_METER);
    CHECK(!s.bypass && !s.want_driver_awake && !s.gate_driver_ready);
    mc_startup_params_t p = SU_P;
    p.r_pre_ohm = NAN; /* the resistor is not selected */
    mc_startup_init(&s, &p);
    in = su_in_ok();
    in.config_ok = false;
    su_run(&s, &in, 10);
    CHECK_EQ_INT(s.missing, MC_SU_MISSING_PARAMS | MC_SU_MISSING_CONFIG);
    CHECK(!s.bypass);
}

static void test_startup_order_and_permission(void)
{
    mc_startup_t s;
    mc_startup_init(&s, &SU_P);
    mc_startup_in_t in = su_in_ok();
    su_run(&s, &in, 2);
    CHECK_EQ_INT(s.state, MC_SU_PRECHARGE);
    CHECK_EQ_INT(s.pc.state, MC_PC_CHARGING);
    CHECK(!s.want_driver_awake); /* VM is the link: the driver sleeps while it charges */
    su_link(&in, 40.0f);
    su_run(&s, &in, 50);
    CHECK(!s.bypass);
    su_link(&in, 46.0f);
    su_run(&s, &in, 1);
    CHECK_EQ_INT(s.state, MC_SU_DRIVER);
    CHECK(s.bypass && s.want_driver_awake && !s.gate_driver_ready);
    in.drv_state = MC_DRV_CONFIGURE;
    su_run(&s, &in, 10);
    CHECK(!s.request_offsets);
    in.drv_state = MC_DRV_READY;
    in.drv_ready = true;
    su_run(&s, &in, 1);
    CHECK_EQ_INT(s.state, MC_SU_OFFSETS);
    CHECK(s.request_offsets && !s.gate_driver_ready);
    in.offsets_done_seq = s.offsets_req_seq - 1u; /* an older measurement is not this one */
    in.offsets_ok = true;
    su_run(&s, &in, 5);
    CHECK_EQ_INT(s.state, MC_SU_OFFSETS);
    in.offsets_done_seq = s.offsets_req_seq;
    su_run(&s, &in, 1);
    CHECK_EQ_INT(s.state, MC_SU_READY);
    CHECK(s.gate_driver_ready);
    in.drv_ready = false; /* one failed status read */
    su_run(&s, &in, 1);
    CHECK(!s.gate_driver_ready);
    in.drv_ready = true;
    in.v_batt_ok = false; /* battery sample stale: bypass stays closed, permission withdrawn */
    su_run(&s, &in, 1);
    CHECK(s.bypass && !s.gate_driver_ready);
    in.v_batt_ok = true;
    su_run(&s, &in, 1);
    CHECK(s.gate_driver_ready);
}

static void test_startup_never_closes_on_bad_measurements(void)
{
    mc_startup_t s;
    mc_startup_in_t in;
    /* Stale or invalid battery sample: no closure, however charged the link reads. */
    mc_startup_init(&s, &SU_P);
    in = su_in_ok();
    in.v_batt_ok = false;
    su_link(&in, 47.5f);
    su_run(&s, &in, 2000);
    CHECK(!s.bypass);
    CHECK_EQ_INT(s.pc.state, MC_PC_WAIT_BATTERY);

    /* Battery current missing at the closing point: no closure, then the precharge timeout. */
    mc_startup_init(&s, &SU_P);
    in = su_in_ok();
    su_run(&s, &in, 2);
    su_link(&in, 46.0f);
    in.i_batt_ok = false;
    su_run(&s, &in, 400);
    CHECK(!s.bypass);
    su_run(&s, &in, 200);
    CHECK_EQ_INT(s.state, MC_SU_FAULT);
    CHECK_EQ_INT(s.pc.fault, MC_PCF_TIMEOUT);

    /* Link sensor stuck high while the link is empty: the resistor current says 0 V. */
    mc_startup_init(&s, &SU_P);
    in = su_in_ok();
    su_run(&s, &in, 2);
    in.v_link_V = 47.0f;
    in.i_batt_A = 48.0f / SU_P.r_pre_ohm;
    su_run(&s, &in, 1);
    CHECK_EQ_INT(s.state, MC_SU_FAULT);
    CHECK_EQ_INT(s.pc.fault, MC_PCF_SENSOR_DISAGREE);
    CHECK(!s.bypass);

    /* Battery reading 3 V low: the link reaches 95 % of the wrong value early; the current disagrees. */
    mc_startup_init(&s, &SU_P);
    in = su_in_ok();
    su_run(&s, &in, 2);
    in.v_batt_V = 45.0f;            /* reported */
    in.v_link_V = 43.0f;            /* real, above 0.95 x 45 */
    in.i_batt_A = (48.0f - 43.0f) / SU_P.r_pre_ohm; /* real current from the real 48 V */
    su_run(&s, &in, 1);
    CHECK_EQ_INT(s.pc.fault, MC_PCF_SENSOR_DISAGREE);

    /* Battery side above the overvoltage trip: treated as absent. */
    mc_startup_init(&s, &SU_P);
    in = su_in_ok();
    in.v_batt_V = 70.0f;
    su_link(&in, 69.0f);
    su_run(&s, &in, 100);
    CHECK(!s.bypass);
    CHECK_EQ_INT(s.pc.state, MC_PC_WAIT_BATTERY);
}

static void test_startup_timeouts_disconnect_attempts_lockout(void)
{
    mc_startup_t s;
    mc_startup_init(&s, &SU_P);
    mc_startup_in_t in = su_in_ok();
    su_run(&s, &in, 2);
    su_link(&in, 46.0f);
    su_run(&s, &in, 1);
    in.drv_state = MC_DRV_CONFIGURE;
    su_run(&s, &in, 190);
    CHECK_EQ_INT(s.state, MC_SU_DRIVER);
    su_run(&s, &in, 20);
    CHECK_EQ_INT(s.state, MC_SU_FAULT);
    CHECK_EQ_INT(s.fault, MC_SU_F_DRIVER_TIMEOUT);
    CHECK(s.bypass); /* the link stays connected: opening it is no safer with the outputs off */

    /* Clear needs the outputs off. */
    in.fault_reset_edge = true;
    in.outputs_off = false;
    su_run(&s, &in, 1);
    CHECK_EQ_INT(s.state, MC_SU_FAULT);
    in.outputs_off = true;
    su_run(&s, &in, 1); /* attempt 1 */
    in.fault_reset_edge = false;
    CHECK_EQ_INT(s.state, MC_SU_DRIVER);
    in.drv_state = MC_DRV_FAULT;
    su_run(&s, &in, 1);
    CHECK_EQ_INT(s.fault, MC_SU_F_DRIVER);
    in.fault_reset_edge = true;
    su_run(&s, &in, 1); /* attempt 2, with a driver clear request */
    in.fault_reset_edge = false;
    CHECK(s.clear_driver);
    in.drv_state = MC_DRV_WAKING;
    su_run(&s, &in, 1);
    CHECK(!s.clear_driver);
    in.drv_state = MC_DRV_READY;
    in.drv_ready = true;
    su_run(&s, &in, 1);
    su_run(&s, &in, 201); /* offsets never measured */
    CHECK_EQ_INT(s.fault, MC_SU_F_OFFSETS);
    in.fault_reset_edge = true;
    su_run(&s, &in, 1); /* a third clear: attempts used up */
    CHECK_EQ_INT(s.state, MC_SU_LOCKOUT);
    su_run(&s, &in, 100);
    CHECK_EQ_INT(s.state, MC_SU_LOCKOUT);
    CHECK(!s.gate_driver_ready);

    /* Battery disconnected while READY: back to PRECHARGE, driver asleep, no fault. */
    mc_startup_init(&s, &SU_P);
    in = su_in_ok();
    su_to_ready(&s, &in);
    CHECK_EQ_INT(s.state, MC_SU_READY);
    in.v_batt_V = 5.0f;
    su_link(&in, 5.0f);
    su_run(&s, &in, 1);
    CHECK_EQ_INT(s.state, MC_SU_PRECHARGE);
    CHECK(!s.bypass && !s.want_driver_awake && !s.gate_driver_ready);
    CHECK_EQ_INT(s.fault, MC_SU_F_NONE);
    /* Reconnected: the whole sequence runs again with a new offsets request. */
    const uint32_t req = s.offsets_req_seq;
    in.v_batt_V = 48.0f;
    in.drv_state = MC_DRV_SLEEP;
    in.drv_ready = false;
    su_to_ready(&s, &in);
    CHECK_EQ_INT(s.state, MC_SU_READY);
    CHECK_EQ_INT(s.offsets_req_seq, req + 1u);

    /* Link sagging after closure (a bypass that does not conduct under load): precharge fault. */
    su_link(&in, 30.0f);
    su_run(&s, &in, 1);
    CHECK(!s.gate_driver_ready);
    su_run(&s, &in, 600);
    CHECK_EQ_INT(s.state, MC_SU_FAULT);
    CHECK_EQ_INT(s.pc.fault, MC_PCF_LINK_LOW_AFTER_CLOSE);
    CHECK(!s.bypass);
}

int main(void)
{
    RUN(test_ina_unverified_never_touches_bus);
    RUN(test_ina_bring_up_scaling_and_sign);
    RUN(test_ina_sample_ages_without_new_conversion);
    RUN(test_ina_bus_errors_identity_readback_and_retries);
    RUN(test_drv_unverified_keeps_enable_low);
    RUN(test_drv_wake_configure_readback_clear);
    RUN(test_drv_faults_and_clear_on_request_only);
    RUN(test_startup_inhibited_until_every_prerequisite);
    RUN(test_startup_order_and_permission);
    RUN(test_startup_never_closes_on_bad_measurements);
    RUN(test_startup_timeouts_disconnect_attempts_lockout);
    TEST_MAIN_END();
}

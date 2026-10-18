/* Host tests for the portable target-support code: measurement scaling, pedal plausibility,
 * precharge sequencing, and register timing values (src/io). Reference values are computed by
 * hand in the comments; the clock and bit-rate cases are the ones in hardware/timing/. */
#include <math.h>
#include <string.h>

#include "mc_test.h"
#include "semmc/mc_io.h"
#include "semmc/mc_periph_timing.h"
#include "semmc/mc_precharge.h"

static void test_ntc_conversion_and_open_short(void)
{
    mc_ntc_t n;
    mc_validity_t v;
    mc_ntc_init(&n, 10000.0f, 3435.0f, 10000.0f);
    CHECK(n.configured);
    CHECK_NEAR(mc_ntc_temp_degC(&n, 0.5f, &v), 25.0f, 0.01f); /* R = bias = R25 */
    CHECK(v == MC_VAL_OK);
    /* 85 degC: R = 10k exp(3435 (1/358.15 - 1/298.15)) = 1.4523 k; ratio = R / (R + 10k) */
    const double r85 = 10000.0 * exp(3435.0 * (1.0 / 358.15 - 1.0 / 298.15));
    CHECK_NEAR(mc_ntc_temp_degC(&n, (float)(r85 / (r85 + 10000.0)), &v), 85.0f, 0.05f);
    (void)mc_ntc_temp_degC(&n, 0.005f, &v);
    CHECK(v == MC_VAL_OUT_OF_RANGE); /* shorted */
    (void)mc_ntc_temp_degC(&n, 0.995f, &v);
    CHECK(v == MC_VAL_OUT_OF_RANGE); /* open */
    mc_ntc_init(&n, NAN, 3435.0f, 10000.0f);
    CHECK(!n.configured);
    CHECK(isnan(mc_ntc_temp_degC(&n, 0.5f, &v)) && v == MC_VAL_MISSING);
}

static void test_pedal_two_tracks(void)
{
    mc_pedal_t p;
    mc_pedal_out_t o;
    const float div = 28.0f / 18.0f; /* sheet 10: 10k series, 18k to ground */
    /* Track A rises 0.5 -> 4.5 V, track B falls 4.5 -> 0.5 V (a common redundant layout). */
    mc_pedal_init(&p, 0.5f, 4.5f, 4.5f, 0.5f, 0.1f, div);
    CHECK(p.configured);
    mc_pedal_eval(&p, 2.5f / div, 2.5f / div, &o);
    CHECK(o.valid);
    CHECK_NEAR(o.throttle, 0.5f, 1e-4f);
    mc_pedal_eval(&p, 4.1f / div, 0.9f / div, &o); /* both at 90 % */
    CHECK(o.valid);
    CHECK_NEAR(o.throttle, 0.9f, 1e-4f);
    mc_pedal_eval(&p, 2.5f / div, 1.3f / div, &o); /* A 50 %, B 80 %: disagree */
    CHECK(!o.valid && o.throttle == 0.0f);
    mc_pedal_eval(&p, 0.0f, 4.5f / div, &o); /* A open wire reads 0 V: -12.5 % */
    CHECK(!o.valid && o.throttle == 0.0f);
    mc_pedal_eval(&p, 2.6f / div, 2.5f / div, &o); /* within tolerance: the lower track wins */
    CHECK(o.valid);
    CHECK_NEAR(o.throttle, 0.5f, 1e-4f);
    mc_pedal_init(&p, NAN, 4.5f, 4.5f, 0.5f, 0.1f, div);
    mc_pedal_eval(&p, 2.5f / div, 2.5f / div, &o);
    CHECK(!p.configured && !o.valid);
    mc_pedal_init(&p, 0.5f, 0.5f, 4.5f, 0.5f, 0.1f, div); /* zero span */
    CHECK(!p.configured);
}

static void test_adc_scaling_offsets_and_vbus(void)
{
    mc_adc_scale_t s;
    const float off[3] = {2048.0f, 2050.0f, 2046.0f};
    mc_adc_scale_init(&s, 3.3f, 12.0f, 0.001f, 20.0f, 0.0f, off, 8.0f, 20.0f);
    CHECK(s.current_configured && s.vbus_configured);
    /* 100 counts above offset = 100 x 3.3/4096 V = 80.57 mV at the amplifier = 4.028 mV at the shunt = 4.028 A */
    CHECK_NEAR(mc_adc_phase_A(&s, 0, 2148u), 4.0283f, 1e-3f);
    mc_adc_scale_init(&s, 3.3f, 12.0f, 0.001f, 20.0f, 1.0f, off, 8.0f, 20.0f);
    CHECK_NEAR(mc_adc_phase_A(&s, 0, 2148u), -4.0283f, 1e-3f);
    mc_validity_t v;
    CHECK_NEAR(mc_adc_vbus_V(&s, 2048u, &v), 33.0f, 1e-3f);
    CHECK(v == MC_VAL_OK);
    (void)mc_adc_vbus_V(&s, 4095u, &v);
    CHECK(v == MC_VAL_SATURATED);
    const float good[3] = {2051.0f, 2047.0f, 2040.0f};
    CHECK(mc_adc_accept_offsets(&s, good));
    CHECK(s.offset[2] == 2040.0f);
    const float bad[3] = {2051.0f, 2047.0f, 2030.0f}; /* phase C 16 counts away */
    CHECK(!mc_adc_accept_offsets(&s, bad));
    CHECK(s.offset[0] == 2048.0f && s.offset[2] == 2046.0f);
    mc_adc_scale_init(&s, 3.3f, 12.0f, 0.001f, 20.0f, NAN, off, 8.0f, 20.0f);
    CHECK(!s.current_configured);
    CHECK(!mc_adc_accept_offsets(&s, good));
    mc_adc_scale_init(&s, 3.3f, 12.0f, 0.001f, 20.0f, 0.0f, off, 8.0f, NAN);
    (void)mc_adc_vbus_V(&s, 2048u, &v);
    CHECK(v == MC_VAL_MISSING);
}

static void test_lowside_sampling_window(void)
{
    /* 200 ns dead time, 1 us settle, 20 kHz: d_max = 1 - 2 x 1.2 us x 20 kHz = 0.952 */
    const mc_duty_t d = {0.5f, 0.96f, 0.2f};
    CHECK_EQ_INT(mc_lowside_sample_mask(&d, true, 200e-9f, 1e-6f, 20000.0f), MC_PH_A | MC_PH_C);
    CHECK_EQ_INT(mc_lowside_sample_mask(&d, false, 200e-9f, 1e-6f, 20000.0f), MC_PH_A | MC_PH_B | MC_PH_C);
    CHECK_EQ_INT(mc_lowside_sample_mask(&d, true, NAN, 1e-6f, 20000.0f), 0);
}

static void test_enable_path_check(void)
{
    mc_enable_check_t e;
    memset(&e, 0, sizeof e);
    CHECK(!mc_enable_path_check(&e, false, true, false));
    CHECK(!mc_enable_path_check(&e, true, true, true));
    CHECK(!mc_enable_path_check(&e, true, false, true)); /* one mismatch: may be an edge in flight */
    CHECK(!mc_enable_path_check(&e, true, false, false));
    CHECK(!mc_enable_path_check(&e, false, false, true));
    CHECK(mc_enable_path_check(&e, false, false, true)); /* two in a row: gated high with the MCU low */
    CHECK(mc_enable_path_check(&e, false, false, false)); /* latched */
}

static void run_pc(mc_precharge_t *p, int ms, float vl, bool vl_ok, float vb, bool vb_ok)
{
    for (int i = 0; i < ms; i++) mc_precharge_step(p, 1e-3f, vl, vl_ok, vb, vb_ok);
}

static void test_precharge_sequence(void)
{
    mc_precharge_t p;
    mc_precharge_init(&p, 0.95f, 0.5f, 30.0f);
    CHECK_EQ_INT(p.state, MC_PC_WAIT_BATTERY);
    run_pc(&p, 10, 0.0f, true, 0.0f, true);
    CHECK_EQ_INT(p.state, MC_PC_WAIT_BATTERY);
    CHECK(!p.bypass);
    run_pc(&p, 1, 0.0f, true, 48.0f, true);
    CHECK_EQ_INT(p.state, MC_PC_CHARGING);
    run_pc(&p, 100, 40.0f, true, 48.0f, true); /* 83 %: still charging */
    CHECK_EQ_INT(p.state, MC_PC_CHARGING);
    CHECK(!p.bypass);
    run_pc(&p, 1, 45.7f, true, 48.0f, true); /* 95.2 % */
    CHECK_EQ_INT(p.state, MC_PC_CLOSED);
    CHECK(p.bypass && p.ready);
    run_pc(&p, 5, 47.9f, true, 48.0f, false); /* battery meter lost: stays closed, not ready */
    CHECK(p.bypass && !p.ready);
    run_pc(&p, 400, 30.0f, true, 48.0f, true); /* link sagging below 95 %: not ready ... */
    CHECK(p.bypass && !p.ready);
    run_pc(&p, 200, 30.0f, true, 48.0f, true); /* ... and a fault once it lasts beyond the timeout */
    CHECK_EQ_INT(p.state, MC_PC_FAULT);
    CHECK_EQ_INT(p.fault, MC_PCF_LINK_LOW_AFTER_CLOSE);
    CHECK(!p.bypass && !p.ready);
    run_pc(&p, 10, 48.0f, true, 48.0f, true);
    CHECK_EQ_INT(p.state, MC_PC_FAULT); /* latched */
    mc_precharge_reset(&p);
    CHECK_EQ_INT(p.state, MC_PC_WAIT_BATTERY);
}

static void test_precharge_timeout_disconnect_and_missing_meter(void)
{
    mc_precharge_t p;
    mc_precharge_init(&p, 0.95f, 0.5f, 30.0f);
    run_pc(&p, 1, 0.0f, true, 48.0f, true);
    run_pc(&p, 499, 10.0f, true, 48.0f, true);
    CHECK_EQ_INT(p.state, MC_PC_CHARGING);
    run_pc(&p, 2, 10.0f, true, 48.0f, true);
    CHECK_EQ_INT(p.state, MC_PC_FAULT);
    CHECK_EQ_INT(p.fault, MC_PCF_TIMEOUT);

    mc_precharge_init(&p, 0.95f, 0.5f, 30.0f);
    run_pc(&p, 1, 0.0f, true, 48.0f, true);
    run_pc(&p, 1, 46.0f, true, 48.0f, true);
    CHECK_EQ_INT(p.state, MC_PC_CLOSED);
    run_pc(&p, 1, 2.0f, true, 2.0f, true); /* isolation opened */
    CHECK_EQ_INT(p.state, MC_PC_WAIT_BATTERY);
    CHECK(!p.bypass);

    /* Battery-side meter never available (INA228 not read in this firmware revision): never closes, no fault. */
    mc_precharge_init(&p, 0.95f, 0.5f, 30.0f);
    run_pc(&p, 2000, 48.0f, true, NAN, false);
    CHECK_EQ_INT(p.state, MC_PC_WAIT_BATTERY);
    CHECK(!p.bypass && !p.ready);

    mc_precharge_init(&p, NAN, 0.5f, 30.0f); /* calibration missing */
    run_pc(&p, 10, 48.0f, true, 48.0f, true);
    CHECK_EQ_INT(p.state, MC_PC_DISABLED);
    CHECK(!p.bypass);
}

static void test_can_bit_timing(void)
{
    mc_can_timing_t t;
    /* 16 MHz kernel (hardware/timing/clock_tree_alternatives.md): 500k = 1 / 32 tq, TSEG1 27, TSEG2 4, 87.5 % */
    CHECK(mc_can_timing_compute(16000000u, 500000u, 0.875f, &t));
    CHECK_EQ_INT(t.brp, 1);
    CHECK_EQ_INT(t.tq_per_bit, 32);
    CHECK_EQ_INT(t.tseg1, 27);
    CHECK_EQ_INT(t.tseg2, 4);
    CHECK_EQ_INT(t.sjw, 4);
    CHECK_NEAR(t.sample_point, 0.875f, 1e-6f);
    CHECK(mc_can_timing_compute(16000000u, 1000000u, 0.875f, &t));
    CHECK_EQ_INT(t.tq_per_bit, 16);
    CHECK_EQ_INT(t.tseg1, 13);
    CHECK_EQ_INT(t.tseg2, 2);
    CHECK(mc_can_timing_compute(16000000u, 250000u, 0.875f, &t));
    CHECK_EQ_INT(t.tq_per_bit, 64);
    CHECK(mc_can_timing_compute(16000000u, 125000u, 0.875f, &t));
    CHECK_EQ_INT(t.tq_per_bit, 128);
    CHECK_EQ_INT(t.tseg1, 111);
    /* 170 MHz: 340 tq at prescaler 1 would need TSEG1 296 > 256; prescaler 2 gives 170 tq, 149/170 = 87.6 % */
    CHECK(mc_can_timing_compute(170000000u, 500000u, 0.875f, &t));
    CHECK_EQ_INT(t.brp, 2);
    CHECK_EQ_INT(t.tq_per_bit, 170);
    CHECK_NEAR(t.sample_point, 149.0f / 170.0f, 1e-6f);
    CHECK(!mc_can_timing_compute(16000000u, 333333u, 0.875f, &t)); /* not exact */
    CHECK(!mc_can_timing_compute(16000000u, 0u, 0.875f, &t));
}

static void test_tim1_arr_and_dead_time(void)
{
    uint32_t arr;
    float f;
    CHECK(mc_tim_center_arr(160000000u, 20000.0f, &arr, &f));
    CHECK_EQ_INT(arr, 4000);
    CHECK_NEAR(f, 20000.0f, 1e-3f);
    CHECK(!mc_tim_center_arr(160000000u, 1000.0f, &arr, &f)); /* 80000 > 16 bits */
    CHECK(!mc_tim_center_arr(160000000u, 900000.0f, &arr, &f)); /* < 100 counts */
    CHECK(!mc_tim_center_arr(160000000u, NAN, &arr, &f));
    uint8_t dtg;
    float dt;
    CHECK(mc_tim_dtg_encode(200e-9f, 160000000u, &dtg, &dt)); /* 32 x 6.25 ns */
    CHECK_EQ_INT(dtg, 32);
    CHECK_NEAR(dt, 200e-9f, 1e-15f);
    CHECK(mc_tim_dtg_encode(1e-6f, 160000000u, &dtg, &dt)); /* 160 ticks: (64 + 16) x 2 */
    CHECK_EQ_INT(dtg, 0x90);
    CHECK_NEAR(dt, 1e-6f, 1e-14f);
    CHECK(mc_tim_dtg_encode(805e-9f, 160000000u, &dtg, &dt)); /* 128.8 ticks -> 130: never shorter */
    CHECK_EQ_INT(dtg, 0x81);
    CHECK(dt >= 805e-9f);
    CHECK(mc_tim_dtg_encode(2e-6f, 160000000u, &dtg, &dt)); /* 320 ticks: (32 + 8) x 8 */
    CHECK_EQ_INT(dtg, 0xC8);
    CHECK(mc_tim_dtg_encode(5e-6f, 160000000u, &dtg, &dt)); /* 800 ticks: (32 + 18) x 16 */
    CHECK_EQ_INT(dtg, 0xF2);
    CHECK(!mc_tim_dtg_encode(7e-6f, 160000000u, &dtg, &dt)); /* 1120 > 1008 */
}

int main(void)
{
    RUN(test_ntc_conversion_and_open_short);
    RUN(test_pedal_two_tracks);
    RUN(test_adc_scaling_offsets_and_vbus);
    RUN(test_lowside_sampling_window);
    RUN(test_enable_path_check);
    RUN(test_precharge_sequence);
    RUN(test_precharge_timeout_disconnect_and_missing_meter);
    RUN(test_can_bit_timing);
    RUN(test_tim1_arr_and_dead_time);
    TEST_MAIN_END();
}

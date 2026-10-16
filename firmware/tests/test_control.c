/* Host tests: PI, transforms, voltage/current limits, SVPWM, currents, hall. */
#include <math.h>
#include <string.h>

#include "mc_test.h"
#include "semmc/mc_control.h"

static void test_clarke_park_roundtrip(void)
{
    /* Balanced currents of peak 10 A at angle th: amplitude-invariant => |dq| = 10. */
    for (int k = 0; k < 36; k++) {
        const float th = (float)k * MC_TWO_PI_F / 36.0f;
        const float ia = 10.0f * cosf(th);
        const float ib = 10.0f * cosf(th - MC_TWO_PI_F / 3.0f);
        const float ic = 10.0f * cosf(th + MC_TWO_PI_F / 3.0f);
        const mc_ab_t ab2 = mc_clarke2(ia, ib);
        const mc_ab_t ab3 = mc_clarke3(ia, ib, ic);
        CHECK_NEAR(ab2.alpha, ab3.alpha, 1e-4);
        CHECK_NEAR(ab2.beta, ab3.beta, 1e-4);
        /* Rotor aligned with the current vector: all current on d. */
        const mc_dq_t dq = mc_park(ab3, sinf(th), cosf(th));
        CHECK_NEAR(dq.d, 10.0f, 1e-3);
        CHECK_NEAR(dq.q, 0.0f, 1e-3);
        const mc_ab_t back = mc_inv_park(dq, sinf(th), cosf(th));
        CHECK_NEAR(back.alpha, ab3.alpha, 1e-3);
        CHECK_NEAR(back.beta, ab3.beta, 1e-3);
        const mc_abc_t abc = mc_inv_clarke(back);
        CHECK_NEAR(abc.a, ia, 1e-3);
        CHECK_NEAR(abc.b, ib, 1e-3);
        CHECK_NEAR(abc.c, ic, 1e-3);
    }
}

/* docs/MATH_SPEC.md (2.1): ia = 1, ib = -0.5 -> alpha 1, beta 0; theta_e = 30 deg -> d 0.866, q -0.5 */
static void test_math_spec_clarke_park_example(void)
{
    const mc_ab_t ab = mc_clarke2(1.0f, -0.5f);
    CHECK_NEAR(ab.alpha, 1.0f, 1e-6f);
    CHECK_NEAR(ab.beta, 0.0f, 1e-6f);
    const float th = 30.0f * 3.14159265f / 180.0f;
    const mc_dq_t dq = mc_park(ab, sinf(th), cosf(th));
    CHECK_NEAR(dq.d, 0.8660254f, 1e-5f);
    CHECK_NEAR(dq.q, -0.5f, 1e-5f);
}

static void test_clarke3_rejects_common_mode(void)
{
    /* A common-mode offset on all three sensors does not change alpha/beta. */
    const mc_ab_t a = mc_clarke3(3.0f, -1.0f, -2.0f);
    const mc_ab_t b = mc_clarke3(3.5f, -0.5f, -1.5f);
    CHECK_NEAR(a.alpha, b.alpha, 1e-6);
    CHECK_NEAR(a.beta, b.beta, 1e-6);
}

static void test_currents_measured_vs_reconstructed(void)
{
    mc_phase_meas_t m = {{4.0f, -1.0f, -3.2f}, MC_PH_A | MC_PH_B | MC_PH_C};
    mc_phase_currents_t pc;
    mc_currents_resolve(&m, &pc);
    CHECK(pc.valid);
    CHECK(pc.kcl_available);
    CHECK_EQ_INT(pc.reconstructed_mask, 0);
    CHECK_NEAR(pc.kcl_residual_A, -0.2f, 1e-5); /* bias shows up as KCL residual */

    m.measured_mask = MC_PH_A | MC_PH_C;        /* B not in a valid sample window */
    mc_currents_resolve(&m, &pc);
    CHECK(pc.valid);
    CHECK(!pc.kcl_available);                   /* reconstructed phase is not independent */
    CHECK_EQ_INT(pc.reconstructed_mask, MC_PH_B);
    CHECK_NEAR(pc.i[1], -(4.0f - 3.2f), 1e-5);

    m.measured_mask = MC_PH_A;
    mc_currents_resolve(&m, &pc);
    CHECK(!pc.valid);

    m.measured_mask = MC_PH_A | MC_PH_B | MC_PH_C;
    m.i[1] = NAN;                               /* nonfinite sample == not measured */
    mc_currents_resolve(&m, &pc);
    CHECK(pc.valid);
    CHECK(!pc.kcl_available);
    CHECK_EQ_INT(pc.reconstructed_mask, MC_PH_B);
}

static void test_pi_antiwindup_and_recovery(void)
{
    mc_pi_t pi;
    mc_pi_init(&pi, 0.5f, 100.0f, -1.0f, 1.0f);
    /* Long saturation: the integrator must not wind beyond the limit. */
    for (int k = 0; k < 10000; k++) (void)mc_pi_step(&pi, 10.0f, 0.0f, 1e-4f, 1e-3f);
    CHECK(pi.saturated);
    CHECK(pi.integ <= 1.0f + 1e-6f);
    /* Reverse the error: the output must leave saturation promptly (within a
     * few steps), not after unwinding a huge integral. */
    int steps = 0;
    float u = 1.0f;
    while (u > 0.0f && steps < 1000) {
        u = mc_pi_step(&pi, -1.0f, 0.0f, 1e-4f, 1e-3f);
        steps++;
    }
    CHECK(steps < 150);
}

static void test_pi_rejects_bad_dt(void)
{
    mc_pi_t pi;
    mc_pi_init(&pi, 1.0f, 10.0f, -5.0f, 5.0f);
    const float u0 = mc_pi_step(&pi, 1.0f, 0.0f, 1e-3f, 1e-2f);
    const float integ = pi.integ;
    CHECK_NEAR(mc_pi_step(&pi, 1.0f, 0.0f, NAN, 1e-2f), u0, 0);
    CHECK(pi.dt_rejected);
    CHECK_NEAR(mc_pi_step(&pi, 1.0f, 0.0f, -1e-3f, 1e-2f), u0, 0);
    CHECK_NEAR(mc_pi_step(&pi, 1.0f, 0.0f, 0.5f, 1e-2f), u0, 0); /* too large */
    CHECK_NEAR(pi.integ, integ, 0);
    (void)mc_pi_step(&pi, 1.0f, 0.0f, 1e-3f, 1e-2f);
    CHECK(!pi.dt_rejected);
}

static void test_pi_time_step_variation(void)
{
    /* The same total time with jittered dt must give (nearly) the same integral. */
    mc_pi_t a, b;
    mc_pi_init(&a, 0.0f, 50.0f, -100.0f, 100.0f);
    mc_pi_init(&b, 0.0f, 50.0f, -100.0f, 100.0f);
    float t = 0.0f;
    for (int k = 0; k < 1000; k++) (void)mc_pi_step(&a, 1.0f, 0.0f, 1e-4f, 1e-3f);
    unsigned s = 12345u;
    while (t < 0.1f - 1e-7f) {
        s = s * 1103515245u + 12345u;
        float dt = 5e-5f + 1e-4f * (float)((s >> 16) & 0x7FFFu) / 32767.0f;
        if (t + dt > 0.1f) dt = 0.1f - t;
        (void)mc_pi_step(&b, 1.0f, 0.0f, dt, 1e-3f);
        t += dt;
    }
    CHECK_NEAR(a.integ, b.integ, 1e-3);
}

static void test_voltage_limit(void)
{
    mc_dq_t v = {3.0f, 4.0f};
    CHECK(!mc_voltage_limit(&v, 5.0f, MC_VLIM_D_PRIORITY));
    v.d = 3.0f; v.q = 8.0f;
    CHECK(mc_voltage_limit(&v, 5.0f, MC_VLIM_D_PRIORITY));
    CHECK_NEAR(v.d, 3.0f, 1e-6);
    CHECK_NEAR(v.q, 4.0f, 1e-5);
    v.d = 6.0f; v.q = 8.0f;
    CHECK(mc_voltage_limit(&v, 5.0f, MC_VLIM_PROPORTIONAL));
    CHECK_NEAR(v.d, 3.0f, 1e-5);
    CHECK_NEAR(v.q, 4.0f, 1e-5);
    v.d = NAN;
    CHECK(mc_voltage_limit(&v, 5.0f, MC_VLIM_PROPORTIONAL));
    CHECK(v.d == 0.0f && v.q == 0.0f);
}

static void test_current_limit(void)
{
    mc_dq_t i = {-3.0f, 10.0f};
    CHECK(mc_current_limit(&i, 5.0f));
    CHECK_NEAR(i.d, -3.0f, 1e-6);
    CHECK_NEAR(i.q, 4.0f, 1e-5);
}

static void test_svpwm_linear_range(void)
{
    /* At the linear limit |v| = Vbus/sqrt(3) duties span exactly [0, 1]. */
    const float vbus = 48.0f;
    for (int k = 0; k < 72; k++) {
        const float th = (float)k * MC_TWO_PI_F / 72.0f;
        mc_ab_t v = {vbus * MC_INV_SQRT3_F * cosf(th), vbus * MC_INV_SQRT3_F * sinf(th)};
        mc_duty_t d;
        (void)mc_svpwm(v, vbus, 0.0f, 1.0f, &d);
        CHECK(d.a >= -1e-5f && d.a <= 1.0f + 1e-5f);
        CHECK(d.b >= -1e-5f && d.b <= 1.0f + 1e-5f);
        CHECK(d.c >= -1e-5f && d.c <= 1.0f + 1e-5f);
        /* Line-line voltages reproduce the request. */
        const mc_abc_t p = mc_inv_clarke(v);
        CHECK_NEAR((d.a - d.b) * vbus, p.a - p.b, 1e-3);
        CHECK_NEAR((d.b - d.c) * vbus, p.b - p.c, 1e-3);
    }
    mc_duty_t d;
    mc_ab_t zero = {0.0f, 0.0f};
    CHECK(mc_svpwm(zero, 0.0f, 0.0f, 1.0f, &d)); /* invalid bus */
    CHECK(d.a == 0.5f && d.b == 0.5f && d.c == 0.5f);
}

static void test_hall_sequence_and_speed(void)
{
    const int8_t tab[8] = {-1, 0, 2, 1, 4, 5, 3, -1};
    const uint8_t fwd[6] = {1, 3, 2, 6, 4, 5};
    mc_hall_t h;
    mc_hall_init(&h, tab, 0.0f, 0.1f);
    /* omega_e = 100 rad/s: one sector (pi/3) every 10.47 ms. */
    const float sector_t = (MC_PI_F / 3.0f) / 100.0f;
    const float dt = 1e-4f;
    float t = 0.0f;
    int idx = 0;
    float next_edge = sector_t;
    for (int k = 0; k < 2000; k++) {
        t += dt;
        if (t >= next_edge) {
            idx = (idx + 1) % 6;
            next_edge += sector_t;
        }
        (void)mc_hall_update(&h, fwd[idx], dt);
    }
    CHECK(!h.invalid);
    CHECK_EQ_INT(h.direction, 1);
    CHECK_NEAR(h.omega_e, 100.0f, 2.0f);
    /* Standstill (no edges) is normal: speed decays to zero, not a fault. */
    for (int k = 0; k < 2000; k++) (void)mc_hall_update(&h, fwd[idx], dt);
    CHECK_NEAR(h.omega_e, 0.0f, 1e-6);
    CHECK(!h.invalid);
    /* A single illegal code is tolerated; persistent illegal codes are not. */
    (void)mc_hall_update(&h, 0, dt);
    CHECK(!h.invalid);
    (void)mc_hall_update(&h, fwd[idx], dt);
    for (int k = 0; k < 3; k++) (void)mc_hall_update(&h, 7, dt);
    CHECK(h.invalid);
}

static void test_slew(void)
{
    CHECK_NEAR(mc_slew(0.0f, 10.0f, 5.0f, 20.0f, 0.1f), 0.5f, 1e-6);
    CHECK_NEAR(mc_slew(1.0f, 0.0f, 5.0f, 20.0f, 0.01f), 0.8f, 1e-6);
    CHECK_NEAR(mc_slew(1.0f, 0.95f, 5.0f, 20.0f, 0.01f), 0.95f, 1e-6);
}

int main(void)
{
    RUN(test_clarke_park_roundtrip);
    RUN(test_math_spec_clarke_park_example);
    RUN(test_clarke3_rejects_common_mode);
    RUN(test_currents_measured_vs_reconstructed);
    RUN(test_pi_antiwindup_and_recovery);
    RUN(test_pi_rejects_bad_dt);
    RUN(test_pi_time_step_variation);
    RUN(test_voltage_limit);
    RUN(test_current_limit);
    RUN(test_svpwm_linear_range);
    RUN(test_hall_sequence_and_speed);
    RUN(test_slew);
    TEST_MAIN_END();
}

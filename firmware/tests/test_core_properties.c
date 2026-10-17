/* Randomised property test of the controller core (host build, synthetic plant).
 *
 * A seeded generator drives the core through the real CAN binding with an
 * adversarial supervisor (normal traffic, silence, exact duplicates, older
 * frames re-sent, corrupted CRCs, wrong session tags, NaN torque, cached
 * samples, companion stalls that end with the cached request, companion
 * restarts, bus-off) and a random driver (throttle, brake,
 * cancel, dead-man, mode and arm switches, fault reset), plus occasional
 * controller reboots. After EVERY slow step it checks:
 *
 *   P1 0 <= accepted torque <= hard ceiling <= static limit; |iq_ref| <= I_max.
 *   P2 brake, dead-man, ECO cancel or a latched fault => zero torque, zero
 *      current reference and PWM off in that same slow step.
 *   P3 ECO_ASSIST only with a valid supervisor input whose last NEW request is
 *      younger than the supervision timeout.
 *   P4 every ECO entry is preceded by a driver mode-switch rising edge seen
 *      after the last arming, ECO exit or reboot.
 *   P5 a duplicate, older, corrupted or wrong-tag request never renews the
 *      request freshness and never changes the stored request.
 *   P6 the slow step after a bus-off report is not in ECO_ASSIST.
 *   P7 in ECO the output rises no faster than slew_up and, above the
 *      envelope, falls at least at slew_down_fast.
 *   P8 recovery: after 10 consecutive clean supervisor periods (200 ms of new,
 *      finite, correctly tagged requests and no reset in between) the
 *      supervisor input is valid again. A disturbance must not lock a healthy
 *      stream out.
 *
 * The run also checks that every injected behaviour actually occurred, so the
 * properties are not satisfied vacuously. Host simulation only. */
#include <math.h>
#include <stdlib.h>
#include <string.h>

#include "mc_test.h"
#include "semmc/mc_core.h"
#include "semmc_protocol.h"
#include "sim_plant.h"
#include "test_support.h"

static uint8_t g_blob[8192];
static size_t g_len;
static mc_core_t C;
static sim_plant_t P;
static mc_config_t PCFG;
static mc_params_t PP;
static mc_slow_inputs_t SI;
static mc_duty_t DUTY = {0.5f, 0.5f, 0.5f};
static bool PWM;
static mc_time_us_t T;
static uint32_t RNG;
static uint16_t BOOT;

static uint32_t rnd(void)
{
    RNG ^= RNG << 13;
    RNG ^= RNG >> 17;
    RNG ^= RNG << 5;
    return RNG;
}
static float rndf(void) { return (float)(rnd() >> 8) * (1.0f / 16777216.0f); }
static bool chance(float p) { return rndf() < p; }

/* ---- adversarial supervisor ---- */
typedef struct {
    uint32_t session;
    uint8_t tag, old_tag;
    uint8_t seq_hello, seq_lim, seq_req, limits_seq;
    float lim_torque, lim_power;
    uint8_t ring[16][8];  /* recent request frames, for re-sending */
    int ring_n;
    uint8_t last_req[8];
    bool have_last;
    uint16_t frozen_src;
    int clean;            /* consecutive clean periods with the controller's current tag */
    bool storm;           /* adversity comes in bursts, so recovery (P8) is checked after each one */
    int stall;            /* periods of companion stall left; the first frame after it is the cached one */
    int phase_ms;
} sup_t;
static sup_t S;

static struct {
    int normal, silence, duplicate, older, corrupt, wrong_tag, nan_req, cached, stall, restart, bus_off, reboot;
    int eco_entries, slow_steps, eco_steps, brake_steps, recovery_checks;
} N;

static void can_rx(uint32_t id, const uint8_t *d) { mc_core_on_can_rx(&C, T, id, d, 8u); }

/* Deliver a frame that must NOT renew authority; check P5 around it. */
static void deliver_rejectable(const uint8_t *d)
{
    const mc_time_us_t before = C.fr_req.last_new_rx_us;
    const float req_before = C.req_torque_Nm;
    const bool inv_before = C.req_invalid;
    can_rx(SEMMC_ID_SUP_TORQUE_REQ, d);
    CHECK(C.fr_req.last_new_rx_us == before);                      /* P5 */
    CHECK(C.req_torque_Nm == req_before && C.req_invalid == inv_before);
}

static void sup_period(void)
{
    uint8_t b[8];
    if (chance(0.5f / 50.0f) || S.seq_hello == 0u) { /* hello, about every 2 s */
        semmc_sup_hello_t h = {S.seq_hello++, 1u, 1u, 1u, S.session};
        (void)semmc_encode_sup_hello(&h, b);
        can_rx(SEMMC_ID_SUP_HELLO, b);
    }
    const int clean_before = S.clean;
    S.clean = 0;
    if ((S.phase_ms -= 20) <= 0) {
        S.storm = !S.storm;
        S.phase_ms = 200 + (int)(rnd() % 1800u);
    }
    if (S.tag == 0u) return;
    bool resend_cached = false;
    if (S.stall > 0) {
        if (--S.stall > 0) return;
        resend_cached = true;
    }
    const float u = (S.storm && !resend_cached) ? rndf() : 1.0f;
    if (u < 0.08f) { N.silence++; return; }
    if (u < 0.09f) { N.stall++; S.stall = 4 + (int)(rnd() % 5u); return; } /* 80..160 ms */
    if (u < 0.14f && S.have_last) { N.duplicate++; deliver_rejectable(S.last_req); return; }
    if (u < 0.19f && S.ring_n > 4) {
        N.older++;
        deliver_rejectable(S.ring[(S.ring_n - 3 - (int)(rnd() % 2u)) % 16]);
        return;
    }
    if (u < 0.22f) {
        semmc_sup_torque_req_t r = {S.seq_req, S.tag, (uint8_t)(S.limits_seq & 0x0Fu), false, 0u, 1.0f,
                                    (uint16_t)(T / 1000u)};
        (void)semmc_encode_sup_torque_req(&r, b);
        b[1 + (int)(rnd() % 7u)] ^= (uint8_t)(1u << (rnd() % 8u)); /* corrupt one bit */
        N.corrupt++;
        deliver_rejectable(b);
        return;
    }
    if (u < 0.25f) {
        semmc_sup_torque_req_t r = {S.seq_req, (uint8_t)(S.tag ^ 0x55u), (uint8_t)(S.limits_seq & 0x0Fu), false, 0u,
                                    3.0f, (uint16_t)(T / 1000u)};
        (void)semmc_encode_sup_torque_req(&r, b);
        N.wrong_tag++;
        deliver_rejectable(b);
        return;
    }
    if (u < 0.255f) { /* companion restart: new session id */
        S.session = rnd() | 1u;
        S.tag = 0u;
        S.seq_hello = 0u;
        N.restart++;
        return;
    }
    if (u < 0.258f) {
        mc_core_on_can_bus_off(&C, true);
        N.bus_off++;
        return;
    }
    /* limits every fifth period, sometimes with a new content */
    if (S.seq_req % 5u == 0u) {
        if (chance(0.1f)) {
            S.lim_torque = 3.0f * rndf();
            S.lim_power = 2000.0f * rndf();
            S.limits_seq++;
        }
        semmc_sup_limits_t l = {S.seq_lim++, S.tag, S.limits_seq, S.lim_torque, S.lim_power};
        (void)semmc_encode_sup_limits(&l, b);
        can_rx(SEMMC_ID_SUP_LIMITS, b);
    }
    float torque = -1.0f + 5.0f * rndf();
    uint16_t src = (uint16_t)(T / 1000u);
    bool clean = S.tag == C.sess.tag;
    if (S.storm && chance(0.02f)) { torque = NAN; N.nan_req++; clean = false; }
    if ((resend_cached || (S.storm && chance(0.03f))) && S.frozen_src != 0u) { src = S.frozen_src; N.cached++; clean = false; }
    S.clean = clean ? clean_before + 1 : 0;
    S.frozen_src = src;
    semmc_sup_torque_req_t r = {S.seq_req++, S.tag, (uint8_t)(S.limits_seq & 0x0Fu), chance(0.1f), 0u, torque, src};
    (void)semmc_encode_sup_torque_req(&r, b);
    can_rx(SEMMC_ID_SUP_TORQUE_REQ, b);
    memcpy(S.last_req, b, 8u);
    S.have_last = true;
    memcpy(S.ring[S.ring_n % 16], b, 8u);
    S.ring_n++;
    N.normal++;
}

/* ---- random driver ---- */
typedef struct {
    int phase_ms;        /* time left in the current driving phase */
    bool eco_phase;
    int brake_ms, cancel_ms, absent_ms, reset_ms, reselect_ms;
} drv_t;
static drv_t D;
static int ECO_EDGES; /* rising edges of the mode switch since the last arming / ECO exit / reboot */

static void driver_ms(void)
{
    mc_driver_inputs_t *d = &SI.driver;
    const bool eco_before = d->mode_eco;
    if (--D.phase_ms <= 0) {
        D.phase_ms = 300 + (int)(rnd() % 2500u);
        D.eco_phase = chance(0.6f);
    }
    /* In an ECO phase the driver re-selects ECO (switch off for 20 ms, then on)
     * when the dashboard shows it is not engaged, as a person would. */
    if (D.reselect_ms > 0) D.reselect_ms--;
    else if (D.eco_phase && C.sm.state != MC_ST_ECO_ASSIST && chance(0.004f)) D.reselect_ms = 20;
    d->mode_eco = D.eco_phase && D.reselect_ms == 0;
    d->throttle = D.eco_phase ? 0.0f : (chance(0.002f) ? rndf() : d->throttle);
    if (!D.eco_phase && chance(0.001f)) d->throttle = 0.0f;
    if (D.brake_ms > 0) D.brake_ms--; else if (chance(0.0006f)) D.brake_ms = 50 + (int)(rnd() % 300u);
    if (D.cancel_ms > 0) D.cancel_ms--; else if (chance(0.0004f)) D.cancel_ms = 30 + (int)(rnd() % 200u);
    if (D.absent_ms > 0) D.absent_ms--; else if (chance(0.0002f)) D.absent_ms = 50 + (int)(rnd() % 400u);
    if (D.reset_ms > 0) D.reset_ms--; else if (chance(0.0005f)) D.reset_ms = 30;
    d->brake = D.brake_ms > 0;
    d->cancel = D.cancel_ms > 0;
    d->driver_present = D.absent_ms == 0;
    d->fault_reset = D.reset_ms > 0;
    if (chance(0.0002f)) d->arm_switch = !d->arm_switch;
    if (!d->arm_switch && chance(0.01f)) { d->arm_switch = true; d->throttle = 0.0f; } /* arms with throttle released */
    if (d->mode_eco && !eco_before) ECO_EDGES++;
}

static void reboot(void)
{
    BOOT++;
    (void)mc_core_init(&C, g_blob, g_len, MC_BUILD_HOST_SIM, BOOT);
    S.tag = 0u;
    S.seq_hello = 0u;
    S.clean = 0;
    ECO_EDGES = 0;
    N.reboot++;
}

static void run_seed(uint32_t seed, int seconds)
{
    RNG = seed;
    BOOT = (uint16_t)(seed & 0xFFFFu);
    mc_cfg_report_t rep;
    mc_cfg_report_clear(&rep);
    (void)mc_config_parse_blob(g_blob, g_len, &PCFG, &rep);
    (void)mc_config_derive(&PCFG, &PP);
    (void)mc_core_init(&C, g_blob, g_len, MC_BUILD_HOST_SIM, BOOT);
    sim_plant_init(&P, &PP);
    memset(&SI, 0, sizeof SI);
    SI.gate_driver_ready = true;
    SI.current_offsets_ok = true;
    SI.driver = (mc_driver_inputs_t){0.0f, true, false, false, false, false, false, true, true};
    memset(&S, 0, sizeof S);
    S.session = seed | 1u;
    S.lim_torque = 2.0f;
    S.lim_power = 2000.0f;
    memset(&D, 0, sizeof D);
    T = 0;
    PWM = false;
    ECO_EDGES = 0;
    const float t_static = fminf(PP.max_motor_torque_Nm, PP.kt_Nm_per_A * PP.max_phase_current_A);
    const mc_time_us_t timeout_us = (mc_time_us_t)(PP.sup_timeout_s * 1e6f);
    mc_state_t prev_state = C.sm.state;
    float prev_acc = 0.0f;
    bool bus_off_reported = false;
    const int reboot_at_ms = 2000 + (int)(rnd() % (uint32_t)((seconds - 4) * 1000)); /* at least one per seed */
    for (int ms = 0; ms < seconds * 1000; ms++) {
        for (int k = 0; k < 20; k++) {
            sim_sensors_t s;
            sim_plant_sense(&P, &DUTY, PWM, &s);
            mc_fast_inputs_t fi = {s.phase, s.hall_code, s.vbus_V, 50e-6f, false};
            mc_fast_outputs_t fo;
            mc_core_fast_step(&C, &fi, &fo);
            PWM = fo.pwm_enable;
            DUTY = fo.duty;
            sim_plant_step(&P, PWM, &DUTY, 25e-6);
            sim_plant_step(&P, PWM, &DUTY, 25e-6);
            T += 50u;
            if (k == 0) {
                SI.vbus_V = s.vbus_V;
                SI.vbus_val = s.vbus_valid ? MC_VAL_OK : MC_VAL_INVALID;
                SI.ibatt_A = s.ibatt_A;
                SI.ibatt_val = s.ibatt_valid ? MC_VAL_OK : MC_VAL_MISSING;
                SI.t_fet_degC = s.t_fet_degC;
                SI.t_fet_val = s.t_fet_valid ? MC_VAL_OK : MC_VAL_INVALID;
                SI.t_motor_degC = s.t_mot_degC;
                SI.t_motor_val = s.t_mot_valid ? MC_VAL_OK : MC_VAL_INVALID;
            }
        }
        driver_ms();
        if (ms % 20 == 0) {
            const int bo_before = N.bus_off;
            sup_period();
            bus_off_reported = N.bus_off != bo_before;
        } else if (C.link_down && chance(0.02f)) {
            mc_core_on_can_bus_off(&C, false);
        }
        if (ms == reboot_at_ms || chance(0.00005f)) reboot();
        mc_core_slow_step(&C, T, &SI);
        uint32_t id;
        uint8_t d[8];
        while (mc_core_can_tx_poll(&C, T, &id, d)) {
            if (id == SEMMC_ID_CTRL_SESSION) {
                semmc_ctrl_session_t ss;
                if (semmc_decode_ctrl_session(d, 8u, &ss).status == SEMMC_OK && ss.companion_session_echo == S.session)
                    S.tag = (uint8_t)ss.session_tag;
            }
        }
        /* ---- properties ---- */
        const mc_state_t st = C.sm.state;
        const float acc = C.arb.accepted_Nm;
        N.slow_steps++;
        CHECK(acc >= 0.0f && acc <= C.arb.hard_ceiling_Nm + 1e-5f && acc <= t_static + 1e-5f);        /* P1 */
        CHECK(fabsf(C.fast_cmd.iq_ref_A) <= PP.max_phase_current_A + 1e-4f);
        CHECK(fabsf(C.fast_cmd.iq_ref_A) * PP.kt_Nm_per_A <= C.arb.hard_ceiling_Nm + 1e-4f);
        const bool inhibit = SI.driver.brake || !SI.driver.driver_present || C.prot.latched != 0u ||
                             (prev_state == MC_ST_ECO_ASSIST && SI.driver.cancel);
        if (SI.driver.brake) N.brake_steps++;
        if (inhibit) {                                                                                  /* P2 */
            CHECK(acc == 0.0f);
            CHECK(C.fast_cmd.iq_ref_A == 0.0f && !C.fast_cmd.pwm_enable);
        }
        if (st == MC_ST_ECO_ASSIST) {                                                                   /* P3 */
            N.eco_steps++;
            CHECK(mc_supervisor_ok(&C.sup));
            CHECK(T - C.fr_req.last_new_rx_us <= timeout_us);
            CHECK(!bus_off_reported);                                                                   /* P6 */
            if (prev_state == MC_ST_ECO_ASSIST) {                                                       /* P7 */
                const float dt = 1e-3f;
                CHECK(acc <= prev_acc + PP.slew_up_Nm_s * dt + 1e-4f);
                if (C.arb.envelope_Nm >= 0.0f && prev_acc > C.arb.envelope_Nm)
                    CHECK(acc <= fmaxf(C.arb.envelope_Nm, prev_acc - PP.slew_down_fast_Nm_s * dt) + 1e-4f);
            } else {
                N.eco_entries++;
                CHECK(ECO_EDGES >= 1);                                                                  /* P4 */
                ECO_EDGES = 0;
            }
        }
        if (S.clean >= 10) {                                                                            /* P8 */
            N.recovery_checks++;
            CHECK(mc_supervisor_ok(&C.sup));
        }
        if (prev_state == MC_ST_ECO_ASSIST && st != MC_ST_ECO_ASSIST) ECO_EDGES = 0;
        if (prev_state == MC_ST_DISARMED && st == MC_ST_READY) ECO_EDGES = 0;
        prev_state = st;
        prev_acc = acc;
    }
}

/* test_core_properties [n_seeds [seconds_per_seed [base_seed]]]: default
 * 6 x 12 s; ctest runs 24 x 12 s; a soak run uses more, e.g. 300 x 30 s with a
 * new base seed. Seeds are derived deterministically from the base. */
int main(int argc, char **argv)
{
    g_len = load_blob(SEMMC_SYNTH_BLOB, g_blob, sizeof g_blob);
    memset(&N, 0, sizeof N);
    const int n_seeds = argc > 1 ? atoi(argv[1]) : 6;
    const int seconds = argc > 2 ? atoi(argv[2]) : 12;
    if (n_seeds < 6 || seconds < 8) {
        printf("need at least 6 seeds of 8 s\n");
        return 2;
    }
    uint32_t seed = argc > 3 ? (uint32_t)strtoul(argv[3], NULL, 0) : 0x1234567u;
    for (int k = 0; k < n_seeds; k++) {
        seed = seed * 1664525u + 1013904223u;
        run_seed(seed | 1u, seconds);
    }
    printf("%d seeds x %d s from base seed 0x%08x\n", n_seeds, seconds, argc > 3 ? (unsigned)strtoul(argv[3], NULL, 0) : 0x1234567u);
    printf("slow steps %d, ECO steps %d (entries %d), brake steps %d, recovery checks %d\n", N.slow_steps, N.eco_steps,
           N.eco_entries, N.brake_steps, N.recovery_checks);
    printf("injected: normal %d silence %d duplicate %d older %d corrupt %d wrong_tag %d nan %d cached %d stall %d "
           "restart %d bus_off %d reboot %d\n", N.normal, N.silence, N.duplicate, N.older, N.corrupt, N.wrong_tag,
           N.nan_req, N.cached, N.stall, N.restart, N.bus_off, N.reboot);
    /* not vacuous: every behaviour was exercised and ECO was actually used */
    CHECK(N.eco_entries >= 10 && N.eco_steps >= 2000 && N.brake_steps > 0);
    CHECK(N.duplicate > 0 && N.older > 0 && N.corrupt > 0 && N.wrong_tag > 0 && N.nan_req > 0 && N.cached > 0 &&
          N.stall > 0);
    CHECK(N.restart > 0 && N.bus_off > 0 && N.silence > 0);
    CHECK(N.recovery_checks > 10000 && N.reboot >= 6);
    printf("%d checks, %d failures\n", mc_test_checks, mc_test_failures);
    return mc_test_failures ? 1 : 0;
}

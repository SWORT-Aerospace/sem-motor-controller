/* HOST-ONLY control-contract report. Drives the arbiter (directly, and through
 * the full core with CAN frames and the synthetic plant) through the scenarios
 * in docs/CONTROL_CONTRACT.md and prints, per sampled update:
 *
 *   requested torque, accepted torque, current reference, the active local
 *   hard ceiling and supervisory envelope computed INDEPENDENTLY here (an
 *   oracle written from the contract, not read back from the arbiter), and
 *   the arbiter's reason bits.
 *
 * Every update (not only printed rows) is checked against the contract:
 *   H: accepted <= hard ceiling and |iq_ref| <= hard/kt on every update.
 *   E: accepted <= envelope, or, while above it, falling by at least
 *      slew_down_fast * dt per update (bounded ramp; deadline in the doc).
 *
 * The program only uses API that exists both before and after the contract
 * correction, so the same source produces the "before" and "after" columns
 * (tools/control_contract_report.py). SYNTHETIC configuration and plant;
 * this is not hardware evidence.
 *
 *   semmc_contract_report <synthetic.bin>    (CSV on stdout)
 */
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "semmc/mc_core.h"
#include "semmc/mc_state_machine.h"
#include "semmc_protocol.h"
#include "sim_plant.h"

#define EPS 1e-4f

static uint8_t g_blob[8192];
static size_t g_len;
static mc_config_t g_cfg;
static mc_params_t g_p;

/* ------------------------------------------------------------ contract oracle */
typedef struct {
    const char *name;
    int n_updates, n_hard_viol, n_env_viol;
    float max_hard_excess, max_env_excess;
    float env_drop_t_ms;   /* first update the envelope fell below accepted */
    float env_settle_ms;   /* time from that drop until accepted <= envelope */
    float prev_acc;
    bool have_prev, env_pending;
} audit_t;

static void audit_begin(audit_t *a, const char *name)
{
    memset(a, 0, sizeof *a);
    a->name = name;
    a->env_drop_t_ms = -1.0f;
    a->env_settle_ms = -1.0f;
}

static float hard_ceiling(const mc_params_t *p, float vbus, float w_signed, bool w_ok, float derate, float batt_scale)
{
    const float t_static = fminf(p->max_motor_torque_Nm, p->kt_Nm_per_A * p->max_phase_current_A);
    float h = t_static;
    const float w = fabsf(w_signed);
    if (w_ok && w > 1.0f && vbus > 0.0f) h = fminf(h, p->min_efficiency_for_limit * vbus * p->battery_current_limit_A / w);
    if (batt_scale < 1.0f) h = fminf(h, t_static * batt_scale);
    if (derate < 1.0f) h = fminf(h, t_static * derate);
    if (w_ok) h = fminf(h, t_static * mc_prot_speed_factor(p, w_signed));
    return fmaxf(h, 0.0f);
}

static float envelope(const mc_params_t *p, float max_t, float max_p, float w_signed, bool w_ok)
{
    float e = max_t;
    const float w = fabsf(w_signed);
    if (w_ok && w > 1.0f && max_p >= 0.0f) e = fminf(e, max_p * p->min_efficiency_for_limit / w);
    return fmaxf(e, 0.0f);
}

static void reasons_str(uint16_t r, char *buf, size_t n)
{
    static const char *names[16] = {"NOT_ARMED", "FAULT_INHIBIT", "HW_TRIP",       "BRAKE",
                                    "CANCEL",    "SUP_INVALID",   "DRIVER_ABSENT", "THROTTLE_LATCH",
                                    "CLAMP_TORQUE", "CLAMP_BATTERY", "CLAMP_DERATE", "CLAMP_SPEED",
                                    "SLEW",      "SUP_BOUND",     "REGEN_OFF",     "COAST"};
    buf[0] = '\0';
    for (int b = 0; b < 16; b++) {
        if (r & (1u << b)) {
            if (buf[0]) strncat(buf, "|", n - strlen(buf) - 1);
            strncat(buf, names[b], n - strlen(buf) - 1);
        }
    }
    if (!buf[0]) strncpy(buf, "-", n);
}

/* Check one update. env < 0 means "no supervisory envelope active". */
static void audit_update(audit_t *a, float t_ms, float dt, const mc_arbiter_t *arb, float hard, float env,
                         const mc_params_t *p)
{
    a->n_updates++;
    const float acc = arb->accepted_Nm;
    const float ex_h = fmaxf(acc - hard, fabsf(arb->iq_ref_A) * p->kt_Nm_per_A - hard);
    if (ex_h > EPS) {
        a->n_hard_viol++;
        if (ex_h > a->max_hard_excess) a->max_hard_excess = ex_h;
    }
    if (env >= 0.0f) {
        float allowed = env;
        if (a->have_prev && a->prev_acc > env) allowed = fmaxf(env, a->prev_acc - p->slew_down_fast_Nm_s * dt);
        const float ex_e = acc - allowed;
        if (ex_e > EPS) {
            a->n_env_viol++;
            if (acc - env > a->max_env_excess) a->max_env_excess = acc - env;
        }
        if (a->have_prev && a->prev_acc > env + EPS && a->env_drop_t_ms < 0.0f) {
            a->env_drop_t_ms = t_ms - dt * 1e3f;
            a->env_pending = true;
        }
    }
    if (a->env_pending && (env < 0.0f || acc <= env + EPS)) {
        a->env_settle_ms = t_ms - a->env_drop_t_ms;
        a->env_pending = false;
    }
    a->prev_acc = acc;
    a->have_prev = true;
}

static void row(const char *scn, float t_ms, const char *event, mc_state_t st, const mc_arbiter_t *arb, float hard,
                float env)
{
    char rs[200];
    reasons_str(arb->reason, rs, sizeof rs);
    char envs[32];
    if (env >= 0.0f) snprintf(envs, sizeof envs, "%.4f", (double)env);
    else snprintf(envs, sizeof envs, "-");
    printf("R,%s,%.1f,%s,%s,%.4f,%.4f,%.3f,%.4f,%s,0x%04X,%s\n", scn, (double)t_ms, event, mc_state_name(st),
           (double)arb->requested_Nm, (double)arb->accepted_Nm, (double)arb->iq_ref_A, (double)hard, envs,
           (unsigned)arb->reason, rs);
}

static void summary(const audit_t *a)
{
    printf("S,%s,%d,%d,%.4f,%d,%.4f,%.1f\n", a->name, a->n_updates, a->n_hard_viol, (double)a->max_hard_excess,
           a->n_env_viol, (double)a->max_env_excess, (double)a->env_settle_ms);
}

/* ------------------------------------------------------------ arbiter rig */
typedef struct {
    mc_params_t p;
    mc_sm_t sm;
    mc_protection_t prot;
    mc_arbiter_t arb;
    mc_driver_inputs_t drv;
    mc_supervisor_input_t sup;
    mc_prot_inputs_t pin;
    mc_arb_meas_t meas;
    mc_sm_aux_t aux;
    mc_time_us_t t;
    audit_t au;
} rig_t;

static rig_t R;

static void rig_init(const char *name)
{
    memset(&R, 0, sizeof R);
    R.p = g_p;
    mc_sm_init(&R.sm);
    mc_prot_init(&R.prot, &R.p);
    mc_arb_init(&R.arb, &R.p);
    R.drv = (mc_driver_inputs_t){0.0f, true, false, false, false, false, false, true, true};
    R.sup = (mc_supervisor_input_t){true, MC_VAL_OK, MC_VAL_OK, true, 1.0f, false, 2.0f, 1000.0f};
    R.pin.vbus_V = 46.0f;
    R.pin.t_fet_degC = 40.0f;
    R.pin.t_motor_degC = 40.0f;
    R.pin.throttle_valid = true;
    R.meas = (mc_arb_meas_t){46.0f, 2.0f, MC_VAL_OK, 100.0f, MC_VAL_OK};
    R.aux = (mc_sm_aux_t){true, true, true, true, false};
    audit_begin(&R.au, name);
}

static float rig_hard(void)
{
    return hard_ceiling(&R.p, R.meas.vbus_V, R.meas.speed_mech_rad_s, mc_usable(R.meas.speed_val), R.prot.derate,
                        R.arb.batt_limit_scale);
}

static float rig_env(void)
{
    if (R.sm.state != MC_ST_ECO_ASSIST) return -1.0f;
    return envelope(&R.p, R.sup.max_torque_Nm, R.sup.max_batt_power_W, R.meas.speed_mech_rad_s,
                    mc_usable(R.meas.speed_val));
}

static void rig_step(int n)
{
    const float dt = 0.001f;
    for (int k = 0; k < n; k++) {
        R.t += 1000u;
        R.pin.throttle_valid = R.drv.throttle_valid;
        mc_prot_evaluate(&R.prot, &R.pin, dt);
        (void)mc_sm_step(&R.sm, &R.p, &R.drv, &R.sup, R.t, &R.prot, &R.aux, dt);
        mc_arb_step(&R.arb, &R.sm, &R.drv, &R.sup, &R.meas, &R.prot, R.aux.hw_trip, dt);
        audit_update(&R.au, (float)R.t * 1e-3f, dt, &R.arb, rig_hard(), rig_env(), &R.p);
    }
}

static void rig_row(const char *event)
{
    row(R.au.name, (float)R.t * 1e-3f, event, R.sm.state, &R.arb, rig_hard(), rig_env());
}

static void rig_ready(void)
{
    R.drv.arm_switch = false;
    rig_step(5);
    R.drv.arm_switch = true;
    rig_step(2);
}

static void rig_eco(void)
{
    R.drv.mode_eco = true;
    rig_step(2);
}

/* A1: high torque, then a lower local hard ceiling (thermal derate step). */
static void a1(void)
{
    rig_init("A1_hard_ceiling_thermal_step");
    rig_ready();
    R.drv.throttle = 1.0f;
    rig_step(1000);
    rig_row("steady_full_torque");
    R.pin.t_fet_degC = 97.5f; /* derate factor 0.5 -> hard ceiling 1.0 N*m */
    rig_step(1);
    rig_row("+1ms_after_ceiling_drop");
    rig_step(4);
    rig_row("+5ms");
    rig_step(5);
    rig_row("+10ms");
    rig_step(90);
    rig_row("+100ms");
    summary(&R.au);
}

/* A2: the same ceiling drop with slow slew settings: the clamp must not depend
 * on slew configuration. */
static void a2(void)
{
    rig_init("A2_hard_ceiling_independent_of_slew");
    R.p.slew_down_Nm_s = 1.0f;
    R.p.slew_down_fast_Nm_s = 1.0f;
    mc_arb_init(&R.arb, &R.p);
    rig_ready();
    R.drv.throttle = 1.0f;
    rig_step(1000);
    rig_row("steady_full_torque");
    R.pin.t_fet_degC = 97.5f;
    rig_step(1);
    rig_row("+1ms_after_ceiling_drop");
    rig_step(99);
    rig_row("+100ms");
    rig_step(400);
    rig_row("+500ms");
    summary(&R.au);
}

/* A3: battery-current feed-forward ceiling at rising speed. */
static void a3(void)
{
    rig_init("A3_battery_ceiling_rising_speed");
    rig_ready();
    R.meas.speed_mech_rad_s = 150.0f;
    R.drv.throttle = 1.0f;
    rig_step(600);
    rig_row("w=150rad/s");
    for (int k = 0; k < 300; k++) { /* 150 -> 450 rad/s in 0.3 s (speed-estimate jumps included) */
        R.meas.speed_mech_rad_s = 150.0f + (float)k;
        rig_step(1);
        if (k == 150 || k == 299) rig_row(k == 150 ? "w=300rad/s" : "w=449rad/s");
    }
    R.meas.speed_mech_rad_s = 1000.0f; /* estimate step (e.g. hall glitch filtered late) */
    rig_step(1);
    rig_row("speed_step_to_1000rad/s");
    summary(&R.au);
}

/* A4: supervisory torque envelope reduced while at high torque. */
static void a4(void)
{
    rig_init("A4_envelope_torque_reduction");
    rig_ready();
    R.sup.torque_req_Nm = 2.0f;
    R.sup.max_torque_Nm = 2.0f;
    rig_eco();
    rig_step(1000);
    rig_row("steady_2Nm");
    R.sup.max_torque_Nm = 0.5f;
    rig_step(1);
    rig_row("+1ms_after_envelope_drop");
    rig_step(9);
    rig_row("+10ms");
    rig_step(10);
    rig_row("+20ms");
    rig_step(130);
    rig_row("+150ms");
    summary(&R.au);
}

/* A5: supervisory power envelope with a speed change. */
static void a5(void)
{
    rig_init("A5_envelope_power_speed_step");
    rig_ready();
    R.meas.speed_mech_rad_s = 60.0f;
    R.sup.torque_req_Nm = 2.0f;
    R.sup.max_torque_Nm = 2.0f;
    R.sup.max_batt_power_W = 150.0f; /* 150 W * 0.7 / 60 rad/s = 1.75 N*m */
    rig_eco();
    rig_step(1000);
    rig_row("w=60rad/s");
    R.meas.speed_mech_rad_s = 120.0f; /* envelope halves to 0.875 N*m */
    rig_step(1);
    rig_row("+1ms_w=120rad/s");
    rig_step(9);
    rig_row("+10ms");
    rig_step(90);
    rig_row("+100ms");
    summary(&R.au);
}

/* A6: brake, dead-man release, re-engagement. */
static void a6(void)
{
    rig_init("A6_brake_deadman_reengage");
    rig_ready();
    R.sup.torque_req_Nm = 1.5f;
    rig_eco();
    rig_step(600);
    rig_row("eco_1.5Nm");
    R.drv.brake = true;
    rig_step(1);
    rig_row("+1ms_brake");
    R.drv.brake = false;
    rig_step(20);
    rig_row("brake_released_no_new_edge");
    R.drv.mode_eco = false;
    rig_step(1);
    rig_eco();
    rig_step(1);
    rig_row("eco_reengaged_+1ms");
    rig_step(299);
    rig_row("eco_reengaged_+300ms");
    R.drv.driver_present = false;
    rig_step(1);
    rig_row("+1ms_deadman_released");
    summary(&R.au);
}

/* ------------------------------------------------------------ core rig (CAN + plant) */
static mc_core_t C;
static sim_plant_t P;
static mc_slow_inputs_t SI;
static mc_duty_t DUTY = {0.5f, 0.5f, 0.5f};
static bool PWM;
static mc_time_us_t T;
static uint8_t TAG, SEQ_REQ, SEQ_LIM, SEQ_HELLO;
static const uint32_t SESSION = 0xC0FFEE01u;
static audit_t AU;
/* oracle view of the supervisor sets: what the controller holds and which set
 * the latest accepted request referenced */
static struct { bool valid; uint8_t seq; float t, pw; } HELD[2];
static uint8_t REF;

static void core_init(const char *name)
{
    (void)mc_core_init(&C, g_blob, g_len, MC_BUILD_HOST_SIM, 0x0101u);
    sim_plant_init(&P, &C.p);
    memset(&SI, 0, sizeof SI);
    SI.gate_driver_ready = true;
    SI.current_offsets_ok = true;
    SI.driver = (mc_driver_inputs_t){0.0f, true, false, false, false, false, false, true, true};
    T = 0;
    PWM = false;
    TAG = 0;
    SEQ_REQ = SEQ_LIM = SEQ_HELLO = 0;
    memset(HELD, 0, sizeof HELD);
    REF = 0xFFu;
    audit_begin(&AU, name);
}

static void hello(void)
{
    uint8_t b[8];
    semmc_sup_hello_t h = {SEQ_HELLO++, 1u, 0u, 1u, SESSION};
    (void)semmc_encode_sup_hello(&h, b);
    mc_core_on_can_rx(&C, T, SEMMC_ID_SUP_HELLO, b, 8u);
}

static void send_limits(uint8_t lseq, float max_t, float max_p)
{
    uint8_t b[8];
    semmc_sup_limits_t l = {SEQ_LIM++, TAG, lseq, max_t, max_p};
    (void)semmc_encode_sup_limits(&l, b);
    mc_core_on_can_rx(&C, T, SEMMC_ID_SUP_LIMITS, b, 8u);
    HELD[1] = HELD[0];
    HELD[0].valid = true;
    HELD[0].seq = lseq;
    HELD[0].t = max_t;
    HELD[0].pw = max_p;
}

static void send_req_seq(uint8_t seq, uint8_t lref, float torque)
{
    uint8_t b[8];
    semmc_sup_torque_req_t r = {seq, TAG, lref, false, 0u, torque, (uint16_t)(T / 1000u)};
    (void)semmc_encode_sup_torque_req(&r, b);
    mc_core_on_can_rx(&C, T, SEMMC_ID_SUP_TORQUE_REQ, b, 8u);
}

static void send_req(uint8_t lref, float torque)
{
    send_req_seq(SEQ_REQ++, lref, torque);
    REF = lref;
}

/* Contract envelope: the tighter of the newest held set and the referenced
 * set (an older reference may only tighten, never restore permission). */
static float core_env(void)
{
    if (C.sm.state != MC_ST_ECO_ASSIST || !HELD[0].valid) return -1.0f;
    float t = HELD[0].t, pw = HELD[0].pw;
    for (int k = 0; k < 2; k++) {
        if (HELD[k].valid && (HELD[k].seq & 0x0Fu) == REF) {
            t = fminf(t, HELD[k].t);
            pw = fminf(pw, HELD[k].pw);
            break;
        }
    }
    return envelope(&C.p, t, pw, C.speed_mech_rad_s, mc_usable(C.speed_val));
}

static float core_hard(void)
{
    return hard_ceiling(&C.p, SI.vbus_V, C.speed_mech_rad_s, mc_usable(C.speed_val), C.prot.derate,
                        C.arb.batt_limit_scale);
}

static void core_ms(int ms)
{
    const uint32_t fast_us = 50u;
    for (int i = 0; i < ms; i++) {
        for (uint32_t k = 0; k < 1000u / fast_us; k++) {
            sim_sensors_t s;
            sim_plant_sense(&P, &DUTY, PWM, &s);
            mc_fast_inputs_t fi = {s.phase, s.hall_code, s.vbus_V, (float)fast_us * 1e-6f, false};
            mc_fast_outputs_t fo;
            mc_core_fast_step(&C, &fi, &fo);
            PWM = fo.pwm_enable;
            DUTY = fo.duty;
            sim_plant_step(&P, PWM, &DUTY, 25e-6);
            sim_plant_step(&P, PWM, &DUTY, 25e-6);
            T += fast_us;
            if (k == 0u) {
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
        mc_core_slow_step(&C, T, &SI);
        audit_update(&AU, (float)T * 1e-3f, 0.001f, &C.arb, core_hard(), core_env(), &C.p);
        uint32_t id;
        uint8_t d[8];
        while (mc_core_can_tx_poll(&C, T, &id, d)) {
            if (id == SEMMC_ID_CTRL_SESSION) {
                semmc_ctrl_session_t s;
                if (semmc_decode_ctrl_session(d, 8u, &s).status == SEMMC_OK && s.companion_session_echo == SESSION)
                    TAG = (uint8_t)s.session_tag;
            }
        }
    }
}

/* Supervisor stream: requests every 20 ms referencing `lref`; with `refresh`
 * the newest limits set is re-sent (same limits_seq, same values) every
 * 100 ms, as a companion does to keep it fresh. */
static void stream_r(int ms, uint8_t lref, float torque, bool refresh)
{
    for (int k = 0; k < ms; k += 20) {
        if (refresh && k % 100 == 0 && HELD[0].valid) {
            const bool v1 = HELD[1].valid;
            const uint8_t s1 = HELD[1].seq;
            const float t1 = HELD[1].t, p1 = HELD[1].pw;
            send_limits(HELD[0].seq, HELD[0].t, HELD[0].pw);
            HELD[1].valid = v1; /* oracle: a refresh is the same set, not a new one */
            HELD[1].seq = s1;
            HELD[1].t = t1;
            HELD[1].pw = p1;
        }
        send_req(lref, torque);
        core_ms(ms - k < 20 ? ms - k : 20);
    }
}

static void stream(int ms, uint8_t lref, float torque)
{
    stream_r(ms, lref, torque, true);
}

static void core_row(const char *event)
{
    row(AU.name, (float)T * 1e-3f, event, C.sm.state, &C.arb, core_hard(), core_env());
}

static void core_to_eco(uint8_t lseq, float max_t, float torque)
{
    core_ms(100);
    SI.driver.arm_switch = true;
    core_ms(5);
    hello();
    core_ms(5);
    send_limits(lseq, max_t, 2000.0f);
    stream(100, lseq, torque);
    SI.driver.mode_eco = true;
    stream(1000, lseq, torque);
}

/* B1: lower envelope committed before any request references it. */
static void b1(void)
{
    core_init("B1_lower_limits_before_matching_request");
    core_to_eco(7u, 2.0f, 1.8f);
    core_row("eco_ref7_bound2.0");
    send_limits(8u, 0.5f, 2000.0f);
    core_ms(1);
    core_row("+1ms_limits8_0.5_committed");
    stream_r(19, 7u, 1.8f, false);
    core_row("+20ms_requests_still_ref7");
    stream_r(40, 7u, 1.8f, false);
    core_row("+60ms_requests_still_ref7");
    stream(200, 8u, 1.8f);
    core_row("requests_ref8");
    summary(&AU);
}

/* B2: a delayed request (new sequence number, old limits_ref) after the
 * tighter set is in force. */
static void b2(void)
{
    core_init("B2_delayed_request_old_limits_ref");
    core_to_eco(7u, 2.0f, 1.8f);
    send_limits(8u, 0.5f, 2000.0f);
    stream_r(200, 8u, 1.8f, false);
    core_row("eco_ref8_bound0.5");
    send_req(7u, 1.8f); /* computed against the old, looser set; delivered late */
    core_ms(1);
    core_row("+1ms_delayed_req_ref7");
    core_ms(19);
    core_row("+20ms");
    stream_r(200, 7u, 1.8f, false);
    core_row("+220ms_stream_ref7");
    summary(&AU);
}

/* B3: a reordered request (older sequence number) is ignored. */
static void b3(void)
{
    core_init("B3_reordered_request_ignored");
    core_to_eco(7u, 2.0f, 0.8f);
    core_row("eco_0.8Nm");
    send_req_seq((uint8_t)(SEQ_REQ - 3u), 7u, 2.0f); /* stale sequence, higher torque */
    core_ms(1);
    core_row("+1ms_reordered_frame");
    core_ms(10);
    core_row("+11ms");
    summary(&AU);
}

/* B4: bus-off, stale commands and re-engagement. */
static void b4(void)
{
    core_init("B4_busoff_stale_reengage");
    core_to_eco(7u, 1.2f, 1.5f);
    core_row("eco_bound1.2");
    mc_core_on_can_bus_off(&C, true);
    core_ms(1);
    core_row("+1ms_bus_off");
    mc_core_on_can_bus_off(&C, false);
    core_ms(50);
    hello();
    core_ms(5);
    send_limits(9u, 0.6f, 2000.0f);
    stream(200, 9u, 1.5f);
    core_row("session_restored_no_driver_edge");
    SI.driver.mode_eco = false;
    stream(20, 9u, 1.5f);
    SI.driver.mode_eco = true;
    stream(20, 9u, 1.5f);
    core_row("driver_edge_+20ms");
    stream(400, 9u, 1.5f);
    core_row("driver_edge_+420ms");
    /* stale: one last request, then the supervisor stops sending */
    send_req(9u, 1.5f);
    core_ms(99);
    core_row("99ms_after_last_new_request");
    core_ms(2);
    core_row("101ms_after_last_new_request");
    summary(&AU);
}

int main(int argc, char **argv)
{
    if (argc < 2) {
        fprintf(stderr, "usage: %s synthetic.bin\n", argv[0]);
        return 2;
    }
    FILE *f = fopen(argv[1], "rb");
    if (!f) return 2;
    g_len = fread(g_blob, 1, sizeof g_blob, f);
    fclose(f);
    mc_cfg_report_t rep;
    mc_cfg_report_clear(&rep);
    if (!mc_config_parse_blob(g_blob, g_len, &g_cfg, &rep) || !mc_config_derive(&g_cfg, &g_p)) return 3;
    printf("# R,scenario,t_ms,event,state,requested_Nm,accepted_Nm,iq_ref_A,hard_ceiling_Nm,envelope_Nm,reason_hex,reasons\n");
    printf("# S,scenario,updates,hard_violations,max_hard_excess_Nm,envelope_violations,max_envelope_excess_Nm,"
           "envelope_settle_ms\n");
    a1();
    a2();
    a3();
    a4();
    a5();
    a6();
    b1();
    b2();
    b3();
    b4();
    return 0;
}

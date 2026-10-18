/* Closed-loop host tests: core + generated codec + simulated plant.
 * These exercise the integration on the HOST against a SYNTHETIC plant. They
 * are not hardware validation. */
#include <math.h>
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

/* supervisor emulation */
static bool SUP_ON;
static uint32_t SUP_SESSION = 0xC0FFEE01u;
static uint8_t SUP_TAG;
static uint8_t SUP_SEQ_REQ, SUP_SEQ_LIM, SUP_SEQ_HELLO;
static float SUP_TORQUE = 1.0f;
static uint16_t SUP_SRC_MS;
static bool SUP_FREEZE_SRC; /* re-send cached sample (src time frozen) */
static mc_time_us_t SUP_LAST_REQ_T;
static uint32_t SUP_BASE = MC_PROTO_MSG_FIRST; /* CAN id of protocol message 0x300 on the emulated bus */
/* Test hooks: last transmitted frame per protocol message, and forced measurement validity. */
static uint8_t LAST_TX[MC_PROTO_MSG_SPAN][8];
static bool HAVE_TX[MC_PROTO_MSG_SPAN];
static bool FORCE_VBUS_VAL_ON, FORCE_IBATT_VAL_ON;
static mc_validity_t FORCE_VBUS_VAL, FORCE_IBATT_VAL;

static void sim_init_blob(mc_build_kind_t build, const uint8_t *blob, size_t len)
{
    mc_cfg_report_t rep;
    mc_cfg_report_clear(&rep);
    (void)mc_config_parse_blob(blob, len, &PCFG, &rep);
    (void)mc_config_derive(&PCFG, &PP);
    (void)mc_core_init(&C, blob, len, build, 0x0101u);
    SUP_BASE = MC_PROTO_MSG_FIRST;
    sim_plant_init(&P, &PP);
    memset(&SI, 0, sizeof SI);
    SI.gate_driver_ready = true;
    SI.current_offsets_ok = true;
    SI.driver = (mc_driver_inputs_t){0.0f, true, false, false, false, false, false, true, true};
    T = 0;
    PWM = false;
    SUP_ON = false;
    SUP_TAG = 0;
    SUP_SRC_MS = 0;
    SUP_FREEZE_SRC = false;
    SUP_SEQ_REQ = SUP_SEQ_LIM = SUP_SEQ_HELLO = 0u; /* no state leaks between tests */
    memset(HAVE_TX, 0, sizeof HAVE_TX);
    FORCE_VBUS_VAL_ON = FORCE_IBATT_VAL_ON = false;
}

static void sim_init(mc_build_kind_t build)
{
    sim_init_blob(build, g_blob, g_len);
}

/* CAN id of a protocol message on the emulated bus (relocatable block). */
static uint32_t bus_id(uint32_t msg) { return msg - MC_PROTO_MSG_FIRST + SUP_BASE; }

static void sup_tx(void)
{
    uint8_t b[8];
    if (SUP_SEQ_HELLO++ % 25u == 0u) {
        semmc_sup_hello_t h = {SUP_SEQ_HELLO, 1u, 0u, 1u, SUP_SESSION};
        (void)semmc_encode_sup_hello(&h, b);
        mc_core_on_can_rx(&C, T, bus_id(SEMMC_ID_SUP_HELLO), b, 8u);
    }
    if (SUP_TAG == 0u) return;
    if (SUP_SEQ_REQ % 5u == 0u) {
        semmc_sup_limits_t l = {SUP_SEQ_LIM++, SUP_TAG, 7u, 2.0f, 2000.0f};
        (void)semmc_encode_sup_limits(&l, b);
        mc_core_on_can_rx(&C, T, bus_id(SEMMC_ID_SUP_LIMITS), b, 8u);
    }
    if (!SUP_FREEZE_SRC) SUP_SRC_MS = (uint16_t)(T / 1000u);
    semmc_sup_torque_req_t r = {SUP_SEQ_REQ++, SUP_TAG, 7u, false, 0u, SUP_TORQUE, SUP_SRC_MS};
    (void)semmc_encode_sup_torque_req(&r, b);
    mc_core_on_can_rx(&C, T, bus_id(SEMMC_ID_SUP_TORQUE_REQ), b, 8u);
    SUP_LAST_REQ_T = T;
}

static void run_ms(int ms)
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
                if (FORCE_VBUS_VAL_ON) SI.vbus_val = FORCE_VBUS_VAL;
                if (FORCE_IBATT_VAL_ON) SI.ibatt_val = FORCE_IBATT_VAL;
            }
        }
        if (SUP_ON && i % 20 == 0) sup_tx();
        mc_core_slow_step(&C, T, &SI);
        uint32_t id;
        uint8_t d[8];
        while (mc_core_can_tx_poll(&C, T, &id, d)) {
            const uint32_t msg = id - SUP_BASE;
            if (msg < MC_PROTO_MSG_SPAN) {
                memcpy(LAST_TX[msg], d, 8u);
                HAVE_TX[msg] = true;
            }
            if (id == bus_id(SEMMC_ID_CTRL_SESSION)) {
                semmc_ctrl_session_t s;
                if (semmc_decode_ctrl_session(d, 8u, &s).status == SEMMC_OK && s.companion_session_echo == SUP_SESSION)
                    SUP_TAG = (uint8_t)s.session_tag;
            }
        }
    }
}

static void arm(void)
{
    run_ms(100);
    CHECK_EQ_INT(C.sm.state, MC_ST_DISARMED);
    SI.driver.arm_switch = true;
    run_ms(5);
    CHECK_EQ_INT(C.sm.state, MC_ST_READY);
}

static void test_foc_tracks_current_and_vehicle_moves(void)
{
    sim_init(MC_BUILD_HOST_SIM);
    arm();
    SI.driver.throttle = 0.5f; /* 1.0 N*m => iq_ref ~16.7 A */
    run_ms(1500);
    CHECK_EQ_INT(C.sm.state, MC_ST_MANUAL);
    CHECK_NEAR(C.arb.accepted_Nm, 1.0f, 1e-3f);
    CHECK_NEAR(C.iq_meas_A, C.fast_cmd.iq_ref_A, 1.0f);
    CHECK(fabs((double)C.id_meas_A) < 1.5);
    CHECK(sim_plant_vehicle_speed(&P) > 0.5);
    CHECK(P.energy_J > 0.0);
    CHECK(!P.rectifying);
    /* Controller-side energy integration (from the battery current measurement)
     * agrees with the plant's terminal energy within a few percent. */
    CHECK(fabs(C.energy_J - P.energy_J) < 0.05 * P.energy_J + 1.0);
}

static void test_eco_handshake_timeout_and_cached_sample(void)
{
    sim_init(MC_BUILD_HOST_SIM);
    arm();
    SUP_ON = true;
    run_ms(300);
    CHECK(SUP_TAG != 0u);
    CHECK(C.sess.established);
    SI.driver.mode_eco = true;
    run_ms(20);
    CHECK_EQ_INT(C.sm.state, MC_ST_ECO_ASSIST);
    run_ms(500);
    CHECK_NEAR(C.arb.accepted_Nm, 1.0f, 1e-3f);
    /* The companion's strategy hangs but its CAN task keeps re-sending the
     * cached request with fresh sequence numbers: validity must not renew. */
    SUP_FREEZE_SRC = true;
    run_ms(150);
    CHECK_EQ_INT(C.sm.state, MC_ST_READY);
    CHECK_EQ_INT(C.last_transition, MC_T_ECO_SUPERVISOR_LOST);
    CHECK(C.arb.accepted_Nm == 0.0f);
    CHECK(C.fr_req.n_repeat > 0u);
}

static void test_supervisor_disconnect(void)
{
    sim_init(MC_BUILD_HOST_SIM);
    arm();
    SUP_ON = true;
    run_ms(300);
    SI.driver.mode_eco = true;
    run_ms(300);
    CHECK_EQ_INT(C.sm.state, MC_ST_ECO_ASSIST);
    SUP_ON = false; /* cable unplugged */
    /* Validity runs from the last NEW request, not from the unplug time. */
    const int until_95 = (int)((SUP_LAST_REQ_T + 95000u - T) / 1000u);
    run_ms(until_95);
    CHECK_EQ_INT(C.sm.state, MC_ST_ECO_ASSIST); /* inside the 100 ms window */
    run_ms(10);
    CHECK_EQ_INT(C.sm.state, MC_ST_READY);
    CHECK_EQ_INT(C.last_transition, MC_T_ECO_SUPERVISOR_LOST);
    /* Reconnect: requests resume, but ECO needs a fresh driver edge. */
    SUP_ON = true;
    run_ms(300);
    CHECK_EQ_INT(C.sm.state, MC_ST_READY);
    CHECK(C.arb.accepted_Nm == 0.0f);
}

static void test_bus_off_exits_eco_immediately(void)
{
    sim_init(MC_BUILD_HOST_SIM);
    arm();
    SUP_ON = true;
    run_ms(300);
    SI.driver.mode_eco = true;
    run_ms(200);
    CHECK_EQ_INT(C.sm.state, MC_ST_ECO_ASSIST);
    mc_core_on_can_bus_off(&C, true);
    run_ms(2);
    CHECK_EQ_INT(C.sm.state, MC_ST_READY);
    CHECK(C.arb.accepted_Nm == 0.0f);
    mc_core_on_can_bus_off(&C, false);
    /* Manual driving does not depend on CAN. */
    SI.driver.mode_eco = false;
    SI.driver.throttle = 0.0f;
    run_ms(2);
    SI.driver.throttle = 0.5f;
    run_ms(300);
    CHECK_EQ_INT(C.sm.state, MC_ST_MANUAL);
}

static void test_controller_reboot_during_active_request(void)
{
    sim_init(MC_BUILD_HOST_SIM);
    arm();
    SUP_ON = true;
    run_ms(300);
    SI.driver.mode_eco = true;
    run_ms(300);
    CHECK_EQ_INT(C.sm.state, MC_ST_ECO_ASSIST);
    const uint8_t old_tag = SUP_TAG;
    /* Watchdog reset mid-request: arm switch, eco switch and supervisor stream
     * all remain active. */
    (void)mc_core_init(&C, g_blob, g_len, MC_BUILD_HOST_SIM, 0x0202u);
    PWM = false;
    run_ms(500);
    CHECK_EQ_INT(C.sm.state, MC_ST_DISARMED);
    CHECK(C.arb.accepted_Nm == 0.0f);
    CHECK(!C.fast_cmd.pwm_enable);
    CHECK(C.can.rx_tag_mismatch > 0u || SUP_TAG != old_tag);
}


static uint8_t NEWEST_LSEQ;
static float NEWEST_T;

static void send_limits(uint8_t lseq, float max_t)
{
    NEWEST_LSEQ = lseq;
    NEWEST_T = max_t;
    uint8_t b[8];
    semmc_sup_limits_t l = {SUP_SEQ_LIM++, SUP_TAG, lseq, max_t, 2000.0f};
    (void)semmc_encode_sup_limits(&l, b);
    mc_core_on_can_rx(&C, T, SEMMC_ID_SUP_LIMITS, b, 8u);
}

static void send_req(uint8_t lref, float torque)
{
    uint8_t b[8];
    semmc_sup_torque_req_t r = {SUP_SEQ_REQ++, SUP_TAG, lref, false, 0u, torque, (uint16_t)(T / 1000u)};
    (void)semmc_encode_sup_torque_req(&r, b);
    mc_core_on_can_rx(&C, T, SEMMC_ID_SUP_TORQUE_REQ, b, 8u);
}

static void test_limits_update_between_requests(void)
{
    sim_init(MC_BUILD_HOST_SIM);
    arm();
    SUP_ON = true;
    run_ms(300);
    SUP_ON = false; /* drive the supervisor by hand from here */
    send_limits(7u, 2.0f);
    send_req(7u, 1.5f);
    SI.driver.mode_eco = true;
    for (int k = 0; k < 20; k++) { send_req(7u, 1.5f); run_ms(20); }
    CHECK_EQ_INT(C.sm.state, MC_ST_ECO_ASSIST);
    /* New, tighter limits arrive; the next request was computed against the
     * OLD set. It stays usable (no spurious supervisor loss), but the newest
     * set bounds it: an older reference never restores permission the newest
     * set withdrew (CONTROL_CONTRACT.md I9). The first version of this test
     * expected the old bound (2.0) here; that expectation was the defect. */
    send_limits(8u, 0.5f);
    run_ms(10);
    CHECK_EQ_INT(C.sm.state, MC_ST_ECO_ASSIST);
    CHECK(C.sup.limits_match);
    CHECK_NEAR(C.sup.max_torque_Nm, 0.5f, 1e-3f);
    send_req(8u, 1.5f); /* now referencing the new set */
    run_ms(500);
    CHECK_NEAR(C.sup.max_torque_Nm, 0.5f, 1e-3f);
    for (int k = 0; k < 20; k++) { send_req(8u, 1.5f); run_ms(20); }
    CHECK(C.arb.accepted_Nm <= 0.5f + 1e-3f);
    /* A request referencing a set the controller does not hold: not usable. */
    send_req(3u, 1.5f);
    run_ms(2);
    CHECK_EQ_INT(C.sm.state, MC_ST_READY);
    CHECK_EQ_INT(C.last_transition, MC_T_ECO_SUPERVISOR_LOST);
}

static void test_reconstructed_phase_is_flagged(void)
{
    sim_init(MC_BUILD_HOST_SIM);
    arm();
    SI.driver.throttle = 0.4f;
    run_ms(500);
    P.fault.phase_missing[1] = true;
    run_ms(200);
    CHECK_EQ_INT(C.sm.state, MC_ST_MANUAL); /* control continues on 2 shunts */
    CHECK(!C.pc.kcl_available);
    CHECK(C.pc.reconstructed_mask & MC_PH_B);
    CHECK_NEAR(C.iq_meas_A, C.fast_cmd.iq_ref_A, 1.5f);
}

static void test_software_overcurrent_trips_in_fast_loop(void)
{
    sim_init(MC_BUILD_HOST_SIM);
    arm();
    SI.driver.throttle = 0.3f;
    run_ms(300);
    P.fault.current_bias_A[0] = 80.0f; /* sensor reads > software trip */
    run_ms(2);
    CHECK_EQ_INT(C.sm.state, MC_ST_FAULT_LATCHED);
    CHECK(C.prot.latched & MC_FAULT_BIT(MC_F_SW_OVERCURRENT));
    CHECK(!C.fast_cmd.pwm_enable);
}

/* The fast step acts on the command the slow step PUBLISHED, never on the slow step's working copy: a half-
 * written working copy cannot reach the PWM. After an overcurrent latch the published command is off. */
static void test_fast_step_reads_published_command_only(void)
{
    sim_init(MC_BUILD_HOST_SIM);
    arm();
    SI.driver.throttle = 0.3f;
    run_ms(300);
    CHECK(C.fast_pub[atomic_load(&C.fast_pub_idx)].pwm_enable);
    CHECK(memcmp(&C.fast_pub[atomic_load(&C.fast_pub_idx)], &C.fast_cmd, sizeof C.fast_cmd) == 0);
    /* Corrupt the working copy only: the next fast step still runs on the published command. */
    C.fast_cmd.pwm_enable = false;
    C.fast_cmd.iq_ref_A = 1.0e6f;
    sim_sensors_t s;
    sim_plant_sense(&P, &DUTY, PWM, &s);
    mc_fast_inputs_t fi = {s.phase, s.hall_code, s.vbus_V, 50e-6f, false};
    mc_fast_outputs_t fo;
    mc_core_fast_step(&C, &fi, &fo);
    CHECK(fo.pwm_enable);
    CHECK(fabsf(C.iq_meas_A) < PP.max_phase_current_A);
    /* An overcurrent seen by the fast step is pending (events != ack) when the slow step starts, and the slow
     * step publishes pwm_enable = false before it acknowledges the event. */
    P.fault.current_bias_A[0] = 80.0f;
    sim_plant_sense(&P, &DUTY, PWM, &s);
    fi.phase = s.phase;
    mc_core_fast_step(&C, &fi, &fo);
    CHECK(!fo.pwm_enable);
    CHECK(atomic_load(&C.fast_oc_events) != atomic_load(&C.fast_oc_ack)); /* pending */
    mc_core_slow_step(&C, T + 1000u, &SI);
    CHECK(C.prot.latched & MC_FAULT_BIT(MC_F_SW_OVERCURRENT));
    CHECK(!C.fast_pub[atomic_load(&C.fast_pub_idx)].pwm_enable);
    CHECK(atomic_load(&C.fast_oc_events) == atomic_load(&C.fast_oc_ack)); /* acknowledged after the publish */
}

static void test_hardware_build_rejects_synthetic(void)
{
    sim_init(MC_BUILD_HARDWARE);
    CHECK(!C.config_ok);
    CHECK(!C.output_permitted);
    SI.driver.arm_switch = false;
    run_ms(50);
    SI.driver.arm_switch = true;
    SI.driver.throttle = 0.0f;
    run_ms(50);
    CHECK_EQ_INT(C.sm.state, MC_ST_FAULT_LATCHED);
    CHECK(C.prot.latched & MC_FAULT_BIT(MC_F_CONFIG_INVALID));
    CHECK(!C.fast_cmd.pwm_enable);
}

static void test_gate_driver_fault(void)
{
    sim_init(MC_BUILD_HOST_SIM);
    arm();
    SI.driver.throttle = 0.5f;
    run_ms(300);
    SI.gate_driver_fault = true;
    run_ms(1);
    CHECK_EQ_INT(C.sm.state, MC_ST_FAULT_LATCHED);
    CHECK(C.prot.latched & MC_FAULT_BIT(MC_F_GATE_DRIVER));
    CHECK(C.arb.accepted_Nm == 0.0f);
    CHECK(!C.fast_cmd.pwm_enable);
}

/* ---- Control contract through CAN (docs/CONTROL_CONTRACT.md) ---- */
/* One supervisor cycle: re-send the newest limits set every 5th request (a
 * refresh, same limits_seq) and send a request referencing `lref`. */
static unsigned TICKS;
static void tick_req(uint8_t lref, float torque)
{
    if (TICKS++ % 5u == 0u) send_limits(NEWEST_LSEQ, NEWEST_T);
    send_req(lref, torque);
}

static void eco_with(uint8_t lseq, float max_t, float torque)
{
    sim_init(MC_BUILD_HOST_SIM);
    arm();
    SUP_ON = true;
    run_ms(300);
    SUP_ON = false;
    send_limits(lseq, max_t);
    SI.driver.mode_eco = true;
    for (int k = 0; k < 40; k++) { tick_req(lseq, torque); run_ms(20); }
    CHECK_EQ_INT(C.sm.state, MC_ST_ECO_ASSIST);
}

static void test_contract_lower_limits_before_matching_request(void)
{
    eco_with(7u, 2.0f, 1.8f);
    CHECK_NEAR(C.arb.accepted_Nm, 1.8f, 1e-3f);
    send_limits(8u, 0.5f);   /* no request references set 8 yet */
    run_ms(1);
    CHECK_NEAR(C.arb.envelope_Nm, 0.5f, 1e-3f);
    CHECK(C.arb.accepted_Nm <= 1.8f - C.p.slew_down_fast_Nm_s * 0.001f + 1e-4f);
    for (int k = 0; k < 3; k++) { send_req(7u, 1.8f); run_ms(20); }
    CHECK_EQ_INT(C.sm.state, MC_ST_ECO_ASSIST); /* still usable */
    CHECK(C.arb.accepted_Nm <= 0.5f + 1e-4f);    /* (1.8-0.5)/100 = 13 ms < 60 ms */
    CHECK(C.env_newest_tighter_steps > 0u);
    CHECK(fabsf(C.fast_cmd.iq_ref_A) <= 0.5f / C.p.kt_Nm_per_A + 1e-3f);
}

static void test_contract_delayed_request_with_older_ref(void)
{
    eco_with(7u, 2.0f, 1.8f);
    send_limits(8u, 0.5f);
    for (int k = 0; k < 10; k++) { send_req(8u, 1.8f); run_ms(20); }
    CHECK(C.arb.accepted_Nm <= 0.5f + 1e-4f);
    /* A request computed against set 7 is delivered late (fresh sequence
     * number, old limits_ref): it must not ramp the output above set 8. */
    for (int k = 0; k < 10; k++) {
        send_req(7u, 1.8f);
        for (int j = 0; j < 20; j++) {
            run_ms(1);
            CHECK(C.arb.accepted_Nm <= 0.5f + 1e-4f);
        }
    }
    CHECK_EQ_INT(C.sm.state, MC_ST_ECO_ASSIST);
}

static void test_contract_limits_refresh_keeps_previous_set(void)
{
    eco_with(7u, 2.0f, 1.0f);
    send_limits(8u, 0.5f);
    send_limits(8u, 0.5f);   /* periodic re-send of the newest set */
    send_limits(8u, 0.5f);
    CHECK(C.lim[1].valid && C.lim[1].seq == 7u);
    send_req(7u, 1.0f);      /* still a held set: no spurious supervisor loss */
    run_ms(20);
    CHECK_EQ_INT(C.sm.state, MC_ST_ECO_ASSIST);
    CHECK(C.arb.accepted_Nm <= 0.5f + 1e-4f);
}

static void test_contract_reordered_request_ignored(void)
{
    eco_with(7u, 2.0f, 0.8f);
    uint8_t b[8];
    semmc_sup_torque_req_t r = {(uint8_t)(SUP_SEQ_REQ - 3u), SUP_TAG, 7u, false, 0u, 2.0f, (uint16_t)(T / 1000u)};
    (void)semmc_encode_sup_torque_req(&r, b);
    mc_core_on_can_rx(&C, T, SEMMC_ID_SUP_TORQUE_REQ, b, 8u);
    run_ms(20);
    CHECK_NEAR(C.arb.requested_Nm, 0.8f, 1e-4f);
    CHECK(C.arb.accepted_Nm <= 0.8f + 1e-4f);
}

static void test_contract_reengage_bounded_by_newest_envelope(void)
{
    eco_with(7u, 1.2f, 1.5f);
    mc_core_on_can_bus_off(&C, true);
    run_ms(1);
    CHECK_EQ_INT(C.sm.state, MC_ST_READY);
    CHECK(C.arb.accepted_Nm == 0.0f);
    CHECK(C.fast_cmd.iq_ref_A == 0.0f);
    mc_core_on_can_bus_off(&C, false);
    SUP_ON = true;            /* companion re-handshakes (new tag) */
    run_ms(300);
    SUP_ON = false;
    send_limits(9u, 0.6f);
    for (int k = 0; k < 5; k++) { tick_req(9u, 1.5f); run_ms(20); }
    CHECK_EQ_INT(C.sm.state, MC_ST_READY);  /* no driver edge yet */
    CHECK(C.arb.accepted_Nm == 0.0f);
    SI.driver.mode_eco = false;
    tick_req(9u, 1.5f);
    run_ms(20);
    SI.driver.mode_eco = true;
    for (int k = 0; k < 30; k++) {
        tick_req(9u, 1.5f);
        for (int j = 0; j < 20; j++) {
            run_ms(1);
            CHECK(C.arb.accepted_Nm <= 0.6f + 1e-4f);
        }
    }
    CHECK_EQ_INT(C.sm.state, MC_ST_ECO_ASSIST);
    CHECK_NEAR(C.arb.accepted_Nm, 0.6f, 1e-3f);
    /* stale: last new request, then silence */
    send_req(9u, 1.5f);
    run_ms(95);
    CHECK_EQ_INT(C.sm.state, MC_ST_ECO_ASSIST);
    run_ms(10);
    CHECK_EQ_INT(C.sm.state, MC_ST_READY);
    CHECK(C.arb.accepted_Nm == 0.0f);
}

/* Found by test_core_properties: after a bus-off the session was reset and the
 * next hello re-issued the SAME tag (it was derived from boot id and companion
 * session only), so a request frame recorded before the bus-off became valid
 * again and was accepted as the first sample of the "new" session. */
static void test_bus_off_recovery_rejects_frames_from_before(void)
{
    eco_with(7u, 2.0f, 0.8f);
    const uint8_t old_tag = SUP_TAG;
    uint8_t stale[8];
    semmc_sup_torque_req_t r = {(uint8_t)(SUP_SEQ_REQ + 40u), old_tag, 7u, false, 0u, 2.0f,
                                (uint16_t)(T / 1000u + 400u)};
    (void)semmc_encode_sup_torque_req(&r, stale);       /* sits in a gateway queue across the bus-off */
    uint8_t seen[8] = {old_tag};
    int n_seen = 1;
    for (int cycle = 0; cycle < 6; cycle++) {
        mc_core_on_can_bus_off(&C, true);
        run_ms(1);
        CHECK_EQ_INT(C.sm.state, MC_ST_READY);
        CHECK(C.sess.tag == 0u);
        mc_core_on_can_bus_off(&C, false);
        SUP_ON = true;                                  /* same companion session re-handshakes */
        run_ms(600);                                    /* the emulated companion sends hello every 500 ms */
        SUP_ON = false;
        CHECK(C.sess.tag != 0u && C.sess.tag == SUP_TAG);
        for (int k = 0; k < n_seen; k++) CHECK(C.sess.tag != seen[k]);  /* distinct from every earlier tag */
        seen[n_seen++] = C.sess.tag;
        const mc_time_us_t before = C.fr_req.last_new_rx_us;
        const uint32_t mism = C.can.rx_tag_mismatch;
        T += 400000u;                                   /* the queued frame's time would now look plausible */
        mc_core_on_can_rx(&C, T, bus_id(SEMMC_ID_SUP_TORQUE_REQ), stale, 8u);
        CHECK(C.fr_req.last_new_rx_us == before);
        CHECK(C.can.rx_tag_mismatch == mism + 1u);
        run_ms(1);
        CHECK(C.arb.accepted_Nm == 0.0f);
    }
}

/* ---- measurement validity reaches telemetry unchanged -------------------- */
static void test_flagged_vbus_is_reported_invalid_not_healthy(void)
{
    /* A bus voltage the platform flags (stale ADC, failed plausibility) but
     * whose number is finite must not appear healthy on the bus: the
     * protection layer already faults on it, and telemetry must agree. */
    sim_init(MC_BUILD_HOST_SIM);
    arm();
    run_ms(150);
    CHECK(HAVE_TX[SEMMC_ID_CTRL_VALIDITY - MC_PROTO_MSG_FIRST]);
    semmc_ctrl_validity_t v;
    CHECK(semmc_decode_ctrl_validity(LAST_TX[SEMMC_ID_CTRL_VALIDITY - MC_PROTO_MSG_FIRST], 8u, &v).status == SEMMC_OK);
    CHECK_EQ_INT((int)v.v_vbus, 0);
    FORCE_VBUS_VAL_ON = true;
    FORCE_VBUS_VAL = MC_VAL_STALE; /* finite value, flagged by the platform */
    run_ms(250);
    CHECK(C.prot.latched & MC_FAULT_BIT(MC_F_VBUS_SENSE_INVALID));
    CHECK(semmc_decode_ctrl_validity(LAST_TX[SEMMC_ID_CTRL_VALIDITY - MC_PROTO_MSG_FIRST], 8u, &v).status == SEMMC_OK);
    CHECK(v.v_vbus != 0u);
    semmc_ctrl_motion_t m;
    CHECK(semmc_decode_ctrl_motion(LAST_TX[SEMMC_ID_CTRL_MOTION - MC_PROTO_MSG_FIRST], 8u, &m).status == SEMMC_OK);
    CHECK(isnan(m.vbus_V));
}

static void test_no_measurement_reported_before_it_exists(void)
{
    /* Frames sent before the first slow step must not carry zero-initialised
     * measurements as if they were real. */
    sim_init(MC_BUILD_HOST_SIM);
    uint32_t id;
    uint8_t d[8];
    int seen = 0;
    while (mc_core_can_tx_poll(&C, 0u, &id, d)) {
        if (id == SEMMC_ID_CTRL_MOTION) {
            semmc_ctrl_motion_t m;
            CHECK(semmc_decode_ctrl_motion(d, 8u, &m).status == SEMMC_OK);
            CHECK(isnan(m.vbus_V) && isnan(m.speed_mech_rad_s));
            seen++;
        } else if (id == SEMMC_ID_CTRL_CURRENTS) {
            semmc_ctrl_currents_t m;
            CHECK(semmc_decode_ctrl_currents(d, 8u, &m).status == SEMMC_OK);
            CHECK(isnan(m.ibatt_A));
            seen++;
        } else if (id == SEMMC_ID_CTRL_THERMAL) {
            semmc_ctrl_thermal_t m;
            CHECK(semmc_decode_ctrl_thermal(d, 8u, &m).status == SEMMC_OK);
            CHECK(isnan(m.t_fet_degC) && isnan(m.t_motor_degC));
            seen++;
        } else if (id == SEMMC_ID_CTRL_VALIDITY) {
            semmc_ctrl_validity_t v;
            CHECK(semmc_decode_ctrl_validity(d, 8u, &v).status == SEMMC_OK);
            CHECK(v.v_vbus != 0u && v.v_ibatt != 0u && v.v_t_fet != 0u && v.v_t_motor != 0u);
            seen++;
        }
    }
    CHECK_EQ_INT(seen, 4);
}

static void test_energy_gaps_are_counted_not_hidden(void)
{
    /* Intervals without a usable battery power (invalid current or voltage, or
     * a late slow step) are reported as gap time; energy_J never integrates them. */
    sim_init(MC_BUILD_HOST_SIM);
    arm();
    SI.driver.throttle = 0.3f;
    run_ms(400);
    CHECK_EQ_INT(C.sm.state, MC_ST_MANUAL);
    CHECK(C.energy_J > 0.0 && C.energy_gap_s < 1e-9);
    const double e0 = C.energy_J, g0 = C.energy_gap_s, i0 = C.energy_integrated_s;
    FORCE_IBATT_VAL_ON = true;
    FORCE_IBATT_VAL = MC_VAL_MISSING;
    run_ms(200);
    CHECK(C.energy_J == e0);                                     /* nothing integrated */
    CHECK(fabs((C.energy_gap_s - g0) - 0.2) < 0.0025);
    CHECK(isnan(C.p_batt_W));
    FORCE_IBATT_VAL_ON = false;
    run_ms(100);
    CHECK(C.energy_J > e0 && C.energy_integrated_s > i0 + 0.09);
    /* a slow step 100 ms late: counted as gap, not integrated as one rectangle */
    const double e1 = C.energy_J, g1 = C.energy_gap_s;
    T += 100000u;
    mc_core_slow_step(&C, T, &SI);
    CHECK(C.energy_J == e1);
    CHECK(fabs((C.energy_gap_s - g1) - 0.1) < 1e-6);
    run_ms(150);
    semmc_ctrl_energy_quality_t q;
    CHECK(HAVE_TX[SEMMC_ID_CTRL_ENERGY_QUALITY - MC_PROTO_MSG_FIRST]);
    CHECK(semmc_decode_ctrl_energy_quality(LAST_TX[SEMMC_ID_CTRL_ENERGY_QUALITY - MC_PROTO_MSG_FIRST], 8u, &q).status ==
          SEMMC_OK);
    CHECK(fabs(q.gap_s - C.energy_gap_s) < 0.011);
    CHECK(q.integrated_s > 0.5f);
}

/* ---- transport independence ------------------------------------------- */
#include "semmc/mc_crc.h"

/* Copy of the synthetic blob with one parameter changed (CRC recomputed). */
static size_t patched_blob(uint8_t *dst, uint16_t id, float v)
{
    memcpy(dst, g_blob, g_len);
    for (size_t off = 32u; off + 8u <= g_len - 4u; off += 8u) {
        const uint16_t eid = (uint16_t)(dst[off] | (dst[off + 1u] << 8));
        if (eid == id) memcpy(&dst[off + 4u], &v, sizeof v); /* little-endian host */
    }
    const uint32_t crc = mc_crc32(dst, g_len - 4u);
    for (unsigned k = 0; k < 4u; k++) dst[g_len - 4u + k] = (uint8_t)(crc >> (8u * k));
    return g_len;
}

static void test_can_binding_relocates_block(void)
{
    static uint8_t blob[8192];
    const size_t n = patched_blob(blob, MC_P_SUPERVISION_CAN_ID_BASE, 1280.0f); /* 0x500 */
    sim_init_blob(MC_BUILD_HOST_SIM, blob, n);
    CHECK(C.config_ok);
    CHECK_EQ_INT((int)mc_can_id_base(&C), 0x500);
    /* the protocol default identifiers are foreign on this bus */
    uint8_t b[8];
    semmc_sup_hello_t h = {1u, 1u, 0u, 1u, SUP_SESSION};
    (void)semmc_encode_sup_hello(&h, b);
    const uint32_t unknown = C.can.rx_unknown;
    mc_core_on_can_rx(&C, T, SEMMC_ID_SUP_HELLO, b, 8u);
    CHECK(C.can.rx_unknown == unknown + 1u);
    CHECK(!C.sess.hello_seen);
    /* every transmitted identifier lies in the relocated block */
    uint32_t id;
    uint8_t d[8];
    int n_tx = 0;
    while (mc_core_can_tx_poll(&C, T, &id, d)) {
        CHECK(id >= 0x500u && id <= 0x53Fu);
        n_tx++;
    }
    CHECK(n_tx > 0);
    /* a complete ECO engagement over the relocated block */
    SUP_BASE = 0x500u;
    arm();
    SUP_ON = true;
    run_ms(300);
    CHECK(C.sess.established);
    SI.driver.mode_eco = true;
    run_ms(20);
    CHECK_EQ_INT(C.sm.state, MC_ST_ECO_ASSIST);
    run_ms(300);
    CHECK_NEAR(C.arb.accepted_Nm, 1.0f, 1e-3f);
}

static void test_core_message_interface_is_transport_neutral(void)
{
    /* Canonical message numbers in and out, whatever CAN block the calibration selects. */
    static uint8_t blob[8192];
    const size_t n = patched_blob(blob, MC_P_SUPERVISION_CAN_ID_BASE, 1280.0f);
    sim_init_blob(MC_BUILD_HOST_SIM, blob, n);
    uint8_t b[8];
    semmc_sup_hello_t h = {1u, 1u, 0u, 1u, SUP_SESSION};
    (void)semmc_encode_sup_hello(&h, b);
    mc_core_on_msg_rx(&C, T, SEMMC_ID_SUP_HELLO, b, 8u);
    CHECK(C.sess.hello_seen);
    uint32_t id;
    uint8_t d[8];
    int n_tx = 0;
    while (mc_core_msg_tx_poll(&C, T, &id, d)) {
        CHECK(id >= MC_PROTO_MSG_FIRST && id < MC_PROTO_MSG_FIRST + MC_PROTO_MSG_SPAN);
        n_tx++;
    }
    CHECK(n_tx > 0);
    mc_core_on_link_state(&C, true); /* link loss: nothing is sent, the session ends */
    CHECK(!mc_core_msg_tx_poll(&C, T, &id, d));
    CHECK(!C.sess.hello_seen);
}

int main(void)
{
    g_len = load_blob(SEMMC_SYNTH_BLOB, g_blob, sizeof g_blob);
    RUN(test_foc_tracks_current_and_vehicle_moves);
    RUN(test_eco_handshake_timeout_and_cached_sample);
    RUN(test_supervisor_disconnect);
    RUN(test_bus_off_exits_eco_immediately);
    RUN(test_controller_reboot_during_active_request);
    RUN(test_limits_update_between_requests);
    RUN(test_reconstructed_phase_is_flagged);
    RUN(test_software_overcurrent_trips_in_fast_loop);
    RUN(test_fast_step_reads_published_command_only);
    RUN(test_hardware_build_rejects_synthetic);
    RUN(test_gate_driver_fault);
    RUN(test_contract_lower_limits_before_matching_request);
    RUN(test_contract_delayed_request_with_older_ref);
    RUN(test_contract_limits_refresh_keeps_previous_set);
    RUN(test_contract_reordered_request_ignored);
    RUN(test_contract_reengage_bounded_by_newest_envelope);
    RUN(test_bus_off_recovery_rejects_frames_from_before);
    RUN(test_flagged_vbus_is_reported_invalid_not_healthy);
    RUN(test_no_measurement_reported_before_it_exists);
    RUN(test_energy_gaps_are_counted_not_hidden);
    RUN(test_can_binding_relocates_block);
    RUN(test_core_message_interface_is_transport_neutral);
    TEST_MAIN_END();
}

/* State machine + command arbitration invariants (I1..I7 in mc_state_machine.h). */
#include <math.h>
#include <string.h>

#include "mc_test.h"
#include "semmc/mc_state_machine.h"
#include "test_support.h"

typedef struct {
    mc_config_t cfg;
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
    mc_transition_t last;
} rig_t;

static rig_t R;

static void rig_init(void)
{
    memset(&R, 0, sizeof R);
    load_synthetic(&R.cfg, &R.p);
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
}

static void step(int n)
{
    const float dt = 0.001f;
    for (int k = 0; k < n; k++) {
        R.t += 1000u;
        R.pin.throttle_valid = R.drv.throttle_valid;
        mc_prot_evaluate(&R.prot, &R.pin, dt);
        const mc_transition_t t = mc_sm_step(&R.sm, &R.p, &R.drv, &R.sup, R.t, &R.prot, &R.aux, dt);
        if (t != MC_T_NONE) R.last = t;
        mc_arb_step(&R.arb, &R.sm, &R.drv, &R.sup, &R.meas, &R.prot, R.aux.hw_trip, dt);
    }
}

/* Boot -> self-test -> DISARMED, then arm with a proper edge. */
static void to_ready(void)
{
    R.drv.arm_switch = false;
    step(5);
    CHECK_EQ_INT(R.sm.state, MC_ST_DISARMED);
    R.drv.arm_switch = true;
    step(2);
    CHECK_EQ_INT(R.sm.state, MC_ST_READY);
}

static void test_no_torque_after_reset_with_switch_held(void)
{
    rig_init();
    R.drv.arm_switch = true;         /* held ON through reset */
    R.drv.throttle = 0.8f;           /* and the pedal pressed */
    step(200);
    CHECK_EQ_INT(R.sm.state, MC_ST_DISARMED);
    CHECK(R.arb.accepted_Nm == 0.0f);
    CHECK(!R.arb.pwm_enable);
    CHECK(R.arb.reason & MC_R_NOT_ARMED);
    /* Releasing the pedal is not enough: the arm switch must go OFF->ON. */
    R.drv.throttle = 0.0f;
    step(20);
    CHECK_EQ_INT(R.sm.state, MC_ST_DISARMED);
    R.drv.arm_switch = false;
    step(2);
    R.drv.arm_switch = true;
    step(2);
    CHECK_EQ_INT(R.sm.state, MC_ST_READY);
}

static void test_arm_refused_with_pedal_pressed_or_estop(void)
{
    rig_init();
    R.drv.arm_switch = false;
    step(5);
    R.drv.throttle = 0.5f;
    R.drv.arm_switch = true;
    step(5);
    CHECK_EQ_INT(R.sm.state, MC_ST_DISARMED);
    R.drv.arm_switch = false;
    R.drv.throttle = 0.0f;
    R.drv.estop_chain_ok = false;
    step(2);
    R.drv.arm_switch = true;
    step(5);
    CHECK_EQ_INT(R.sm.state, MC_ST_DISARMED);
}

static void test_manual_slew_and_estop(void)
{
    rig_init();
    to_ready();
    R.drv.throttle = 1.0f;
    step(1);
    CHECK_EQ_INT(R.sm.state, MC_ST_MANUAL);
    step(100); /* 0.1 s at 5 N*m/s => 0.5 N*m */
    CHECK_NEAR(R.arb.accepted_Nm, 0.5f, 0.02f);
    CHECK(R.arb.reason & MC_R_SLEW);
    step(1000);
    CHECK_NEAR(R.arb.accepted_Nm, 2.0f, 1e-3f);
    CHECK_NEAR(R.arb.iq_ref_A, 2.0f / R.p.kt_Nm_per_A, 1e-2f);
    R.drv.estop_chain_ok = false;
    step(1);
    CHECK_EQ_INT(R.sm.state, MC_ST_DISARMED);
    CHECK_EQ_INT(R.last, MC_T_ESTOP);
    CHECK(R.arb.accepted_Nm == 0.0f);
}

static void engage_eco(void)
{
    R.drv.mode_eco = true;
    step(2);
    CHECK_EQ_INT(R.sm.state, MC_ST_ECO_ASSIST);
    CHECK_EQ_INT(R.sm.owner, MC_OWNER_SUPERVISOR);
}

static void test_eco_supervisor_loss_never_jumps_to_manual(void)
{
    rig_init();
    to_ready();
    engage_eco();
    step(500);
    CHECK_NEAR(R.arb.accepted_Nm, 1.0f, 1e-3f);
    /* Driver rests a foot on the pedal (below engage) ... */
    R.drv.throttle = 0.07f;
    step(10);
    /* ... then the supervisor goes stale. */
    R.sup.req_val = MC_VAL_STALE;
    R.drv.throttle = 0.9f; /* and the pedal is now pressed hard */
    step(1);
    CHECK_EQ_INT(R.sm.state, MC_ST_READY);
    CHECK_EQ_INT(R.last, MC_T_ECO_SUPERVISOR_LOST);
    CHECK(R.arb.accepted_Nm == 0.0f);
    step(200);
    CHECK_EQ_INT(R.sm.state, MC_ST_READY); /* held pedal does not engage (I4) */
    CHECK(R.arb.accepted_Nm == 0.0f);
    CHECK(R.arb.reason & MC_R_THROTTLE_LATCH);
    /* Mode switch to manual, release, press: now manual is allowed. */
    R.drv.mode_eco = false;
    R.drv.throttle = 0.0f;
    step(2);
    R.drv.throttle = 0.5f;
    step(2);
    CHECK_EQ_INT(R.sm.state, MC_ST_MANUAL);
}

static void test_brake_and_cancel_are_immediate(void)
{
    rig_init();
    to_ready();
    engage_eco();
    step(500);
    CHECK(R.arb.accepted_Nm > 0.9f);
    R.drv.brake = true;
    step(1);
    CHECK(R.arb.accepted_Nm == 0.0f); /* no slew on driver override */
    CHECK_EQ_INT(R.sm.state, MC_ST_READY);
    CHECK_EQ_INT(R.last, MC_T_ECO_DRIVER_CANCEL);
    R.drv.brake = false;
    step(5);
    CHECK_EQ_INT(R.sm.state, MC_ST_READY); /* eco needs a NEW edge */
    R.drv.mode_eco = false;
    step(1);
    engage_eco();
    step(300);
    R.drv.cancel = true;
    step(1);
    CHECK(R.arb.accepted_Nm == 0.0f);
    CHECK_EQ_INT(R.sm.state, MC_ST_READY);
}

static void test_hw_trip_immediate_and_reset_does_not_resume(void)
{
    rig_init();
    to_ready();
    engage_eco();
    step(500);
    R.aux.hw_trip = true;
    R.pin.hw_overcurrent = true;
    step(1);
    CHECK(R.arb.accepted_Nm == 0.0f);
    CHECK(!R.arb.pwm_enable);
    CHECK(R.arb.reason & MC_R_HW_TRIP);
    CHECK_EQ_INT(R.sm.state, MC_ST_FAULT_LATCHED);
    CHECK(R.prot.latched & MC_FAULT_BIT(MC_F_HW_OVERCURRENT));
    /* Reset while the trip is still asserted: refused. */
    R.drv.fault_reset = true;
    step(1);
    R.drv.fault_reset = false;
    step(1);
    CHECK_EQ_INT(R.sm.state, MC_ST_FAULT_LATCHED);
    /* Trip clears; reset edge -> DISARMED, never back to ECO. */
    R.aux.hw_trip = false;
    R.pin.hw_overcurrent = false;
    step(1);
    R.drv.fault_reset = true;
    step(1);
    CHECK_EQ_INT(R.sm.state, MC_ST_DISARMED);
    CHECK_EQ_INT(R.last, MC_T_FAULT_RESET);
    step(100);
    CHECK_EQ_INT(R.sm.state, MC_ST_DISARMED); /* arm switch still ON: needs OFF->ON */
    CHECK(R.arb.accepted_Nm == 0.0f);
    R.drv.fault_reset = false;
    R.drv.arm_switch = false;
    step(1);
    R.drv.arm_switch = true;
    step(1);
    CHECK_EQ_INT(R.sm.state, MC_ST_READY);
    step(50);
    CHECK_EQ_INT(R.sm.state, MC_ST_READY); /* eco switch still ON: no automatic resume */
    CHECK(R.arb.accepted_Nm == 0.0f);
}

static void test_supervisor_cannot_arm_or_exceed_limits(void)
{
    rig_init();
    R.drv.arm_switch = false;
    step(5);
    R.sup.torque_req_Nm = 50.0f;
    R.sup.max_torque_Nm = 50.0f;
    step(500);
    CHECK_EQ_INT(R.sm.state, MC_ST_DISARMED);
    R.drv.arm_switch = true;
    step(1);
    engage_eco();
    step(2000);
    CHECK(R.arb.accepted_Nm <= R.p.max_motor_torque_Nm + 1e-6f);
    CHECK(R.arb.reason & MC_R_CLAMP_TORQUE);
    /* Supervisor bound tighter than the controller's: honoured. */
    R.sup.max_torque_Nm = 0.5f;
    step(1000);
    CHECK_NEAR(R.arb.accepted_Nm, 0.5f, 1e-3f);
    CHECK(R.arb.reason & MC_R_SUPERVISOR_BOUND);
    /* Negative (regen) request clamps to zero while regen is deferred. */
    R.sup.torque_req_Nm = -1.0f;
    step(500);
    CHECK(R.arb.accepted_Nm == 0.0f);
    CHECK(R.arb.reason & MC_R_REGEN_DISABLED);
}

static void test_coast_request_gate_off(void)
{
    rig_init();
    to_ready();
    engage_eco();
    step(500);
    CHECK(R.arb.pwm_enable);
    R.sup.coast_request = true;
    step(500);
    CHECK(R.arb.accepted_Nm == 0.0f);
    CHECK(R.arb.reason & MC_R_COAST);
    CHECK(!R.arb.pwm_enable); /* synthetic config: coast_mode = gate_off */
}

static void test_thermal_derate_and_recovery(void)
{
    rig_init();
    to_ready();
    R.drv.throttle = 1.0f;
    step(1000);
    CHECK_NEAR(R.arb.accepted_Nm, 2.0f, 1e-3f);
    /* FET heats into the derate band (85..110 degC): halfway => factor 0.5. */
    R.pin.t_fet_degC = 97.5f;
    step(1);
    CHECK_EQ_INT(R.sm.state, MC_ST_DERATED);
    step(200);
    CHECK_NEAR(R.arb.accepted_Nm, 1.0f, 0.01f);
    CHECK(R.arb.reason & MC_R_CLAMP_DERATE);
    CHECK(R.prot.latched == 0u); /* thermal drift is not a fault */
    R.pin.t_fet_degC = 50.0f;
    step(500);
    CHECK_EQ_INT(R.sm.state, MC_ST_DERATED); /* recovers slowly with hold */
    step(5000);
    CHECK_EQ_INT(R.sm.state, MC_ST_MANUAL);
    CHECK_NEAR(R.arb.accepted_Nm, 2.0f, 1e-3f);
    /* Over the trip: latched fault, immediate zero. */
    R.pin.t_fet_degC = 111.0f;
    step(1);
    CHECK_EQ_INT(R.sm.state, MC_ST_FAULT_LATCHED);
    CHECK(R.arb.accepted_Nm == 0.0f);
}

static void test_unknown_temperature_derates_not_faults(void)
{
    rig_init();
    to_ready();
    R.drv.throttle = 1.0f;
    step(1000);
    R.pin.t_motor_val = MC_VAL_STALE;
    step(300);
    CHECK(R.prot.latched == 0u);
    CHECK(R.prot.derate_reasons & MC_DR_TEMP_UNKNOWN);
    CHECK_NEAR(R.arb.accepted_Nm, 2.0f * R.p.unknown_temp_derate_factor, 0.01f);
}

static void test_voltage_sag_derates_then_trips_after_debounce(void)
{
    rig_init();
    to_ready();
    R.drv.throttle = 1.0f;
    step(1000);
    R.pin.vbus_V = 37.0f; /* inside 36..38 derate band: normal sag */
    step(50);
    CHECK(R.prot.latched == 0u);
    CHECK(R.prot.derate_reasons & MC_DR_UNDERVOLTAGE);
    R.pin.vbus_V = 35.0f; /* below trip: brief dip tolerated */
    step(50);
    CHECK(R.prot.latched == 0u);
    R.pin.vbus_V = 37.0f;
    step(10);
    R.pin.vbus_V = 35.0f; /* sustained */
    step(150);
    CHECK(R.prot.latched & MC_FAULT_BIT(MC_F_BUS_UNDERVOLTAGE));
    CHECK_EQ_INT(R.sm.state, MC_ST_FAULT_LATCHED);
}

static void test_battery_current_limiter(void)
{
    rig_init();
    to_ready();
    R.drv.throttle = 1.0f;
    step(1000);
    const float before = R.arb.accepted_Nm;
    R.meas.ibatt_A = R.p.battery_current_limit_A + 5.0f; /* measured over the limit */
    step(500);
    CHECK(R.arb.accepted_Nm < before);
    CHECK(R.arb.reason & MC_R_CLAMP_BATTERY);
    /* Feed-forward: at high speed the power bound dominates. */
    rig_init();
    to_ready();
    R.drv.throttle = 1.0f;
    R.meas.speed_mech_rad_s = 420.0f;
    step(2000);
    const float t_ff = R.p.min_efficiency_for_limit * 46.0f * R.p.battery_current_limit_A / 420.0f;
    const float t_spd = R.p.max_motor_torque_Nm * mc_prot_speed_factor(&R.p, 420.0f);
    CHECK(R.arb.accepted_Nm <= fminf(t_ff, t_spd) + 1e-3f);
}

static void test_driver_absent_immediate(void)
{
    rig_init();
    to_ready();
    R.drv.throttle = 1.0f;
    step(500);
    R.drv.driver_present = false;
    step(1);
    CHECK(R.arb.accepted_Nm == 0.0f);
    CHECK_EQ_INT(R.sm.state, MC_ST_READY);
    CHECK_EQ_INT(R.last, MC_T_DRIVER_ABSENT);
    R.drv.driver_present = true;
    step(10);
    CHECK_EQ_INT(R.sm.state, MC_ST_READY); /* pedal held: needs release + press */
    R.drv.throttle = 0.0f;
    step(1);
    R.drv.throttle = 0.5f;
    step(1);
    CHECK_EQ_INT(R.sm.state, MC_ST_MANUAL);
}

static void test_driver_takeover_from_eco(void)
{
    rig_init();
    to_ready();
    engage_eco();
    step(300);
    R.drv.throttle = 0.8f;
    step(1);
    CHECK_EQ_INT(R.sm.state, MC_ST_MANUAL);
    CHECK_EQ_INT(R.last, MC_T_DRIVER_TAKEOVER);
}

static void test_config_invalid_never_resets(void)
{
    rig_init();
    R.aux.config_ok = false;
    step(5);
    CHECK_EQ_INT(R.sm.state, MC_ST_FAULT_LATCHED);
    CHECK(R.prot.latched & MC_FAULT_BIT(MC_F_CONFIG_INVALID));
    R.drv.fault_reset = false;
    step(1);
    R.drv.fault_reset = true;
    step(1);
    CHECK_EQ_INT(R.sm.state, MC_ST_FAULT_LATCHED);
}

static void test_throttle_implausible_faults(void)
{
    rig_init();
    to_ready();
    R.drv.throttle = 0.5f;
    step(100);
    R.drv.throttle_valid = false;
    step(1);
    CHECK_EQ_INT(R.sm.state, MC_ST_FAULT_LATCHED);
    CHECK(R.arb.accepted_Nm == 0.0f);
}

int main(void)
{
    RUN(test_no_torque_after_reset_with_switch_held);
    RUN(test_arm_refused_with_pedal_pressed_or_estop);
    RUN(test_manual_slew_and_estop);
    RUN(test_eco_supervisor_loss_never_jumps_to_manual);
    RUN(test_brake_and_cancel_are_immediate);
    RUN(test_hw_trip_immediate_and_reset_does_not_resume);
    RUN(test_supervisor_cannot_arm_or_exceed_limits);
    RUN(test_coast_request_gate_off);
    RUN(test_thermal_derate_and_recovery);
    RUN(test_unknown_temperature_derates_not_faults);
    RUN(test_voltage_sag_derates_then_trips_after_debounce);
    RUN(test_battery_current_limiter);
    RUN(test_driver_absent_immediate);
    RUN(test_driver_takeover_from_eco);
    RUN(test_config_invalid_never_resets);
    RUN(test_throttle_implausible_faults);
    TEST_MAIN_END();
}

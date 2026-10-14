/* Operating state machine and command arbitration.
 *
 * States: BOOT, SELF_TEST, DISARMED, READY, MANUAL, ECO_ASSIST, DERATED,
 * FAULT_LATCHED. Every transition has a stable id (MC_T_*) documented in
 * docs/ARCHITECTURE_FREEZE.md section "State machine" and logged.
 *
 * Invariants (tested in firmware/tests/test_state_machine.c):
 *  I1 No torque after reset: BOOT/SELF_TEST/DISARMED/FAULT_LATCHED produce 0.
 *  I2 Arming needs an arm-switch OFF->ON edge observed after boot; a switch
 *     held ON through a reset does not arm.
 *  I3 Fault recovery goes FAULT_LATCHED -> DISARMED only; a fresh arm edge,
 *     a throttle release and (for eco) a fresh eco request edge are needed.
 *  I4 Losing the supervisor in ECO_ASSIST goes to READY with zero torque,
 *     never directly into a nonzero manual demand.
 *  I5 Brake / cancel / driver-absent remove torque immediately (no slew).
 *  I6 Hardware trips and latched faults remove torque and PWM immediately.
 *  I7 The supervisor can never arm, never reset faults and never select a
 *     mode: those inputs are local (wired) driver controls only.
 *  I8 accepted torque and |iq_ref|*kt never exceed the local hard ceiling
 *     computed in the same update (no ramp on a ceiling reduction).
 *  I9 Above a reduced supervisory envelope the output falls at least at
 *     slew_down_fast; an envelope is never looser than the newest committed
 *     limits set, whatever limits_ref the request carries.
 */
#ifndef SEMMC_MC_STATE_MACHINE_H
#define SEMMC_MC_STATE_MACHINE_H

#include "semmc/mc_config.h"
#include "semmc/mc_protection.h"
#include "semmc/mc_types.h"

typedef enum {
    MC_ST_BOOT = 0,
    MC_ST_SELF_TEST = 1,
    MC_ST_DISARMED = 2,
    MC_ST_READY = 3,
    MC_ST_MANUAL = 4,
    MC_ST_ECO_ASSIST = 5,
    MC_ST_DERATED = 6,
    MC_ST_FAULT_LATCHED = 7
} mc_state_t;

typedef enum { MC_OWNER_NONE = 0, MC_OWNER_DRIVER = 1, MC_OWNER_SUPERVISOR = 2 } mc_owner_t;

typedef enum {
    MC_T_NONE = 0,
    MC_T_BOOT_CONFIG_OK = 1,       /* BOOT -> SELF_TEST */
    MC_T_BOOT_CONFIG_BAD = 2,      /* BOOT -> FAULT_LATCHED */
    MC_T_SELFTEST_PASS = 3,        /* SELF_TEST -> DISARMED */
    MC_T_SELFTEST_FAIL = 4,        /* SELF_TEST -> FAULT_LATCHED */
    MC_T_ARM = 5,                  /* DISARMED -> READY */
    MC_T_MANUAL_ENGAGE = 6,        /* READY -> MANUAL */
    MC_T_ECO_ENGAGE = 7,           /* READY/MANUAL -> ECO_ASSIST */
    MC_T_ECO_DRIVER_CANCEL = 8,    /* ECO_ASSIST -> READY (brake or cancel) */
    MC_T_ECO_DESELECT = 9,         /* ECO_ASSIST -> READY (mode switch to manual) */
    MC_T_ECO_SUPERVISOR_LOST = 10, /* ECO_ASSIST -> READY */
    MC_T_DRIVER_TAKEOVER = 11,     /* ECO_ASSIST -> MANUAL */
    MC_T_DERATE = 12,              /* READY/MANUAL/ECO_ASSIST -> DERATED */
    MC_T_DERATE_CLEAR = 13,        /* DERATED -> MANUAL */
    MC_T_DISARM = 14,              /* armed -> DISARMED (arm switch off) */
    MC_T_ESTOP = 15,               /* armed -> DISARMED (e-stop chain open) */
    MC_T_FAULT = 16,               /* any -> FAULT_LATCHED */
    MC_T_FAULT_RESET = 17,         /* FAULT_LATCHED -> DISARMED */
    MC_T_DRIVER_ABSENT = 18        /* MANUAL/ECO_ASSIST/DERATED -> READY (dead-man released) */
} mc_transition_t;

/* Reason bits for the requested -> accepted command (16 bits on CAN). */
#define MC_R_NOT_ARMED          0x0001u
#define MC_R_FAULT_INHIBIT      0x0002u
#define MC_R_HW_TRIP            0x0004u
#define MC_R_BRAKE_OVERRIDE     0x0008u
#define MC_R_CANCEL_OVERRIDE    0x0010u
#define MC_R_SUPERVISOR_INVALID 0x0020u /* stale/missing/integrity/session/limits */
#define MC_R_DRIVER_ABSENT      0x0040u
#define MC_R_THROTTLE_LATCH     0x0080u /* must release throttle before torque */
#define MC_R_CLAMP_TORQUE       0x0100u /* static torque / phase-current limit */
#define MC_R_CLAMP_BATTERY      0x0200u /* battery current limit */
#define MC_R_CLAMP_DERATE       0x0400u /* thermal / undervoltage / unknown-temperature */
#define MC_R_CLAMP_SPEED        0x0800u
#define MC_R_SLEW               0x1000u
#define MC_R_SUPERVISOR_BOUND   0x2000u /* clamped by supervisor-declared bounds */
#define MC_R_REGEN_DISABLED     0x4000u
#define MC_R_COAST              0x8000u /* coast request honoured */

/* Local, wired driver controls (never from CAN). */
typedef struct {
    float throttle;          /* 0..1 */
    bool throttle_valid;     /* redundant-track agreement etc. */
    bool brake;
    bool cancel;
    bool mode_eco;           /* mode switch position */
    bool arm_switch;
    bool fault_reset;
    bool estop_chain_ok;     /* sense of the independent hardware isolation chain */
    bool driver_present;     /* dead-man / driver-presence sense */
} mc_driver_inputs_t;

/* Supervisory request after protocol decoding and freshness tracking. */
typedef struct {
    bool session_established;  /* handshake done in this controller boot */
    mc_validity_t req_val;     /* torque request validity (fresh => 0) */
    mc_validity_t limits_val;
    bool limits_match;         /* request references the committed limits set */
    float torque_req_Nm;
    bool coast_request;
    /* Supervisory envelope: the tighter of the newest committed limits set
     * and the set the request references (mc_core.c). Never raises the
     * controller's own hard ceilings. */
    float max_torque_Nm;
    float max_batt_power_W;
} mc_supervisor_input_t;

typedef struct {
    float vbus_V;
    float ibatt_A;             /* + discharge; NaN if unavailable */
    mc_validity_t ibatt_val;
    float speed_mech_rad_s;
    mc_validity_t speed_val;
} mc_arb_meas_t;

typedef struct {
    mc_state_t state;
    mc_owner_t owner;
    mc_transition_t last_transition;
    uint32_t transition_count;
    /* edge tracking */
    bool prev_arm_switch;
    bool arm_seen_off;         /* arm switch observed OFF since boot / last disarm */
    bool prev_fault_reset;
    bool prev_mode_eco;
    bool eco_edge_pending;     /* eco request rising edge not yet consumed */
    bool throttle_latch;       /* true until throttle observed released */
    float selftest_timer_s;
} mc_sm_t;

typedef struct {
    const mc_params_t *p;
    float accepted_Nm;
    float requested_Nm;
    float iq_ref_A;
    float id_ref_A;
    float batt_limit_scale;    /* closed-loop battery-current limiter state */
    /* Diagnostics of the last update (docs/CONTROL_CONTRACT.md). */
    float hard_ceiling_Nm;     /* L2 local hard ceiling; accepted_Nm <= this, always */
    float envelope_Nm;         /* L3 supervisory envelope; < 0 when none is active */
    float target_Nm;           /* request after L2/L3 bounds, before slew */
    uint16_t reason;
    bool pwm_enable;
} mc_arbiter_t;

typedef struct {
    bool config_ok;
    bool selftest_done;
    bool selftest_pass;
    bool output_permitted;     /* host sim: true (virtual); hardware: config gate */
    bool hw_trip;              /* any independent hardware trip asserted now */
} mc_sm_aux_t;

void mc_sm_init(mc_sm_t *sm);
/* One supervisory-rate step. Returns the transition taken (MC_T_NONE if none). */
mc_transition_t mc_sm_step(mc_sm_t *sm, const mc_params_t *p, const mc_driver_inputs_t *drv,
                           const mc_supervisor_input_t *sup, mc_time_us_t now_us,
                           mc_protection_t *prot, const mc_sm_aux_t *aux, float dt);
bool mc_supervisor_ok(const mc_supervisor_input_t *sup);
const char *mc_state_name(mc_state_t s);

void mc_arb_init(mc_arbiter_t *a, const mc_params_t *p);
void mc_arb_step(mc_arbiter_t *a, const mc_sm_t *sm, const mc_driver_inputs_t *drv,
                 const mc_supervisor_input_t *sup, const mc_arb_meas_t *meas,
                 const mc_protection_t *prot, bool hw_trip, float dt);

#endif /* SEMMC_MC_STATE_MACHINE_H */

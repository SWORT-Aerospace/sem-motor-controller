/* Power-stage start-up sequence: the one place that decides when the precharge bypass may close, when
 * the gate driver is woken and when the core may arm.
 *
 * The order follows this board, not a generic controller. The DC link charges through the precharge
 * resistor as soon as the battery is connected (the MCU cannot start or stop that current; it only
 * closes the bypass), and the DRV8353 is supplied from the link (VM = VDC, sheet 04). So:
 *
 *   INHIBITED  a prerequisite is permanently missing (bits in `missing`): calibration, start-up
 *              parameters, a verified gate-driver description or a verified battery-meter
 *              description. Bypass open, driver asleep. Left as soon as nothing is missing.
 *   PRECHARGE  bypass open, driver asleep. Waits for a fresh, valid battery-side sample at or above the
 *              undervoltage trip and at or below the overvoltage trip, then for the link to reach the
 *              closing fraction (mc_precharge, with its timeout). Before the bypass closes, the link
 *              reading is checked against the resistor current measured on the battery side:
 *              |V_link - (V_batt - I_batt x R_pre)| <= agreement. This catches a link or battery reading
 *              that is stuck or offset (either one alone), which the voltage ratio cannot.
 *   DRIVER     bypass closed: the driver is woken with the gates held off and configured, read back
 *              and cleared (mc_drv835x). Bounded by step_timeout_s.
 *   OFFSETS    driver ready, gates off: the platform measures the current-sense zero offsets with the
 *              amplifiers running, against a request number so an old result cannot be reused.
 *              Bounded by step_timeout_s.
 *   READY      gate_driver_ready (the core's permission to arm) while the driver is ready and the
 *              precharge reports both voltages verified.
 *   FAULT      latched. The fault reset (rising edge, outputs off) clears it at most max_attempts
 *              times per power cycle and restarts from PRECHARGE or DRIVER; then LOCKOUT.
 *   LOCKOUT    until the next reset.
 *
 * Every measurement passed in must already carry its age check (mc_ina228_vbus_V with the maximum age):
 * a stale, invalid or never-received sample is passed as not ok, and the bypass never closes on it.
 * A battery disconnect (the battery side below the undervoltage trip) returns to PRECHARGE with the
 * driver asleep; it is not a fault. A reset loses all of this state: the bypass opens in reset
 * (PRECHG_EN pulled down), the link stays charged through the resistor, and the sequence repeats.
 *
 * Not detected (needs the link capacitance and a measured RC time): a shorted bypass or a missing
 * precharge resistor. Not preventable by the MCU: a shorted link dissipates V_batt^2 / R_pre in the
 * precharge resistor for as long as the battery is connected (hardware/review/DESIGN_REVIEW.md, 8). */
#ifndef SEMMC_MC_STARTUP_H
#define SEMMC_MC_STARTUP_H

#include <stdbool.h>
#include <stdint.h>

#include "semmc/mc_drv835x.h"
#include "semmc/mc_ina228.h"
#include "semmc/mc_precharge.h"

typedef enum {
    MC_SU_INHIBITED = 0,
    MC_SU_PRECHARGE,
    MC_SU_DRIVER,
    MC_SU_OFFSETS,
    MC_SU_READY,
    MC_SU_FAULT,
    MC_SU_LOCKOUT
} mc_su_state_t;

/* Why INHIBITED. */
#define MC_SU_MISSING_CONFIG 0x01u /* calibration not valid for hardware */
#define MC_SU_MISSING_PARAMS 0x02u /* a start-up parameter is null or out of range */
#define MC_SU_MISSING_DRIVER 0x04u /* no verified DRV835x description and settings */
#define MC_SU_MISSING_METER  0x08u /* no verified INA228 description and settings */

typedef enum {
    MC_SU_F_NONE = 0,
    MC_SU_F_PRECHARGE,      /* mc_precharge fault: see precharge.fault */
    MC_SU_F_DRIVER,         /* the driver reported a fault: see its error */
    MC_SU_F_DRIVER_TIMEOUT, /* not ready within step_timeout_s */
    MC_SU_F_OFFSETS,        /* offsets rejected or not measured within step_timeout_s */
} mc_su_fault_t;

typedef struct {
    float fraction, timeout_s;  /* power.precharge_complete_fraction, power.precharge_timeout_s */
    float uv_trip_V, ov_trip_V; /* limits.undervoltage_trip_V, limits.overvoltage_trip_V */
    float r_pre_ohm;            /* power.precharge_resistor_ohm */
    float agreement_V;          /* power.precharge_agreement_V */
    float sample_max_age_s;     /* power.battery_sample_max_age_s: applied by the caller to every sample */
    float step_timeout_s;       /* power.startup_step_timeout_s */
    uint32_t max_attempts;      /* power.startup_max_attempts */
} mc_startup_params_t;

typedef struct {
    bool config_ok;
    mc_drv_state_t drv_state;
    bool drv_ready;           /* mc_drv835x_ready() */
    mc_ina_state_t ina_state;
    float v_batt_V, i_batt_A; /* battery side, discharge positive */
    bool v_batt_ok, i_batt_ok; /* fresh and valid */
    float v_link_V;
    bool v_link_ok;
    uint32_t offsets_done_seq; /* request number of the last completed offset measurement */
    bool offsets_ok;           /* its result */
    bool fault_reset_edge;
    bool outputs_off;
} mc_startup_in_t;

typedef struct {
    mc_startup_params_t p;
    bool params_ok;
    mc_precharge_t pc;
    mc_su_state_t state;
    mc_su_fault_t fault;
    uint8_t missing;
    float t_state_s;
    uint32_t attempts;
    uint32_t offsets_req_seq;
    /* outputs, valid after each step */
    bool bypass;            /* PRECHG_EN */
    bool want_driver_awake; /* to mc_drv835x_step */
    bool clear_driver;      /* call mc_drv835x_request_clear this step */
    bool request_offsets;   /* measure offsets for offsets_req_seq */
    bool gate_driver_ready; /* to the core */
} mc_startup_t;

void mc_startup_init(mc_startup_t *s, const mc_startup_params_t *p);
void mc_startup_step(mc_startup_t *s, float dt_s, const mc_startup_in_t *in);

#endif /* SEMMC_MC_STARTUP_H */

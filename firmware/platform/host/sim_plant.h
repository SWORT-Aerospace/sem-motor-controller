/* HOST-ONLY simulated plant for closed-loop tests. NOT a validated model of
 * any real motor, inverter, battery or vehicle.
 *
 *  - PMSM in dq (Ld, Lq, R, lambda, p) with averaged inverter (no dead time).
 *  - Gate-off: currents decay through the diodes; if line-line back-EMF
 *    exceeds Vbus a rectification flag is raised (configs that allow this are
 *    rejected by the validator, so the flag should never appear).
 *  - Rigid drivetrain coupling (no freewheel; freewheel coast is modelled in
 *    models/vehicle). Rolling + aero + grade resistance.
 *  - Battery: OCV - R_int * I. Inverter loss: simple conduction + switching.
 *  - First-order FET and winding temperatures.
 *  - Sensors with noise, low-side shunt sampling windows, and fault injection.
 */
#ifndef SEMMC_SIM_PLANT_H
#define SEMMC_SIM_PLANT_H

#include <stdbool.h>
#include <stdint.h>

#include "semmc/mc_config.h"
#include "semmc/mc_control.h"

typedef struct {
    /* plant constants (synthetic) */
    double ocv_V, r_int_ohm;
    double crr, cda_m2, rho_air, g;
    double rds_on_ohm, k_sw_W_per_VA, aux_W;
    double rth_fet_K_W, cth_fet_J_K, rth_mot_K_W, cth_mot_J_K, t_amb_degC;
    double shunt_window;     /* min low-side fraction for a valid sample */
    double i_noise_A, v_noise_V;
} sim_plant_const_t;

typedef struct {
    double current_bias_A[3];
    bool phase_missing[3];
    bool hall_stuck;
    uint8_t hall_stuck_code;
    bool vbus_sensor_nan;
    bool tfet_sensor_nan;
    bool tmotor_sensor_nan;
    double ibatt_bias_A;
    bool ibatt_missing;
    double tfet_offset_degC;
    double grade_rad;
    bool hw_overcurrent;      /* forced hardware trip */
    bool gate_driver_fault;
    double extra_load_N;
} sim_fault_t;

typedef struct {
    const mc_params_t *p;
    sim_plant_const_t k;
    sim_fault_t fault;
    /* state */
    double id, iq;            /* A */
    double w_m;               /* motor mech rad/s */
    double th_e;              /* rad */
    double s_m;               /* vehicle position */
    double vbus;              /* V */
    double ibatt;             /* A (+discharge) */
    double t_fet, t_mot;      /* degC */
    double energy_J;          /* battery terminal energy, + discharge */
    double p_batt_W;
    double te_Nm;
    bool rectifying;
    uint32_t rng;
} sim_plant_t;

typedef struct {
    mc_phase_meas_t phase;
    uint8_t hall_code;
    float vbus_V;
    float ibatt_A;
    bool ibatt_valid;
    float t_fet_degC, t_mot_degC;
    bool vbus_valid, t_fet_valid, t_mot_valid;
} sim_sensors_t;

void sim_plant_init(sim_plant_t *s, const mc_params_t *p);
/* Advance by dt with the given duties (pwm_enable=false => gate-off). */
void sim_plant_step(sim_plant_t *s, bool pwm_enable, const mc_duty_t *duty, double dt);
void sim_plant_sense(sim_plant_t *s, const mc_duty_t *duty, bool pwm_enable, sim_sensors_t *out);
double sim_plant_vehicle_speed(const sim_plant_t *s);

#endif

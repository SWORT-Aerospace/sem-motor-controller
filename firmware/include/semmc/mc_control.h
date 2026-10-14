/* Portable motor-control primitives.
 *
 * Conventions (documented once, used everywhere):
 *  - Clarke transform is AMPLITUDE-INVARIANT: a balanced set of phase currents
 *    of peak I gives |(i_alpha, i_beta)| = I.
 *        2-input (a, b measured; c = -(a+b)):  alpha = a,  beta = (a + 2b)/sqrt(3)
 *        3-input (a, b, c measured):           alpha = (2a - b - c)/3,  beta = (b - c)/sqrt(3)
 *    The 3-input form removes any common-mode (zero-sequence) error.
 *  - Park: d =  alpha cos(th) + beta sin(th);  q = -alpha sin(th) + beta cos(th)
 *    th = electrical angle of the rotor PM d-axis from the phase-a axis,
 *    increasing for a->b->c rotation (forward).
 *  - Torque: T = 1.5 p (lambda iq + (Ld - Lq) id iq).
 *  - Phase voltage limit for linear SVPWM: |v_dq| <= Vbus / sqrt(3).
 *
 * Every function here is deterministic, allocation-free and safe to call from
 * the current-control interrupt (no I/O, no logging, no blocking).
 */
#ifndef SEMMC_MC_CONTROL_H
#define SEMMC_MC_CONTROL_H

#include "semmc/mc_types.h"

/* ---- PI controller ------------------------------------------------------ */
typedef struct {
    float kp, ki;          /* output units per error unit, per (error unit * s) */
    float out_min, out_max;
    float integ;           /* integrator state, in output units */
    bool saturated;        /* last output was clamped */
    bool dt_rejected;      /* last call had an invalid dt (output held) */
    float last_out;
} mc_pi_t;

void mc_pi_init(mc_pi_t *pi, float kp, float ki, float out_min, float out_max);
void mc_pi_reset(mc_pi_t *pi);
/* Change limits at run time (e.g. voltage limit follows Vbus). The integrator
 * is clamped into the new limits immediately. */
void mc_pi_set_limits(mc_pi_t *pi, float out_min, float out_max);
/* u = kp*e + integ + ff, clamped to [out_min, out_max].
 * Anti-windup: conditional integration - the integrator only moves when the
 * output is unsaturated or the error drives it back out of saturation; the
 * integrator itself is also clamped to the limits.
 * dt must be finite and in (0, dt_max]; otherwise the previous output is held,
 * nothing integrates and dt_rejected is set. */
float mc_pi_step(mc_pi_t *pi, float err, float ff, float dt, float dt_max);

/* ---- transforms --------------------------------------------------------- */
typedef struct { float alpha, beta; } mc_ab_t;
typedef struct { float d, q; } mc_dq_t;
typedef struct { float a, b, c; } mc_abc_t;

mc_ab_t mc_clarke2(float a, float b);
mc_ab_t mc_clarke3(float a, float b, float c);
mc_abc_t mc_inv_clarke(mc_ab_t v);
mc_dq_t mc_park(mc_ab_t x, float sin_th, float cos_th);
mc_ab_t mc_inv_park(mc_dq_t x, float sin_th, float cos_th);

/* ---- phase currents: measured vs reconstructed ---------------------------- */
#define MC_PH_A 0x1u
#define MC_PH_B 0x2u
#define MC_PH_C 0x4u

typedef struct {
    float i[3];              /* A, + into motor. Entries not in measured_mask are ignored. */
    uint8_t measured_mask;   /* phases sampled in a VALID low-side window this cycle */
} mc_phase_meas_t;

typedef struct {
    float i[3];
    uint8_t measured_mask;
    uint8_t reconstructed_mask;  /* derived by KCL from the other two */
    bool kcl_available;          /* true only when all three were measured */
    float kcl_residual_A;        /* a+b+c, meaningful only when kcl_available */
    bool valid;                  /* >= 2 phases measured */
} mc_phase_currents_t;

/* Resolve one sample. With 3 measured phases nothing is reconstructed and the
 * KCL residual is available as an independent check. With exactly 2, the
 * third is reconstructed and flagged - it is NOT independent evidence and the
 * KCL residual is unavailable (it would be identically zero). */
void mc_currents_resolve(const mc_phase_meas_t *in, mc_phase_currents_t *out);
mc_ab_t mc_currents_clarke(const mc_phase_currents_t *pc);

/* ---- voltage limiting and modulation --------------------------------------- */
typedef enum { MC_VLIM_D_PRIORITY = 0, MC_VLIM_PROPORTIONAL = 1 } mc_vlim_mode_t;

/* Limit |v| <= vmax. Returns true when limiting was applied. */
bool mc_voltage_limit(mc_dq_t *v, float vmax, mc_vlim_mode_t mode);

typedef struct { float a, b, c; } mc_duty_t;

/* Min-max zero-sequence injection (equivalent to symmetric SVPWM).
 * duty in [duty_min, duty_max]; returns true if any duty had to be clamped.
 * vbus <= 0 or nonfinite inputs give 50 % duties and return true. */
bool mc_svpwm(mc_ab_t v, float vbus, float duty_min, float duty_max, mc_duty_t *duty);

/* ---- dq current limit ---------------------------------------------------- */
/* Scale (id, iq) so that id^2 + iq^2 <= imax^2, keeping id priority (field
 * component is kept, q is reduced first). Returns true if limited. */
bool mc_current_limit(mc_dq_t *i_ref, float imax);

/* ---- FOC current loop -------------------------------------------------------- */
typedef struct {
    mc_pi_t pi_d, pi_q;
    float ld_H, lq_H, lambda_Wb;
    float vlimit_fraction;     /* fraction of Vbus/sqrt(3) usable, e.g. 0.95 */
    float duty_min, duty_max;
    float dt_max_s;
    bool decoupling;           /* cross-coupling + back-EMF feed-forward */
} mc_foc_t;

typedef struct {
    mc_dq_t i_ref;             /* A */
    float sin_th, cos_th;      /* of the electrical angle used for control */
    float omega_e;             /* electrical rad/s (for feed-forward) */
    float vbus;                /* V, measured */
    float dt;                  /* s since last step */
} mc_foc_in_t;

typedef struct {
    mc_dq_t i_meas;            /* dq of the resolved measured currents */
    mc_dq_t v_cmd;             /* after limiting */
    mc_ab_t v_ab;
    mc_duty_t duty;
    bool v_limited;
    bool duty_clamped;
    bool inhibit;              /* inputs invalid: caller must disable outputs */
} mc_foc_out_t;

void mc_foc_init(mc_foc_t *f, float kp, float ki, float ld, float lq, float lambda,
                 float duty_min, float duty_max, float dt_max_s);
void mc_foc_reset(mc_foc_t *f);
void mc_foc_step(mc_foc_t *f, const mc_foc_in_t *in, const mc_phase_currents_t *pc, mc_foc_out_t *out);

/* ---- Hall-sensor rotor position --------------------------------------------- */
typedef struct {
    int8_t code_to_sector[8];  /* -1 illegal */
    float offset_rad;          /* electrical angle of the START of sector 0 */
    float timeout_s;           /* no edge for this long => speed 0, interpolation off */
    /* state */
    bool have_sector;
    int8_t sector;
    int8_t direction;          /* +1 forward, -1 reverse, 0 unknown */
    float t_since_edge;        /* s */
    float edge_period;         /* s between the last two edges, 0 = unknown */
    float omega_e;             /* rad/s electrical, signed */
    uint16_t illegal_codes;    /* consecutive illegal codes */
    uint16_t skipped_sectors;  /* consecutive non-adjacent transitions */
    bool invalid;
} mc_hall_t;

void mc_hall_init(mc_hall_t *h, const int8_t code_to_sector[8], float offset_rad, float timeout_s);
/* Advance by dt with the current 3-bit code (bit0 = A, bit1 = B, bit2 = C).
 * Returns the estimated electrical angle in [0, 2pi). Angle is interpolated
 * within a sector using the measured edge period, clamped to the sector. */
float mc_hall_update(mc_hall_t *h, uint8_t code, float dt);

/* ---- small helpers ------------------------------------------------------------- */
float mc_wrap_2pi(float th);
float mc_slew(float current, float target, float up_rate, float down_rate, float dt);

#endif /* SEMMC_MC_CONTROL_H */

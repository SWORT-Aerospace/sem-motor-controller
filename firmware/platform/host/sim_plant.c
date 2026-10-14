/* HOST-ONLY simulated plant. See sim_plant.h for scope and limitations. */
#include "sim_plant.h"

#include <math.h>
#include <string.h>

#define PI_D 3.141592653589793

static double urand(uint32_t *s)
{
    *s = *s * 1664525u + 1013904223u;
    return ((double)(*s >> 8) / 16777216.0) - 0.5;
}

static double noise(uint32_t *s)
{
    return (urand(s) + urand(s) + urand(s)) * 2.0; /* approx N(0, 0.5) */
}

void sim_plant_init(sim_plant_t *s, const mc_params_t *p)
{
    memset(s, 0, sizeof(*s));
    s->p = p;
    /* SYNTHETIC constants (not measured). */
    s->k.ocv_V = 46.0;
    s->k.r_int_ohm = 0.08;
    s->k.crr = 0.0025;
    s->k.cda_m2 = 0.035;
    s->k.rho_air = 1.2;
    s->k.g = 9.81;
    s->k.rds_on_ohm = 0.004;
    s->k.k_sw_W_per_VA = 0.0004;
    s->k.aux_W = 3.0;
    s->k.rth_fet_K_W = 2.0;
    s->k.cth_fet_J_K = 30.0;
    s->k.rth_mot_K_W = 1.5;
    s->k.cth_mot_J_K = 400.0;
    s->k.t_amb_degC = 30.0;
    s->k.shunt_window = 0.06;
    s->k.i_noise_A = 0.05;
    s->k.v_noise_V = 0.02;
    s->vbus = s->k.ocv_V;
    s->t_fet = s->k.t_amb_degC;
    s->t_mot = s->k.t_amb_degC;
    s->rng = 12345u;
    s->th_e = 0.3;
}

double sim_plant_vehicle_speed(const sim_plant_t *s)
{
    const double r = s->p->wheel_circumference_m / (2.0 * PI_D);
    return s->w_m * r / s->p->gear_ratio;
}

void sim_plant_step(sim_plant_t *s, bool pwm_enable, const mc_duty_t *duty, double dt)
{
    const mc_params_t *p = s->p;
    const double pp = (double)p->pole_pairs;
    const double R = p->rs_ohm, Ld = p->ld_H, Lq = p->lq_H, lam = p->lambda_Wb;
    const double w_e = s->w_m * pp;
    const double vbus = s->vbus;
    double vd = 0.0, vq = 0.0;
    s->rectifying = false;
    if (pwm_enable) {
        const double va = ((double)duty->a - 0.5) * vbus, vb = ((double)duty->b - 0.5) * vbus,
                     vc = ((double)duty->c - 0.5) * vbus;
        const double valpha = (2.0 * va - vb - vc) / 3.0, vbeta = (vb - vc) / sqrt(3.0);
        const double c = cos(s->th_e), sn = sin(s->th_e);
        vd = valpha * c + vbeta * sn;
        vq = -valpha * sn + vbeta * c;
        s->id += dt * (vd - R * s->id + w_e * Lq * s->iq) / Ld;
        s->iq += dt * (vq - R * s->iq - w_e * Ld * s->id - w_e * lam) / Lq;
    } else {
        /* Diodes clamp the decaying current against the bus. */
        const double mag = sqrt(s->id * s->id + s->iq * s->iq);
        if (mag > 0.0) {
            const double di = dt * vbus / ((Ld + Lq) * 0.5);
            const double k = mag > di ? (mag - di) / mag : 0.0;
            s->id *= k;
            s->iq *= k;
        }
        if (sqrt(3.0) * lam * fabs(w_e) > vbus) s->rectifying = true;
    }

    const double te = 1.5 * pp * (lam * s->iq + (Ld - Lq) * s->id * s->iq);
    s->te_Nm = te;

    /* Vehicle (rigid coupling). */
    const double r = p->wheel_circumference_m / (2.0 * PI_D);
    const double G = p->gear_ratio, eta = p->drivetrain_eff, m = p->mass_kg;
    const double v = s->w_m * r / G;
    const double f_drive = te >= 0.0 ? te * G * eta / r : te * G / (eta * r);
    const double f_aero = 0.5 * s->k.rho_air * s->k.cda_m2 * v * fabs(v);
    const double f_grade = m * s->k.g * sin(s->fault.grade_rad);
    const double f_roll_mag = s->k.crr * m * s->k.g * cos(s->fault.grade_rad);
    double f_net = f_drive - f_aero - f_grade - s->fault.extra_load_N;
    if (v > 1e-4) {
        f_net -= f_roll_mag;
    } else if (v < -1e-4) {
        f_net += f_roll_mag;
    } else {
        /* standstill: rolling resistance holds unless exceeded */
        if (fabs(f_net) <= f_roll_mag) f_net = 0.0;
        else f_net -= (f_net > 0.0 ? f_roll_mag : -f_roll_mag);
    }
    const double j_eff = p->inertia_kg_m2 + m * r * r / (G * G);
    s->w_m += dt * f_net * (r / G) / j_eff; /* motor-side torque of the net force over total inertia */
    if (fabs(sim_plant_vehicle_speed(s)) < 1e-4 && f_net == 0.0) s->w_m = 0.0;
    s->th_e = fmod(s->th_e + s->w_m * pp * dt, 2.0 * PI_D);
    if (s->th_e < 0.0) s->th_e += 2.0 * PI_D;
    s->s_m += sim_plant_vehicle_speed(s) * dt;

    /* Electrical power balance. */
    const double p_phase = pwm_enable ? 1.5 * (vd * s->id + vq * s->iq) : 0.0;
    const double i_pk = sqrt(s->id * s->id + s->iq * s->iq);
    const double i_rms = i_pk / sqrt(2.0);
    const double p_inv = pwm_enable ? (3.0 * i_rms * i_rms * s->k.rds_on_ohm + s->k.k_sw_W_per_VA * vbus * i_pk * 3.0) : 0.0;
    const double p_dc = p_phase + p_inv + s->k.aux_W;
    double i = p_dc / vbus;
    s->vbus = s->k.ocv_V - s->k.r_int_ohm * i;
    if (s->vbus < 1.0) s->vbus = 1.0;
    i = p_dc / s->vbus;
    s->ibatt = i;
    s->p_batt_W = s->vbus * i;
    s->energy_J += s->p_batt_W * dt;

    const double p_cu = 1.5 * R * (s->id * s->id + s->iq * s->iq);
    s->t_fet += dt * (p_inv - (s->t_fet - s->k.t_amb_degC) / s->k.rth_fet_K_W) / s->k.cth_fet_J_K;
    s->t_mot += dt * (p_cu - (s->t_mot - s->k.t_amb_degC) / s->k.rth_mot_K_W) / s->k.cth_mot_J_K;
}

void sim_plant_sense(sim_plant_t *s, const mc_duty_t *duty, bool pwm_enable, sim_sensors_t *o)
{
    const mc_params_t *p = s->p;
    const double c = cos(s->th_e), sn = sin(s->th_e);
    const double ia = s->id * c - s->iq * sn;
    const double ib_ = s->id * sn + s->iq * c; /* beta */
    const double iabc[3] = {ia, -0.5 * ia + 0.5 * sqrt(3.0) * ib_, -0.5 * ia - 0.5 * sqrt(3.0) * ib_};
    const float d[3] = {duty->a, duty->b, duty->c};
    o->phase.measured_mask = 0u;
    for (int k = 0; k < 3; k++) {
        o->phase.i[k] = (float)(iabc[k] + s->fault.current_bias_A[k] + s->k.i_noise_A * noise(&s->rng));
        /* Low-side shunt: valid only if the low switch is on long enough. */
        const bool window_ok = !pwm_enable || (1.0 - (double)d[k]) >= s->k.shunt_window;
        if (window_ok && !s->fault.phase_missing[k]) o->phase.measured_mask |= (uint8_t)(1u << k);
    }
    /* Hall code from the true angle. */
    const double sector_f = (s->th_e - (double)p->hall_angle_offset_rad) / (PI_D / 3.0);
    int sector = (int)floor(sector_f);
    sector = ((sector % 6) + 6) % 6;
    uint8_t code = 0u;
    for (uint8_t k = 0; k < 8u; k++) {
        if (p->hall_code_to_sector[k] == sector) code = k;
    }
    o->hall_code = s->fault.hall_stuck ? s->fault.hall_stuck_code : code;
    o->vbus_V = (float)(s->vbus + s->k.v_noise_V * noise(&s->rng));
    o->vbus_valid = !s->fault.vbus_sensor_nan;
    if (s->fault.vbus_sensor_nan) o->vbus_V = NAN;
    o->ibatt_A = (float)(s->ibatt + s->fault.ibatt_bias_A + 0.01 * noise(&s->rng));
    o->ibatt_valid = !s->fault.ibatt_missing;
    o->t_fet_degC = (float)(s->t_fet + s->fault.tfet_offset_degC);
    o->t_mot_degC = (float)s->t_mot;
    o->t_fet_valid = !s->fault.tfet_sensor_nan;
    o->t_mot_valid = !s->fault.tmotor_sensor_nan;
    if (s->fault.tfet_sensor_nan) o->t_fet_degC = NAN;
    if (s->fault.tmotor_sensor_nan) o->t_mot_degC = NAN;
}

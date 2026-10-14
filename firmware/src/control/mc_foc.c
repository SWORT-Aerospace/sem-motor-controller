/* Field-oriented current loop: measured currents -> dq -> PI -> limit -> SVPWM. */
#include <math.h>

#include "semmc/mc_control.h"

void mc_foc_init(mc_foc_t *f, float kp, float ki, float ld, float lq, float lambda,
                 float duty_min, float duty_max, float dt_max_s)
{
    mc_pi_init(&f->pi_d, kp, ki, 0.0f, 0.0f);
    mc_pi_init(&f->pi_q, kp, ki, 0.0f, 0.0f);
    f->ld_H = ld;
    f->lq_H = lq;
    f->lambda_Wb = lambda;
    f->vlimit_fraction = 0.95f;
    f->duty_min = duty_min;
    f->duty_max = duty_max;
    f->dt_max_s = dt_max_s;
    f->decoupling = true;
}

void mc_foc_reset(mc_foc_t *f)
{
    mc_pi_reset(&f->pi_d);
    mc_pi_reset(&f->pi_q);
}

void mc_foc_step(mc_foc_t *f, const mc_foc_in_t *in, const mc_phase_currents_t *pc, mc_foc_out_t *out)
{
    out->inhibit = false;
    out->v_limited = false;
    out->duty_clamped = false;
    out->v_cmd.d = out->v_cmd.q = 0.0f;
    out->v_ab.alpha = out->v_ab.beta = 0.0f;
    out->duty.a = out->duty.b = out->duty.c = 0.5f;
    out->i_meas.d = out->i_meas.q = 0.0f;

    if (!pc->valid || !(in->vbus > 0.0f) || !mc_isfinite(in->vbus) || !mc_isfinite(in->sin_th) ||
        !mc_isfinite(in->cos_th) || !mc_isfinite(in->i_ref.d) || !mc_isfinite(in->i_ref.q) ||
        !mc_isfinite(in->omega_e)) {
        out->inhibit = true;
        mc_foc_reset(f);
        return;
    }

    const mc_ab_t iab = mc_currents_clarke(pc);
    out->i_meas = mc_park(iab, in->sin_th, in->cos_th);

    const float vmax = f->vlimit_fraction * in->vbus * MC_INV_SQRT3_F;
    /* d has priority for the voltage budget; q gets what remains. */
    mc_pi_set_limits(&f->pi_d, -vmax, vmax);

    float ff_d = 0.0f, ff_q = 0.0f;
    if (f->decoupling) {
        ff_d = -in->omega_e * f->lq_H * out->i_meas.q;
        ff_q = in->omega_e * (f->ld_H * out->i_meas.d + f->lambda_Wb);
    }
    const float vd = mc_pi_step(&f->pi_d, in->i_ref.d - out->i_meas.d, ff_d, in->dt, f->dt_max_s);
    const float vq_max = sqrtf(mc_maxf(vmax * vmax - vd * vd, 0.0f));
    mc_pi_set_limits(&f->pi_q, -vq_max, vq_max);
    const float vq = mc_pi_step(&f->pi_q, in->i_ref.q - out->i_meas.q, ff_q, in->dt, f->dt_max_s);

    if (f->pi_d.dt_rejected || f->pi_q.dt_rejected) {
        /* Invalid time step: do not apply a stale voltage vector. */
        out->inhibit = true;
        return;
    }

    out->v_cmd.d = vd;
    out->v_cmd.q = vq;
    out->v_limited = mc_voltage_limit(&out->v_cmd, vmax, MC_VLIM_D_PRIORITY) || f->pi_d.saturated || f->pi_q.saturated;
    out->v_ab = mc_inv_park(out->v_cmd, in->sin_th, in->cos_th);
    out->duty_clamped = mc_svpwm(out->v_ab, in->vbus, f->duty_min, f->duty_max, &out->duty);
}

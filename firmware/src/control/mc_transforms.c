#include <math.h>

#include "semmc/mc_control.h"

mc_ab_t mc_clarke2(float a, float b)
{
    mc_ab_t r;
    r.alpha = a;
    r.beta = (a + 2.0f * b) * MC_INV_SQRT3_F;
    return r;
}

mc_ab_t mc_clarke3(float a, float b, float c)
{
    mc_ab_t r;
    r.alpha = (2.0f * a - b - c) * (1.0f / 3.0f);
    r.beta = (b - c) * MC_INV_SQRT3_F;
    return r;
}

mc_abc_t mc_inv_clarke(mc_ab_t v)
{
    mc_abc_t r;
    r.a = v.alpha;
    r.b = -0.5f * v.alpha + 0.5f * MC_SQRT3_F * v.beta;
    r.c = -0.5f * v.alpha - 0.5f * MC_SQRT3_F * v.beta;
    return r;
}

mc_dq_t mc_park(mc_ab_t x, float s, float c)
{
    mc_dq_t r;
    r.d = x.alpha * c + x.beta * s;
    r.q = -x.alpha * s + x.beta * c;
    return r;
}

mc_ab_t mc_inv_park(mc_dq_t x, float s, float c)
{
    mc_ab_t r;
    r.alpha = x.d * c - x.q * s;
    r.beta = x.d * s + x.q * c;
    return r;
}

void mc_currents_resolve(const mc_phase_meas_t *in, mc_phase_currents_t *out)
{
    out->measured_mask = (uint8_t)(in->measured_mask & 0x7u);
    out->reconstructed_mask = 0u;
    out->kcl_available = false;
    out->kcl_residual_A = 0.0f;
    out->valid = false;
    for (int k = 0; k < 3; k++) out->i[k] = in->i[k];
    /* Nonfinite samples are treated as not measured. */
    for (int k = 0; k < 3; k++) {
        if ((out->measured_mask & (1u << k)) && !mc_isfinite(in->i[k])) {
            out->measured_mask = (uint8_t)(out->measured_mask & ~(1u << k));
        }
    }
    switch (out->measured_mask) {
    case MC_PH_A | MC_PH_B | MC_PH_C:
        out->kcl_available = true;
        out->kcl_residual_A = in->i[0] + in->i[1] + in->i[2];
        out->valid = true;
        break;
    case MC_PH_A | MC_PH_B:
        out->i[2] = -(in->i[0] + in->i[1]);
        out->reconstructed_mask = MC_PH_C;
        out->valid = true;
        break;
    case MC_PH_A | MC_PH_C:
        out->i[1] = -(in->i[0] + in->i[2]);
        out->reconstructed_mask = MC_PH_B;
        out->valid = true;
        break;
    case MC_PH_B | MC_PH_C:
        out->i[0] = -(in->i[1] + in->i[2]);
        out->reconstructed_mask = MC_PH_A;
        out->valid = true;
        break;
    default:
        out->i[0] = out->i[1] = out->i[2] = 0.0f;
        break;
    }
}

mc_ab_t mc_currents_clarke(const mc_phase_currents_t *pc)
{
    if (pc->kcl_available) return mc_clarke3(pc->i[0], pc->i[1], pc->i[2]);
    return mc_clarke2(pc->i[0], pc->i[1]); /* c (or the missing one) is implied by KCL */
}

bool mc_voltage_limit(mc_dq_t *v, float vmax, mc_vlim_mode_t mode)
{
    if (!(vmax > 0.0f) || !mc_isfinite(v->d) || !mc_isfinite(v->q)) {
        v->d = 0.0f;
        v->q = 0.0f;
        return true;
    }
    const float mag2 = v->d * v->d + v->q * v->q;
    if (mag2 <= vmax * vmax) return false;
    if (mode == MC_VLIM_D_PRIORITY) {
        v->d = mc_clampf(v->d, -vmax, vmax);
        const float qmax = sqrtf(mc_maxf(vmax * vmax - v->d * v->d, 0.0f));
        v->q = mc_clampf(v->q, -qmax, qmax);
    } else {
        const float k = vmax / sqrtf(mag2);
        v->d *= k;
        v->q *= k;
    }
    return true;
}

bool mc_current_limit(mc_dq_t *i, float imax)
{
    if (!(imax > 0.0f) || !mc_isfinite(i->d) || !mc_isfinite(i->q)) {
        i->d = 0.0f;
        i->q = 0.0f;
        return true;
    }
    const float mag2 = i->d * i->d + i->q * i->q;
    if (mag2 <= imax * imax) return false;
    i->d = mc_clampf(i->d, -imax, imax);
    const float qmax = sqrtf(mc_maxf(imax * imax - i->d * i->d, 0.0f));
    i->q = mc_clampf(i->q, -qmax, qmax);
    return true;
}

bool mc_svpwm(mc_ab_t v, float vbus, float duty_min, float duty_max, mc_duty_t *duty)
{
    if (!(vbus > 0.0f) || !mc_isfinite(vbus) || !mc_isfinite(v.alpha) || !mc_isfinite(v.beta)) {
        duty->a = duty->b = duty->c = 0.5f;
        return true;
    }
    const mc_abc_t p = mc_inv_clarke(v);
    const float vmax = mc_maxf(p.a, mc_maxf(p.b, p.c));
    const float vmin = mc_minf(p.a, mc_minf(p.b, p.c));
    const float v0 = -0.5f * (vmax + vmin);
    const float inv = 1.0f / vbus;
    float d[3] = {0.5f + (p.a + v0) * inv, 0.5f + (p.b + v0) * inv, 0.5f + (p.c + v0) * inv};
    bool clamped = false;
    for (int k = 0; k < 3; k++) {
        const float c = mc_clampf(d[k], duty_min, duty_max);
        clamped = clamped || (c != d[k]);
        d[k] = c;
    }
    duty->a = d[0];
    duty->b = d[1];
    duty->c = d[2];
    return clamped;
}

#include "semmc/mc_io.h"

#include <math.h>

static bool all_finite(const float *v, int n)
{
    for (int i = 0; i < n; i++) {
        if (!mc_isfinite(v[i])) return false;
    }
    return true;
}

/* ---------------------------------------------------------------- NTC */
void mc_ntc_init(mc_ntc_t *n, float r25_ohm, float beta_K, float bias_ohm)
{
    const float v[3] = {r25_ohm, beta_K, bias_ohm};
    n->r25_ohm = r25_ohm;
    n->beta_K = beta_K;
    n->bias_ohm = bias_ohm;
    n->configured = all_finite(v, 3) && r25_ohm > 0.0f && beta_K > 0.0f && bias_ohm > 0.0f;
}

float mc_ntc_temp_degC(const mc_ntc_t *n, float ratio, mc_validity_t *val)
{
    if (!n->configured) {
        *val = MC_VAL_MISSING;
        return NAN;
    }
    if (!mc_isfinite(ratio)) {
        *val = MC_VAL_NONFINITE;
        return NAN;
    }
    if (ratio <= MC_NTC_RATIO_MIN || ratio >= MC_NTC_RATIO_MAX) {
        *val = MC_VAL_OUT_OF_RANGE; /* open (ratio -> 1) or shorted (ratio -> 0) sensor */
        return NAN;
    }
    /* Divider: bias from the supply to the node, NTC from the node to ground. */
    const float r = n->bias_ohm * ratio / (1.0f - ratio);
    const float inv_t = 1.0f / 298.15f + logf(r / n->r25_ohm) / n->beta_K;
    *val = MC_VAL_OK;
    return 1.0f / inv_t - 273.15f;
}

/* ---------------------------------------------------------------- pedal */
void mc_pedal_init(mc_pedal_t *p, float a_rel_V, float a_full_V, float b_rel_V, float b_full_V, float tol,
                   float divider)
{
    const float v[6] = {a_rel_V, a_full_V, b_rel_V, b_full_V, tol, divider};
    p->a_rel_V = a_rel_V;
    p->a_full_V = a_full_V;
    p->b_rel_V = b_rel_V;
    p->b_full_V = b_full_V;
    p->tol = tol;
    p->divider = divider;
    p->configured = all_finite(v, 6) && a_full_V != a_rel_V && b_full_V != b_rel_V && tol > 0.0f && divider > 0.0f;
}

void mc_pedal_eval(const mc_pedal_t *p, float va_pin_V, float vb_pin_V, mc_pedal_out_t *out)
{
    out->throttle = 0.0f;
    out->valid = false;
    out->frac_a = out->frac_b = NAN;
    if (!p->configured || !mc_isfinite(va_pin_V) || !mc_isfinite(vb_pin_V)) return;
    /* A track may rise or fall with travel; the calibration end points carry the direction. */
    const float fa = (va_pin_V * p->divider - p->a_rel_V) / (p->a_full_V - p->a_rel_V);
    const float fb = (vb_pin_V * p->divider - p->b_rel_V) / (p->b_full_V - p->b_rel_V);
    out->frac_a = fa;
    out->frac_b = fb;
    const bool in_range = fa >= -p->tol && fa <= 1.0f + p->tol && fb >= -p->tol && fb <= 1.0f + p->tol;
    const bool agree = mc_absf(fa - fb) <= p->tol;
    if (!in_range || !agree) return; /* open wire, short, or a track that disagrees: no torque */
    out->valid = true;
    out->throttle = mc_clampf(mc_minf(fa, fb), 0.0f, 1.0f); /* the lower track: never more than either reads */
}

/* ---------------------------------------------------------------- ADC scaling */
void mc_adc_scale_init(mc_adc_scale_t *s, float vref_V, float bits, float shunt_ohm, float gain, float polarity,
                       const float offset_counts[3], float offset_tol_counts, float vbus_ratio)
{
    const float cur[8] = {vref_V, bits, shunt_ohm, gain, polarity, offset_counts[0], offset_counts[1], offset_counts[2]};
    s->vref_V = vref_V;
    s->full_scale = mc_isfinite(bits) ? ldexpf(1.0f, (int)bits) : NAN;
    s->vbus_ratio = vbus_ratio;
    for (int k = 0; k < 3; k++) s->offset[k] = s->offset_cal[k] = offset_counts[k];
    s->offset_tol = offset_tol_counts;
    s->vbus_configured = mc_isfinite(vref_V) && vref_V > 0.0f && mc_isfinite(s->full_scale) &&
                         mc_isfinite(vbus_ratio) && vbus_ratio > 0.0f;
    s->current_configured = all_finite(cur, 8) && shunt_ohm > 0.0f && gain > 0.0f && vref_V > 0.0f &&
                            (polarity == 0.0f || polarity == 1.0f) && mc_isfinite(offset_tol_counts) &&
                            offset_tol_counts > 0.0f;
    const float sign = polarity == 1.0f ? -1.0f : 1.0f;
    s->amps_per_count = s->current_configured ? sign * (vref_V / s->full_scale) / (gain * shunt_ohm) : NAN;
}

float mc_adc_vbus_V(const mc_adc_scale_t *s, uint32_t counts, mc_validity_t *val)
{
    if (!s->vbus_configured) {
        *val = MC_VAL_MISSING;
        return NAN;
    }
    /* At full scale the divider output is clipped and the bus could be anywhere above it. */
    *val = (float)counts >= s->full_scale - 1.0f ? MC_VAL_SATURATED : MC_VAL_OK;
    return mc_adc_volts(s, counts) * s->vbus_ratio;
}

bool mc_adc_accept_offsets(mc_adc_scale_t *s, const float measured[3])
{
    if (!s->current_configured) return false;
    for (int k = 0; k < 3; k++) {
        if (!mc_isfinite(measured[k]) || mc_absf(measured[k] - s->offset_cal[k]) > s->offset_tol) {
            for (int j = 0; j < 3; j++) s->offset[j] = s->offset_cal[j];
            return false;
        }
    }
    for (int k = 0; k < 3; k++) s->offset[k] = measured[k];
    return true;
}

/* ---------------------------------------------------------------- sampling window */
uint8_t mc_lowside_sample_mask(const mc_duty_t *applied, bool outputs_on, float deadtime_s, float settle_s,
                               float f_pwm_Hz)
{
    if (!outputs_on) return MC_PH_A | MC_PH_B | MC_PH_C;
    const float dmax = 1.0f - 2.0f * (deadtime_s + settle_s) * f_pwm_Hz;
    if (!mc_isfinite(dmax)) return 0u;
    uint8_t m = 0u;
    if (applied->a <= dmax) m |= MC_PH_A;
    if (applied->b <= dmax) m |= MC_PH_B;
    if (applied->c <= dmax) m |= MC_PH_C;
    return m;
}

/* ---------------------------------------------------------------- enable path */
bool mc_enable_path_check(mc_enable_check_t *e, bool mcu_en, bool hw_permit, bool gated)
{
    if (gated != (mcu_en && hw_permit)) {
        if (e->mismatch_run < 255u) e->mismatch_run++;
    } else {
        e->mismatch_run = 0u;
    }
    if (e->mismatch_run >= 2u) e->fault = true;
    return e->fault;
}

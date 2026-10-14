#include "semmc/mc_control.h"

void mc_pi_init(mc_pi_t *pi, float kp, float ki, float out_min, float out_max)
{
    pi->kp = kp;
    pi->ki = ki;
    pi->out_min = out_min;
    pi->out_max = out_max;
    mc_pi_reset(pi);
}

void mc_pi_reset(mc_pi_t *pi)
{
    pi->integ = 0.0f;
    pi->saturated = false;
    pi->dt_rejected = false;
    pi->last_out = 0.0f;
}

void mc_pi_set_limits(mc_pi_t *pi, float out_min, float out_max)
{
    if (!(out_min <= out_max)) { /* also catches NaN */
        out_min = 0.0f;
        out_max = 0.0f;
    }
    pi->out_min = out_min;
    pi->out_max = out_max;
    pi->integ = mc_clampf(pi->integ, out_min, out_max);
}

float mc_pi_step(mc_pi_t *pi, float err, float ff, float dt, float dt_max)
{
    if (!mc_isfinite(dt) || dt <= 0.0f || dt > dt_max || !mc_isfinite(err) || !mc_isfinite(ff)) {
        pi->dt_rejected = true;
        return pi->last_out;
    }
    pi->dt_rejected = false;
    const float p = pi->kp * err;
    const float u_pre = p + pi->integ + ff;
    /* Conditional integration: integrate unless saturated in the direction
     * the error is pushing. */
    const bool sat_hi = u_pre >= pi->out_max && err > 0.0f;
    const bool sat_lo = u_pre <= pi->out_min && err < 0.0f;
    if (!sat_hi && !sat_lo) {
        pi->integ += pi->ki * err * dt;
        pi->integ = mc_clampf(pi->integ, pi->out_min, pi->out_max);
    }
    const float u_raw = p + pi->integ + ff;
    const float u = mc_clampf(u_raw, pi->out_min, pi->out_max);
    pi->saturated = (u != u_raw);
    pi->last_out = u;
    return u;
}

float mc_slew(float current, float target, float up_rate, float down_rate, float dt)
{
    /* "up" means increasing magnitude away from zero, "down" toward zero. */
    const float delta = target - current;
    const bool toward_zero = (mc_absf(target) < mc_absf(current)) || (current > 0.0f && target < current) ||
                             (current < 0.0f && target > current);
    const float rate = toward_zero ? down_rate : up_rate;
    const float step = rate * dt;
    if (delta > step) return current + step;
    if (delta < -step) return current - step;
    return target;
}

float mc_wrap_2pi(float th)
{
    if (!mc_isfinite(th)) return 0.0f;
    while (th >= MC_TWO_PI_F) th -= MC_TWO_PI_F;
    while (th < 0.0f) th += MC_TWO_PI_F;
    return th;
}

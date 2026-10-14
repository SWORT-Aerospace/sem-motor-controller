#include "semmc/mc_protection.h"

void mc_prot_init(mc_protection_t *pr, const mc_params_t *p)
{
    pr->p = p;
    pr->active = 0u;
    pr->latched = 0u;
    pr->first_fault = MC_FAULT_NONE;
    pr->fault_count = 0u;
    pr->derate_raw = 1.0f;
    pr->derate = 1.0f;
    pr->derate_reasons = 0u;
    pr->uv_timer_s = 0.0f;
    pr->derate_clear_timer_s = MC_DERATE_CLEAR_HOLD_S; /* not derating at boot */
}

void mc_prot_latch(mc_protection_t *pr, mc_fault_t f)
{
    const uint32_t bit = MC_FAULT_BIT(f);
    if ((pr->latched & bit) == 0u) {
        if (pr->latched == 0u) pr->first_fault = (uint8_t)f;
        pr->latched |= bit;
        if (pr->fault_count < UINT16_MAX) pr->fault_count++;
    }
}

static float ramp_factor(float x, float start, float trip)
{
    if (x <= start) return 1.0f;
    if (x >= trip) return 0.0f;
    return (trip - x) / (trip - start);
}

float mc_prot_speed_factor(const mc_params_t *p, float w)
{
    const float aw = mc_absf(w);
    if (!mc_isfinite(aw)) return 0.0f;
    return ramp_factor(aw, p->speed_taper_start_rad_s, p->overspeed_trip_rad_s);
}

void mc_prot_evaluate(mc_protection_t *pr, const mc_prot_inputs_t *in, float dt)
{
    const mc_params_t *p = pr->p;
    uint32_t a = 0u;
    if (!mc_isfinite(dt) || dt < 0.0f) dt = 0.0f;

    if (in->hw_overcurrent) a |= MC_FAULT_BIT(MC_F_HW_OVERCURRENT);
    if (in->hw_overvoltage) a |= MC_FAULT_BIT(MC_F_HW_OVERVOLTAGE);
    if (in->gate_driver_fault) a |= MC_FAULT_BIT(MC_F_GATE_DRIVER);
    if (in->watchdog_fault) a |= MC_FAULT_BIT(MC_F_WATCHDOG);
    if (in->fast_overcurrent) a |= MC_FAULT_BIT(MC_F_SW_OVERCURRENT);
    if (in->fast_dt_invalid) a |= MC_FAULT_BIT(MC_F_CONTROL_DT_INVALID);
    if (in->hall_invalid) a |= MC_FAULT_BIT(MC_F_HALL_INVALID);
    if (in->current_sense_invalid) a |= MC_FAULT_BIT(MC_F_CURRENT_SENSE_INVALID);
    if (!in->throttle_valid) a |= MC_FAULT_BIT(MC_F_THROTTLE_IMPLAUSIBLE);
    if (in->rotor_stall) a |= MC_FAULT_BIT(MC_F_ROTOR_STALL);

    float f_fet = 1.0f, f_mot = 1.0f, f_uv = 1.0f, f_unk = 1.0f;
    uint8_t reasons = 0u;

    /* Bus voltage: a missing/invalid measurement is a fault, not a guess. */
    if (!mc_usable(in->vbus_val) || !mc_isfinite(in->vbus_V)) {
        a |= MC_FAULT_BIT(MC_F_VBUS_SENSE_INVALID);
        pr->uv_timer_s = 0.0f;
    } else {
        if (in->vbus_V > p->ov_trip_V) a |= MC_FAULT_BIT(MC_F_BUS_OVERVOLTAGE);
        if (in->vbus_V < p->uv_trip_V) {
            pr->uv_timer_s += dt;
            if (pr->uv_timer_s >= MC_UV_TRIP_DEBOUNCE_S) a |= MC_FAULT_BIT(MC_F_BUS_UNDERVOLTAGE);
        } else {
            pr->uv_timer_s = 0.0f;
        }
        /* Normal voltage sag under load lands in the derate band and limits
         * torque (self-limiting) instead of tripping. */
        if (in->vbus_V < p->uv_derate_V) {
            f_uv = (in->vbus_V <= p->uv_trip_V) ? 0.0f
                                                : (in->vbus_V - p->uv_trip_V) / (p->uv_derate_V - p->uv_trip_V);
            reasons |= MC_DR_UNDERVOLTAGE;
        }
    }

    /* Temperatures: an unknown temperature derates (assume the worst within a
     * bounded factor) rather than either ignoring it or tripping. */
    if (mc_usable(in->t_fet_val) && mc_isfinite(in->t_fet_degC)) {
        if (in->t_fet_degC >= p->fet_trip_degC) a |= MC_FAULT_BIT(MC_F_FET_OVERTEMP);
        f_fet = ramp_factor(in->t_fet_degC, p->fet_derate_start_degC, p->fet_trip_degC);
        if (f_fet < 1.0f) reasons |= MC_DR_FET_TEMP;
    } else {
        f_unk = p->unknown_temp_derate_factor;
        reasons |= MC_DR_TEMP_UNKNOWN;
    }
    if (mc_usable(in->t_motor_val) && mc_isfinite(in->t_motor_degC)) {
        if (in->t_motor_degC >= p->motor_trip_degC) a |= MC_FAULT_BIT(MC_F_MOTOR_OVERTEMP);
        f_mot = ramp_factor(in->t_motor_degC, p->motor_derate_start_degC, p->motor_trip_degC);
        if (f_mot < 1.0f) reasons |= MC_DR_MOTOR_TEMP;
    } else {
        f_unk = p->unknown_temp_derate_factor;
        reasons |= MC_DR_TEMP_UNKNOWN;
    }

    if (mc_isfinite(in->speed_mech_rad_s) && mc_absf(in->speed_mech_rad_s) > p->overspeed_trip_rad_s)
        a |= MC_FAULT_BIT(MC_F_OVERSPEED);

    pr->active = a;
    for (unsigned f = 0; f < (unsigned)MC_F_COUNT; f++) {
        if (a & (1u << f)) mc_prot_latch(pr, (mc_fault_t)f);
    }

    pr->derate_raw = mc_minf(mc_minf(f_fet, f_mot), mc_minf(f_uv, f_unk));
    pr->derate_reasons = reasons;
    if (pr->derate_raw < pr->derate) {
        pr->derate = pr->derate_raw; /* reduce immediately */
    } else {
        pr->derate = mc_minf(pr->derate_raw, pr->derate + MC_DERATE_RECOVERY_PER_S * dt);
    }
    if (pr->derate_raw >= 1.0f && pr->derate >= 1.0f) {
        pr->derate_clear_timer_s = mc_minf(pr->derate_clear_timer_s + dt, 2.0f * MC_DERATE_CLEAR_HOLD_S);
    } else {
        pr->derate_clear_timer_s = 0.0f;
    }
}

bool mc_prot_derating(const mc_protection_t *pr)
{
    return pr->derate < 1.0f || pr->derate_raw < 1.0f || pr->derate_clear_timer_s < MC_DERATE_CLEAR_HOLD_S;
}

bool mc_prot_try_reset(mc_protection_t *pr)
{
    /* Only faults whose condition is gone can clear; never CONFIG_INVALID. */
    const uint32_t keep = pr->active | (pr->latched & MC_FAULT_BIT(MC_F_CONFIG_INVALID));
    pr->latched &= keep;
    if (pr->latched == 0u) pr->first_fault = MC_FAULT_NONE;
    return pr->latched == 0u;
}

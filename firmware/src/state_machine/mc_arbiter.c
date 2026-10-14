/* Command arbitration: owner request -> limits -> slew -> current reference.
 *
 * Order of precedence (highest first):
 *   1. independent hardware trip            -> 0 now, outputs off   (MC_R_HW_TRIP)
 *   2. latched fault / not in a torque state -> 0 now, outputs off
 *   3. driver absent, brake, eco cancel      -> 0 now (no slew)
 *   4. electrical / thermal / speed limits   -> clamp (reductions at fast rate)
 *   5. supervisor-declared bounds (ECO only) -> clamp
 *   6. normal slew limiting                  -> toward target
 * The supervisor never bypasses 1-5: its request is only ever an input to 4-6.
 */
#include "semmc/mc_control.h"
#include "semmc/mc_state_machine.h"

#define MC_BATT_LIMITER_GAIN_PER_A_S 0.5f   /* scale reduction per amp of excess per second */
#define MC_BATT_LIMITER_RECOVER_PER_S 0.5f
#define MC_OMEGA_MIN_FOR_POWER_LIMIT 1.0f   /* rad/s; below this torque is current-limited only */

void mc_arb_init(mc_arbiter_t *a, const mc_params_t *p)
{
    a->p = p;
    a->accepted_Nm = 0.0f;
    a->requested_Nm = 0.0f;
    a->iq_ref_A = 0.0f;
    a->id_ref_A = 0.0f;
    a->batt_limit_scale = 1.0f;
    a->reason = 0u;
    a->pwm_enable = false;
}

static void zero_now(mc_arbiter_t *a)
{
    a->accepted_Nm = 0.0f;
    a->iq_ref_A = 0.0f;
    a->id_ref_A = 0.0f;
    a->pwm_enable = false;
}

void mc_arb_step(mc_arbiter_t *a, const mc_sm_t *sm, const mc_driver_inputs_t *drv,
                 const mc_supervisor_input_t *sup, const mc_arb_meas_t *meas,
                 const mc_protection_t *prot, bool hw_trip, float dt)
{
    const mc_params_t *p = a->p;
    const mc_state_t st = sm->state;
    uint16_t r = 0u;
    if (!mc_isfinite(dt) || dt < 0.0f) dt = 0.0f;

    /* ---- requested torque from the current owner ---- */
    float req = 0.0f;
    if (st == MC_ST_MANUAL || st == MC_ST_DERATED) {
        if (sm->throttle_latch) {
            r |= MC_R_THROTTLE_LATCH;
        } else if (drv->throttle_valid) {
            req = mc_clampf(drv->throttle, 0.0f, 1.0f) * p->manual_max_torque_Nm;
        }
    } else if (st == MC_ST_ECO_ASSIST) {
        req = sup->torque_req_Nm;
        if (!mc_supervisor_ok(sup)) r |= MC_R_SUPERVISOR_INVALID;
    } else if (st == MC_ST_READY) {
        if (sm->throttle_latch) r |= MC_R_THROTTLE_LATCH;
        if (drv->mode_eco && !mc_supervisor_ok(sup)) r |= MC_R_SUPERVISOR_INVALID;
    }
    if (!mc_isfinite(req)) req = 0.0f;
    a->requested_Nm = req;

    /* ---- 1..3: immediate inhibition ---- */
    if (hw_trip) {
        a->reason = (uint16_t)(r | MC_R_HW_TRIP);
        zero_now(a);
        return;
    }
    if (prot->latched != 0u || st == MC_ST_FAULT_LATCHED) {
        a->reason = (uint16_t)(r | MC_R_FAULT_INHIBIT);
        zero_now(a);
        return;
    }
    if (st != MC_ST_MANUAL && st != MC_ST_ECO_ASSIST && st != MC_ST_DERATED) {
        if (st != MC_ST_READY) r |= MC_R_NOT_ARMED;
        a->reason = r;
        zero_now(a);
        a->batt_limit_scale = 1.0f;
        return;
    }
    if (!drv->driver_present) {
        a->reason = (uint16_t)(r | MC_R_DRIVER_ABSENT);
        zero_now(a);
        return;
    }
    if (drv->brake) {
        a->reason = (uint16_t)(r | MC_R_BRAKE_OVERRIDE);
        zero_now(a);
        return;
    }
    if (st == MC_ST_ECO_ASSIST && drv->cancel) {
        a->reason = (uint16_t)(r | MC_R_CANCEL_OVERRIDE);
        zero_now(a);
        return;
    }

    /* ---- 4/5: limits ---- */
    float target = req;
    if (target < 0.0f && !p->regen_enabled) {
        target = 0.0f;
        r |= MC_R_REGEN_DISABLED;
    }
    const float t_static = mc_minf(p->max_motor_torque_Nm, p->kt_Nm_per_A * p->max_phase_current_A);
    float limit = t_static;

    const bool speed_ok = mc_usable(meas->speed_val) && mc_isfinite(meas->speed_mech_rad_s);
    const float w = speed_ok ? mc_absf(meas->speed_mech_rad_s) : 0.0f;

    /* Battery current: feed-forward bound from speed and bus voltage using the
     * conservative efficiency, times a closed-loop scale from measured current. */
    if (speed_ok && w > MC_OMEGA_MIN_FOR_POWER_LIMIT && meas->vbus_V > 0.0f) {
        const float t_batt = p->min_efficiency_for_limit * meas->vbus_V * p->battery_current_limit_A / w;
        if (t_batt < limit) {
            limit = t_batt;
            if (target > limit) r |= MC_R_CLAMP_BATTERY;
        }
    }
    if (mc_usable(meas->ibatt_val) && mc_isfinite(meas->ibatt_A)) {
        const float excess = meas->ibatt_A - p->battery_current_limit_A;
        if (excess > 0.0f) {
            a->batt_limit_scale -= MC_BATT_LIMITER_GAIN_PER_A_S * excess * dt;
        } else {
            a->batt_limit_scale += MC_BATT_LIMITER_RECOVER_PER_S * dt;
        }
        a->batt_limit_scale = mc_clampf(a->batt_limit_scale, 0.0f, 1.0f);
    }
    if (a->batt_limit_scale < 1.0f) {
        const float t_cl = t_static * a->batt_limit_scale;
        if (t_cl < limit) limit = t_cl;
        if (target > t_cl) r |= MC_R_CLAMP_BATTERY;
    }
    if (prot->derate < 1.0f) {
        const float t_der = t_static * prot->derate;
        if (t_der < limit) limit = t_der;
        if (target > t_der) r |= MC_R_CLAMP_DERATE;
    }
    {
        const float sf = speed_ok ? mc_prot_speed_factor(p, meas->speed_mech_rad_s) : 1.0f;
        const float t_spd = t_static * sf;
        if (t_spd < limit) limit = t_spd;
        if (target > t_spd) r |= MC_R_CLAMP_SPEED;
    }
    if (target > t_static) r |= MC_R_CLAMP_TORQUE;

    if (st == MC_ST_ECO_ASSIST) {
        if (target > sup->max_torque_Nm) {
            target = sup->max_torque_Nm;
            r |= MC_R_SUPERVISOR_BOUND;
        }
        if (speed_ok && w > MC_OMEGA_MIN_FOR_POWER_LIMIT && sup->max_batt_power_W >= 0.0f) {
            const float t_pow = sup->max_batt_power_W * p->min_efficiency_for_limit / w;
            if (target > t_pow) {
                target = t_pow;
                r |= MC_R_SUPERVISOR_BOUND;
            }
        }
        if (sup->coast_request) {
            target = 0.0f;
            r |= MC_R_COAST;
        }
    }
    target = mc_clampf(target, 0.0f, mc_maxf(limit, 0.0f));

    /* ---- 6: slew. Limit reductions use the fast rate; normal changes the
     * normal rates. ---- */
    float prev = a->accepted_Nm;
    if (prev > limit) {
        prev = mc_slew(prev, mc_maxf(limit, 0.0f), p->slew_up_Nm_s, p->slew_down_fast_Nm_s, dt);
        a->accepted_Nm = prev;
        if (prev != target) r |= MC_R_SLEW;
    } else {
        a->accepted_Nm = mc_slew(prev, target, p->slew_up_Nm_s, p->slew_down_Nm_s, dt);
        if (a->accepted_Nm != target) r |= MC_R_SLEW;
    }

    a->iq_ref_A = mc_clampf(a->accepted_Nm / p->kt_Nm_per_A, -p->max_phase_current_A, p->max_phase_current_A);
    a->id_ref_A = 0.0f; /* surface-PM assumption; MTPA deferred (EFFICIENCY_RESEARCH.md H4) */
    /* Gate-off coasting only once torque has actually reached zero. */
    a->pwm_enable = !(a->accepted_Nm == 0.0f && target == 0.0f && p->coast_mode == MC_COAST_MODE_GATE_OFF);
    a->reason = r;
}

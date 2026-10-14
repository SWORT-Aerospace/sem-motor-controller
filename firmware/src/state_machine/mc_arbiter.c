/* Command arbitration: owner request -> bounds -> slew -> current reference.
 *
 * Four layers, strictly ordered (docs/CONTROL_CONTRACT.md):
 *
 *  L0 Independent hardware shutdown (comparator/BKIN, gate-driver fault,
 *     e-stop chain). Gates are already off in hardware; firmware sets 0 and
 *     PWM off on this update.                                 (MC_R_HW_TRIP)
 *  L1 Immediate inhibits: latched fault, not in a torque state, driver
 *     absent (dead-man), brake, eco cancel -> 0 on this update, no slew.
 *  L2 Local hard ceilings, computed here every update from configuration
 *     and the controller's own measurements: static torque / phase current,
 *     battery current (feed-forward and closed-loop trim), thermal and
 *     undervoltage derate, speed taper. accepted <= hard ceiling on EVERY
 *     update, whatever the previous output, the slew settings, the owner or
 *     the supervisor's limits reference. A reduction clamps on the update in
 *     which it is computed; no ramp.
 *  L3 Supervisory operating envelope (ECO only): max torque and battery
 *     power declared by the companion (the core passes the tighter of the
 *     newest committed set and the set the request references). A reduction
 *     below the current output ramps down at slew_down_fast; the worst-case
 *     ramp time t_static / slew_down_fast is validated to be no longer than
 *     the supervision timeout (MC_CFG_E_ENVELOPE_RAMP_DEADLINE).
 *  L4 Owner request (driver throttle or optimiser request) with comfort
 *     slew (slew_up / slew_down).
 *
 * The supervisor never bypasses L0-L2: its request and envelope are only
 * inputs to L3-L4, and nothing it sends can raise the L2 ceiling.
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
    a->hard_ceiling_Nm = 0.0f;
    a->envelope_Nm = -1.0f;
    a->target_Nm = 0.0f;
    a->reason = 0u;
    a->pwm_enable = false;
}

static void zero_now(mc_arbiter_t *a)
{
    a->accepted_Nm = 0.0f;
    a->target_Nm = 0.0f;
    a->envelope_Nm = -1.0f;
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

    /* ---- L2: local hard ceilings ---- */
    float target = req;
    if (target < 0.0f && !p->regen_enabled) {
        target = 0.0f;
        r |= MC_R_REGEN_DISABLED;
    }
    const float t_static = mc_minf(p->max_motor_torque_Nm, p->kt_Nm_per_A * p->max_phase_current_A);
    const float prev = a->accepted_Nm;
    float hard = t_static;
    uint16_t hard_bits = 0u; /* which ceilings bind below prev or the request */

    const bool speed_ok = mc_usable(meas->speed_val) && mc_isfinite(meas->speed_mech_rad_s);
    const float w = speed_ok ? mc_absf(meas->speed_mech_rad_s) : 0.0f;
    const float demand = mc_maxf(target, prev);

    /* Battery current: feed-forward bound from speed and bus voltage using the
     * conservative efficiency, times a closed-loop scale from measured current. */
    if (speed_ok && w > MC_OMEGA_MIN_FOR_POWER_LIMIT && meas->vbus_V > 0.0f) {
        const float t_batt = p->min_efficiency_for_limit * meas->vbus_V * p->battery_current_limit_A / w;
        if (t_batt < hard) hard = t_batt;
        if (demand > t_batt) hard_bits |= MC_R_CLAMP_BATTERY;
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
        if (t_cl < hard) hard = t_cl;
        if (demand > t_cl) hard_bits |= MC_R_CLAMP_BATTERY;
    }
    if (prot->derate < 1.0f) {
        const float t_der = t_static * prot->derate;
        if (t_der < hard) hard = t_der;
        if (demand > t_der) hard_bits |= MC_R_CLAMP_DERATE;
    }
    {
        const float sf = speed_ok ? mc_prot_speed_factor(p, meas->speed_mech_rad_s) : 1.0f;
        const float t_spd = t_static * sf;
        if (t_spd < hard) hard = t_spd;
        if (demand > t_spd) hard_bits |= MC_R_CLAMP_SPEED;
    }
    if (demand > t_static) hard_bits |= MC_R_CLAMP_TORQUE;
    if (!mc_isfinite(hard) || hard < 0.0f) hard = 0.0f;
    r |= hard_bits;

    /* ---- L3: supervisory envelope (ECO only) ---- */
    float env = -1.0f; /* < 0: no envelope */
    if (st == MC_ST_ECO_ASSIST) {
        env = mc_isfinite(sup->max_torque_Nm) ? mc_maxf(sup->max_torque_Nm, 0.0f) : 0.0f;
        if (speed_ok && w > MC_OMEGA_MIN_FOR_POWER_LIMIT && sup->max_batt_power_W >= 0.0f) {
            const float t_pow = sup->max_batt_power_W * p->min_efficiency_for_limit / w;
            if (t_pow < env) env = t_pow;
        }
        if (!mc_isfinite(env)) env = 0.0f;
        if (target > env || prev > env) r |= MC_R_SUPERVISOR_BOUND;
        if (target > env) target = env;
        if (sup->coast_request) {
            target = 0.0f;
            r |= MC_R_COAST;
        }
    }
    target = mc_clampf(target, 0.0f, hard);

    /* ---- L4: comfort slew toward the bounded target ---- */
    float next = mc_slew(mc_minf(prev, hard), target, p->slew_up_Nm_s, p->slew_down_Nm_s, dt);
    if (env >= 0.0f && next > env) {
        /* Envelope reduction below the present output: at least the fast
         * down rate, never slower than the comfort ramp computed above. */
        next = mc_minf(next, mc_maxf(env, prev - p->slew_down_fast_Nm_s * dt));
    }
    /* L2 is applied last so that nothing above can leave the output over it. */
    next = mc_clampf(next, 0.0f, hard);
    if (next != target) r |= MC_R_SLEW;
    a->accepted_Nm = next;
    a->hard_ceiling_Nm = hard;
    a->envelope_Nm = env;
    a->target_Nm = target;

    a->iq_ref_A = mc_clampf(a->accepted_Nm / p->kt_Nm_per_A, -p->max_phase_current_A, p->max_phase_current_A);
    a->id_ref_A = 0.0f; /* surface-PM assumption; MTPA deferred (EFFICIENCY_RESEARCH.md H4) */
    /* Gate-off coasting only once torque has actually reached zero. */
    a->pwm_enable = !(a->accepted_Nm == 0.0f && target == 0.0f && p->coast_mode == MC_COAST_MODE_GATE_OFF);
    a->reason = r;
}

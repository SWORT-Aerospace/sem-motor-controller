/* Operating state machine. See mc_state_machine.h for invariants I1..I7. */
#include "semmc/mc_state_machine.h"

const char *mc_state_name(mc_state_t s)
{
    switch (s) {
    case MC_ST_BOOT: return "BOOT";
    case MC_ST_SELF_TEST: return "SELF_TEST";
    case MC_ST_DISARMED: return "DISARMED";
    case MC_ST_READY: return "READY";
    case MC_ST_MANUAL: return "MANUAL";
    case MC_ST_ECO_ASSIST: return "ECO_ASSIST";
    case MC_ST_DERATED: return "DERATED";
    case MC_ST_FAULT_LATCHED: return "FAULT_LATCHED";
    default: return "?";
    }
}

void mc_sm_init(mc_sm_t *sm)
{
    sm->state = MC_ST_BOOT;
    sm->owner = MC_OWNER_NONE;
    sm->last_transition = MC_T_NONE;
    sm->transition_count = 0u;
    /* Assume the arm switch was ON before boot: arming needs an observed
     * OFF first (invariant I2). Same for the fault-reset button. */
    sm->prev_arm_switch = true;
    sm->arm_seen_off = false;
    sm->prev_fault_reset = true;
    sm->prev_mode_eco = true;
    sm->eco_edge_pending = false;
    sm->throttle_latch = true;
    sm->selftest_timer_s = 0.0f;
}

bool mc_supervisor_ok(const mc_supervisor_input_t *sup)
{
    return sup->session_established && mc_valid(sup->req_val) && mc_valid(sup->limits_val) &&
           sup->limits_match && mc_isfinite(sup->torque_req_Nm) && mc_isfinite(sup->max_torque_Nm) &&
           mc_isfinite(sup->max_batt_power_W);
}

static mc_owner_t owner_of(mc_state_t s)
{
    switch (s) {
    case MC_ST_MANUAL:
    case MC_ST_DERATED: return MC_OWNER_DRIVER;
    case MC_ST_ECO_ASSIST: return MC_OWNER_SUPERVISOR;
    default: return MC_OWNER_NONE;
    }
}

static mc_transition_t go(mc_sm_t *sm, mc_state_t to, mc_transition_t t)
{
    sm->state = to;
    sm->owner = owner_of(to);
    sm->last_transition = t;
    sm->transition_count++;
    switch (to) {
    case MC_ST_DISARMED:
    case MC_ST_FAULT_LATCHED:
        sm->arm_seen_off = false;     /* re-arming needs a fresh OFF->ON edge */
        sm->eco_edge_pending = false;
        sm->throttle_latch = true;
        break;
    default:
        break;
    }
    return t;
}

static bool is_armed(mc_state_t s)
{
    return s == MC_ST_READY || s == MC_ST_MANUAL || s == MC_ST_ECO_ASSIST || s == MC_ST_DERATED;
}

mc_transition_t mc_sm_step(mc_sm_t *sm, const mc_params_t *p, const mc_driver_inputs_t *drv,
                           const mc_supervisor_input_t *sup, mc_time_us_t now_us,
                           mc_protection_t *prot, const mc_sm_aux_t *aux, float dt)
{
    (void)now_us;
    /* ---- edge detection on local controls ---- */
    if (!drv->arm_switch) sm->arm_seen_off = true;
    const bool arm_rise = drv->arm_switch && !sm->prev_arm_switch && sm->arm_seen_off;
    const bool reset_rise = drv->fault_reset && !sm->prev_fault_reset;
    if (drv->mode_eco && !sm->prev_mode_eco) sm->eco_edge_pending = true;
    if (!drv->mode_eco) sm->eco_edge_pending = false;
    sm->prev_arm_switch = drv->arm_switch;
    sm->prev_fault_reset = drv->fault_reset;
    sm->prev_mode_eco = drv->mode_eco;

    const bool released = drv->throttle_valid && drv->throttle <= p->throttle_release;
    if (released) sm->throttle_latch = false;
    const bool engage = drv->throttle_valid && !sm->throttle_latch && drv->throttle >= p->throttle_engage;
    const bool eco_ok = drv->mode_eco && sm->eco_edge_pending && mc_supervisor_ok(sup) && released &&
                        !drv->brake && !drv->cancel && drv->driver_present;
    const bool derating = mc_prot_derating(prot);

    /* ---- BOOT is handled first: nothing else is meaningful without config ---- */
    if (sm->state == MC_ST_BOOT) {
        if (aux->config_ok) return go(sm, MC_ST_SELF_TEST, MC_T_BOOT_CONFIG_OK);
        mc_prot_latch(prot, MC_F_CONFIG_INVALID);
        return go(sm, MC_ST_FAULT_LATCHED, MC_T_BOOT_CONFIG_BAD);
    }

    /* ---- latched faults win everywhere (I6) ---- */
    if (sm->state != MC_ST_FAULT_LATCHED && prot->latched != 0u) {
        return go(sm, MC_ST_FAULT_LATCHED, MC_T_FAULT);
    }

    /* ---- armed-state common exits ---- */
    if (is_armed(sm->state)) {
        if (!drv->estop_chain_ok) return go(sm, MC_ST_DISARMED, MC_T_ESTOP);
        if (!drv->arm_switch) return go(sm, MC_ST_DISARMED, MC_T_DISARM);
    }

    switch (sm->state) {
    case MC_ST_SELF_TEST:
        sm->selftest_timer_s += (dt > 0.0f) ? dt : 0.0f;
        if (aux->selftest_done) {
            if (aux->selftest_pass) return go(sm, MC_ST_DISARMED, MC_T_SELFTEST_PASS);
            mc_prot_latch(prot, MC_F_SELFTEST);
            return go(sm, MC_ST_FAULT_LATCHED, MC_T_SELFTEST_FAIL);
        }
        break;

    case MC_ST_DISARMED:
        if (arm_rise && drv->estop_chain_ok && released && prot->latched == 0u && prot->active == 0u &&
            aux->output_permitted && !aux->hw_trip) {
            sm->eco_edge_pending = false; /* eco needs an edge after arming */
            return go(sm, MC_ST_READY, MC_T_ARM);
        }
        break;

    case MC_ST_READY:
        if (derating) return go(sm, MC_ST_DERATED, MC_T_DERATE);
        if (eco_ok) {
            sm->eco_edge_pending = false;
            return go(sm, MC_ST_ECO_ASSIST, MC_T_ECO_ENGAGE);
        }
        if (!drv->mode_eco && drv->driver_present && engage) return go(sm, MC_ST_MANUAL, MC_T_MANUAL_ENGAGE);
        break;

    case MC_ST_MANUAL:
        if (!drv->driver_present) {
            sm->throttle_latch = true;
            return go(sm, MC_ST_READY, MC_T_DRIVER_ABSENT);
        }
        if (derating) return go(sm, MC_ST_DERATED, MC_T_DERATE);
        if (eco_ok) {
            sm->eco_edge_pending = false;
            return go(sm, MC_ST_ECO_ASSIST, MC_T_ECO_ENGAGE);
        }
        break;

    case MC_ST_ECO_ASSIST:
        if (!drv->driver_present) {
            sm->throttle_latch = true;
            return go(sm, MC_ST_READY, MC_T_DRIVER_ABSENT);
        }
        if (drv->brake || drv->cancel) {
            sm->throttle_latch = true;
            return go(sm, MC_ST_READY, MC_T_ECO_DRIVER_CANCEL);
        }
        if (!drv->mode_eco) {
            sm->throttle_latch = true;
            return go(sm, MC_ST_READY, MC_T_ECO_DESELECT);
        }
        if (!mc_supervisor_ok(sup)) {
            sm->throttle_latch = true; /* I4: no jump into a held manual demand */
            return go(sm, MC_ST_READY, MC_T_ECO_SUPERVISOR_LOST);
        }
        if (derating) {
            sm->throttle_latch = true;
            return go(sm, MC_ST_DERATED, MC_T_DERATE);
        }
        if (engage) return go(sm, MC_ST_MANUAL, MC_T_DRIVER_TAKEOVER);
        break;

    case MC_ST_DERATED:
        if (!drv->driver_present) {
            sm->throttle_latch = true;
            return go(sm, MC_ST_READY, MC_T_DRIVER_ABSENT);
        }
        if (!derating) return go(sm, MC_ST_MANUAL, MC_T_DERATE_CLEAR);
        break;

    case MC_ST_FAULT_LATCHED:
        if (reset_rise && released) {
            if (mc_prot_try_reset(prot)) return go(sm, MC_ST_DISARMED, MC_T_FAULT_RESET);
        }
        break;

    default:
        break;
    }
    return MC_T_NONE;
}

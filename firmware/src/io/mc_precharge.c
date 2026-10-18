#include "semmc/mc_precharge.h"

#include "semmc/mc_types.h"

void mc_precharge_init(mc_precharge_t *p, float fraction, float timeout_s, float uv_trip_V)
{
    p->fraction = fraction;
    p->timeout_s = timeout_s;
    p->uv_trip_V = uv_trip_V;
    p->fault = MC_PCF_NONE;
    p->t_state_s = 0.0f;
    p->mismatch_s = 0.0f;
    p->bypass = false;
    p->ready = false;
    const bool ok = mc_isfinite(fraction) && fraction > 0.0f && fraction < 1.0f && mc_isfinite(timeout_s) &&
                    timeout_s > 0.0f && mc_isfinite(uv_trip_V) && uv_trip_V > 0.0f;
    p->state = ok ? MC_PC_WAIT_BATTERY : MC_PC_DISABLED;
}

static void enter(mc_precharge_t *p, mc_pc_state_t s)
{
    p->state = s;
    p->t_state_s = 0.0f;
    p->mismatch_s = 0.0f;
}

void mc_precharge_step(mc_precharge_t *p, float dt_s, float v_link, bool v_link_ok, float v_batt, bool v_batt_ok)
{
    if (!mc_isfinite(dt_s) || dt_s < 0.0f) dt_s = 0.0f;
    v_link_ok = v_link_ok && mc_isfinite(v_link);
    v_batt_ok = v_batt_ok && mc_isfinite(v_batt);
    const bool battery_present = v_batt_ok && v_batt >= p->uv_trip_V;
    const bool link_charged = v_link_ok && battery_present && v_link >= p->fraction * v_batt;
    p->t_state_s += dt_s;

    switch (p->state) {
    case MC_PC_DISABLED:
    case MC_PC_FAULT:
        break;
    case MC_PC_WAIT_BATTERY:
        if (battery_present) enter(p, MC_PC_CHARGING);
        break;
    case MC_PC_CHARGING:
        if (link_charged) {
            enter(p, MC_PC_CLOSED);
        } else if (v_batt_ok && !battery_present) {
            enter(p, MC_PC_WAIT_BATTERY); /* battery disconnected before the link charged */
        } else if (p->t_state_s > p->timeout_s) {
            p->fault = MC_PCF_TIMEOUT;
            enter(p, MC_PC_FAULT);
        }
        break;
    case MC_PC_CLOSED:
        if (v_batt_ok && !battery_present) {
            enter(p, MC_PC_WAIT_BATTERY); /* isolated: the next connection must precharge again */
        } else if (v_link_ok && v_batt_ok) {
            p->mismatch_s = link_charged ? 0.0f : p->mismatch_s + dt_s;
            if (p->mismatch_s > p->timeout_s) {
                p->fault = MC_PCF_LINK_LOW_AFTER_CLOSE;
                enter(p, MC_PC_FAULT);
            }
        }
        break;
    }
    p->bypass = p->state == MC_PC_CLOSED;
    p->ready = p->state == MC_PC_CLOSED && v_link_ok && v_batt_ok && p->mismatch_s == 0.0f;
}

void mc_precharge_force_fault(mc_precharge_t *p, mc_pc_fault_t f)
{
    if (p->state == MC_PC_DISABLED) return;
    p->fault = f;
    enter(p, MC_PC_FAULT);
    p->bypass = false;
    p->ready = false;
}

void mc_precharge_reset(mc_precharge_t *p)
{
    if (p->state != MC_PC_FAULT) return;
    p->fault = MC_PCF_NONE;
    enter(p, MC_PC_WAIT_BATTERY);
    p->bypass = false;
    p->ready = false;
}

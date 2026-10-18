#include "semmc/mc_startup.h"

#include <string.h>

#include "semmc/mc_types.h"

static bool pos(float x) { return mc_isfinite(x) && x > 0.0f; }

void mc_startup_init(mc_startup_t *s, const mc_startup_params_t *p)
{
    memset(s, 0, sizeof *s);
    s->p = *p;
    mc_precharge_init(&s->pc, p->fraction, p->timeout_s, p->uv_trip_V);
    s->params_ok = s->pc.state != MC_PC_DISABLED && pos(p->ov_trip_V) && p->ov_trip_V > p->uv_trip_V &&
                   pos(p->r_pre_ohm) && pos(p->agreement_V) && pos(p->sample_max_age_s) &&
                   pos(p->step_timeout_s) && p->max_attempts > 0u;
    s->state = MC_SU_INHIBITED;
}

static void enter(mc_startup_t *s, mc_su_state_t st)
{
    s->state = st;
    s->t_state_s = 0.0f;
}

static void fail(mc_startup_t *s, mc_su_fault_t f)
{
    s->fault = f;
    enter(s, MC_SU_FAULT);
}

static uint8_t missing(const mc_startup_t *s, const mc_startup_in_t *in)
{
    uint8_t m = 0u;
    if (!in->config_ok) m |= MC_SU_MISSING_CONFIG;
    if (!s->params_ok) m |= MC_SU_MISSING_PARAMS;
    if (in->drv_state == MC_DRV_UNVERIFIED) m |= MC_SU_MISSING_DRIVER;
    if (in->ina_state == MC_INA_UNVERIFIED) m |= MC_SU_MISSING_METER;
    return m;
}

/* The precharge, with the closing condition cross-checked against the resistor current. */
static void step_precharge(mc_startup_t *s, float dt_s, const mc_startup_in_t *in)
{
    const mc_startup_params_t *p = &s->p;
    const bool batt_ok = in->v_batt_ok && mc_isfinite(in->v_batt_V) && in->v_batt_V <= p->ov_trip_V;
    bool link_ok = in->v_link_ok && mc_isfinite(in->v_link_V);
    if (s->pc.state == MC_PC_CHARGING && batt_ok && link_ok && in->v_batt_V >= p->uv_trip_V &&
        in->v_link_V >= p->fraction * in->v_batt_V) {
        /* About to close: the reading must agree with the link voltage the resistor current implies. */
        const bool i_ok = in->i_batt_ok && mc_isfinite(in->i_batt_A);
        if (!i_ok || s->state != MC_SU_PRECHARGE) {
            link_ok = false; /* no closure without the cross-check, nor outside PRECHARGE */
        } else {
            const float implied = in->v_batt_V - in->i_batt_A * p->r_pre_ohm;
            const float d = in->v_link_V - implied;
            if (d > p->agreement_V || d < -p->agreement_V) {
                mc_precharge_force_fault(&s->pc, MC_PCF_SENSOR_DISAGREE);
                return;
            }
        }
    }
    mc_precharge_step(&s->pc, dt_s, in->v_link_V, link_ok, in->v_batt_V, batt_ok);
}

void mc_startup_step(mc_startup_t *s, float dt_s, const mc_startup_in_t *in)
{
    if (!mc_isfinite(dt_s) || dt_s < 0.0f) dt_s = 0.0f;
    s->t_state_s += dt_s;
    s->clear_driver = false;
    s->missing = missing(s, in);

    if (s->state == MC_SU_INHIBITED) {
        if (s->missing == 0u) enter(s, MC_SU_PRECHARGE);
    } else {
        step_precharge(s, dt_s, in);
    }

    switch (s->state) {
    case MC_SU_INHIBITED:
        break;
    case MC_SU_PRECHARGE:
        if (s->pc.state == MC_PC_FAULT) {
            fail(s, MC_SU_F_PRECHARGE);
        } else if (s->pc.state == MC_PC_CLOSED) {
            enter(s, MC_SU_DRIVER);
        }
        break;
    case MC_SU_DRIVER:
    case MC_SU_OFFSETS:
    case MC_SU_READY:
        if (s->pc.state == MC_PC_FAULT) {
            fail(s, MC_SU_F_PRECHARGE);
        } else if (s->pc.state != MC_PC_CLOSED) {
            enter(s, MC_SU_PRECHARGE); /* battery disconnected: the driver sleeps, the next connection precharges */
        } else if (in->drv_state == MC_DRV_FAULT) {
            fail(s, MC_SU_F_DRIVER);
        } else if (s->state == MC_SU_DRIVER) {
            if (in->drv_ready) {
                s->offsets_req_seq++;
                enter(s, MC_SU_OFFSETS);
            } else if (s->t_state_s > s->p.step_timeout_s) {
                fail(s, MC_SU_F_DRIVER_TIMEOUT);
            }
        } else if (s->state == MC_SU_OFFSETS) {
            if (in->offsets_done_seq == s->offsets_req_seq) {
                if (in->offsets_ok) {
                    enter(s, MC_SU_READY);
                } else {
                    fail(s, MC_SU_F_OFFSETS);
                }
            } else if (s->t_state_s > s->p.step_timeout_s) {
                fail(s, MC_SU_F_OFFSETS);
            }
        }
        break;
    case MC_SU_FAULT:
        if (in->fault_reset_edge && in->outputs_off) {
            if (s->attempts >= s->p.max_attempts) {
                enter(s, MC_SU_LOCKOUT);
                break;
            }
            s->attempts++;
            s->fault = MC_SU_F_NONE;
            mc_precharge_reset(&s->pc);
            s->clear_driver = in->drv_state == MC_DRV_FAULT;
            enter(s, s->pc.state == MC_PC_CLOSED ? MC_SU_DRIVER : MC_SU_PRECHARGE);
        }
        break;
    case MC_SU_LOCKOUT:
        break;
    }

    const bool live = s->state != MC_SU_INHIBITED;
    s->bypass = live && s->pc.bypass;
    s->want_driver_awake = live && s->pc.state == MC_PC_CLOSED; /* VM is the link */
    s->request_offsets = s->state == MC_SU_OFFSETS;
    s->gate_driver_ready = s->state == MC_SU_READY && in->config_ok && in->drv_ready && s->pc.ready;
}

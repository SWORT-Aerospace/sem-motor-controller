/* Controller core: wiring of protocol RX/TX, freshness, supervisor session,
 * protection, state machine, arbitration and the FOC fast loop.
 *
 * Nothing here allocates, blocks, formats text or performs I/O. The fast step
 * touches only fast-loop state plus the slow->fast handoff struct.
 */
#include "semmc/mc_core.h"

#include <math.h>
#include <string.h>

#include "semmc_protocol.h"

#define MC_HALL_TIMEOUT_S 0.25f
#define MC_HELLO_MAX_AGE_US 3000000u
#define MC_CSIA_MAX_AGE_US 500000u
#define MC_SELFTEST_MIN_S 0.05f
#define MC_CURRENT_INVALID_LIMIT 3u
#define MC_REQ_TIME_SKEW_MS 100u

/* ---------------------------------------------------------------- helpers */

static uint8_t make_tag(uint16_t boot_id, uint32_t companion_session, uint8_t prev)
{
    /* Deterministic, non-zero, different from the previous tag. Not secret. */
    uint32_t x = ((uint32_t)boot_id << 16) ^ companion_session ^ 0x9E3779B9u;
    x ^= x >> 15;
    x *= 0x2C1B3C6Du;
    x ^= x >> 12;
    uint8_t t = (uint8_t)(x ^ (x >> 8) ^ (x >> 16) ^ (x >> 24));
    if (t == 0u) t = 1u;
    if (t == prev) t = (uint8_t)(t == 255u ? 1u : t + 1u);
    return t;
}

static void sup_session_reset(mc_core_t *c)
{
    const uint8_t prev = c->sess.tag;
    memset(&c->sess, 0, sizeof c->sess);
    c->sess.tag = 0u;
    (void)prev;
    mc_fresh_reset(&c->fr_req);
    mc_fresh_reset(&c->fr_limits);
    memset(c->lim, 0, sizeof c->lim);
    c->limits_committed = false;
    c->req_torque_Nm = 0.0f;
    c->req_coast = false;
}

static int tx_index(uint32_t id)
{
    const int i = semmc_msg_index(id);
    return (i >= 0 && i < 16) ? i : 0;
}

static void force_tx(mc_core_t *c, uint32_t id)
{
    c->tx_force_mask |= (1u << (unsigned)tx_index(id));
}

/* ---------------------------------------------------------------- init */
bool mc_core_init(mc_core_t *c, const uint8_t *cal_blob, size_t cal_len, mc_build_kind_t build, uint16_t boot_id)
{
    memset(c, 0, sizeof(*c));
    c->build = build;
    c->boot_id = boot_id;
    mc_cfg_report_t rep;
    mc_cfg_report_clear(&rep);
    bool ok = mc_config_parse_blob(cal_blob, cal_len, &c->cfg, &rep) && mc_config_derive(&c->cfg, &c->p);
    if (ok && build == MC_BUILD_HARDWARE) {
        /* A hardware build only runs with a hardware-valid, bench-measured
         * calibration that explicitly permits output. Anything else stays in
         * FAULT_LATCHED(CONFIG_INVALID). */
        ok = mc_config_permits_physical_output(&c->cfg, build);
    }
    c->config_ok = ok;
    if (!ok) memset(&c->p, 0, sizeof c->p);
    /* Host simulation drives a virtual plant only; there is no physical output. */
    c->output_permitted = ok && (build == MC_BUILD_HOST_SIM || mc_config_permits_physical_output(&c->cfg, build));

    mc_prot_init(&c->prot, &c->p);
    mc_sm_init(&c->sm);
    mc_arb_init(&c->arb, &c->p);
    const float fpwm = ok ? c->p.pwm_frequency_Hz : 20000.0f;
    mc_foc_init(&c->foc, c->p.current_kp, c->p.current_ki, c->p.ld_H, c->p.lq_H, c->p.lambda_Wb, c->p.duty_min,
                c->p.duty_max, 5.0f / fpwm);
    const int8_t no_hall[8] = {-1, -1, -1, -1, -1, -1, -1, -1};
    mc_hall_init(&c->hall, ok ? c->p.hall_code_to_sector : no_hall, c->p.hall_angle_offset_rad, MC_HALL_TIMEOUT_S);
    mc_csia_init(&c->csia, MC_CSIA_MAX_AGE_US);

    const uint32_t req_age = ok ? (uint32_t)(c->p.sup_timeout_s * 1e6f) : 0u;
    const uint32_t lim_age = ok ? (uint32_t)(c->p.sup_limits_timeout_s * 1e6f) : 0u;
    mc_fresh_init(&c->fr_req, req_age, MC_CLOCK_DOMAIN_COMPANION, MC_REQ_TIME_SKEW_MS);
    mc_fresh_init_seq_only(&c->fr_limits, lim_age, MC_CLOCK_DOMAIN_COMPANION);
    mc_fresh_init_seq_only(&c->fr_hello, MC_HELLO_MAX_AGE_US, MC_CLOCK_DOMAIN_COMPANION);
    sup_session_reset(c);
    c->speed_val = MC_VAL_MISSING;
    c->energy_J = 0.0;
    c->tx_force_mask = 0xFFFFu;
    return ok;
}

/* ---------------------------------------------------------------- CAN RX */
void mc_core_on_can_bus_off(mc_core_t *c, bool bus_off)
{
    if (bus_off && !c->can_bus_off) {
        c->can.bus_off_events++;
        /* Bus-off ends any supervisor session immediately (ECO -> READY on the
         * next slow step); manual driving does not depend on CAN. */
        sup_session_reset(c);
    }
    c->can_bus_off = bus_off;
}

void mc_core_on_can_rx(mc_core_t *c, mc_time_us_t now_us, uint32_t can_id, const uint8_t *data, uint8_t len)
{
    c->can.rx_frames++;
    semmc_result_t r;
    switch (can_id) {
    case SEMMC_ID_SUP_HELLO: {
        semmc_sup_hello_t m;
        r = semmc_decode_sup_hello(data, len, &m);
        if (r.status != SEMMC_OK) { c->can.rx_crc_fail++; mc_fresh_on_integrity_fail(&c->fr_hello); return; }
        if (m.proto_major != SEMMC_PROTO_MAJOR || m.role != 1u) { c->can.rx_proto_mismatch++; return; }
        (void)mc_fresh_on_rx(&c->fr_hello, now_us, m.companion_session, MC_CLOCK_DOMAIN_COMPANION, m.seq, 0u);
        if (!c->sess.hello_seen || c->sess.companion_session != m.companion_session || c->sess.tag == 0u) {
            /* New companion session (first, rebooted, or after bus-off): assign
             * a fresh tag; nothing from an earlier session is honoured. */
            const uint8_t prev = c->sess.tag;
            sup_session_reset(c);
            c->sess.hello_seen = true;
            c->sess.companion_session = m.companion_session;
            c->sess.tag = make_tag(c->boot_id, m.companion_session, prev);
            force_tx(c, SEMMC_ID_CTRL_SESSION);
        }
        c->sess.last_hello_us = now_us;
        return;
    }
    case SEMMC_ID_SUP_LIMITS: {
        semmc_sup_limits_t m;
        r = semmc_decode_sup_limits(data, len, &m);
        if (r.status != SEMMC_OK) { c->can.rx_crc_fail++; mc_fresh_on_integrity_fail(&c->fr_limits); return; }
        if (c->sess.tag == 0u || m.session_tag != c->sess.tag) { c->can.rx_tag_mismatch++; return; }
        if (r.out_of_range != 0u) return;
        const mc_rx_result_t fr = mc_fresh_on_rx(&c->fr_limits, now_us, c->sess.tag, MC_CLOCK_DOMAIN_COMPANION, m.seq, 0u);
        if (!mc_rx_renews(fr)) return;
        /* Commit atomically: a set is only usable once its frame is fully
         * received and checked. A new limits_seq shifts the previous set to
         * lim[1]; a periodic re-send of the newest set (same limits_seq)
         * refreshes it in place and does not evict lim[1]. */
        if (!(c->lim[0].valid && c->lim[0].seq == (uint8_t)m.limits_seq)) c->lim[1] = c->lim[0];
        c->lim[0].valid = true;
        c->lim[0].seq = (uint8_t)m.limits_seq;
        c->lim[0].max_torque_Nm = m.max_torque_Nm;
        c->lim[0].max_batt_power_W = m.max_batt_power_W;
        c->limits_committed = true;
        c->sess.limits_tag_ok = true;
        break;
    }
    case SEMMC_ID_SUP_TORQUE_REQ: {
        semmc_sup_torque_req_t m;
        r = semmc_decode_sup_torque_req(data, len, &m);
        if (r.status != SEMMC_OK) { c->can.rx_crc_fail++; mc_fresh_on_integrity_fail(&c->fr_req); return; }
        if (c->sess.tag == 0u || m.session_tag != c->sess.tag) { c->can.rx_tag_mismatch++; return; }
        const mc_rx_result_t fr = mc_fresh_on_rx(&c->fr_req, now_us, c->sess.tag, MC_CLOCK_DOMAIN_COMPANION, m.seq,
                                                 (uint16_t)m.src_time_ms);
        if (!mc_rx_renews(fr)) return;
        /* A request carrying the invalid sentinel (NaN) or an out-of-range
         * torque is a well-formed frame whose content is unusable: it marks
         * the supervisor input INVALID (ECO exits) rather than being read as
         * a zero-torque command. */
        c->req_invalid = (r.invalid & SEMMC_F_SUP_TORQUE_REQ_TORQUE_NM) != 0u ||
                         (r.out_of_range & SEMMC_F_SUP_TORQUE_REQ_TORQUE_NM) != 0u;
        c->req_torque_Nm = c->req_invalid ? 0.0f : m.torque_Nm;
        c->req_coast = m.coast_request;
        c->req_limits_ref = (uint8_t)m.limits_ref;
        c->sess.req_tag_ok = true;
        break;
    }
    case SEMMC_ID_CSIA_ADVISORY: {
        semmc_csia_advisory_t m;
        r = semmc_decode_csia_advisory(data, len, &m);
        if (r.status != SEMMC_OK) { c->can.rx_crc_fail++; mc_fresh_on_integrity_fail(&c->csia.fresh); return; }
        mc_csia_on_advisory(&c->csia, now_us, m.trust, (uint8_t)m.mode, (uint8_t)m.observability, m.monitor_ok,
                            m.evidence_fresh, (uint8_t)m.evidence_mask, (uint8_t)m.explanation, m.seq,
                            (uint16_t)m.src_time_ms);
        return;
    }
    default:
        c->can.rx_unknown++; /* includes frames carrying our own TX ids */
        return;
    }
    if (!c->sess.established && c->sess.limits_tag_ok && c->sess.req_tag_ok) {
        c->sess.established = true;
        mc_fresh_ack_session(&c->fr_req);
        mc_fresh_ack_session(&c->fr_limits);
    }
}

/* ---------------------------------------------------------------- slow step */
static mc_validity_t vcheck(float x, mc_validity_t v)
{
    if (!mc_isfinite(x)) v |= MC_VAL_NONFINITE;
    return v;
}

void mc_core_slow_step(mc_core_t *c, mc_time_us_t now_us, const mc_slow_inputs_t *in)
{
    float dt = 0.0f;
    if (c->have_slow && now_us >= c->last_slow_us) dt = (float)(now_us - c->last_slow_us) * 1e-6f;
    c->have_slow = true;
    c->last_slow_us = now_us;
    c->now_us = now_us;
    c->last_driver = in->driver;
    c->reset_reason = in->reset_reason;

    /* ---- measurements ---- */
    c->slow_vbus_V = in->vbus_V;
    const mc_validity_t vbus_val = vcheck(in->vbus_V, in->vbus_val);
    c->slow_ibatt_A = in->ibatt_A;
    c->slow_ibatt_val = vcheck(in->ibatt_A, in->ibatt_val);
    c->t_fet_degC = in->t_fet_degC;
    c->t_fet_val = vcheck(in->t_fet_degC, in->t_fet_val);
    c->t_motor_degC = in->t_motor_degC;
    c->t_motor_val = vcheck(in->t_motor_degC, in->t_motor_val);
    if (c->config_ok && c->p.pole_pairs > 0) {
        c->speed_mech_rad_s = c->hall.omega_e / (float)c->p.pole_pairs;
        c->speed_val = c->hall.invalid ? MC_VAL_INVALID : (c->hall.have_sector ? MC_VAL_OK : MC_VAL_MISSING);
    }
    if (mc_usable(c->slow_ibatt_val) && mc_usable(vbus_val)) {
        c->p_batt_W = in->vbus_V * in->ibatt_A;
        c->energy_J += (double)c->p_batt_W * (double)dt;
    } else {
        c->p_batt_W = NAN; /* energy is NOT integrated from guesses */
    }

    /* ---- protection ---- */
    mc_prot_inputs_t pi;
    memset(&pi, 0, sizeof pi);
    pi.hw_overcurrent = in->hw_overcurrent;
    pi.hw_overvoltage = in->hw_overvoltage;
    pi.gate_driver_fault = in->gate_driver_fault;
    pi.watchdog_fault = in->watchdog_fault;
    pi.fast_overcurrent = c->fast_overcurrent;
    pi.fast_dt_invalid = c->fast_dt_invalid;
    pi.vbus_V = in->vbus_V;
    pi.vbus_val = vbus_val;
    pi.t_fet_degC = in->t_fet_degC;
    pi.t_fet_val = c->t_fet_val;
    pi.t_motor_degC = in->t_motor_degC;
    pi.t_motor_val = c->t_motor_val;
    pi.speed_mech_rad_s = c->speed_mech_rad_s;
    pi.hall_invalid = c->hall.invalid;
    pi.current_sense_invalid = c->current_invalid_run >= MC_CURRENT_INVALID_LIMIT;
    pi.throttle_valid = in->driver.throttle_valid;
    /* Stall / stuck-hall plausibility: a large q current with no hall edge
     * for MC_STALL_TIME_S means either a blocked rotor or a hall sensor stuck
     * at a legal code (undetectable from the code alone). Either way the
     * commutation angle cannot be trusted. Low-speed operation produces
     * edges, so normal crawling does not trip this. */
    {
        const bool high = c->config_ok && c->fast_cmd.pwm_enable &&
                          mc_absf(c->iq_meas_A) > MC_STALL_CURRENT_FRACTION * c->p.max_phase_current_A;
        const bool edge = c->hall.t_since_edge < c->stall_prev_t_since_edge; /* an edge reset it */
        c->stall_prev_t_since_edge = c->hall.t_since_edge;
        /* Count only time at high current WITHOUT a new edge since the current
         * rose: a long standstill before pulling away does not count. */
        c->stall_timer_s = (high && !edge) ? c->stall_timer_s + dt : 0.0f;
    }
    pi.rotor_stall = c->stall_timer_s >= MC_STALL_TIME_S;
    if (c->config_ok) mc_prot_evaluate(&c->prot, &pi, dt);
    c->fast_overcurrent = false; /* consumed (latched in prot if it was set) */
    c->fast_dt_invalid = false;

    /* ---- supervisor input ---- */
    c->sup.session_established = c->sess.established && !c->can_bus_off;
    c->sup.req_val = mc_fresh_status(&c->fr_req, now_us);
    if (c->req_invalid) c->sup.req_val |= MC_VAL_INVALID;
    c->sup.limits_val = mc_fresh_status(&c->fr_limits, now_us);
    /* Envelope: the request must reference a set the controller holds, and
     * the bound applied is the tighter of that set and the NEWEST committed
     * set. An older reference may only tighten; it never restores
     * permission the newest set has withdrawn (docs/CONTROL_CONTRACT.md). */
    c->sup.limits_match = false;
    c->sup.max_torque_Nm = 0.0f;
    c->sup.max_batt_power_W = 0.0f;
    if (c->lim[0].valid) {
        for (int k = 0; k < 2; k++) {
            if (c->lim[k].valid && (c->lim[k].seq & 0x0Fu) == c->req_limits_ref) {
                c->sup.limits_match = true;
                c->sup.max_torque_Nm = mc_minf(c->lim[0].max_torque_Nm, c->lim[k].max_torque_Nm);
                c->sup.max_batt_power_W = mc_minf(c->lim[0].max_batt_power_W, c->lim[k].max_batt_power_W);
                if (k != 0 && (c->lim[0].max_torque_Nm < c->lim[k].max_torque_Nm ||
                               c->lim[0].max_batt_power_W < c->lim[k].max_batt_power_W)) {
                    c->env_newest_tighter_steps++;
                }
                break;
            }
        }
    }
    c->sup.torque_req_Nm = c->req_torque_Nm;
    c->sup.coast_request = c->req_coast;

    /* ---- self test ---- */
    const bool hw_trip = in->hw_overcurrent || in->hw_overvoltage || in->gate_driver_fault;
    mc_sm_aux_t aux;
    aux.config_ok = c->config_ok;
    aux.output_permitted = c->output_permitted;
    aux.hw_trip = hw_trip;
    aux.selftest_done = c->sm.state == MC_ST_SELF_TEST && c->sm.selftest_timer_s >= MC_SELFTEST_MIN_S;
    aux.selftest_pass = in->gate_driver_ready && !in->gate_driver_fault && !in->watchdog_fault &&
                        in->current_offsets_ok && mc_usable(vbus_val) && in->vbus_V >= c->p.uv_trip_V &&
                        in->vbus_V <= c->p.ov_trip_V && c->hall.have_sector && !c->hall.invalid &&
                        mc_usable(c->t_fet_val) && mc_usable(c->t_motor_val);

    /* ---- state machine + arbitration ---- */
    const mc_state_t before = c->sm.state;
    const mc_transition_t t = mc_sm_step(&c->sm, &c->p, &in->driver, &c->sup, now_us, &c->prot, &aux, dt);
    if (t != MC_T_NONE) {
        c->last_transition = t;
        force_tx(c, SEMMC_ID_CTRL_STATUS);
        if (c->sm.state == MC_ST_FAULT_LATCHED || before == MC_ST_FAULT_LATCHED) force_tx(c, SEMMC_ID_CTRL_FAULT);
    }
    mc_arb_meas_t am;
    am.vbus_V = in->vbus_V;
    am.ibatt_A = in->ibatt_A;
    am.ibatt_val = c->slow_ibatt_val;
    am.speed_mech_rad_s = c->speed_mech_rad_s;
    am.speed_val = c->speed_val;
    if (c->config_ok) {
        mc_arb_step(&c->arb, &c->sm, &in->driver, &c->sup, &am, &c->prot, hw_trip, dt);
    } else {
        c->arb.accepted_Nm = 0.0f;
        c->arb.iq_ref_A = 0.0f;
        c->arb.pwm_enable = false;
        c->arb.reason = MC_R_FAULT_INHIBIT;
    }

    /* ---- slow -> fast handoff ---- */
    c->fast_cmd.pwm_enable = c->arb.pwm_enable && c->output_permitted && !hw_trip && c->prot.latched == 0u &&
                             (c->sm.state == MC_ST_MANUAL || c->sm.state == MC_ST_ECO_ASSIST ||
                              c->sm.state == MC_ST_DERATED);
    c->fast_cmd.iq_ref_A = c->fast_cmd.pwm_enable ? c->arb.iq_ref_A : 0.0f;
    c->fast_cmd.id_ref_A = c->fast_cmd.pwm_enable ? c->arb.id_ref_A : 0.0f;
}

/* ---------------------------------------------------------------- fast step */
void mc_core_fast_step(mc_core_t *c, const mc_fast_inputs_t *in, mc_fast_outputs_t *out)
{
    out->pwm_enable = false;
    out->duty.a = out->duty.b = out->duty.c = 0.5f;
    if (!c->config_ok) return;

    const float dt = in->dt;
    const bool dt_ok = mc_isfinite(dt) && dt > 0.0f && dt <= c->foc.dt_max_s;
    if (!dt_ok) c->fast_dt_invalid = true;

    c->theta_e = mc_hall_update(&c->hall, in->hall_code, dt_ok ? dt : 0.0f);
    mc_currents_resolve(&in->phase, &c->pc);

    /* Software overcurrent: any phase, measured or reconstructed. Acts in this
     * interrupt (outputs off now) and latches in the next slow step. */
    if (c->pc.valid) {
        for (int k = 0; k < 3; k++) {
            if (mc_absf(c->pc.i[k]) > c->p.sw_overcurrent_A) c->fast_overcurrent = true;
        }
    }
    const bool enable = c->fast_cmd.pwm_enable && dt_ok && !in->hw_trip && !c->fast_overcurrent && !c->fast_dt_invalid;
    if (enable && !c->pc.valid) {
        if (c->current_invalid_run < UINT32_MAX) c->current_invalid_run++;
    } else if (c->pc.valid) {
        c->current_invalid_run = 0u;
    }
    if (!enable || !c->pc.valid) {
        mc_foc_reset(&c->foc);
        c->fast_pwm_was_enabled = false;
        if (c->pc.valid) {
            const mc_ab_t iab = mc_currents_clarke(&c->pc);
            const mc_dq_t idq = mc_park(iab, sinf(c->theta_e), cosf(c->theta_e));
            c->id_meas_A = idq.d;
            c->iq_meas_A = idq.q;
        }
        return;
    }
    if (!c->fast_pwm_was_enabled) mc_foc_reset(&c->foc); /* fresh start, no stale integrators */
    c->fast_pwm_was_enabled = true;

    mc_foc_in_t fi;
    fi.i_ref.d = c->fast_cmd.id_ref_A;
    fi.i_ref.q = c->fast_cmd.iq_ref_A;
    fi.sin_th = sinf(c->theta_e);
    fi.cos_th = cosf(c->theta_e);
    fi.omega_e = c->hall.omega_e;
    fi.vbus = in->vbus_V;
    fi.dt = dt;
    mc_foc_out_t fo;
    mc_foc_step(&c->foc, &fi, &c->pc, &fo);
    c->id_meas_A = fo.i_meas.d;
    c->iq_meas_A = fo.i_meas.q;
    if (fo.inhibit) return;
    out->pwm_enable = true;
    out->duty = fo.duty;
}

/* ---------------------------------------------------------------- CAN TX */
static uint8_t validity_nibble(mc_validity_t v)
{
    uint8_t n = 0u;
    if (v & MC_VAL_MISSING) n |= 1u;
    if (v & MC_VAL_STALE) n |= 2u;
    if (v & (MC_VAL_INVALID | MC_VAL_NONFINITE | MC_VAL_OUT_OF_RANGE | MC_VAL_INTEGRITY)) n |= 4u;
    if (v & MC_VAL_SATURATED) n |= 8u;
    return n;
}

static uint32_t sup_link(const mc_core_t *c)
{
    if (c->sess.established) {
        return mc_supervisor_ok(&c->sup) ? MC_SUP_LINK_ESTABLISHED : MC_SUP_LINK_LOST;
    }
    return c->sess.hello_seen ? MC_SUP_LINK_HELLO : MC_SUP_LINK_NONE;
}

static bool build_frame(mc_core_t *c, uint32_t id, uint8_t seq, uint8_t out[8])
{
    semmc_result_t r;
    r.status = SEMMC_E_LEN;
    switch (id) {
    case SEMMC_ID_CTRL_FAULT: {
        semmc_ctrl_fault_t m = {seq, c->prot.latched & 0xFFFFFFu, c->prot.first_fault, c->reset_reason,
                                c->prot.fault_count > 255u ? 255u : c->prot.fault_count};
        r = semmc_encode_ctrl_fault(&m, out);
        break;
    }
    case SEMMC_ID_CTRL_STATUS: {
        semmc_ctrl_status_t m;
        m.seq = seq;
        m.state = (uint32_t)c->sm.state;
        m.owner = (uint32_t)c->sm.owner;
        m.sup_link = sup_link(c);
        m.session_tag = c->sess.tag;
        m.boot_id = c->boot_id;
        m.build_is_sim = c->build == MC_BUILD_HOST_SIM;
        m.cal_provenance = c->config_ok ? c->p.provenance : 0u;
        m.output_permitted = c->output_permitted;
        m.pwm_enabled = c->fast_cmd.pwm_enable;
        m.derating = c->sm.state == MC_ST_DERATED;
        m.hw_trip = (c->arb.reason & MC_R_HW_TRIP) != 0u;
        m.reserved = 0u;
        m.last_transition = (uint32_t)c->last_transition;
        r = semmc_encode_ctrl_status(&m, out);
        break;
    }
    case SEMMC_ID_CTRL_CMD_TRACE: {
        semmc_ctrl_cmd_trace_t m = {seq, c->arb.requested_Nm, c->arb.accepted_Nm, c->arb.reason};
        r = semmc_encode_ctrl_cmd_trace(&m, out);
        break;
    }
    case SEMMC_ID_DRIVER_CONTROLS: {
        const mc_driver_inputs_t *d = &c->last_driver;
        semmc_driver_controls_t m = {seq, d->throttle_valid ? d->throttle : NAN, d->brake, d->cancel, d->mode_eco,
                                     d->arm_switch, d->estop_chain_ok, d->driver_present, d->fault_reset,
                                     d->throttle_valid, 0u};
        r = semmc_encode_driver_controls(&m, out);
        break;
    }
    case SEMMC_ID_CTRL_SESSION: {
        semmc_ctrl_session_t m = {seq, c->sess.tag, c->sess.companion_session, SEMMC_PROTO_MAJOR, SEMMC_PROTO_MINOR};
        r = semmc_encode_ctrl_session(&m, out);
        break;
    }
    case SEMMC_ID_CTRL_MOTION: {
        semmc_ctrl_motion_t m = {seq, mc_usable(c->speed_val) ? c->speed_mech_rad_s : NAN,
                                 c->pc.valid ? c->iq_meas_A : NAN, mc_isfinite(c->slow_vbus_V) ? c->slow_vbus_V : NAN};
        r = semmc_encode_ctrl_motion(&m, out);
        break;
    }
    case SEMMC_ID_CTRL_CURRENTS: {
        semmc_ctrl_currents_t m = {seq, c->pc.valid ? c->id_meas_A : NAN,
                                   mc_usable(c->slow_ibatt_val) ? c->slow_ibatt_A : NAN,
                                   c->pc.measured_mask, c->pc.reconstructed_mask, c->pc.kcl_available, 0u,
                                   c->pc.kcl_available ? c->pc.kcl_residual_A : NAN};
        r = semmc_encode_ctrl_currents(&m, out);
        break;
    }
    case SEMMC_ID_CTRL_ENERGY: {
        semmc_ctrl_energy_t m = {seq, (float)c->energy_J, c->p_batt_W};
        r = semmc_encode_ctrl_energy(&m, out);
        break;
    }
    case SEMMC_ID_CTRL_THERMAL: {
        semmc_ctrl_thermal_t m = {seq, mc_usable(c->t_fet_val) ? c->t_fet_degC : NAN,
                                  mc_usable(c->t_motor_val) ? c->t_motor_degC : NAN, c->prot.derate,
                                  c->prot.derate_reasons};
        r = semmc_encode_ctrl_thermal(&m, out);
        break;
    }
    case SEMMC_ID_CTRL_VALIDITY: {
        const uint8_t vi = c->pc.valid ? 0u : 4u;
        semmc_ctrl_validity_t m;
        m.seq = seq;
        m.v_speed = validity_nibble(c->speed_val);
        m.v_ia = (c->pc.measured_mask & MC_PH_A) ? 0u : vi | ((c->pc.reconstructed_mask & MC_PH_A) ? 0u : 1u);
        m.v_ib = (c->pc.measured_mask & MC_PH_B) ? 0u : vi | ((c->pc.reconstructed_mask & MC_PH_B) ? 0u : 1u);
        m.v_ic = (c->pc.measured_mask & MC_PH_C) ? 0u : vi | ((c->pc.reconstructed_mask & MC_PH_C) ? 0u : 1u);
        m.v_vbus = mc_isfinite(c->slow_vbus_V) ? 0u : 4u;
        m.v_ibatt = validity_nibble(c->slow_ibatt_val);
        m.v_t_fet = validity_nibble(c->t_fet_val);
        m.v_t_motor = validity_nibble(c->t_motor_val);
        m.v_throttle = c->last_driver.throttle_valid ? 0u : 4u;
        m.v_sup_req = validity_nibble(c->sup.req_val);
        m.v_sup_limits = validity_nibble(c->sup.limits_val);
        m.v_hall = c->hall.invalid ? 4u : (c->hall.have_sector ? 0u : 1u);
        r = semmc_encode_ctrl_validity(&m, out);
        break;
    }
    case SEMMC_ID_CTRL_IDENTITY: {
        semmc_ctrl_identity_t m = {seq, SEMMC_PROTO_MAJOR, SEMMC_PROTO_MINOR, MC_FW_MAJOR, MC_FW_MINOR,
                                   c->config_ok ? (c->p.cal_version & 0xFFFFu) : 0u,
                                   c->config_ok ? c->p.provenance : 0u, c->build == MC_BUILD_HOST_SIM, 0u};
        r = semmc_encode_ctrl_identity(&m, out);
        break;
    }
    default:
        return false;
    }
    return r.status == SEMMC_OK;
}

static const uint32_t k_tx_ids[] = {
    SEMMC_ID_CTRL_FAULT,   SEMMC_ID_CTRL_STATUS,  SEMMC_ID_CTRL_CMD_TRACE, SEMMC_ID_DRIVER_CONTROLS,
    SEMMC_ID_CTRL_SESSION, SEMMC_ID_CTRL_MOTION,  SEMMC_ID_CTRL_CURRENTS,  SEMMC_ID_CTRL_ENERGY,
    SEMMC_ID_CTRL_THERMAL, SEMMC_ID_CTRL_VALIDITY, SEMMC_ID_CTRL_IDENTITY};
static const uint32_t k_tx_period_us[] = {
    SEMMC_PERIOD_US_CTRL_FAULT,   SEMMC_PERIOD_US_CTRL_STATUS,  SEMMC_PERIOD_US_CTRL_CMD_TRACE,
    SEMMC_PERIOD_US_DRIVER_CONTROLS, SEMMC_PERIOD_US_CTRL_SESSION, SEMMC_PERIOD_US_CTRL_MOTION,
    SEMMC_PERIOD_US_CTRL_CURRENTS, SEMMC_PERIOD_US_CTRL_ENERGY,  SEMMC_PERIOD_US_CTRL_THERMAL,
    SEMMC_PERIOD_US_CTRL_VALIDITY, SEMMC_PERIOD_US_CTRL_IDENTITY};

bool mc_core_can_tx_poll(mc_core_t *c, mc_time_us_t now_us, uint32_t *can_id, uint8_t data[8])
{
    if (c->can_bus_off) return false;
    for (size_t k = 0; k < sizeof k_tx_ids / sizeof k_tx_ids[0]; k++) { /* ascending id == priority */
        const uint32_t id = k_tx_ids[k];
        const unsigned idx = (unsigned)tx_index(id);
        const bool forced = (c->tx_force_mask & (1u << idx)) != 0u;
        if (!forced && now_us < c->tx_next_us[idx]) continue;
        c->tx_force_mask &= ~(1u << idx);
        c->tx_next_us[idx] = now_us + k_tx_period_us[k];
        if (!build_frame(c, id, c->tx_seq[idx], data)) continue;
        c->tx_seq[idx]++;
        *can_id = id;
        c->can.tx_frames++;
        return true;
    }
    return false;
}

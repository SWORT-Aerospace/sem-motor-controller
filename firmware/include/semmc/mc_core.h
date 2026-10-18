/* Controller core: owns the slow (supervisory, ~1 kHz) and fast (PWM-rate)
 * steps for one motor. Platform code calls:
 *
 *   mc_core_init()            once, with the calibration blob
 *   mc_core_on_msg_rx()       from the link RX task (NOT the current ISR)
 *   mc_core_slow_step()       at the supervisory rate
 *   mc_core_fast_step()       in the current-control interrupt
 *   mc_core_msg_tx_poll()     from the link TX task
 *
 * The core is transport-neutral: it exchanges 8-byte protocol messages
 * identified by the protocol's canonical message numbers (SEMMC_ID_*). Each
 * message carries its own data id, sequence and CRC, so integrity does not
 * depend on the transport's addressing. A transport binding maps the numbers
 * onto its own addressing; the CAN binding (src/transport/mc_can_binding.c)
 * is one such binding and the only one implemented. Manual driving never
 * depends on any link.
 *
 * Shared state between the fast step (current interrupt) and the slow step.
 * Every shared variable has exactly one writing context. The mechanism, not
 * "volatile", is what makes it correct:
 *
 *   fast_pub[2], fast_pub_idx   slow writes, fast reads. The slow step fills
 *       the buffer the index does not select, then stores the index with
 *       release ordering; the fast step loads it with acquire ordering. On
 *       the target the fast step runs in an interrupt the slow step cannot
 *       preempt (PRIO_FAST < PRIO_SLOW, platform/stm32g4/src/main.c), so a
 *       fast step that starts after the index store reads the whole new
 *       buffer before the slow step runs again, and the buffer the slow step
 *       writes next is never being read.
 *   fast_oc_events, fast_dt_events   fast writes (+1 per fast step that saw a
 *       software overcurrent / an invalid dt), slow reads.
 *   fast_oc_ack, fast_dt_ack   slow writes, fast reads: the event count the
 *       slow step has reacted to, stored only after it has published the
 *       command that reacts (a latched fault withdraws pwm_enable). The fast
 *       step keeps the outputs off while events != ack. An event that
 *       arrives while the slow step is acknowledging raises the count past
 *       the ack and is seen by the next slow step: none is erased.
 *   current_invalid_run   fast writes, slow reads.
 *
 * These are C11 atomics: word-sized and lock-free on Cortex-M4
 * (ATOMIC_INT_LOCK_FREE == 2; checked below), so each load and store is
 * single-copy atomic, and release/acquire orders the buffer writes before
 * the index store (GCC emits DMB on ARMv7-M; tests/integration/
 * test_target_firmware.py checks the image). Values read only for
 * telemetry or plausibility (id/iq measured, the phase-current struct, hall
 * times) are written by the fast step word by word; a slow-step read may
 * combine words from two fast steps, which those uses tolerate.
 */
#ifndef SEMMC_MC_CORE_H
#define SEMMC_MC_CORE_H

#include <stdatomic.h>

#include "semmc/mc_config.h"
#include "semmc/mc_control.h"
#include "semmc/mc_csia_shadow.h"
#include "semmc/mc_freshness.h"
#include "semmc/mc_protection.h"
#include "semmc/mc_state_machine.h"
#include "semmc/mc_types.h"

_Static_assert(ATOMIC_INT_LOCK_FREE == 2, "fast/slow handoff needs lock-free word atomics");

#define MC_FW_MAJOR 0u
#define MC_FW_MINOR 1u

#define MC_CLOCK_DOMAIN_COMPANION 1u
/* Longest slow-step interval that is integrated into energy_J; a longer interval
 * (a stalled or late slow step) is counted in energy_gap_s instead of being
 * integrated as one rectangle of the latest power. */
#define MC_ENERGY_MAX_DT_S 0.02f

typedef enum { MC_SUP_LINK_NONE = 0, MC_SUP_LINK_HELLO = 1, MC_SUP_LINK_ESTABLISHED = 2, MC_SUP_LINK_LOST = 3 } mc_sup_link_t;

/* Inputs sampled by the platform for the slow step. */
typedef struct {
    mc_driver_inputs_t driver;
    bool hw_overcurrent;
    bool hw_overvoltage;
    bool gate_driver_fault;
    bool gate_driver_ready;
    bool watchdog_fault;
    float vbus_V;
    mc_validity_t vbus_val;
    float ibatt_A;            /* independent DC-bus meter (e.g. INA228), + discharge */
    mc_validity_t ibatt_val;
    float t_fet_degC;
    mc_validity_t t_fet_val;
    float t_motor_degC;
    mc_validity_t t_motor_val;
    bool current_offsets_ok;  /* self-test: zero-current ADC offsets within tolerance */
    uint8_t reset_reason;
} mc_slow_inputs_t;

/* Inputs for the fast step. */
typedef struct {
    mc_phase_meas_t phase;    /* calibrated phase currents and which are valid this cycle */
    uint8_t hall_code;
    float vbus_V;
    float dt;                 /* s since previous fast step (measured) */
    bool hw_trip;             /* independent hardware trip line (already disabled the gates) */
} mc_fast_inputs_t;

typedef struct {
    bool pwm_enable;
    mc_duty_t duty;
} mc_fast_outputs_t;

/* Slow -> fast handoff. */
typedef struct {
    bool pwm_enable;
    float id_ref_A, iq_ref_A;
} mc_fast_cmd_t;

typedef struct {
    uint8_t tag;               /* 0 = none */
    uint32_t companion_session;
    bool hello_seen;
    bool established;          /* tag echoed back in both limits and request */
    bool limits_tag_ok, req_tag_ok;
    mc_time_us_t last_hello_us;
} mc_sup_session_t;

typedef struct {
    uint32_t rx_frames, rx_crc_fail, rx_len_fail, rx_unknown, rx_tag_mismatch, rx_proto_mismatch;
    uint32_t tx_frames;
    uint32_t bus_off_events;
} mc_can_stats_t;

typedef struct {
    /* configuration */
    mc_config_t cfg;
    mc_params_t p;
    bool config_ok;
    mc_build_kind_t build;
    bool output_permitted;
    uint16_t boot_id;
    /* subsystems */
    mc_protection_t prot;
    mc_sm_t sm;
    mc_arbiter_t arb;
    mc_foc_t foc;
    mc_hall_t hall;
    mc_csia_shadow_t csia;
    /* supervisor */
    mc_sup_session_t sess;
    uint32_t tags_issued;      /* session tags issued since boot; survives session resets */
    mc_fresh_t fr_req, fr_limits, fr_hello;
    mc_supervisor_input_t sup;
    /* Double-buffered supervisor bounds: [0] = newest committed set, [1] = the
     * set before it. A request must reference a held set (limits_ref), so a
     * limits update between two requests does not cause a spurious supervisor
     * loss; the bound applied is min(newest, referenced), so a tighter newest
     * set takes effect on the next slow step, before any matching request. */
    struct {
        bool valid;
        uint8_t seq;
        float max_torque_Nm;
        float max_batt_power_W;
    } lim[2];
    bool limits_committed;
    float req_torque_Nm;
    bool req_invalid;          /* last accepted request carried the sentinel / out-of-range torque */
    bool req_coast;
    float stall_timer_s;
    float stall_prev_t_since_edge;
    uint8_t req_limits_ref;
    uint32_t env_newest_tighter_steps; /* slow steps where the newest set bounded an older reference */
    /* measurements / estimates */
    float speed_mech_rad_s;
    mc_validity_t speed_val;
    float theta_e;
    float id_meas_A, iq_meas_A;
    mc_phase_currents_t pc;
    float p_batt_W;
    double energy_J;           /* controller input (bus shunt), integrated in the slow step */
    double energy_integrated_s; /* time covered by energy_J */
    double energy_gap_s;       /* time NOT integrated: invalid V or I, or update interval > MC_ENERGY_MAX_DT_S */
    float slow_vbus_V;
    mc_validity_t slow_vbus_val; /* platform flags + finiteness; telemetry reports it as is */
    float slow_ibatt_A;
    mc_validity_t slow_ibatt_val;
    float t_fet_degC, t_motor_degC;
    mc_validity_t t_fet_val, t_motor_val;
    mc_driver_inputs_t last_driver;
    uint8_t reset_reason;
    /* fast loop */
    mc_fast_cmd_t fast_cmd;          /* latest command computed by the slow step */
    mc_fast_cmd_t fast_pub[2];       /* published copies; the fast step reads fast_pub[fast_pub_idx] */
    atomic_uint fast_pub_idx;        /* shared: see "Shared state" above */
    bool fast_pwm_was_enabled;       /* fast step only */
    atomic_uint fast_oc_events, fast_dt_events; /* written by the fast step only */
    atomic_uint fast_oc_ack, fast_dt_ack;       /* written by the slow step only */
    atomic_uint current_invalid_run; /* consecutive fast steps without a valid current sample; fast writes */
    bool link_down;            /* transport reports the link unusable (CAN: bus-off) */
    /* time */
    mc_time_us_t now_us;
    mc_time_us_t last_slow_us;
    bool have_slow;
    mc_time_us_t tx_next_us[16];
    uint8_t tx_seq[16];
    uint32_t tx_force_mask;    /* on-change messages pending */
    /* diagnostics */
    mc_can_stats_t can;
    mc_transition_t last_transition;
} mc_core_t;

/* Returns false if the blob was rejected; the core then stays in BOOT ->
 * FAULT_LATCHED(CONFIG_INVALID) and never produces torque. */
bool mc_core_init(mc_core_t *c, const uint8_t *cal_blob, size_t cal_len, mc_build_kind_t build, uint16_t boot_id);
void mc_core_slow_step(mc_core_t *c, mc_time_us_t now_us, const mc_slow_inputs_t *in);
void mc_core_fast_step(mc_core_t *c, const mc_fast_inputs_t *in, mc_fast_outputs_t *out);

/* ---- transport-neutral message interface ------------------------------- */
/* Protocol message numbers occupy MC_PROTO_MSG_FIRST .. MC_PROTO_MSG_FIRST + MC_PROTO_MSG_SPAN - 1. */
#define MC_PROTO_MSG_FIRST 0x300u
#define MC_PROTO_MSG_SPAN 0x40u
void mc_core_on_msg_rx(mc_core_t *c, mc_time_us_t now_us, uint32_t msg_id, const uint8_t *data, uint8_t len);
/* A lost link ends any supervisor session at once (ECO -> READY on the next slow step). */
void mc_core_on_link_state(mc_core_t *c, bool link_down);
/* Emit at most one due message. Returns true and fills msg_id/data if one is due. */
bool mc_core_msg_tx_poll(mc_core_t *c, mc_time_us_t now_us, uint32_t *msg_id, uint8_t data[8]);

/* ---- CAN binding (src/transport/mc_can_binding.c) ----------------------- */
/* 11-bit identifier = base + (message number - MC_PROTO_MSG_FIRST), base = supervision.can_id_base
 * (validated: multiple of 0x40). With an invalid calibration the protocol default 0x300 is used
 * (bench diagnostics only: a hardware build refuses to run without a valid calibration). */
uint32_t mc_can_id_base(const mc_core_t *c);
void mc_core_on_can_rx(mc_core_t *c, mc_time_us_t now_us, uint32_t can_id, const uint8_t *data, uint8_t len);
void mc_core_on_can_bus_off(mc_core_t *c, bool bus_off);
bool mc_core_can_tx_poll(mc_core_t *c, mc_time_us_t now_us, uint32_t *can_id, uint8_t data[8]);

#endif /* SEMMC_MC_CORE_H */

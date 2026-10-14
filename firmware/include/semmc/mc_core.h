/* Controller core: owns the slow (supervisory, ~1 kHz) and fast (PWM-rate)
 * steps for one motor. Platform code calls:
 *
 *   mc_core_init()            once, with the calibration blob
 *   mc_core_on_can_rx()       from the CAN RX task (NOT the current ISR)
 *   mc_core_slow_step()       at the supervisory rate
 *   mc_core_fast_step()       in the current-control interrupt
 *   mc_core_can_tx_poll()     from the CAN TX task
 *
 * Data handoff slow -> fast is a single struct written by the slow step and
 * read by the fast step; on the target this must be done with a sequence
 * lock or with the fast ISR masked for the copy (documented in
 * firmware/platform/stm32g4/README.md). The host simulation is single-threaded.
 */
#ifndef SEMMC_MC_CORE_H
#define SEMMC_MC_CORE_H

#include "semmc/mc_config.h"
#include "semmc/mc_control.h"
#include "semmc/mc_csia_shadow.h"
#include "semmc/mc_freshness.h"
#include "semmc/mc_protection.h"
#include "semmc/mc_state_machine.h"
#include "semmc/mc_types.h"

#define MC_FW_MAJOR 0u
#define MC_FW_MINOR 1u

#define MC_CLOCK_DOMAIN_COMPANION 1u

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
    mc_fresh_t fr_req, fr_limits, fr_hello;
    mc_supervisor_input_t sup;
    /* Double-buffered supervisor bounds: [0] = newest committed set, [1] = the
     * set before it. A request is bounded by the set it references
     * (limits_ref), so a limits update between two requests never leaves a
     * request without its bounds. */
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
    /* measurements / estimates */
    float speed_mech_rad_s;
    mc_validity_t speed_val;
    float theta_e;
    float id_meas_A, iq_meas_A;
    mc_phase_currents_t pc;
    float p_batt_W;
    double energy_J;           /* battery-side, integrated in the slow step */
    float slow_vbus_V;
    float slow_ibatt_A;
    mc_validity_t slow_ibatt_val;
    float t_fet_degC, t_motor_degC;
    mc_validity_t t_fet_val, t_motor_val;
    mc_driver_inputs_t last_driver;
    uint8_t reset_reason;
    /* fast loop */
    mc_fast_cmd_t fast_cmd;
    bool fast_pwm_was_enabled;
    volatile bool fast_overcurrent;
    volatile bool fast_dt_invalid;
    uint32_t current_invalid_run;  /* consecutive fast steps without a valid current sample */
    bool can_bus_off;
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
void mc_core_on_can_rx(mc_core_t *c, mc_time_us_t now_us, uint32_t can_id, const uint8_t *data, uint8_t len);
void mc_core_on_can_bus_off(mc_core_t *c, bool bus_off);
void mc_core_slow_step(mc_core_t *c, mc_time_us_t now_us, const mc_slow_inputs_t *in);
void mc_core_fast_step(mc_core_t *c, const mc_fast_inputs_t *in, mc_fast_outputs_t *out);
/* Emit at most one due frame. Returns true and fills id/data if a frame is due. */
bool mc_core_can_tx_poll(mc_core_t *c, mc_time_us_t now_us, uint32_t *can_id, uint8_t data[8]);

#endif /* SEMMC_MC_CORE_H */

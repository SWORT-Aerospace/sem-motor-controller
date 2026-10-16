/* GENERATED from protocol/protocol.yaml by tools/gen_protocol.py - do not edit. */
/* semmc CAN protocol v1.1, spec hash 3365b84b45a16c63 */
#ifndef SEMMC_PROTOCOL_H
#define SEMMC_PROTOCOL_H

#include <stdbool.h>
#include <stdint.h>

#define SEMMC_PROTO_MAJOR 1u
#define SEMMC_PROTO_MINOR 1u
#define SEMMC_PROTO_SPEC_HASH "3365b84b45a16c63"
#define SEMMC_NOMINAL_BITRATE 500000u
#define SEMMC_FRAME_LEN 8u

typedef enum { SEMMC_OK = 0, SEMMC_E_LEN = 1, SEMMC_E_CRC = 2, SEMMC_E_NAN = 3 } semmc_status_t;

typedef struct {
    semmc_status_t status;
    uint32_t saturated;    /* bit i: field i was clamped */
    uint32_t invalid;      /* bit i: field i carried / was encoded as the sentinel */
    uint32_t out_of_range; /* bit i: decoded raw outside the declared range */
} semmc_result_t;

uint8_t semmc_crc8_data_id(uint16_t data_id, const uint8_t *payload7);
/* Returns the message index for a CAN id, or -1. */
int semmc_msg_index(uint32_t can_id);

/* ctrl_fault - Latched faults, first fault since reset and last MCU reset reason. */
#define SEMMC_ID_CTRL_FAULT 0x300u
#define SEMMC_DATAID_CTRL_FAULT 0x0B00u
#define SEMMC_PERIOD_US_CTRL_FAULT 1000000u
#define SEMMC_F_CTRL_FAULT_LATCHED (1u << 0)
#define SEMMC_F_CTRL_FAULT_FIRST_FAULT (1u << 1)
#define SEMMC_F_CTRL_FAULT_RESET_REASON (1u << 2)
#define SEMMC_F_CTRL_FAULT_FAULT_COUNT (1u << 3)
typedef struct {
    uint8_t seq;
    uint32_t latched;
    uint32_t first_fault;
    uint32_t reset_reason;
    uint32_t fault_count;
} semmc_ctrl_fault_t;
semmc_result_t semmc_encode_ctrl_fault(const semmc_ctrl_fault_t *m, uint8_t out[8]);
semmc_result_t semmc_decode_ctrl_fault(const uint8_t *in, uint8_t len, semmc_ctrl_fault_t *m);

/* sup_torque_req - Supervisory torque request (motor shaft). PROVISIONAL 50 Hz / 100 ms timeout, simulation only, pending hazard and latency analysis. */
#define SEMMC_ID_SUP_TORQUE_REQ 0x308u
#define SEMMC_DATAID_SUP_TORQUE_REQ 0x0B08u
#define SEMMC_PERIOD_US_SUP_TORQUE_REQ 20000u
#define SEMMC_F_SUP_TORQUE_REQ_SESSION_TAG (1u << 0)
#define SEMMC_F_SUP_TORQUE_REQ_LIMITS_REF (1u << 1)
#define SEMMC_F_SUP_TORQUE_REQ_COAST_REQUEST (1u << 2)
#define SEMMC_F_SUP_TORQUE_REQ_RESERVED (1u << 3)
#define SEMMC_F_SUP_TORQUE_REQ_TORQUE_NM (1u << 4)
#define SEMMC_F_SUP_TORQUE_REQ_SRC_TIME_MS (1u << 5)
typedef struct {
    uint8_t seq;
    uint32_t session_tag;
    uint32_t limits_ref;
    bool coast_request;
    uint32_t reserved;
    float torque_Nm; /* N*m */
    uint32_t src_time_ms;
} semmc_sup_torque_req_t;
semmc_result_t semmc_encode_sup_torque_req(const semmc_sup_torque_req_t *m, uint8_t out[8]);
semmc_result_t semmc_decode_sup_torque_req(const uint8_t *in, uint8_t len, semmc_sup_torque_req_t *m);

/* sup_limits - Supervisor-declared bounds; can only tighten controller limits. */
#define SEMMC_ID_SUP_LIMITS 0x309u
#define SEMMC_DATAID_SUP_LIMITS 0x0B09u
#define SEMMC_PERIOD_US_SUP_LIMITS 100000u
#define SEMMC_F_SUP_LIMITS_SESSION_TAG (1u << 0)
#define SEMMC_F_SUP_LIMITS_LIMITS_SEQ (1u << 1)
#define SEMMC_F_SUP_LIMITS_MAX_TORQUE_NM (1u << 2)
#define SEMMC_F_SUP_LIMITS_MAX_BATT_POWER_W (1u << 3)
typedef struct {
    uint8_t seq;
    uint32_t session_tag;
    uint32_t limits_seq;
    float max_torque_Nm; /* N*m */
    float max_batt_power_W; /* W */
} semmc_sup_limits_t;
semmc_result_t semmc_encode_sup_limits(const semmc_sup_limits_t *m, uint8_t out[8]);
semmc_result_t semmc_decode_sup_limits(const uint8_t *in, uint8_t len, semmc_sup_limits_t *m);

/* sup_hello - Companion session announcement / handshake. Cannot arm or select a mode. */
#define SEMMC_ID_SUP_HELLO 0x30Au
#define SEMMC_DATAID_SUP_HELLO 0x0B0Au
#define SEMMC_PERIOD_US_SUP_HELLO 500000u
#define SEMMC_F_SUP_HELLO_PROTO_MAJOR (1u << 0)
#define SEMMC_F_SUP_HELLO_PROTO_MINOR (1u << 1)
#define SEMMC_F_SUP_HELLO_ROLE (1u << 2)
#define SEMMC_F_SUP_HELLO_COMPANION_SESSION (1u << 3)
typedef struct {
    uint8_t seq;
    uint32_t proto_major;
    uint32_t proto_minor;
    uint32_t role;
    uint32_t companion_session;
} semmc_sup_hello_t;
semmc_result_t semmc_encode_sup_hello(const semmc_sup_hello_t *m, uint8_t out[8]);
semmc_result_t semmc_decode_sup_hello(const uint8_t *in, uint8_t len, semmc_sup_hello_t *m);

/* ctrl_status - Operating state, owner, supervisor link and boot identity. */
#define SEMMC_ID_CTRL_STATUS 0x310u
#define SEMMC_DATAID_CTRL_STATUS 0x0B10u
#define SEMMC_PERIOD_US_CTRL_STATUS 20000u
#define SEMMC_F_CTRL_STATUS_STATE (1u << 0)
#define SEMMC_F_CTRL_STATUS_OWNER (1u << 1)
#define SEMMC_F_CTRL_STATUS_SUP_LINK (1u << 2)
#define SEMMC_F_CTRL_STATUS_SESSION_TAG (1u << 3)
#define SEMMC_F_CTRL_STATUS_BOOT_ID (1u << 4)
#define SEMMC_F_CTRL_STATUS_BUILD_IS_SIM (1u << 5)
#define SEMMC_F_CTRL_STATUS_CAL_PROVENANCE (1u << 6)
#define SEMMC_F_CTRL_STATUS_OUTPUT_PERMITTED (1u << 7)
#define SEMMC_F_CTRL_STATUS_PWM_ENABLED (1u << 8)
#define SEMMC_F_CTRL_STATUS_DERATING (1u << 9)
#define SEMMC_F_CTRL_STATUS_HW_TRIP (1u << 10)
#define SEMMC_F_CTRL_STATUS_RESERVED (1u << 11)
#define SEMMC_F_CTRL_STATUS_LAST_TRANSITION (1u << 12)
typedef struct {
    uint8_t seq;
    uint32_t state;
    uint32_t owner;
    uint32_t sup_link;
    uint32_t session_tag;
    uint32_t boot_id;
    bool build_is_sim;
    uint32_t cal_provenance;
    bool output_permitted;
    bool pwm_enabled;
    bool derating;
    bool hw_trip;
    uint32_t reserved;
    uint32_t last_transition;
} semmc_ctrl_status_t;
semmc_result_t semmc_encode_ctrl_status(const semmc_ctrl_status_t *m, uint8_t out[8]);
semmc_result_t semmc_decode_ctrl_status(const uint8_t *in, uint8_t len, semmc_ctrl_status_t *m);

/* ctrl_cmd_trace - Requested (owner) vs accepted torque and reason bits (MC_R_*). */
#define SEMMC_ID_CTRL_CMD_TRACE 0x311u
#define SEMMC_DATAID_CTRL_CMD_TRACE 0x0B11u
#define SEMMC_PERIOD_US_CTRL_CMD_TRACE 20000u
#define SEMMC_F_CTRL_CMD_TRACE_REQUESTED_NM (1u << 0)
#define SEMMC_F_CTRL_CMD_TRACE_ACCEPTED_NM (1u << 1)
#define SEMMC_F_CTRL_CMD_TRACE_REASON (1u << 2)
typedef struct {
    uint8_t seq;
    float requested_Nm; /* N*m */
    float accepted_Nm; /* N*m */
    uint32_t reason;
} semmc_ctrl_cmd_trace_t;
semmc_result_t semmc_encode_ctrl_cmd_trace(const semmc_ctrl_cmd_trace_t *m, uint8_t out[8]);
semmc_result_t semmc_decode_ctrl_cmd_trace(const uint8_t *in, uint8_t len, semmc_ctrl_cmd_trace_t *m);

/* driver_controls - Wired driver controls AS SEEN BY THE CONTROLLER (report only; never an input). */
#define SEMMC_ID_DRIVER_CONTROLS 0x312u
#define SEMMC_DATAID_DRIVER_CONTROLS 0x0B12u
#define SEMMC_PERIOD_US_DRIVER_CONTROLS 20000u
#define SEMMC_F_DRIVER_CONTROLS_THROTTLE (1u << 0)
#define SEMMC_F_DRIVER_CONTROLS_BRAKE (1u << 1)
#define SEMMC_F_DRIVER_CONTROLS_CANCEL (1u << 2)
#define SEMMC_F_DRIVER_CONTROLS_MODE_ECO (1u << 3)
#define SEMMC_F_DRIVER_CONTROLS_ARM_SWITCH (1u << 4)
#define SEMMC_F_DRIVER_CONTROLS_ESTOP_CHAIN_OK (1u << 5)
#define SEMMC_F_DRIVER_CONTROLS_DRIVER_PRESENT (1u << 6)
#define SEMMC_F_DRIVER_CONTROLS_FAULT_RESET (1u << 7)
#define SEMMC_F_DRIVER_CONTROLS_THROTTLE_VALID (1u << 8)
#define SEMMC_F_DRIVER_CONTROLS_RESERVED (1u << 9)
typedef struct {
    uint8_t seq;
    float throttle; /* 1 */
    bool brake;
    bool cancel;
    bool mode_eco;
    bool arm_switch;
    bool estop_chain_ok;
    bool driver_present;
    bool fault_reset;
    bool throttle_valid;
    uint32_t reserved;
} semmc_driver_controls_t;
semmc_result_t semmc_encode_driver_controls(const semmc_driver_controls_t *m, uint8_t out[8]);
semmc_result_t semmc_decode_driver_controls(const uint8_t *in, uint8_t len, semmc_driver_controls_t *m);

/* ctrl_session - Handshake reply - session tag assigned to the echoed companion session. */
#define SEMMC_ID_CTRL_SESSION 0x313u
#define SEMMC_DATAID_CTRL_SESSION 0x0B13u
#define SEMMC_PERIOD_US_CTRL_SESSION 500000u
#define SEMMC_F_CTRL_SESSION_SESSION_TAG (1u << 0)
#define SEMMC_F_CTRL_SESSION_COMPANION_SESSION_ECHO (1u << 1)
#define SEMMC_F_CTRL_SESSION_PROTO_MAJOR (1u << 2)
#define SEMMC_F_CTRL_SESSION_PROTO_MINOR (1u << 3)
typedef struct {
    uint8_t seq;
    uint32_t session_tag;
    uint32_t companion_session_echo;
    uint32_t proto_major;
    uint32_t proto_minor;
} semmc_ctrl_session_t;
semmc_result_t semmc_encode_ctrl_session(const semmc_ctrl_session_t *m, uint8_t out[8]);
semmc_result_t semmc_decode_ctrl_session(const uint8_t *in, uint8_t len, semmc_ctrl_session_t *m);

/* ctrl_motion - Rotor mechanical speed, measured q current, bus voltage. */
#define SEMMC_ID_CTRL_MOTION 0x318u
#define SEMMC_DATAID_CTRL_MOTION 0x0B18u
#define SEMMC_PERIOD_US_CTRL_MOTION 10000u
#define SEMMC_F_CTRL_MOTION_SPEED_MECH_RAD_S (1u << 0)
#define SEMMC_F_CTRL_MOTION_IQ_A (1u << 1)
#define SEMMC_F_CTRL_MOTION_VBUS_V (1u << 2)
typedef struct {
    uint8_t seq;
    float speed_mech_rad_s; /* rad/s */
    float iq_A; /* A */
    float vbus_V; /* V */
} semmc_ctrl_motion_t;
semmc_result_t semmc_encode_ctrl_motion(const semmc_ctrl_motion_t *m, uint8_t out[8]);
semmc_result_t semmc_decode_ctrl_motion(const uint8_t *in, uint8_t len, semmc_ctrl_motion_t *m);

/* ctrl_currents - d current, battery current (+ discharge), phase-measurement provenance, KCL residual. */
#define SEMMC_ID_CTRL_CURRENTS 0x319u
#define SEMMC_DATAID_CTRL_CURRENTS 0x0B19u
#define SEMMC_PERIOD_US_CTRL_CURRENTS 10000u
#define SEMMC_F_CTRL_CURRENTS_ID_A (1u << 0)
#define SEMMC_F_CTRL_CURRENTS_IBATT_A (1u << 1)
#define SEMMC_F_CTRL_CURRENTS_MEASURED_MASK (1u << 2)
#define SEMMC_F_CTRL_CURRENTS_RECONSTRUCTED_MASK (1u << 3)
#define SEMMC_F_CTRL_CURRENTS_KCL_AVAILABLE (1u << 4)
#define SEMMC_F_CTRL_CURRENTS_RESERVED (1u << 5)
#define SEMMC_F_CTRL_CURRENTS_KCL_RESIDUAL_A (1u << 6)
typedef struct {
    uint8_t seq;
    float id_A; /* A */
    float ibatt_A; /* A */
    uint32_t measured_mask;
    uint32_t reconstructed_mask;
    bool kcl_available;
    uint32_t reserved;
    float kcl_residual_A; /* A */
} semmc_ctrl_currents_t;
semmc_result_t semmc_encode_ctrl_currents(const semmc_ctrl_currents_t *m, uint8_t out[8]);
semmc_result_t semmc_decode_ctrl_currents(const uint8_t *in, uint8_t len, semmc_ctrl_currents_t *m);

/* ctrl_energy - Battery-side energy since controller boot and instantaneous battery power. */
#define SEMMC_ID_CTRL_ENERGY 0x320u
#define SEMMC_DATAID_CTRL_ENERGY 0x0B20u
#define SEMMC_PERIOD_US_CTRL_ENERGY 100000u
#define SEMMC_F_CTRL_ENERGY_ENERGY_J (1u << 0)
#define SEMMC_F_CTRL_ENERGY_P_BATT_W (1u << 1)
typedef struct {
    uint8_t seq;
    float energy_J; /* J */
    float p_batt_W; /* W */
} semmc_ctrl_energy_t;
semmc_result_t semmc_encode_ctrl_energy(const semmc_ctrl_energy_t *m, uint8_t out[8]);
semmc_result_t semmc_decode_ctrl_energy(const uint8_t *in, uint8_t len, semmc_ctrl_energy_t *m);

/* ctrl_thermal - Temperatures and derating. */
#define SEMMC_ID_CTRL_THERMAL 0x321u
#define SEMMC_DATAID_CTRL_THERMAL 0x0B21u
#define SEMMC_PERIOD_US_CTRL_THERMAL 100000u
#define SEMMC_F_CTRL_THERMAL_T_FET_DEGC (1u << 0)
#define SEMMC_F_CTRL_THERMAL_T_MOTOR_DEGC (1u << 1)
#define SEMMC_F_CTRL_THERMAL_DERATE (1u << 2)
#define SEMMC_F_CTRL_THERMAL_DERATE_REASONS (1u << 3)
typedef struct {
    uint8_t seq;
    float t_fet_degC; /* degC */
    float t_motor_degC; /* degC */
    float derate; /* 1 */
    uint32_t derate_reasons;
} semmc_ctrl_thermal_t;
semmc_result_t semmc_encode_ctrl_thermal(const semmc_ctrl_thermal_t *m, uint8_t out[8]);
semmc_result_t semmc_decode_ctrl_thermal(const uint8_t *in, uint8_t len, semmc_ctrl_thermal_t *m);

/* ctrl_validity - Per-signal validity nibbles (bit0 missing, bit1 stale, bit2 invalid/nonfinite/ out-of-range/integrity, bit3 saturated). */
#define SEMMC_ID_CTRL_VALIDITY 0x322u
#define SEMMC_DATAID_CTRL_VALIDITY 0x0B22u
#define SEMMC_PERIOD_US_CTRL_VALIDITY 100000u
#define SEMMC_F_CTRL_VALIDITY_V_SPEED (1u << 0)
#define SEMMC_F_CTRL_VALIDITY_V_IA (1u << 1)
#define SEMMC_F_CTRL_VALIDITY_V_IB (1u << 2)
#define SEMMC_F_CTRL_VALIDITY_V_IC (1u << 3)
#define SEMMC_F_CTRL_VALIDITY_V_VBUS (1u << 4)
#define SEMMC_F_CTRL_VALIDITY_V_IBATT (1u << 5)
#define SEMMC_F_CTRL_VALIDITY_V_T_FET (1u << 6)
#define SEMMC_F_CTRL_VALIDITY_V_T_MOTOR (1u << 7)
#define SEMMC_F_CTRL_VALIDITY_V_THROTTLE (1u << 8)
#define SEMMC_F_CTRL_VALIDITY_V_SUP_REQ (1u << 9)
#define SEMMC_F_CTRL_VALIDITY_V_SUP_LIMITS (1u << 10)
#define SEMMC_F_CTRL_VALIDITY_V_HALL (1u << 11)
typedef struct {
    uint8_t seq;
    uint32_t v_speed;
    uint32_t v_ia;
    uint32_t v_ib;
    uint32_t v_ic;
    uint32_t v_vbus;
    uint32_t v_ibatt;
    uint32_t v_t_fet;
    uint32_t v_t_motor;
    uint32_t v_throttle;
    uint32_t v_sup_req;
    uint32_t v_sup_limits;
    uint32_t v_hall;
} semmc_ctrl_validity_t;
semmc_result_t semmc_encode_ctrl_validity(const semmc_ctrl_validity_t *m, uint8_t out[8]);
semmc_result_t semmc_decode_ctrl_validity(const uint8_t *in, uint8_t len, semmc_ctrl_validity_t *m);

/* ctrl_energy_quality - Completeness of ctrl_energy.energy_J. integrated_s is the time over which battery power was integrated; gap_s is the time NOT integrated because battery current or bus voltage was invalid, or because an update interval exceeded the integration limit. energy_J is complete only while gap_s is 0. */
#define SEMMC_ID_CTRL_ENERGY_QUALITY 0x323u
#define SEMMC_DATAID_CTRL_ENERGY_QUALITY 0x0B23u
#define SEMMC_PERIOD_US_CTRL_ENERGY_QUALITY 100000u
#define SEMMC_F_CTRL_ENERGY_QUALITY_INTEGRATED_S (1u << 0)
#define SEMMC_F_CTRL_ENERGY_QUALITY_GAP_S (1u << 1)
typedef struct {
    uint8_t seq;
    float integrated_s; /* s */
    float gap_s; /* s */
} semmc_ctrl_energy_quality_t;
semmc_result_t semmc_encode_ctrl_energy_quality(const semmc_ctrl_energy_quality_t *m, uint8_t out[8]);
semmc_result_t semmc_decode_ctrl_energy_quality(const uint8_t *in, uint8_t len, semmc_ctrl_energy_quality_t *m);

/* csia_advisory - CSIA vehicle-adapter advisory. v0.1 = SHADOW ONLY: the controller logs and re-reports it but never changes a command because of it (ADR-0008). */
#define SEMMC_ID_CSIA_ADVISORY 0x328u
#define SEMMC_DATAID_CSIA_ADVISORY 0x0B28u
#define SEMMC_PERIOD_US_CSIA_ADVISORY 100000u
#define SEMMC_F_CSIA_ADVISORY_TRUST (1u << 0)
#define SEMMC_F_CSIA_ADVISORY_MODE (1u << 1)
#define SEMMC_F_CSIA_ADVISORY_OBSERVABILITY (1u << 2)
#define SEMMC_F_CSIA_ADVISORY_MONITOR_OK (1u << 3)
#define SEMMC_F_CSIA_ADVISORY_EVIDENCE_FRESH (1u << 4)
#define SEMMC_F_CSIA_ADVISORY_RESERVED (1u << 5)
#define SEMMC_F_CSIA_ADVISORY_EVIDENCE_MASK (1u << 6)
#define SEMMC_F_CSIA_ADVISORY_EXPLANATION (1u << 7)
#define SEMMC_F_CSIA_ADVISORY_SRC_TIME_MS (1u << 8)
typedef struct {
    uint8_t seq;
    float trust; /* 1 */
    uint32_t mode;
    uint32_t observability;
    bool monitor_ok;
    bool evidence_fresh;
    uint32_t reserved;
    uint32_t evidence_mask;
    uint32_t explanation;
    uint32_t src_time_ms;
} semmc_csia_advisory_t;
semmc_result_t semmc_encode_csia_advisory(const semmc_csia_advisory_t *m, uint8_t out[8]);
semmc_result_t semmc_decode_csia_advisory(const uint8_t *in, uint8_t len, semmc_csia_advisory_t *m);

/* ctrl_identity - Protocol, firmware and calibration identity. */
#define SEMMC_ID_CTRL_IDENTITY 0x330u
#define SEMMC_DATAID_CTRL_IDENTITY 0x0B30u
#define SEMMC_PERIOD_US_CTRL_IDENTITY 1000000u
#define SEMMC_F_CTRL_IDENTITY_PROTO_MAJOR (1u << 0)
#define SEMMC_F_CTRL_IDENTITY_PROTO_MINOR (1u << 1)
#define SEMMC_F_CTRL_IDENTITY_FW_MAJOR (1u << 2)
#define SEMMC_F_CTRL_IDENTITY_FW_MINOR (1u << 3)
#define SEMMC_F_CTRL_IDENTITY_CAL_VERSION (1u << 4)
#define SEMMC_F_CTRL_IDENTITY_CAL_PROVENANCE (1u << 5)
#define SEMMC_F_CTRL_IDENTITY_BUILD_IS_SIM (1u << 6)
#define SEMMC_F_CTRL_IDENTITY_HW_REV (1u << 7)
typedef struct {
    uint8_t seq;
    uint32_t proto_major;
    uint32_t proto_minor;
    uint32_t fw_major;
    uint32_t fw_minor;
    uint32_t cal_version;
    uint32_t cal_provenance;
    bool build_is_sim;
    uint32_t hw_rev;
} semmc_ctrl_identity_t;
semmc_result_t semmc_encode_ctrl_identity(const semmc_ctrl_identity_t *m, uint8_t out[8]);
semmc_result_t semmc_decode_ctrl_identity(const uint8_t *in, uint8_t len, semmc_ctrl_identity_t *m);

#endif /* SEMMC_PROTOCOL_H */

/* Calibration blob loader and configuration validator.
 *
 * The blob is produced by tools/config_tool.py from a vehicle.*.yaml file.
 * Format v1 (little endian):
 *   0  "SMCB" magic | u16 format_version | u16 schema_version | u8 provenance |
 *      u8 flags | u16 n_entries | char cal_id[16] | u32 cal_version   (32 bytes)
 *   32 n_entries x { u16 id | u8 kind | u8 reserved | f32 value }    (8 bytes each)
 *   .. u32 CRC-32 (zlib) over all preceding bytes
 * Absent ids are unknown (null). Unknown ids, duplicates, length or CRC
 * mismatch reject the whole blob.
 *
 * mc_config_validate() applies the same rule set as tools/config_tool.py
 * (rule codes are shared; see MC_CFG_E_*). It runs once at boot, not in any
 * control loop, and computes in double precision for exact parity with the
 * Python validator.
 */
#ifndef SEMMC_MC_CONFIG_H
#define SEMMC_MC_CONFIG_H

#include "semmc/mc_params_generated.h"
#include "semmc/mc_types.h"

#define MC_CFG_BLOB_FORMAT_VERSION 1u
#define MC_CFG_MAX_ISSUES 48u

/* Stable rule codes (mirror tools/config_tool.py E{}). */
enum {
    MC_CFG_E_MISSING_REQUIRED = 1,
    MC_CFG_E_NONFINITE = 2,
    MC_CFG_E_OUT_OF_RANGE = 3,
    MC_CFG_E_NOT_INTEGER = 4,
    MC_CFG_E_BAD_ENUM = 5,
    MC_CFG_E_BLOB_FORMAT = 6,
    MC_CFG_E_BATT_VOLTAGE_ORDER = 10,
    MC_CFG_E_CELL_VOLTAGE_IMPLAUSIBLE = 11,
    MC_CFG_E_BUS_RATING_MARGIN = 12,
    MC_CFG_E_OV_TRIP_RANGE = 13,
    MC_CFG_E_UV_ORDER = 14,
    MC_CFG_E_CURRENT_TRIP_ORDER = 15,
    MC_CFG_E_CURRENT_SENSE_RANGE = 16,
    MC_CFG_E_BATT_CURRENT_LIMIT = 17,
    MC_CFG_E_REGEN_DEFERRED = 18,
    MC_CFG_E_TORQUE_LIMIT_ORDER = 19,
    MC_CFG_E_TORQUE_UNACHIEVABLE = 20,
    MC_CFG_E_SPEED_ORDER = 21,
    MC_CFG_E_BACKEMF_EXCEEDS_MIN_BUS = 22,
    MC_CFG_E_BACKEMF_EXCEEDS_RATING = 23,
    MC_CFG_E_TEMP_ORDER = 24,
    MC_CFG_E_SLEW_ORDER = 25,
    MC_CFG_E_THROTTLE_THRESH_ORDER = 26,
    MC_CFG_E_DUTY_ORDER = 27,
    MC_CFG_E_SUPERVISION_TIMING = 28,
    MC_CFG_E_SUPERVISION_NOT_HAZARD_ANALYSED = 29,
    MC_CFG_E_ARCH_MOTOR_TYPE = 30,
    MC_CFG_E_ROTOR_SENSOR_UNSUPPORTED = 31,
    MC_CFG_E_HALL_TABLE = 32,
    MC_CFG_E_PROVENANCE = 33,
    MC_CFG_E_CURRENT_LOOP_BANDWIDTH = 34,
    MC_CFG_E_DEADTIME_TOO_LONG = 35,
    MC_CFG_E_PHASE_CURRENT_RMS_PEAK = 36,
    MC_CFG_E_VBUS_SENSE_RANGE = 37
};

typedef enum { MC_CFG_MODE_SIM = 0, MC_CFG_MODE_HW = 1 } mc_cfg_mode_t;

typedef struct {
    uint8_t code;
    uint8_t param_id; /* 0 when the rule spans several parameters */
} mc_cfg_issue_t;

typedef struct {
    uint16_t count;               /* total issues found (may exceed stored) */
    mc_cfg_issue_t items[MC_CFG_MAX_ISSUES];
    uint32_t codes_seen[4];       /* bitset of codes 0..127 */
} mc_cfg_report_t;

typedef struct {
    uint16_t schema_version;
    uint8_t provenance;
    char cal_id[16];
    uint32_t cal_version;
    uint32_t present[8];          /* bitset over ids 0..255 */
    float value[256];
} mc_config_t;

/* Typed parameters used by the control core, produced only from a config
 * that passed validation. */
typedef struct {
    /* motor */
    int pole_pairs;
    float rs_ohm, ld_H, lq_H, lambda_Wb, kt_Nm_per_A;
    float max_mech_speed_rad_s, inertia_kg_m2;
    int8_t hall_code_to_sector[8];
    float hall_angle_offset_rad;
    /* battery */
    float vbatt_min_V, vbatt_nom_V, vbatt_max_V;
    /* vehicle */
    float mass_kg, gear_ratio, wheel_circumference_m, drivetrain_eff;
    bool freewheel_present;
    /* inverter */
    float pwm_frequency_Hz, deadtime_s, duty_min, duty_max;
    float shunt_ohm, amp_gain, adc_vref_V, adc_full_scale_counts;
    float current_offset_counts[3];
    float vbus_divider_ratio;
    float hw_overcurrent_trip_A;
    float fet_derate_start_degC, fet_trip_degC;
    float current_kp, current_ki;
    /* limits */
    float max_motor_torque_Nm, manual_max_torque_Nm, max_phase_current_A;
    float battery_current_limit_A, min_efficiency_for_limit;
    bool regen_enabled;
    float overspeed_trip_rad_s, speed_taper_start_rad_s;
    float uv_derate_V, uv_trip_V, ov_trip_V;
    float motor_derate_start_degC, motor_trip_degC;
    float slew_up_Nm_s, slew_down_Nm_s, slew_down_fast_Nm_s;
    float unknown_temp_derate_factor;
    float throttle_release, throttle_engage;
    float sw_overcurrent_A;
    uint8_t coast_mode;
    /* supervision */
    float sup_period_s, sup_timeout_s, sup_limits_timeout_s;
    uint8_t timing_status;
    /* identity */
    uint8_t provenance;
    bool physical_output_permitted;
    uint32_t cal_version;
} mc_params_t;

void mc_cfg_report_clear(mc_cfg_report_t *rep);
bool mc_cfg_report_has(const mc_cfg_report_t *rep, uint8_t code);

/* Parse a blob. Returns true on success. On failure reports MC_CFG_E_BLOB_FORMAT
 * and leaves *out zeroed (no partial configuration is ever usable). */
bool mc_config_parse_blob(const uint8_t *blob, size_t len, mc_config_t *out, mc_cfg_report_t *rep);

bool mc_config_has(const mc_config_t *cfg, uint8_t id);
float mc_config_get(const mc_config_t *cfg, uint8_t id); /* NaN if absent */

/* Returns true when no issues were found for the mode. */
bool mc_config_validate(const mc_config_t *cfg, mc_cfg_mode_t mode, mc_cfg_report_t *rep);

/* Fill typed parameters. Precondition: mc_config_validate(cfg, MODE_SIM or HW) passed. */
bool mc_config_derive(const mc_config_t *cfg, mc_params_t *p);

/* The ONLY gate for enabling a physical power-stage output:
 * hardware build AND hardware-mode validation clean AND bench-measured
 * provenance AND explicit physical_output_permitted. A host simulation build
 * always returns false (there is no physical output to enable). */
bool mc_config_permits_physical_output(const mc_config_t *cfg, mc_build_kind_t build);

#endif /* SEMMC_MC_CONFIG_H */

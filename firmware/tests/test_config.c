/* Calibration blob parsing and configuration validation (C side). */
#include <math.h>
#include <string.h>

#include "mc_test.h"
#include "semmc/mc_crc.h"
#include "test_support.h"

static uint8_t g_blob[8192];
static size_t g_len;

static void test_crc_check_values(void)
{
    const uint8_t s[] = "123456789";
    CHECK_EQ_INT(mc_crc8_j1850(s, 9), 0x4B);
    CHECK(mc_crc32(s, 9) == 0xCBF43926u);
}

static void test_synthetic_valid_for_sim_only(void)
{
    mc_config_t cfg;
    mc_cfg_report_t rep;
    mc_cfg_report_clear(&rep);
    CHECK(mc_config_parse_blob(g_blob, g_len, &cfg, &rep));
    CHECK(mc_config_validate(&cfg, MC_CFG_MODE_SIM, &rep));
    mc_cfg_report_clear(&rep);
    CHECK(!mc_config_validate(&cfg, MC_CFG_MODE_HW, &rep));
    CHECK(mc_cfg_report_has(&rep, MC_CFG_E_PROVENANCE));
    CHECK(mc_cfg_report_has(&rep, MC_CFG_E_SUPERVISION_NOT_HAZARD_ANALYSED));
    /* Synthetic configuration can never enable a physical output. */
    CHECK(!mc_config_permits_physical_output(&cfg, MC_BUILD_HARDWARE));
    CHECK(!mc_config_permits_physical_output(&cfg, MC_BUILD_HOST_SIM));
}

static void test_synthetic_cannot_claim_physical_output(void)
{
    mc_config_t cfg;
    mc_cfg_report_t rep;
    mc_cfg_report_clear(&rep);
    CHECK(mc_config_parse_blob(g_blob, g_len, &cfg, &rep));
    cfg.value[MC_P_CALIBRATION_PHYSICAL_OUTPUT_PERMITTED] = 1.0f;
    CHECK(!mc_config_validate(&cfg, MC_CFG_MODE_SIM, &rep));
    CHECK(mc_cfg_report_has(&rep, MC_CFG_E_PROVENANCE));
}

static void test_unconfigured_rejected(void)
{
    static uint8_t buf[8192];
    const size_t n = load_blob(SEMMC_UNCONF_BLOB, buf, sizeof buf);
    mc_config_t cfg;
    mc_cfg_report_t rep;
    mc_cfg_report_clear(&rep);
    CHECK(mc_config_parse_blob(buf, n, &cfg, &rep));
    CHECK(!mc_config_validate(&cfg, MC_CFG_MODE_HW, &rep));
    CHECK(mc_cfg_report_has(&rep, MC_CFG_E_MISSING_REQUIRED));
    mc_params_t p;
    CHECK(!mc_config_derive(&cfg, &p));
}

static void test_blob_corruption_rejected(void)
{
    mc_config_t cfg;
    mc_cfg_report_t rep;
    static uint8_t b[8192];
    for (size_t k = 0; k < g_len; k += 7) {
        memcpy(b, g_blob, g_len);
        b[k] ^= 0x10u;
        mc_cfg_report_clear(&rep);
        CHECK(!mc_config_parse_blob(b, g_len, &cfg, &rep));
        CHECK(mc_cfg_report_has(&rep, MC_CFG_E_BLOB_FORMAT));
    }
    mc_cfg_report_clear(&rep);
    CHECK(!mc_config_parse_blob(g_blob, g_len - 1u, &cfg, &rep)); /* truncated */
    CHECK(!mc_config_parse_blob(NULL, 0u, &cfg, &rep));
}

static void mutate_expect(uint8_t id, float v, uint8_t code)
{
    mc_config_t cfg;
    mc_cfg_report_t rep;
    mc_cfg_report_clear(&rep);
    CHECK(mc_config_parse_blob(g_blob, g_len, &cfg, &rep));
    cfg.value[id] = v;
    CHECK(!mc_config_validate(&cfg, MC_CFG_MODE_SIM, &rep));
    if (!mc_cfg_report_has(&rep, code)) {
        fprintf(stderr, "  id %u value %g: expected code %u\n", id, (double)v, code);
        CHECK(0);
    }
}

static void test_rule_violations(void)
{
    mutate_expect(MC_P_MOTOR_PHASE_RESISTANCE_OHM, NAN, MC_CFG_E_NONFINITE);
    mutate_expect(MC_P_MOTOR_PHASE_RESISTANCE_OHM, INFINITY, MC_CFG_E_NONFINITE);
    mutate_expect(MC_P_MOTOR_D_INDUCTANCE_H, 150.0f, MC_CFG_E_OUT_OF_RANGE); /* uH typed as H */
    mutate_expect(MC_P_MOTOR_POLE_PAIRS, 4.5f, MC_CFG_E_NOT_INTEGER);
    mutate_expect(MC_P_MOTOR_TYPE, 9.0f, MC_CFG_E_BAD_ENUM);
    mutate_expect(MC_P_MOTOR_TYPE, (float)MC_MOTOR_TYPE_BRUSHED_DC, MC_CFG_E_ARCH_MOTOR_TYPE);
    mutate_expect(MC_P_BATTERY_NOMINAL_VOLTAGE_V, 60.0f, MC_CFG_E_BATT_VOLTAGE_ORDER);
    mutate_expect(MC_P_INVERTER_BUS_VOLTAGE_RATING_V, 55.0f, MC_CFG_E_BUS_RATING_MARGIN);
    mutate_expect(MC_P_INVERTER_HW_OVERCURRENT_TRIP_A, 50.0f, MC_CFG_E_CURRENT_TRIP_ORDER);
    mutate_expect(MC_P_INVERTER_HW_OVERCURRENT_TRIP_A, 90.0f, MC_CFG_E_CURRENT_SENSE_RANGE);
    mutate_expect(MC_P_LIMITS_BATTERY_CURRENT_LIMIT_A, 45.0f, MC_CFG_E_BATT_CURRENT_LIMIT);
    mutate_expect(MC_P_LIMITS_REGEN_ENABLED, 1.0f, MC_CFG_E_REGEN_DEFERRED);
    mutate_expect(MC_P_LIMITS_MAX_MOTOR_TORQUE_NM, 5.0f, MC_CFG_E_TORQUE_UNACHIEVABLE);
    mutate_expect(MC_P_MOTOR_FLUX_LINKAGE_WB, 0.02f, MC_CFG_E_BACKEMF_EXCEEDS_MIN_BUS);
    mutate_expect(MC_P_LIMITS_MOTOR_TEMP_TRIP_DEGC, 130.0f, MC_CFG_E_TEMP_ORDER);
    mutate_expect(MC_P_SUPERVISION_TIMEOUT_S, 0.03f, MC_CFG_E_SUPERVISION_TIMING);
    mutate_expect(MC_P_MOTOR_HALL_CODE_TO_SECTOR_0, 0.0f, MC_CFG_E_HALL_TABLE);
    mutate_expect(MC_P_INVERTER_CURRENT_KP_V_PER_A, 5.0f, MC_CFG_E_CURRENT_LOOP_BANDWIDTH);
    mutate_expect(MC_P_INVERTER_DEADTIME_S, 3.0e-6f, MC_CFG_E_DEADTIME_TOO_LONG);
    mutate_expect(MC_P_INVERTER_VBUS_DIVIDER_RATIO, 10.0f, MC_CFG_E_VBUS_SENSE_RANGE);
    mutate_expect(MC_P_LIMITS_TORQUE_SLEW_DOWN_FAST_NM_S, 15.0f, MC_CFG_E_ENVELOPE_RAMP_DEADLINE);
}

static void test_missing_required(void)
{
    mc_config_t cfg;
    mc_cfg_report_t rep;
    mc_cfg_report_clear(&rep);
    CHECK(mc_config_parse_blob(g_blob, g_len, &cfg, &rep));
    cfg.present[MC_P_MOTOR_FLUX_LINKAGE_WB / 32u] &= ~(1u << (MC_P_MOTOR_FLUX_LINKAGE_WB % 32u));
    CHECK(!mc_config_validate(&cfg, MC_CFG_MODE_SIM, &rep));
    CHECK(mc_cfg_report_has(&rep, MC_CFG_E_MISSING_REQUIRED));
    CHECK(rep.items[0].param_id == MC_P_MOTOR_FLUX_LINKAGE_WB);
}

int main(void)
{
    g_len = load_blob(SEMMC_SYNTH_BLOB, g_blob, sizeof g_blob);
    RUN(test_crc_check_values);
    RUN(test_synthetic_valid_for_sim_only);
    RUN(test_synthetic_cannot_claim_physical_output);
    RUN(test_unconfigured_rejected);
    RUN(test_blob_corruption_rejected);
    RUN(test_rule_violations);
    RUN(test_missing_required);
    TEST_MAIN_END();
}

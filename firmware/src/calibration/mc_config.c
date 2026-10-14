/* Calibration blob parser and configuration validator. Runs at boot only. */
#include "semmc/mc_config.h"

#include <math.h>
#include <string.h>

#include "semmc/mc_crc.h"

#define MC_PI_D 3.141592653589793

static const mc_param_info_t k_params[MC_PARAM_COUNT] = MC_PARAM_TABLE_INIT;

static const mc_param_info_t *find_param(uint16_t id)
{
    for (size_t i = 0; i < MC_PARAM_COUNT; i++) {
        if (k_params[i].id == id) return &k_params[i];
    }
    return NULL;
}

void mc_cfg_report_clear(mc_cfg_report_t *rep)
{
    memset(rep, 0, sizeof(*rep));
}

static void report(mc_cfg_report_t *rep, uint8_t code, uint8_t param_id)
{
    if (rep == NULL) return;
    if (rep->count < MC_CFG_MAX_ISSUES) {
        rep->items[rep->count].code = code;
        rep->items[rep->count].param_id = param_id;
    }
    if (rep->count < UINT16_MAX) rep->count++;
    if (code < 128u) rep->codes_seen[code / 32u] |= (1u << (code % 32u));
}

bool mc_cfg_report_has(const mc_cfg_report_t *rep, uint8_t code)
{
    return code < 128u && (rep->codes_seen[code / 32u] & (1u << (code % 32u))) != 0u;
}

static uint16_t rd16(const uint8_t *p) { return (uint16_t)(p[0] | (p[1] << 8)); }
static uint32_t rd32(const uint8_t *p)
{
    return (uint32_t)p[0] | ((uint32_t)p[1] << 8) | ((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 24);
}
static float rdf32(const uint8_t *p)
{
    uint32_t u = rd32(p);
    float f;
    memcpy(&f, &u, sizeof f);
    return f;
}

bool mc_config_has(const mc_config_t *cfg, uint8_t id)
{
    return (cfg->present[id / 32u] & (1u << (id % 32u))) != 0u;
}

float mc_config_get(const mc_config_t *cfg, uint8_t id)
{
    return mc_config_has(cfg, id) ? cfg->value[id] : NAN;
}

bool mc_config_parse_blob(const uint8_t *blob, size_t len, mc_config_t *out, mc_cfg_report_t *rep)
{
    memset(out, 0, sizeof(*out));
    if (blob == NULL || len < 36u) goto fail;
    if (mc_crc32(blob, len - 4u) != rd32(blob + len - 4u)) goto fail;
    if (memcmp(blob, "SMCB", 4) != 0) goto fail;
    if (rd16(blob + 4) != MC_CFG_BLOB_FORMAT_VERSION) goto fail;
    {
        const uint16_t n = rd16(blob + 10);
        if (len != 32u + (size_t)n * 8u + 4u) goto fail;
        mc_config_t tmp;
        memset(&tmp, 0, sizeof tmp);
        tmp.schema_version = rd16(blob + 6);
        tmp.provenance = blob[8];
        memcpy(tmp.cal_id, blob + 12, 15);
        tmp.cal_id[15] = '\0';
        tmp.cal_version = rd32(blob + 28);
        for (uint16_t i = 0; i < n; i++) {
            const uint8_t *e = blob + 32u + (size_t)i * 8u;
            const uint16_t id = rd16(e);
            const mc_param_info_t *info = find_param(id);
            if (info == NULL || info->kind != e[2] || id > 255u) goto fail;
            if (mc_config_has(&tmp, (uint8_t)id)) goto fail; /* duplicate */
            tmp.present[id / 32u] |= (1u << (id % 32u));
            tmp.value[id] = rdf32(e + 4);
        }
        *out = tmp;
        return true;
    }
fail:
    memset(out, 0, sizeof(*out));
    report(rep, MC_CFG_E_BLOB_FORMAT, 0);
    return false;
}

/* ---- validation ---------------------------------------------------------- */

typedef struct {
    const mc_config_t *cfg;
    uint32_t ok[8]; /* ids that passed per-parameter checks */
} vctx_t;

static bool ok1(const vctx_t *c, uint8_t id) { return (c->ok[id / 32u] & (1u << (id % 32u))) != 0u; }
static double g(const vctx_t *c, uint8_t id) { return (double)c->cfg->value[id]; }

#define HAVE2(a, b) (ok1(c, a) && ok1(c, b))
#define HAVE3(a, b, x) (HAVE2(a, b) && ok1(c, x))
#define HAVE4(a, b, x, y) (HAVE3(a, b, x) && ok1(c, y))

static void cross_rules(const vctx_t *c, mc_cfg_mode_t mode, mc_cfg_report_t *rep)
{
    /* R20 provenance / physical output */
    if (HAVE2(MC_P_CALIBRATION_PROVENANCE, MC_P_CALIBRATION_PHYSICAL_OUTPUT_PERMITTED)) {
        const int prov = (int)g(c, MC_P_CALIBRATION_PROVENANCE);
        const double phys = g(c, MC_P_CALIBRATION_PHYSICAL_OUTPUT_PERMITTED);
        if (prov == MC_PROVENANCE_SYNTHETIC && phys != 0.0) report(rep, MC_CFG_E_PROVENANCE, MC_P_CALIBRATION_PHYSICAL_OUTPUT_PERMITTED);
        if (mode == MC_CFG_MODE_HW && prov != MC_PROVENANCE_BENCH_MEASURED) report(rep, MC_CFG_E_PROVENANCE, MC_P_CALIBRATION_PROVENANCE);
        if (mode == MC_CFG_MODE_HW && phys != 1.0) report(rep, MC_CFG_E_PROVENANCE, MC_P_CALIBRATION_PHYSICAL_OUTPUT_PERMITTED);
    }
    /* R1, R2 */
    if (HAVE3(MC_P_BATTERY_MIN_VOLTAGE_V, MC_P_BATTERY_NOMINAL_VOLTAGE_V, MC_P_BATTERY_MAX_CHARGED_VOLTAGE_V)) {
        const double vmin = g(c, MC_P_BATTERY_MIN_VOLTAGE_V), vnom = g(c, MC_P_BATTERY_NOMINAL_VOLTAGE_V);
        const double vmax = g(c, MC_P_BATTERY_MAX_CHARGED_VOLTAGE_V);
        if (!(vmin < vnom && vnom < vmax)) report(rep, MC_CFG_E_BATT_VOLTAGE_ORDER, 0);
        if (ok1(c, MC_P_BATTERY_SERIES_CELLS)) {
            const double n = g(c, MC_P_BATTERY_SERIES_CELLS);
            if (!(2.0 <= vmax / n && vmax / n <= 4.5 && 1.5 <= vmin / n && vmin / n <= 4.3))
                report(rep, MC_CFG_E_CELL_VOLTAGE_IMPLAUSIBLE, MC_P_BATTERY_SERIES_CELLS);
        }
    }
    /* R3 */
    if (HAVE3(MC_P_BATTERY_MAX_CHARGED_VOLTAGE_V, MC_P_INVERTER_TRANSIENT_MARGIN_FRACTION, MC_P_INVERTER_BUS_VOLTAGE_RATING_V)) {
        const double need = g(c, MC_P_BATTERY_MAX_CHARGED_VOLTAGE_V) * (1.0 + g(c, MC_P_INVERTER_TRANSIENT_MARGIN_FRACTION));
        if (need > g(c, MC_P_INVERTER_BUS_VOLTAGE_RATING_V)) report(rep, MC_CFG_E_BUS_RATING_MARGIN, MC_P_INVERTER_BUS_VOLTAGE_RATING_V);
    }
    /* R4 */
    if (HAVE3(MC_P_LIMITS_OVERVOLTAGE_TRIP_V, MC_P_BATTERY_MAX_CHARGED_VOLTAGE_V, MC_P_INVERTER_BUS_VOLTAGE_RATING_V)) {
        const double ov = g(c, MC_P_LIMITS_OVERVOLTAGE_TRIP_V);
        if (!(g(c, MC_P_BATTERY_MAX_CHARGED_VOLTAGE_V) < ov && ov <= g(c, MC_P_INVERTER_BUS_VOLTAGE_RATING_V)))
            report(rep, MC_CFG_E_OV_TRIP_RANGE, MC_P_LIMITS_OVERVOLTAGE_TRIP_V);
    }
    /* R5 */
    if (HAVE4(MC_P_LIMITS_UNDERVOLTAGE_TRIP_V, MC_P_LIMITS_UNDERVOLTAGE_DERATE_V, MC_P_BATTERY_MIN_VOLTAGE_V, MC_P_BATTERY_NOMINAL_VOLTAGE_V)) {
        const double uvt = g(c, MC_P_LIMITS_UNDERVOLTAGE_TRIP_V), uvd = g(c, MC_P_LIMITS_UNDERVOLTAGE_DERATE_V);
        if (!(g(c, MC_P_BATTERY_MIN_VOLTAGE_V) <= uvt && uvt <= uvd && uvd <= g(c, MC_P_BATTERY_NOMINAL_VOLTAGE_V)))
            report(rep, MC_CFG_E_UV_ORDER, 0);
    }
    /* R6 */
    if (HAVE4(MC_P_LIMITS_MAX_PHASE_CURRENT_A, MC_P_MOTOR_PEAK_PHASE_CURRENT_A, MC_P_LIMITS_SOFTWARE_OVERCURRENT_A, MC_P_INVERTER_HW_OVERCURRENT_TRIP_A)) {
        const double imax = g(c, MC_P_LIMITS_MAX_PHASE_CURRENT_A), ipk = g(c, MC_P_MOTOR_PEAK_PHASE_CURRENT_A);
        const double isw = g(c, MC_P_LIMITS_SOFTWARE_OVERCURRENT_A), ihw = g(c, MC_P_INVERTER_HW_OVERCURRENT_TRIP_A);
        if (!(imax <= ipk && imax < isw && isw < ihw)) report(rep, MC_CFG_E_CURRENT_TRIP_ORDER, 0);
    }
    if (HAVE4(MC_P_INVERTER_HW_OVERCURRENT_TRIP_A, MC_P_INVERTER_ADC_VREF_V, MC_P_INVERTER_AMP_GAIN_V_PER_V, MC_P_INVERTER_SHUNT_OHM)) {
        const double i_fs = 0.5 * g(c, MC_P_INVERTER_ADC_VREF_V) / (g(c, MC_P_INVERTER_AMP_GAIN_V_PER_V) * g(c, MC_P_INVERTER_SHUNT_OHM));
        if (g(c, MC_P_INVERTER_HW_OVERCURRENT_TRIP_A) >= i_fs) report(rep, MC_CFG_E_CURRENT_SENSE_RANGE, MC_P_INVERTER_HW_OVERCURRENT_TRIP_A);
    }
    /* R7 */
    if (HAVE2(MC_P_LIMITS_BATTERY_CURRENT_LIMIT_A, MC_P_BATTERY_BMS_MAX_DISCHARGE_CURRENT_A)) {
        if (g(c, MC_P_LIMITS_BATTERY_CURRENT_LIMIT_A) > g(c, MC_P_BATTERY_BMS_MAX_DISCHARGE_CURRENT_A))
            report(rep, MC_CFG_E_BATT_CURRENT_LIMIT, MC_P_LIMITS_BATTERY_CURRENT_LIMIT_A);
    }
    /* R8 */
    if (ok1(c, MC_P_LIMITS_REGEN_ENABLED) && g(c, MC_P_LIMITS_REGEN_ENABLED) != 0.0)
        report(rep, MC_CFG_E_REGEN_DEFERRED, MC_P_LIMITS_REGEN_ENABLED);
    /* R9 */
    if (HAVE2(MC_P_LIMITS_MANUAL_MAX_TORQUE_NM, MC_P_LIMITS_MAX_MOTOR_TORQUE_NM)) {
        if (g(c, MC_P_LIMITS_MANUAL_MAX_TORQUE_NM) > g(c, MC_P_LIMITS_MAX_MOTOR_TORQUE_NM))
            report(rep, MC_CFG_E_TORQUE_LIMIT_ORDER, MC_P_LIMITS_MANUAL_MAX_TORQUE_NM);
    }
    if (HAVE4(MC_P_LIMITS_MAX_MOTOR_TORQUE_NM, MC_P_MOTOR_POLE_PAIRS, MC_P_MOTOR_FLUX_LINKAGE_WB, MC_P_LIMITS_MAX_PHASE_CURRENT_A)) {
        const double kt = 1.5 * g(c, MC_P_MOTOR_POLE_PAIRS) * g(c, MC_P_MOTOR_FLUX_LINKAGE_WB);
        if (g(c, MC_P_LIMITS_MAX_MOTOR_TORQUE_NM) > kt * g(c, MC_P_LIMITS_MAX_PHASE_CURRENT_A) * 1.0001)
            report(rep, MC_CFG_E_TORQUE_UNACHIEVABLE, MC_P_LIMITS_MAX_MOTOR_TORQUE_NM);
    }
    /* R10 */
    if (HAVE4(MC_P_MOTOR_RATED_MECH_SPEED_RAD_S, MC_P_MOTOR_MAX_MECH_SPEED_RAD_S, MC_P_LIMITS_OVERSPEED_TRIP_RAD_S, MC_P_LIMITS_SPEED_TAPER_START_RAD_S)) {
        const double rated = g(c, MC_P_MOTOR_RATED_MECH_SPEED_RAD_S), wmax = g(c, MC_P_MOTOR_MAX_MECH_SPEED_RAD_S);
        const double trip = g(c, MC_P_LIMITS_OVERSPEED_TRIP_RAD_S), taper = g(c, MC_P_LIMITS_SPEED_TAPER_START_RAD_S);
        if (!(rated <= wmax && taper < trip && trip <= wmax)) report(rep, MC_CFG_E_SPEED_ORDER, 0);
    }
    /* R11 */
    if (HAVE4(MC_P_MOTOR_FLUX_LINKAGE_WB, MC_P_MOTOR_POLE_PAIRS, MC_P_LIMITS_OVERSPEED_TRIP_RAD_S, MC_P_BATTERY_MIN_VOLTAGE_V)) {
        const double e_ll = sqrt(3.0) * g(c, MC_P_MOTOR_FLUX_LINKAGE_WB) * g(c, MC_P_MOTOR_POLE_PAIRS) * g(c, MC_P_LIMITS_OVERSPEED_TRIP_RAD_S);
        if (e_ll >= g(c, MC_P_BATTERY_MIN_VOLTAGE_V)) report(rep, MC_CFG_E_BACKEMF_EXCEEDS_MIN_BUS, MC_P_LIMITS_OVERSPEED_TRIP_RAD_S);
    }
    if (HAVE4(MC_P_MOTOR_FLUX_LINKAGE_WB, MC_P_MOTOR_POLE_PAIRS, MC_P_MOTOR_MAX_MECH_SPEED_RAD_S, MC_P_INVERTER_BUS_VOLTAGE_RATING_V)) {
        const double e_ll = sqrt(3.0) * g(c, MC_P_MOTOR_FLUX_LINKAGE_WB) * g(c, MC_P_MOTOR_POLE_PAIRS) * g(c, MC_P_MOTOR_MAX_MECH_SPEED_RAD_S);
        if (e_ll >= g(c, MC_P_INVERTER_BUS_VOLTAGE_RATING_V)) report(rep, MC_CFG_E_BACKEMF_EXCEEDS_RATING, MC_P_MOTOR_MAX_MECH_SPEED_RAD_S);
    }
    /* R12 */
    {
        bool bad = false;
        if (HAVE2(MC_P_INVERTER_FET_TEMP_DERATE_START_DEGC, MC_P_INVERTER_FET_TEMP_TRIP_DEGC))
            bad |= !(g(c, MC_P_INVERTER_FET_TEMP_DERATE_START_DEGC) < g(c, MC_P_INVERTER_FET_TEMP_TRIP_DEGC));
        if (HAVE3(MC_P_LIMITS_MOTOR_TEMP_DERATE_START_DEGC, MC_P_LIMITS_MOTOR_TEMP_TRIP_DEGC, MC_P_MOTOR_MAX_WINDING_TEMP_DEGC))
            bad |= !(g(c, MC_P_LIMITS_MOTOR_TEMP_DERATE_START_DEGC) < g(c, MC_P_LIMITS_MOTOR_TEMP_TRIP_DEGC) &&
                     g(c, MC_P_LIMITS_MOTOR_TEMP_TRIP_DEGC) <= g(c, MC_P_MOTOR_MAX_WINDING_TEMP_DEGC));
        if (bad) report(rep, MC_CFG_E_TEMP_ORDER, 0);
    }
    /* R13..R15 */
    if (HAVE2(MC_P_LIMITS_TORQUE_SLEW_DOWN_FAST_NM_S, MC_P_LIMITS_TORQUE_SLEW_DOWN_NM_S) &&
        g(c, MC_P_LIMITS_TORQUE_SLEW_DOWN_FAST_NM_S) < g(c, MC_P_LIMITS_TORQUE_SLEW_DOWN_NM_S))
        report(rep, MC_CFG_E_SLEW_ORDER, MC_P_LIMITS_TORQUE_SLEW_DOWN_FAST_NM_S);
    if (HAVE2(MC_P_LIMITS_THROTTLE_RELEASE_THRESHOLD, MC_P_LIMITS_THROTTLE_ENGAGE_THRESHOLD) &&
        !(g(c, MC_P_LIMITS_THROTTLE_RELEASE_THRESHOLD) < g(c, MC_P_LIMITS_THROTTLE_ENGAGE_THRESHOLD)))
        report(rep, MC_CFG_E_THROTTLE_THRESH_ORDER, 0);
    if (HAVE2(MC_P_INVERTER_DUTY_MIN, MC_P_INVERTER_DUTY_MAX) &&
        !(g(c, MC_P_INVERTER_DUTY_MIN) < g(c, MC_P_INVERTER_DUTY_MAX)))
        report(rep, MC_CFG_E_DUTY_ORDER, 0);
    /* R16 */
    if (HAVE2(MC_P_SUPERVISION_TIMEOUT_S, MC_P_SUPERVISION_UPDATE_PERIOD_S) &&
        g(c, MC_P_SUPERVISION_TIMEOUT_S) < 2.0 * g(c, MC_P_SUPERVISION_UPDATE_PERIOD_S))
        report(rep, MC_CFG_E_SUPERVISION_TIMING, MC_P_SUPERVISION_TIMEOUT_S);
    if (mode == MC_CFG_MODE_HW && ok1(c, MC_P_SUPERVISION_TIMING_STATUS) &&
        (int)g(c, MC_P_SUPERVISION_TIMING_STATUS) != MC_TIMING_STATUS_HAZARD_ANALYSED)
        report(rep, MC_CFG_E_SUPERVISION_NOT_HAZARD_ANALYSED, MC_P_SUPERVISION_TIMING_STATUS);
    /* R17, R18 */
    if (ok1(c, MC_P_MOTOR_TYPE) && (int)g(c, MC_P_MOTOR_TYPE) != MC_MOTOR_TYPE_PMSM_SINUSOIDAL)
        report(rep, MC_CFG_E_ARCH_MOTOR_TYPE, MC_P_MOTOR_TYPE);
    if (ok1(c, MC_P_MOTOR_ROTOR_SENSOR) && (int)g(c, MC_P_MOTOR_ROTOR_SENSOR) != MC_ROTOR_SENSOR_HALL)
        report(rep, MC_CFG_E_ROTOR_SENSOR_UNSUPPORTED, MC_P_MOTOR_ROTOR_SENSOR);
    /* R19 */
    {
        bool all = true;
        for (uint8_t k = 0; k < 8u; k++) all = all && ok1(c, (uint8_t)(MC_P_MOTOR_HALL_CODE_TO_SECTOR_0 + k));
        if (all) {
            int seen[6] = {0, 0, 0, 0, 0, 0};
            bool bad = (int)g(c, MC_P_MOTOR_HALL_CODE_TO_SECTOR_0) != -1 || (int)g(c, MC_P_MOTOR_HALL_CODE_TO_SECTOR_7) != -1;
            for (uint8_t k = 0; k < 8u; k++) {
                const int s = (int)g(c, (uint8_t)(MC_P_MOTOR_HALL_CODE_TO_SECTOR_0 + k));
                if (s >= 0 && s <= 5) seen[s]++;
            }
            for (int s = 0; s < 6; s++) bad = bad || seen[s] != 1;
            if (bad) report(rep, MC_CFG_E_HALL_TABLE, MC_P_MOTOR_HALL_CODE_TO_SECTOR_0);
        }
    }
    /* R21 */
    if (HAVE4(MC_P_INVERTER_CURRENT_KP_V_PER_A, MC_P_MOTOR_Q_INDUCTANCE_H, MC_P_MOTOR_D_INDUCTANCE_H, MC_P_INVERTER_PWM_FREQUENCY_HZ)) {
        const double lq = g(c, MC_P_MOTOR_Q_INDUCTANCE_H), ld = g(c, MC_P_MOTOR_D_INDUCTANCE_H);
        const double lmin = lq < ld ? lq : ld;
        const double wc = g(c, MC_P_INVERTER_CURRENT_KP_V_PER_A) / lmin;
        if (wc > 2.0 * MC_PI_D * g(c, MC_P_INVERTER_PWM_FREQUENCY_HZ) / 10.0)
            report(rep, MC_CFG_E_CURRENT_LOOP_BANDWIDTH, MC_P_INVERTER_CURRENT_KP_V_PER_A);
    }
    /* R22 */
    if (HAVE2(MC_P_INVERTER_DEADTIME_S, MC_P_INVERTER_PWM_FREQUENCY_HZ) &&
        g(c, MC_P_INVERTER_DEADTIME_S) > 0.05 / g(c, MC_P_INVERTER_PWM_FREQUENCY_HZ))
        report(rep, MC_CFG_E_DEADTIME_TOO_LONG, MC_P_INVERTER_DEADTIME_S);
    /* R24 */
    if (HAVE2(MC_P_MOTOR_CONTINUOUS_PHASE_CURRENT_A_RMS, MC_P_MOTOR_PEAK_PHASE_CURRENT_A) &&
        g(c, MC_P_MOTOR_CONTINUOUS_PHASE_CURRENT_A_RMS) * sqrt(2.0) > g(c, MC_P_MOTOR_PEAK_PHASE_CURRENT_A) * 1.0001)
        report(rep, MC_CFG_E_PHASE_CURRENT_RMS_PEAK, 0);
    /* vbus sense range */
    if (HAVE3(MC_P_INVERTER_ADC_VREF_V, MC_P_INVERTER_VBUS_DIVIDER_RATIO, MC_P_LIMITS_OVERVOLTAGE_TRIP_V) &&
        g(c, MC_P_INVERTER_ADC_VREF_V) * g(c, MC_P_INVERTER_VBUS_DIVIDER_RATIO) < 1.05 * g(c, MC_P_LIMITS_OVERVOLTAGE_TRIP_V))
        report(rep, MC_CFG_E_VBUS_SENSE_RANGE, MC_P_INVERTER_VBUS_DIVIDER_RATIO);
}

bool mc_config_validate(const mc_config_t *cfg, mc_cfg_mode_t mode, mc_cfg_report_t *rep)
{
    vctx_t c;
    memset(&c, 0, sizeof c);
    c.cfg = cfg;
    const uint16_t before = rep ? rep->count : 0u;
    for (size_t i = 0; i < MC_PARAM_COUNT; i++) {
        const mc_param_info_t *p = &k_params[i];
        const bool required = (mode == MC_CFG_MODE_HW) ? p->req_hw : p->req_sim;
        if (!mc_config_has(cfg, p->id)) {
            if (required) report(rep, MC_CFG_E_MISSING_REQUIRED, p->id);
            continue;
        }
        const float v = cfg->value[p->id];
        if (!mc_isfinite(v)) { report(rep, MC_CFG_E_NONFINITE, p->id); continue; }
        const double dv = (double)v;
        if (p->kind != MC_PKIND_REAL && dv != floor(dv)) { report(rep, MC_CFG_E_NOT_INTEGER, p->id); continue; }
        if (p->kind == MC_PKIND_ENUM || p->kind == MC_PKIND_BOOL) {
            /* Registry enums are dense 0..max, so the range is the value set. */
            if (dv < (double)p->min || dv > (double)p->max) { report(rep, MC_CFG_E_BAD_ENUM, p->id); continue; }
        } else if (dv < (double)p->min || dv > (double)p->max) {
            report(rep, MC_CFG_E_OUT_OF_RANGE, p->id);
            continue;
        }
        c.ok[p->id / 32u] |= (1u << (p->id % 32u));
    }
    cross_rules(&c, mode, rep);
    return rep ? rep->count == before : true;
}

bool mc_config_derive(const mc_config_t *cfg, mc_params_t *p)
{
    mc_cfg_report_t rep;
    mc_cfg_report_clear(&rep);
    if (!mc_config_validate(cfg, MC_CFG_MODE_SIM, &rep)) return false;
#define V(id) (cfg->value[(id)])
    memset(p, 0, sizeof(*p));
    p->pole_pairs = (int)V(MC_P_MOTOR_POLE_PAIRS);
    p->rs_ohm = V(MC_P_MOTOR_PHASE_RESISTANCE_OHM);
    p->ld_H = V(MC_P_MOTOR_D_INDUCTANCE_H);
    p->lq_H = V(MC_P_MOTOR_Q_INDUCTANCE_H);
    p->lambda_Wb = V(MC_P_MOTOR_FLUX_LINKAGE_WB);
    p->kt_Nm_per_A = 1.5f * (float)p->pole_pairs * p->lambda_Wb;
    p->max_mech_speed_rad_s = V(MC_P_MOTOR_MAX_MECH_SPEED_RAD_S);
    p->inertia_kg_m2 = V(MC_P_MOTOR_INERTIA_KG_M2);
    for (uint8_t k = 0; k < 8u; k++) p->hall_code_to_sector[k] = (int8_t)V(MC_P_MOTOR_HALL_CODE_TO_SECTOR_0 + k);
    p->hall_angle_offset_rad = V(MC_P_MOTOR_HALL_ANGLE_OFFSET_RAD);
    p->vbatt_min_V = V(MC_P_BATTERY_MIN_VOLTAGE_V);
    p->vbatt_nom_V = V(MC_P_BATTERY_NOMINAL_VOLTAGE_V);
    p->vbatt_max_V = V(MC_P_BATTERY_MAX_CHARGED_VOLTAGE_V);
    p->mass_kg = V(MC_P_VEHICLE_MASS_WITH_DRIVER_KG);
    p->gear_ratio = V(MC_P_VEHICLE_GEAR_RATIO);
    p->wheel_circumference_m = V(MC_P_VEHICLE_WHEEL_CIRCUMFERENCE_M);
    p->drivetrain_eff = V(MC_P_VEHICLE_DRIVETRAIN_EFFICIENCY);
    p->freewheel_present = V(MC_P_VEHICLE_FREEWHEEL_PRESENT) != 0.0f;
    p->pwm_frequency_Hz = V(MC_P_INVERTER_PWM_FREQUENCY_HZ);
    p->deadtime_s = V(MC_P_INVERTER_DEADTIME_S);
    p->duty_min = V(MC_P_INVERTER_DUTY_MIN);
    p->duty_max = V(MC_P_INVERTER_DUTY_MAX);
    p->shunt_ohm = V(MC_P_INVERTER_SHUNT_OHM);
    p->amp_gain = V(MC_P_INVERTER_AMP_GAIN_V_PER_V);
    p->adc_vref_V = V(MC_P_INVERTER_ADC_VREF_V);
    p->adc_full_scale_counts = (float)((1u << (unsigned)V(MC_P_INVERTER_ADC_BITS)) - 1u);
    for (uint8_t k = 0; k < 3u; k++) p->current_offset_counts[k] = V(MC_P_INVERTER_CURRENT_OFFSET_COUNTS_0 + k);
    p->vbus_divider_ratio = V(MC_P_INVERTER_VBUS_DIVIDER_RATIO);
    p->hw_overcurrent_trip_A = V(MC_P_INVERTER_HW_OVERCURRENT_TRIP_A);
    p->fet_derate_start_degC = V(MC_P_INVERTER_FET_TEMP_DERATE_START_DEGC);
    p->fet_trip_degC = V(MC_P_INVERTER_FET_TEMP_TRIP_DEGC);
    p->current_kp = V(MC_P_INVERTER_CURRENT_KP_V_PER_A);
    p->current_ki = V(MC_P_INVERTER_CURRENT_KI_V_PER_A_S);
    p->max_motor_torque_Nm = V(MC_P_LIMITS_MAX_MOTOR_TORQUE_NM);
    p->manual_max_torque_Nm = V(MC_P_LIMITS_MANUAL_MAX_TORQUE_NM);
    p->max_phase_current_A = V(MC_P_LIMITS_MAX_PHASE_CURRENT_A);
    p->battery_current_limit_A = V(MC_P_LIMITS_BATTERY_CURRENT_LIMIT_A);
    p->min_efficiency_for_limit = V(MC_P_LIMITS_MIN_EFFICIENCY_FOR_LIMIT);
    p->regen_enabled = V(MC_P_LIMITS_REGEN_ENABLED) != 0.0f;
    p->overspeed_trip_rad_s = V(MC_P_LIMITS_OVERSPEED_TRIP_RAD_S);
    p->speed_taper_start_rad_s = V(MC_P_LIMITS_SPEED_TAPER_START_RAD_S);
    p->uv_derate_V = V(MC_P_LIMITS_UNDERVOLTAGE_DERATE_V);
    p->uv_trip_V = V(MC_P_LIMITS_UNDERVOLTAGE_TRIP_V);
    p->ov_trip_V = V(MC_P_LIMITS_OVERVOLTAGE_TRIP_V);
    p->motor_derate_start_degC = V(MC_P_LIMITS_MOTOR_TEMP_DERATE_START_DEGC);
    p->motor_trip_degC = V(MC_P_LIMITS_MOTOR_TEMP_TRIP_DEGC);
    p->slew_up_Nm_s = V(MC_P_LIMITS_TORQUE_SLEW_UP_NM_S);
    p->slew_down_Nm_s = V(MC_P_LIMITS_TORQUE_SLEW_DOWN_NM_S);
    p->slew_down_fast_Nm_s = V(MC_P_LIMITS_TORQUE_SLEW_DOWN_FAST_NM_S);
    p->unknown_temp_derate_factor = V(MC_P_LIMITS_UNKNOWN_TEMPERATURE_DERATE_FACTOR);
    p->throttle_release = V(MC_P_LIMITS_THROTTLE_RELEASE_THRESHOLD);
    p->throttle_engage = V(MC_P_LIMITS_THROTTLE_ENGAGE_THRESHOLD);
    p->sw_overcurrent_A = V(MC_P_LIMITS_SOFTWARE_OVERCURRENT_A);
    p->coast_mode = (uint8_t)V(MC_P_LIMITS_COAST_MODE);
    p->sup_period_s = V(MC_P_SUPERVISION_UPDATE_PERIOD_S);
    p->sup_timeout_s = V(MC_P_SUPERVISION_TIMEOUT_S);
    p->sup_limits_timeout_s = V(MC_P_SUPERVISION_LIMITS_TIMEOUT_S);
    p->timing_status = (uint8_t)V(MC_P_SUPERVISION_TIMING_STATUS);
    p->provenance = (uint8_t)V(MC_P_CALIBRATION_PROVENANCE);
    p->physical_output_permitted = V(MC_P_CALIBRATION_PHYSICAL_OUTPUT_PERMITTED) != 0.0f;
    p->cal_version = (uint32_t)V(MC_P_CALIBRATION_VERSION);
#undef V
    return true;
}

bool mc_config_permits_physical_output(const mc_config_t *cfg, mc_build_kind_t build)
{
    if (build != MC_BUILD_HARDWARE) return false;
    mc_cfg_report_t rep;
    mc_cfg_report_clear(&rep);
    if (!mc_config_validate(cfg, MC_CFG_MODE_HW, &rep)) return false;
    return (int)cfg->value[MC_P_CALIBRATION_PROVENANCE] == MC_PROVENANCE_BENCH_MEASURED &&
           cfg->value[MC_P_CALIBRATION_PHYSICAL_OUTPUT_PERMITTED] == 1.0f;
}

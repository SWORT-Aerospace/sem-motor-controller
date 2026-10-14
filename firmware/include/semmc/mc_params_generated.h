/* GENERATED from config/parameters.yaml by tools/gen_config.py - do not edit. */
#ifndef SEMMC_MC_PARAMS_GENERATED_H
#define SEMMC_MC_PARAMS_GENERATED_H

#include <stdint.h>

/* Parameter element ids in the calibration blob. */
typedef enum {
    MC_P_CALIBRATION_VERSION = 1,
    MC_P_CALIBRATION_PROVENANCE = 2,
    MC_P_CALIBRATION_PHYSICAL_OUTPUT_PERMITTED = 3,
    MC_P_MOTOR_TYPE = 10,
    MC_P_MOTOR_POLE_PAIRS = 11,
    MC_P_MOTOR_PHASE_RESISTANCE_OHM = 12,
    MC_P_MOTOR_RESISTANCE_REF_TEMP_DEGC = 13,
    MC_P_MOTOR_D_INDUCTANCE_H = 14,
    MC_P_MOTOR_Q_INDUCTANCE_H = 15,
    MC_P_MOTOR_FLUX_LINKAGE_WB = 16,
    MC_P_MOTOR_RATED_MECH_SPEED_RAD_S = 17,
    MC_P_MOTOR_MAX_MECH_SPEED_RAD_S = 18,
    MC_P_MOTOR_CONTINUOUS_PHASE_CURRENT_A_RMS = 19,
    MC_P_MOTOR_PEAK_PHASE_CURRENT_A = 20,
    MC_P_MOTOR_PEAK_CURRENT_DURATION_S = 21,
    MC_P_MOTOR_MAX_WINDING_TEMP_DEGC = 22,
    MC_P_MOTOR_ROTOR_SENSOR = 23,
    MC_P_MOTOR_HALL_SUPPLY_V = 24,
    MC_P_MOTOR_HALL_ANGLE_OFFSET_RAD = 25,
    MC_P_MOTOR_INERTIA_KG_M2 = 26,
    MC_P_MOTOR_HALL_CODE_TO_SECTOR_0 = 30,
    MC_P_MOTOR_HALL_CODE_TO_SECTOR_1 = 31,
    MC_P_MOTOR_HALL_CODE_TO_SECTOR_2 = 32,
    MC_P_MOTOR_HALL_CODE_TO_SECTOR_3 = 33,
    MC_P_MOTOR_HALL_CODE_TO_SECTOR_4 = 34,
    MC_P_MOTOR_HALL_CODE_TO_SECTOR_5 = 35,
    MC_P_MOTOR_HALL_CODE_TO_SECTOR_6 = 36,
    MC_P_MOTOR_HALL_CODE_TO_SECTOR_7 = 37,
    MC_P_BATTERY_CHEMISTRY = 50,
    MC_P_BATTERY_SERIES_CELLS = 51,
    MC_P_BATTERY_MIN_VOLTAGE_V = 52,
    MC_P_BATTERY_NOMINAL_VOLTAGE_V = 53,
    MC_P_BATTERY_MAX_CHARGED_VOLTAGE_V = 54,
    MC_P_BATTERY_BMS_MAX_DISCHARGE_CURRENT_A = 55,
    MC_P_BATTERY_BMS_PEAK_DISCHARGE_CURRENT_A = 56,
    MC_P_BATTERY_BMS_PEAK_DURATION_S = 57,
    MC_P_BATTERY_BMS_MAX_CHARGE_CURRENT_A = 58,
    MC_P_VEHICLE_CATEGORY = 70,
    MC_P_VEHICLE_MASS_WITH_DRIVER_KG = 71,
    MC_P_VEHICLE_GEAR_RATIO = 72,
    MC_P_VEHICLE_WHEEL_CIRCUMFERENCE_M = 73,
    MC_P_VEHICLE_FREEWHEEL_PRESENT = 74,
    MC_P_VEHICLE_DRIVETRAIN_EFFICIENCY = 75,
    MC_P_INVERTER_BUS_VOLTAGE_RATING_V = 90,
    MC_P_INVERTER_TRANSIENT_MARGIN_FRACTION = 91,
    MC_P_INVERTER_SHUNT_OHM = 92,
    MC_P_INVERTER_AMP_GAIN_V_PER_V = 93,
    MC_P_INVERTER_ADC_VREF_V = 94,
    MC_P_INVERTER_ADC_BITS = 95,
    MC_P_INVERTER_CURRENT_OFFSET_COUNTS_0 = 96,
    MC_P_INVERTER_CURRENT_OFFSET_COUNTS_1 = 97,
    MC_P_INVERTER_CURRENT_OFFSET_COUNTS_2 = 98,
    MC_P_INVERTER_VBUS_DIVIDER_RATIO = 100,
    MC_P_INVERTER_HW_OVERCURRENT_TRIP_A = 101,
    MC_P_INVERTER_PWM_FREQUENCY_HZ = 102,
    MC_P_INVERTER_DEADTIME_S = 103,
    MC_P_INVERTER_FET_TEMP_DERATE_START_DEGC = 104,
    MC_P_INVERTER_FET_TEMP_TRIP_DEGC = 105,
    MC_P_INVERTER_DUTY_MIN = 106,
    MC_P_INVERTER_DUTY_MAX = 107,
    MC_P_INVERTER_CURRENT_KP_V_PER_A = 108,
    MC_P_INVERTER_CURRENT_KI_V_PER_A_S = 109,
    MC_P_LIMITS_MAX_MOTOR_TORQUE_NM = 120,
    MC_P_LIMITS_MANUAL_MAX_TORQUE_NM = 121,
    MC_P_LIMITS_MAX_PHASE_CURRENT_A = 122,
    MC_P_LIMITS_BATTERY_CURRENT_LIMIT_A = 123,
    MC_P_LIMITS_REGEN_ENABLED = 124,
    MC_P_LIMITS_REGEN_CURRENT_LIMIT_A = 125,
    MC_P_LIMITS_MIN_EFFICIENCY_FOR_LIMIT = 126,
    MC_P_LIMITS_OVERSPEED_TRIP_RAD_S = 127,
    MC_P_LIMITS_SPEED_TAPER_START_RAD_S = 128,
    MC_P_LIMITS_UNDERVOLTAGE_DERATE_V = 129,
    MC_P_LIMITS_UNDERVOLTAGE_TRIP_V = 130,
    MC_P_LIMITS_OVERVOLTAGE_TRIP_V = 131,
    MC_P_LIMITS_MOTOR_TEMP_DERATE_START_DEGC = 132,
    MC_P_LIMITS_MOTOR_TEMP_TRIP_DEGC = 133,
    MC_P_LIMITS_TORQUE_SLEW_UP_NM_S = 134,
    MC_P_LIMITS_TORQUE_SLEW_DOWN_NM_S = 135,
    MC_P_LIMITS_TORQUE_SLEW_DOWN_FAST_NM_S = 136,
    MC_P_LIMITS_UNKNOWN_TEMPERATURE_DERATE_FACTOR = 137,
    MC_P_LIMITS_THROTTLE_RELEASE_THRESHOLD = 138,
    MC_P_LIMITS_THROTTLE_ENGAGE_THRESHOLD = 139,
    MC_P_LIMITS_SOFTWARE_OVERCURRENT_A = 140,
    MC_P_LIMITS_COAST_MODE = 141,
    MC_P_SUPERVISION_UPDATE_PERIOD_S = 160,
    MC_P_SUPERVISION_TIMEOUT_S = 161,
    MC_P_SUPERVISION_TIMING_STATUS = 162,
    MC_P_SUPERVISION_LIMITS_TIMEOUT_S = 163,
    MC_P_MAX_ID = 163
} mc_param_id_t;

/* Enumerations (values stored as exact small floats in the blob). */
#define MC_PROVENANCE_UNSET 0
#define MC_PROVENANCE_SYNTHETIC 1
#define MC_PROVENANCE_BENCH_MEASURED 2
#define MC_PROVENANCE_COUNT 3
#define MC_MOTOR_TYPE_UNKNOWN 0
#define MC_MOTOR_TYPE_PMSM_SINUSOIDAL 1
#define MC_MOTOR_TYPE_BLDC_TRAPEZOIDAL 2
#define MC_MOTOR_TYPE_BRUSHED_DC 3
#define MC_MOTOR_TYPE_INDUCTION 4
#define MC_MOTOR_TYPE_COUNT 5
#define MC_ROTOR_SENSOR_UNKNOWN 0
#define MC_ROTOR_SENSOR_HALL 1
#define MC_ROTOR_SENSOR_ENCODER 2
#define MC_ROTOR_SENSOR_NONE 3
#define MC_ROTOR_SENSOR_COUNT 4
#define MC_CHEMISTRY_UNKNOWN 0
#define MC_CHEMISTRY_LI_ION_NMC 1
#define MC_CHEMISTRY_LI_ION_LFP 2
#define MC_CHEMISTRY_LI_ION_NCA 3
#define MC_CHEMISTRY_OTHER 4
#define MC_CHEMISTRY_COUNT 5
#define MC_CATEGORY_UNKNOWN 0
#define MC_CATEGORY_PROTOTYPE 1
#define MC_CATEGORY_URBAN_CONCEPT 2
#define MC_CATEGORY_COUNT 3
#define MC_COAST_MODE_ZERO_CURRENT 0
#define MC_COAST_MODE_GATE_OFF 1
#define MC_COAST_MODE_COUNT 2
#define MC_TIMING_STATUS_PROVISIONAL_SIMULATION_ONLY 0
#define MC_TIMING_STATUS_HAZARD_ANALYSED 1
#define MC_TIMING_STATUS_COUNT 2

#define MC_PKIND_REAL 0
#define MC_PKIND_INT  1
#define MC_PKIND_BOOL 2
#define MC_PKIND_ENUM 3

typedef struct {
    uint8_t id;
    uint8_t kind;
    uint8_t req_sim;
    uint8_t req_hw;
    float min;
    float max;
    const char *path;
} mc_param_info_t;

#define MC_PARAM_TABLE_INIT { \
    {1u, 1u, 1u, 1u, 1.0f, 16777215.0f, "calibration.version"}, \
    {2u, 3u, 1u, 1u, 0.0f, 2.0f, "calibration.provenance"}, \
    {3u, 2u, 1u, 1u, 0.0f, 1.0f, "calibration.physical_output_permitted"}, \
    {10u, 3u, 1u, 1u, 0.0f, 4.0f, "motor.type"}, \
    {11u, 1u, 1u, 1u, 1.0f, 64.0f, "motor.pole_pairs"}, \
    {12u, 0u, 1u, 1u, 0.0001f, 10.0f, "motor.phase_resistance_ohm"}, \
    {13u, 0u, 1u, 1u, -40.0f, 150.0f, "motor.resistance_ref_temp_degC"}, \
    {14u, 0u, 1u, 1u, 1.0e-07f, 0.1f, "motor.d_inductance_H"}, \
    {15u, 0u, 1u, 1u, 1.0e-07f, 0.1f, "motor.q_inductance_H"}, \
    {16u, 0u, 1u, 1u, 1.0e-05f, 1.0f, "motor.flux_linkage_Wb"}, \
    {17u, 0u, 1u, 1u, 1.0f, 3000.0f, "motor.rated_mech_speed_rad_s"}, \
    {18u, 0u, 1u, 1u, 1.0f, 3000.0f, "motor.max_mech_speed_rad_s"}, \
    {19u, 0u, 1u, 1u, 0.1f, 500.0f, "motor.continuous_phase_current_A_rms"}, \
    {20u, 0u, 1u, 1u, 0.1f, 1000.0f, "motor.peak_phase_current_A"}, \
    {21u, 0u, 1u, 1u, 0.0f, 3600.0f, "motor.peak_current_duration_s"}, \
    {22u, 0u, 1u, 1u, 20.0f, 250.0f, "motor.max_winding_temp_degC"}, \
    {23u, 3u, 1u, 1u, 0.0f, 3.0f, "motor.rotor_sensor"}, \
    {24u, 0u, 0u, 1u, 2.5f, 24.0f, "motor.hall_supply_V"}, \
    {25u, 0u, 1u, 1u, -6.2832f, 6.2832f, "motor.hall_angle_offset_rad"}, \
    {26u, 0u, 1u, 0u, 1.0e-07f, 10.0f, "motor.inertia_kg_m2"}, \
    {30u, 1u, 1u, 1u, -1.0f, 5.0f, "motor.hall_code_to_sector[0]"}, \
    {31u, 1u, 1u, 1u, -1.0f, 5.0f, "motor.hall_code_to_sector[1]"}, \
    {32u, 1u, 1u, 1u, -1.0f, 5.0f, "motor.hall_code_to_sector[2]"}, \
    {33u, 1u, 1u, 1u, -1.0f, 5.0f, "motor.hall_code_to_sector[3]"}, \
    {34u, 1u, 1u, 1u, -1.0f, 5.0f, "motor.hall_code_to_sector[4]"}, \
    {35u, 1u, 1u, 1u, -1.0f, 5.0f, "motor.hall_code_to_sector[5]"}, \
    {36u, 1u, 1u, 1u, -1.0f, 5.0f, "motor.hall_code_to_sector[6]"}, \
    {37u, 1u, 1u, 1u, -1.0f, 5.0f, "motor.hall_code_to_sector[7]"}, \
    {50u, 3u, 1u, 1u, 0.0f, 4.0f, "battery.chemistry"}, \
    {51u, 1u, 1u, 1u, 1.0f, 40.0f, "battery.series_cells"}, \
    {52u, 0u, 1u, 1u, 1.0f, 200.0f, "battery.min_voltage_V"}, \
    {53u, 0u, 1u, 1u, 1.0f, 200.0f, "battery.nominal_voltage_V"}, \
    {54u, 0u, 1u, 1u, 1.0f, 200.0f, "battery.max_charged_voltage_V"}, \
    {55u, 0u, 1u, 1u, 0.1f, 1000.0f, "battery.bms_max_discharge_current_A"}, \
    {56u, 0u, 1u, 1u, 0.1f, 2000.0f, "battery.bms_peak_discharge_current_A"}, \
    {57u, 0u, 1u, 1u, 0.0f, 3600.0f, "battery.bms_peak_duration_s"}, \
    {58u, 0u, 1u, 1u, 0.0f, 1000.0f, "battery.bms_max_charge_current_A"}, \
    {70u, 3u, 1u, 1u, 0.0f, 2.0f, "vehicle.category"}, \
    {71u, 0u, 1u, 1u, 10.0f, 1000.0f, "vehicle.mass_with_driver_kg"}, \
    {72u, 0u, 1u, 1u, 0.1f, 100.0f, "vehicle.gear_ratio"}, \
    {73u, 0u, 1u, 1u, 0.2f, 5.0f, "vehicle.wheel_circumference_m"}, \
    {74u, 2u, 1u, 1u, 0.0f, 1.0f, "vehicle.freewheel_present"}, \
    {75u, 0u, 1u, 0u, 0.3f, 1.0f, "vehicle.drivetrain_efficiency"}, \
    {90u, 0u, 1u, 1u, 5.0f, 200.0f, "inverter.bus_voltage_rating_V"}, \
    {91u, 0u, 1u, 1u, 0.0f, 2.0f, "inverter.transient_margin_fraction"}, \
    {92u, 0u, 1u, 1u, 1.0e-05f, 1.0f, "inverter.shunt_ohm"}, \
    {93u, 0u, 1u, 1u, 1.0f, 1000.0f, "inverter.amp_gain_V_per_V"}, \
    {94u, 0u, 1u, 1u, 1.0f, 5.0f, "inverter.adc_vref_V"}, \
    {95u, 1u, 1u, 1u, 8.0f, 24.0f, "inverter.adc_bits"}, \
    {96u, 0u, 1u, 1u, 0.0f, 16777215.0f, "inverter.current_offset_counts[0]"}, \
    {97u, 0u, 1u, 1u, 0.0f, 16777215.0f, "inverter.current_offset_counts[1]"}, \
    {98u, 0u, 1u, 1u, 0.0f, 16777215.0f, "inverter.current_offset_counts[2]"}, \
    {100u, 0u, 1u, 1u, 1.0f, 1000.0f, "inverter.vbus_divider_ratio"}, \
    {101u, 0u, 1u, 1u, 0.1f, 2000.0f, "inverter.hw_overcurrent_trip_A"}, \
    {102u, 0u, 1u, 1u, 1000.0f, 200000.0f, "inverter.pwm_frequency_Hz"}, \
    {103u, 0u, 1u, 1u, 1.0e-08f, 5.0e-06f, "inverter.deadtime_s"}, \
    {104u, 0u, 1u, 1u, 20.0f, 175.0f, "inverter.fet_temp_derate_start_degC"}, \
    {105u, 0u, 1u, 1u, 20.0f, 175.0f, "inverter.fet_temp_trip_degC"}, \
    {106u, 0u, 1u, 1u, 0.0f, 0.2f, "inverter.duty_min"}, \
    {107u, 0u, 1u, 1u, 0.8f, 1.0f, "inverter.duty_max"}, \
    {108u, 0u, 1u, 1u, 0.0001f, 100.0f, "inverter.current_kp_V_per_A"}, \
    {109u, 0u, 1u, 1u, 0.01f, 1000000.0f, "inverter.current_ki_V_per_A_s"}, \
    {120u, 0u, 1u, 1u, 0.01f, 1000.0f, "limits.max_motor_torque_Nm"}, \
    {121u, 0u, 1u, 1u, 0.0f, 1000.0f, "limits.manual_max_torque_Nm"}, \
    {122u, 0u, 1u, 1u, 0.1f, 1000.0f, "limits.max_phase_current_A"}, \
    {123u, 0u, 1u, 1u, 0.1f, 1000.0f, "limits.battery_current_limit_A"}, \
    {124u, 2u, 1u, 1u, 0.0f, 1.0f, "limits.regen_enabled"}, \
    {125u, 0u, 1u, 1u, 0.0f, 1000.0f, "limits.regen_current_limit_A"}, \
    {126u, 0u, 1u, 1u, 0.3f, 1.0f, "limits.min_efficiency_for_limit"}, \
    {127u, 0u, 1u, 1u, 1.0f, 3500.0f, "limits.overspeed_trip_rad_s"}, \
    {128u, 0u, 1u, 1u, 1.0f, 3500.0f, "limits.speed_taper_start_rad_s"}, \
    {129u, 0u, 1u, 1u, 1.0f, 200.0f, "limits.undervoltage_derate_V"}, \
    {130u, 0u, 1u, 1u, 1.0f, 200.0f, "limits.undervoltage_trip_V"}, \
    {131u, 0u, 1u, 1u, 1.0f, 200.0f, "limits.overvoltage_trip_V"}, \
    {132u, 0u, 1u, 1u, 20.0f, 250.0f, "limits.motor_temp_derate_start_degC"}, \
    {133u, 0u, 1u, 1u, 20.0f, 250.0f, "limits.motor_temp_trip_degC"}, \
    {134u, 0u, 1u, 1u, 0.01f, 100000.0f, "limits.torque_slew_up_Nm_s"}, \
    {135u, 0u, 1u, 1u, 0.01f, 100000.0f, "limits.torque_slew_down_Nm_s"}, \
    {136u, 0u, 1u, 1u, 0.01f, 1000000.0f, "limits.torque_slew_down_fast_Nm_s"}, \
    {137u, 0u, 1u, 1u, 0.0f, 1.0f, "limits.unknown_temperature_derate_factor"}, \
    {138u, 0u, 1u, 1u, 0.0f, 0.5f, "limits.throttle_release_threshold"}, \
    {139u, 0u, 1u, 1u, 0.0f, 0.9f, "limits.throttle_engage_threshold"}, \
    {140u, 0u, 1u, 1u, 0.1f, 1000.0f, "limits.software_overcurrent_A"}, \
    {141u, 3u, 1u, 1u, 0.0f, 1.0f, "limits.coast_mode"}, \
    {160u, 0u, 1u, 1u, 0.001f, 1.0f, "supervision.update_period_s"}, \
    {161u, 0u, 1u, 1u, 0.005f, 2.0f, "supervision.timeout_s"}, \
    {162u, 3u, 1u, 1u, 0.0f, 1.0f, "supervision.timing_status"}, \
    {163u, 0u, 1u, 1u, 0.01f, 10.0f, "supervision.limits_timeout_s"}, \
}

#define MC_PARAM_COUNT 88

#endif /* SEMMC_MC_PARAMS_GENERATED_H */

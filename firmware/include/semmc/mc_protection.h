/* Software protection: fault detection, latching and derating.
 *
 * This is the SOFTWARE layer. It is not the primary protection: independent
 * hardware (overcurrent comparator / gate-driver VDS monitor, overvoltage
 * comparator, external watchdog, physical e-stop isolation) must act without
 * this code (Architecture Freeze boundary E). The platform reports those
 * hardware trips here so software state follows hardware state.
 *
 * All faults latch until an explicit local reset; CONFIG_INVALID never
 * resets. Derating is not a fault: it scales the torque limit.
 */
#ifndef SEMMC_MC_PROTECTION_H
#define SEMMC_MC_PROTECTION_H

#include "semmc/mc_config.h"
#include "semmc/mc_types.h"

typedef enum {
    MC_F_CONFIG_INVALID = 0,
    MC_F_SELFTEST,
    MC_F_HW_OVERCURRENT,
    MC_F_HW_OVERVOLTAGE,
    MC_F_GATE_DRIVER,
    MC_F_SW_OVERCURRENT,
    MC_F_BUS_OVERVOLTAGE,
    MC_F_BUS_UNDERVOLTAGE,
    MC_F_FET_OVERTEMP,
    MC_F_MOTOR_OVERTEMP,
    MC_F_HALL_INVALID,
    MC_F_CURRENT_SENSE_INVALID,
    MC_F_VBUS_SENSE_INVALID,
    MC_F_WATCHDOG,
    MC_F_OVERSPEED,
    MC_F_THROTTLE_IMPLAUSIBLE,
    MC_F_CONTROL_DT_INVALID,
    MC_F_ROTOR_STALL,            /* significant q current, no hall edge for MC_STALL_TIME_S */
    MC_F_COUNT
} mc_fault_t;

#define MC_FAULT_BIT(f) (1u << (unsigned)(f))
#define MC_FAULT_NONE 0xFFu

/* Derate reasons */
#define MC_DR_FET_TEMP      0x01u
#define MC_DR_MOTOR_TEMP    0x02u
#define MC_DR_UNDERVOLTAGE  0x04u
#define MC_DR_TEMP_UNKNOWN  0x08u

typedef struct {
    /* hardware (independent) status, reported by platform */
    bool hw_overcurrent;
    bool hw_overvoltage;
    bool gate_driver_fault;
    bool watchdog_fault;
    /* fast-loop software trip (set in the current ISR, consumed here) */
    bool fast_overcurrent;
    bool fast_dt_invalid;
    /* measurements */
    float vbus_V;
    mc_validity_t vbus_val;
    float t_fet_degC;
    mc_validity_t t_fet_val;
    float t_motor_degC;
    mc_validity_t t_motor_val;
    float speed_mech_rad_s;
    bool hall_invalid;
    bool current_sense_invalid;
    bool throttle_valid;
    bool rotor_stall;            /* computed by the core from hall edges vs current */
} mc_prot_inputs_t;

#define MC_STALL_TIME_S 1.0f
#define MC_STALL_CURRENT_FRACTION 0.3f

typedef struct {
    const mc_params_t *p;
    uint32_t active;         /* conditions present this tick */
    uint32_t latched;
    uint8_t first_fault;     /* first latched since last reset, MC_FAULT_NONE if none */
    uint16_t fault_count;
    float derate_raw;        /* min of instantaneous derate factors */
    float derate;            /* applied factor: drops immediately, recovers slowly */
    uint8_t derate_reasons;
    float uv_timer_s;        /* time spent below UV trip (debounce) */
    float derate_clear_timer_s;
} mc_protection_t;

#define MC_UV_TRIP_DEBOUNCE_S 0.10f
#define MC_DERATE_RECOVERY_PER_S 0.20f
#define MC_DERATE_CLEAR_HOLD_S 1.0f

void mc_prot_init(mc_protection_t *pr, const mc_params_t *p);
void mc_prot_evaluate(mc_protection_t *pr, const mc_prot_inputs_t *in, float dt);
void mc_prot_latch(mc_protection_t *pr, mc_fault_t f);
/* Clear latched faults whose conditions are no longer active. Returns true if
 * nothing remains latched. CONFIG_INVALID can never be cleared. */
bool mc_prot_try_reset(mc_protection_t *pr);
/* True when derating is active (including the recovery hold). */
bool mc_prot_derating(const mc_protection_t *pr);
/* Torque-limit factor from mechanical speed (taper to 0 at overspeed trip). */
float mc_prot_speed_factor(const mc_params_t *p, float speed_mech_rad_s);

#endif /* SEMMC_MC_PROTECTION_H */

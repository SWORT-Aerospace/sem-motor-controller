/* Precharge sequencing for the DC link (hardware/kicad sheet 01, power input and precharge).
 *
 * The board charges the link through a resistor whenever the battery is connected; the MCU only
 * closes the bypass MOSFET (PRECHG_EN, pulled down: open in reset). The link voltage is read at
 * VBUS_SENSE (link side) and the battery voltage at the INA228 (battery side of the precharge).
 *
 *   WAIT_BATTERY  bypass open; waits for the battery side to exceed the undervoltage trip
 *   CHARGING      bypass open; closes when link >= fraction x battery, faults after the timeout
 *   CLOSED        bypass closed; a link that stays below fraction x battery for longer than the
 *                 timeout is a fault (bypass not conducting, or a load the precharge cannot hold)
 *   FAULT         bypass open, latched until mc_precharge_reset()
 *   DISABLED      calibration missing: bypass open for ever
 *
 * Loss of either measurement while CLOSED keeps the bypass closed (opening it under load would put
 * the load current through the precharge resistor) but clears "ready", which the platform feeds to
 * the core as gate_driver_ready = false.
 *
 * Not detected here, because it needs the precharge resistor and link capacitance, which are not
 * selected: a link that charges implausibly fast (bypass shorted, or resistor bypassed). */
#ifndef SEMMC_MC_PRECHARGE_H
#define SEMMC_MC_PRECHARGE_H

#include <stdbool.h>
#include <stdint.h>

typedef enum {
    MC_PC_DISABLED = 0,
    MC_PC_WAIT_BATTERY = 1,
    MC_PC_CHARGING = 2,
    MC_PC_CLOSED = 3,
    MC_PC_FAULT = 4
} mc_pc_state_t;

typedef enum { MC_PCF_NONE = 0, MC_PCF_TIMEOUT = 1, MC_PCF_LINK_LOW_AFTER_CLOSE = 2 } mc_pc_fault_t;

typedef struct {
    float fraction, timeout_s, uv_trip_V;
    mc_pc_state_t state;
    mc_pc_fault_t fault;
    float t_state_s;
    float mismatch_s;
    bool bypass;   /* command to PRECHG_EN */
    bool ready;    /* bypass closed and both voltages currently verified */
} mc_precharge_t;

void mc_precharge_init(mc_precharge_t *p, float fraction, float timeout_s, float uv_trip_V);
void mc_precharge_step(mc_precharge_t *p, float dt_s, float v_link, bool v_link_ok, float v_batt, bool v_batt_ok);
/* Clears a latched fault (driver fault-reset while not driving). Returns to WAIT_BATTERY. */
void mc_precharge_reset(mc_precharge_t *p);

#endif /* SEMMC_MC_PRECHARGE_H */

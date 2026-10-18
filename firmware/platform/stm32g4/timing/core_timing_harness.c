/* Instruction-count harness for the controller core on Cortex-M4F (NOT a flashable image).
 *
 * tools/emulate_core_timing.py loads this ELF into an instruction-level emulator (unicorn, QEMU's
 * Cortex-M4 model), places the synthetic calibration blob in RAM and calls bench_run(). The harness
 * drives the real core (compiled with the target's compiler, flags and libraries) against the host
 * plant model (platform/host/sim_plant.c): arm, then hold half throttle. The emulator counts the
 * instructions executed between bench_fast_begin/bench_fast_end and bench_slow_begin/bench_slow_end.
 *
 * Counts are instructions, not cycles: wait states, the flash accelerator, pipeline refills and
 * FPU latencies are not modelled. The platform's own interrupt code (ADC reads, pin reads, duty
 * writes) is not included because it touches peripherals the emulator does not model. */
#include <stdint.h>
#include <string.h>

#include "semmc/mc_core.h"
#include "sim_plant.h"

extern uint32_t _sidata, _sdata, _edata, _sbss, _ebss;

static mc_core_t C;
static sim_plant_t P;
static mc_config_t CFG;
static mc_params_t PP;

volatile uint32_t bench_pwm_enabled; /* read by the emulator at bench_fast_end */

__attribute__((noinline, used)) void bench_fast_begin(void) { __asm volatile("nop"); }
__attribute__((noinline, used)) void bench_fast_end(void) { __asm volatile("nop"); }
__attribute__((noinline, used)) void bench_slow_begin(void) { __asm volatile("nop"); }
__attribute__((noinline, used)) void bench_slow_end(void) { __asm volatile("nop"); }

int bench_run(const uint8_t *blob, uint32_t len, uint32_t ms);

int bench_run(const uint8_t *blob, uint32_t len, uint32_t ms)
{
    uint32_t *src = &_sidata;
    for (uint32_t *dst = &_sdata; dst < &_edata;) *dst++ = *src++;
    for (uint32_t *dst = &_sbss; dst < &_ebss;) *dst++ = 0u;

    mc_cfg_report_t rep;
    mc_cfg_report_clear(&rep);
    if (!mc_config_parse_blob(blob, len, &CFG, &rep) || !mc_config_derive(&CFG, &PP)) return -1;
    if (!mc_core_init(&C, blob, len, MC_BUILD_HOST_SIM, 1u)) return -2;
    sim_plant_init(&P, &PP);

    mc_slow_inputs_t si;
    memset(&si, 0, sizeof si);
    si.gate_driver_ready = true;
    si.current_offsets_ok = true;
    si.driver = (mc_driver_inputs_t){0.0f, true, false, false, false, false, false, true, true};
    mc_duty_t duty = {0.5f, 0.5f, 0.5f};
    bool pwm = false;
    mc_time_us_t t = 0u;
    for (uint32_t i = 0; i < ms; i++) {
        if (i == 100u) si.driver.arm_switch = true;
        if (i == 110u) si.driver.throttle = 0.5f;
        for (uint32_t k = 0; k < 20u; k++) {
            sim_sensors_t s;
            sim_plant_sense(&P, &duty, pwm, &s);
            mc_fast_inputs_t fi = {s.phase, s.hall_code, s.vbus_V, 50e-6f, false};
            mc_fast_outputs_t fo;
            bench_fast_begin();
            mc_core_fast_step(&C, &fi, &fo);
            bench_pwm_enabled = fo.pwm_enable ? 1u : 0u;
            bench_fast_end();
            pwm = fo.pwm_enable;
            duty = fo.duty;
            sim_plant_step(&P, pwm, &duty, 25e-6);
            sim_plant_step(&P, pwm, &duty, 25e-6);
            t += 50u;
            if (k == 0u) {
                si.vbus_V = s.vbus_V;
                si.vbus_val = s.vbus_valid ? MC_VAL_OK : MC_VAL_INVALID;
                si.ibatt_A = s.ibatt_A;
                si.ibatt_val = s.ibatt_valid ? MC_VAL_OK : MC_VAL_MISSING;
                si.t_fet_degC = s.t_fet_degC;
                si.t_fet_val = s.t_fet_valid ? MC_VAL_OK : MC_VAL_INVALID;
                si.t_motor_degC = s.t_mot_degC;
                si.t_motor_val = s.t_mot_valid ? MC_VAL_OK : MC_VAL_INVALID;
            }
        }
        bench_slow_begin();
        mc_core_slow_step(&C, t, &si);
        bench_slow_end();
    }
    return (int)C.sm.state;
}

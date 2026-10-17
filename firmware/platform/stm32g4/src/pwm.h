/* TIM1: three-phase complementary PWM, break inputs and the current-sampling trigger.
 *
 * Counting: centre-aligned mode 1, f_pwm = 160 MHz / (2 ARR). Channels 1..3 in PWM mode 2 with
 * preload: the high-side output is active while CNT >= CCR, i.e. centred on the counter peak, and
 * the low-side (complementary) output is centred on the counter valley. CCR = (1 - duty) ARR. New
 * compare values load at the next update event (peak or valley); the fast step writes them after
 * the valley sample, so they take effect at the following peak and the next valley's low-side
 * window is symmetric. The fast step must finish within half a PWM period: pwm_overruns counts the
 * cycles where it did not (the counter was already counting down when the duties were written).
 *
 * Current-sampling trigger: OC4REF in PWM mode 1 with CCR4 = 1 rises one timer tick before the
 * valley; TRGO2 = OC4REF starts the injected conversions of ADC1, ADC2 and ADC3 (adc.c).
 *
 * Protection, in hardware, without software in the path:
 *   BKIN  (PE15): DRV_NFAULT, the gate driver's open-drain fault output, active low
 *   BKIN2 (PC3):  BRK2_N, the TLV7041 bus-overvoltage comparator (sheet 02), active low
 * Either clears MOE; with OSSI = 1 and OISx = OISxN = 0 all six outputs then go to their inactive
 * (low) level after the dead time. Digital filter 4 samples at 160 MHz (25 ns) on both. AOE = 0: MOE
 * stays cleared after the break until software sets it again. BDTR is locked (LOCK level 1) after
 * configuration, so dead time, break enables and polarities cannot be changed by a later fault.
 * The system break (core lockup, flash double-ECC error) is routed to TIM1 as well.
 * The break interrupt only records which input fired (pwm_break_flags). */
#ifndef SEMMC_STM32G4_PWM_H
#define SEMMC_STM32G4_PWM_H

#include <stdbool.h>
#include <stdint.h>

#include "semmc/mc_control.h"

#define PWM_BREAK_DRIVER 0x1u   /* BKIN: gate driver nFAULT */
#define PWM_BREAK_OVERVOLT 0x2u /* BKIN2: bus overvoltage comparator */
#define PWM_BREAK_SYSTEM 0x4u   /* system break: core lockup or flash double-ECC error */

typedef struct {
    uint32_t arr;
    float f_pwm_Hz;
    float deadtime_s;     /* as programmed, >= the configured value */
    uint8_t dtg;
} pwm_setup_t;

/* Configures and starts the counter with the outputs off (MOE = 0). Returns false, leaving TIM1 off
 * and the gate pins low as GPIO, if the frequency or dead time cannot be programmed. */
bool pwm_init(float f_pwm_Hz, float deadtime_s, uint32_t brk_priority, pwm_setup_t *out);
bool pwm_running(void);
void pwm_write_duty(const mc_duty_t *d);
void pwm_outputs_on(void);
void pwm_outputs_off(void);
bool pwm_outputs_are_on(void);
/* Latched break sources since the last pwm_break_clear(); the hardware already cleared MOE. */
uint32_t pwm_break_flags(void);
/* Clears the latch only if both break inputs are inactive now. Returns true if cleared. */
bool pwm_break_clear(void);
bool pwm_counting_down(void);

#endif
